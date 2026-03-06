"""Token management module for enforcing token limits and tracking distributions.

Uses tiktoken with cl100k_base encoding as a proxy for token counting.
Provides truncation strategies that preserve context around comment locations.
"""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from typing import Any

import tiktoken

logger = logging.getLogger(__name__)

# Default token limits
DEFAULT_MAX_INPUT_TOKENS = 2048
DEFAULT_MAX_OUTPUT_TOKENS = 512
DEFAULT_ENCODING = "cl100k_base"

# Number of context lines to keep around the comment during truncation
DEFAULT_TRUNCATION_CONTEXT_LINES = 20

# Safety margin for token counting to avoid off-by-one truncation issues
_TOKEN_SAFETY_MARGIN = 10


@dataclass
class TokenStats:
    """Token distribution statistics."""

    input_token_counts: list[int] = field(default_factory=list)
    output_token_counts: list[int] = field(default_factory=list)
    total_samples: int = 0
    truncated_inputs: int = 0
    truncated_outputs: int = 0
    dropped_samples: int = 0

    def to_dict(self) -> dict[str, Any]:
        def _distribution(values: list[int]) -> dict[str, float]:
            if not values:
                return {"count": 0, "mean": 0, "median": 0, "min": 0, "max": 0, "p95": 0, "p99": 0}
            sorted_v = sorted(values)
            n = len(sorted_v)
            return {
                "count": n,
                "mean": round(statistics.mean(sorted_v), 1),
                "median": round(statistics.median(sorted_v), 1),
                "min": sorted_v[0],
                "max": sorted_v[-1],
                "p95": sorted_v[int(n * 0.95)] if n > 1 else sorted_v[0],
                "p99": sorted_v[int(n * 0.99)] if n > 1 else sorted_v[0],
            }

        return {
            "total_samples": self.total_samples,
            "truncated_inputs": self.truncated_inputs,
            "truncated_outputs": self.truncated_outputs,
            "dropped_samples": self.dropped_samples,
            "input_tokens": _distribution(self.input_token_counts),
            "output_tokens": _distribution(self.output_token_counts),
        }


class TokenManager:
    """Manages token counting, enforcement of limits, and truncation.

    Uses tiktoken's cl100k_base encoding as a proxy for sub-word token counting.
    This is the encoding used by GPT-4 and serves as a reasonable approximation
    for other LLMs as well.
    """

    def __init__(
        self,
        max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        encoding_name: str = DEFAULT_ENCODING,
        truncation_context_lines: int = DEFAULT_TRUNCATION_CONTEXT_LINES,
    ) -> None:
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.truncation_context_lines = truncation_context_lines
        self._encoding = tiktoken.get_encoding(encoding_name)
        self._stats = TokenStats()

    @property
    def stats(self) -> TokenStats:
        return self._stats

    def count_tokens(self, text: str) -> int:
        """Count the number of tokens in the given text."""
        if not text:
            return 0
        return len(self._encoding.encode(text))

    def process_batch(self, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Process a batch of instruction samples, enforcing token limits.

        Each sample dict must have 'instruction', 'input', and 'output' keys.

        Returns:
            List of samples with token counts added, truncated as needed.
            Samples that cannot be meaningfully truncated are dropped.
        """
        self._stats = TokenStats(total_samples=len(samples))
        processed: list[dict[str, Any]] = []

        for sample in samples:
            result = self._process_single(sample)
            if result is not None:
                processed.append(result)

        logger.info(
            "Token processing complete: %d -> %d samples (%d truncated inputs, %d truncated outputs, %d dropped)",
            self._stats.total_samples,
            len(processed),
            self._stats.truncated_inputs,
            self._stats.truncated_outputs,
            self._stats.dropped_samples,
        )
        return processed

    def _process_single(self, sample: dict[str, Any]) -> dict[str, Any] | None:
        """Process a single sample: count tokens, truncate if needed."""
        instruction = sample.get("instruction", "")
        input_text = sample.get("input", "")
        output_text = sample.get("output", "")

        # Count tokens for instruction + input combined (they form the prompt)
        instruction_tokens = self.count_tokens(instruction)
        input_tokens = self.count_tokens(input_text)
        output_tokens = self.count_tokens(output_text)

        total_input_tokens = instruction_tokens + input_tokens

        # Truncate output if too long
        if output_tokens > self.max_output_tokens:
            output_text = self._truncate_output(output_text)
            output_tokens = self.count_tokens(output_text)
            self._stats.truncated_outputs += 1

        # Truncate input if too long
        if total_input_tokens > self.max_input_tokens:
            # Budget for input text = max_input - instruction tokens
            input_budget = self.max_input_tokens - instruction_tokens
            if input_budget <= 50:
                # Not enough room even for minimal input
                self._stats.dropped_samples += 1
                return None

            input_text = self._truncate_input(input_text, input_budget, sample.get("comment_line"))
            input_tokens = self.count_tokens(input_text)
            total_input_tokens = instruction_tokens + input_tokens
            self._stats.truncated_inputs += 1

        self._stats.input_token_counts.append(total_input_tokens)
        self._stats.output_token_counts.append(output_tokens)

        result = dict(sample)
        result["input"] = input_text
        result["output"] = output_text
        result["input_tokens"] = total_input_tokens
        result["output_tokens"] = output_tokens
        return result

    def _truncate_input(self, input_text: str, max_tokens: int, comment_line: int | None = None) -> str:
        """Truncate input text (file path + diff) to fit within token budget.

        Strategy:
        1. Preserve the header (File:, Language:, Diff: markers).
        2. Truncate the diff portion, keeping context around the comment line.
        3. If no comment line info, keep the beginning of the diff.
        """
        lines = input_text.split("\n")

        # Find where the diff content starts (after "```diff")
        diff_start_idx = None
        diff_end_idx = None
        for i, line in enumerate(lines):
            if line.strip() == "```diff":
                diff_start_idx = i + 1
            elif diff_start_idx is not None and line.strip() == "```":
                diff_end_idx = i
                break

        if diff_start_idx is None:
            # No diff block found, do simple token truncation
            return self._truncate_text_to_tokens(input_text, max_tokens)

        if diff_end_idx is None:
            diff_end_idx = len(lines)

        header_lines = lines[:diff_start_idx]  # includes "```diff"
        diff_lines = lines[diff_start_idx:diff_end_idx]
        footer_lines = lines[diff_end_idx:]  # includes closing "```"

        header_text = "\n".join(header_lines)
        footer_text = "\n".join(footer_lines)
        overhead_tokens = self.count_tokens(header_text) + self.count_tokens(footer_text) + 2  # +2 for newlines

        diff_budget = max_tokens - overhead_tokens - _TOKEN_SAFETY_MARGIN
        if diff_budget <= 20:
            return self._truncate_text_to_tokens(input_text, max_tokens)

        truncated_diff_lines = self._truncate_diff_lines(diff_lines, diff_budget, comment_line)

        result = "\n".join(header_lines + truncated_diff_lines + footer_lines)

        # Final enforcement: if still over budget, do hard token truncation
        if self.count_tokens(result) > max_tokens:
            result = self._truncate_text_to_tokens(result, max_tokens)

        return result

    def _truncate_diff_lines(
        self, diff_lines: list[str], max_tokens: int, comment_line: int | None = None
    ) -> list[str]:
        """Truncate diff lines to fit within token budget, keeping context around comment."""
        full_diff = "\n".join(diff_lines)
        if self.count_tokens(full_diff) <= max_tokens:
            return diff_lines

        if comment_line is not None:
            target_idx = self._find_line_in_diff(diff_lines, comment_line)
        else:
            target_idx = None

        if target_idx is not None:
            # Keep context around the target line
            ctx = self.truncation_context_lines
            start = max(0, target_idx - ctx)
            end = min(len(diff_lines), target_idx + ctx + 1)

            # Include nearest hunk header
            for i in range(start, -1, -1):
                if diff_lines[i].startswith("@@"):
                    start = i
                    break

            candidate = list(diff_lines[start:end])
            candidate_text = "\n".join(candidate)

            # Shrink if still too long
            while self.count_tokens(candidate_text) > max_tokens and len(candidate) > 3:
                # Remove lines from both ends, preferring the far end from target
                target_rel = target_idx - start
                if target_rel < 0:
                    target_rel = 0
                if len(candidate) - 1 - target_rel > target_rel:
                    candidate.pop()
                    end -= 1
                else:
                    candidate.pop(0)
                    start += 1
                candidate_text = "\n".join(candidate)

            result: list[str] = []
            if start > 0:
                result.append(f"... ({start} lines truncated above) ...")
            result.extend(candidate)
            if end < len(diff_lines):
                result.append(f"... ({len(diff_lines) - end} lines truncated below) ...")
            return result
        else:
            # No target: keep from the beginning
            result = []
            current_tokens = 0
            for line in diff_lines:
                line_tokens = self.count_tokens(line + "\n")
                if current_tokens + line_tokens > max_tokens:
                    remaining = len(diff_lines) - len(result)
                    result.append(f"... ({remaining} lines truncated) ...")
                    break
                result.append(line)
                current_tokens += line_tokens
            return result

    def _truncate_output(self, text: str) -> str:
        """Truncate output text to fit within max_output_tokens.

        Tries to cut at a sentence boundary.
        """
        return self._truncate_text_to_tokens(text, self.max_output_tokens, prefer_sentence_boundary=True)

    def _truncate_text_to_tokens(
        self,
        text: str,
        max_tokens: int,
        prefer_sentence_boundary: bool = False,
    ) -> str:
        """Truncate text to fit within a token budget."""
        tokens = self._encoding.encode(text)
        if len(tokens) <= max_tokens:
            return text

        # Leave room for truncation marker
        truncated_tokens = tokens[: max_tokens - 5]
        truncated_text = self._encoding.decode(truncated_tokens)

        if prefer_sentence_boundary:
            # Try to cut at last sentence-ending punctuation
            for sep in [". ", ".\n", "! ", "!\n", "? ", "?\n"]:
                last_idx = truncated_text.rfind(sep)
                if last_idx > len(truncated_text) * 0.5:
                    truncated_text = truncated_text[: last_idx + 1]
                    break

        return truncated_text + " [truncated]"

    @staticmethod
    def _find_line_in_diff(diff_lines: list[str], target_line: int) -> int | None:
        """Find the diff_lines index corresponding to a file line number."""
        current_new_line = 0

        for i, line in enumerate(diff_lines):
            hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if hunk_match:
                current_new_line = int(hunk_match.group(1))
                continue

            if line.startswith("-"):
                continue

            if current_new_line == target_line:
                return i

            if not line.startswith("-"):
                current_new_line += 1

        return None
