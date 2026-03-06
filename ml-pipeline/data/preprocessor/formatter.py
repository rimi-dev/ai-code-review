"""Instruction-tuning format converter for PR review data.

Converts raw PR data into instruction / input / output triples suitable
for supervised fine-tuning of a code review model.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default system prompt for code reviewer role
DEFAULT_SYSTEM_PROMPT = (
    "You are an expert code reviewer. Analyze the given code diff and provide a constructive, "
    "specific, and actionable review comment. Focus on code quality, potential bugs, performance, "
    "security, and best practices. Be concise but thorough."
)

# Maximum diff length in characters before truncation (as a safety net before tokenization)
DEFAULT_MAX_DIFF_CHARS = 8000

# Context lines to keep around the comment location during truncation
DEFAULT_CONTEXT_LINES = 30


@dataclass
class FormattingStats:
    """Statistics from the formatting process."""

    total_prs: int = 0
    total_comments: int = 0
    total_pairs_generated: int = 0
    skipped_no_diff: int = 0
    skipped_no_comment_mapping: int = 0
    truncated_diffs: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_prs": self.total_prs,
            "total_comments": self.total_comments,
            "total_pairs_generated": self.total_pairs_generated,
            "skipped_no_diff": self.skipped_no_diff,
            "skipped_no_comment_mapping": self.skipped_no_comment_mapping,
            "truncated_diffs": self.truncated_diffs,
        }


@dataclass
class InstructionSample:
    """A single instruction-tuning sample."""

    instruction: str
    input: str
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instruction": self.instruction,
            "input": self.input,
            "output": self.output,
            **self.metadata,
        }


class InstructionFormatter:
    """Converts raw PR review data into instruction-tuning format.

    Expected input schema per PR document (from MongoDB):
    {
        "repo": "owner/repo",
        "pr_number": 123,
        "title": "PR title",
        "files": [
            {
                "path": "src/foo.py",
                "language": "Python",
                "diff": "unified diff text",
                "patch": "patch text (alternative to diff)"
            }
        ],
        "comments": [
            {
                "author": "reviewer",
                "body": "review comment",
                "path": "src/foo.py",
                "line": 42,
                "side": "RIGHT",
                "diff_hunk": "@@  ... @@ context"
            }
        ]
    }

    Produces one InstructionSample per (file, comment) pair.
    """

    def __init__(
        self,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS,
        context_lines: int = DEFAULT_CONTEXT_LINES,
    ) -> None:
        self.system_prompt = system_prompt
        self.max_diff_chars = max_diff_chars
        self.context_lines = context_lines
        self._stats = FormattingStats()

    @property
    def stats(self) -> FormattingStats:
        return self._stats

    def format_batch(self, prs: list[dict[str, Any]]) -> list[InstructionSample]:
        """Format a batch of PR documents into instruction samples.

        Args:
            prs: List of PR documents from MongoDB.

        Returns:
            List of InstructionSample objects.
        """
        self._stats = FormattingStats(total_prs=len(prs))
        samples: list[InstructionSample] = []

        for pr in prs:
            pr_samples = self._format_pr(pr)
            samples.extend(pr_samples)

        self._stats.total_pairs_generated = len(samples)
        logger.info(
            "Formatting complete: %d PRs -> %d instruction pairs (%d comments processed)",
            self._stats.total_prs,
            self._stats.total_pairs_generated,
            self._stats.total_comments,
        )
        return samples

    def _format_pr(self, pr: dict[str, Any]) -> list[InstructionSample]:
        """Format a single PR into instruction samples."""
        files = pr.get("files", [])
        comments = pr.get("comments", [])
        repo = pr.get("repo", "unknown")
        pr_number = pr.get("pr_number", 0)

        # Build file lookup: path -> file data
        file_lookup: dict[str, dict[str, Any]] = {}
        for f in files:
            path = f.get("path", "")
            if path:
                file_lookup[path] = f

        samples: list[InstructionSample] = []

        for comment in comments:
            self._stats.total_comments += 1
            path = comment.get("path", "")
            body = comment.get("body", "")

            if not path or not body:
                self._stats.skipped_no_comment_mapping += 1
                continue

            file_data = file_lookup.get(path)
            if file_data is None:
                self._stats.skipped_no_comment_mapping += 1
                continue

            diff = file_data.get("diff") or file_data.get("patch", "")
            if not diff:
                self._stats.skipped_no_diff += 1
                continue

            language = file_data.get("language", self._detect_language(path))
            comment_line = comment.get("line") or comment.get("original_line")
            diff_hunk = comment.get("diff_hunk", "")

            # Truncate diff if too long, keeping context around comment location
            processed_diff = self._truncate_diff(
                diff=diff,
                comment_line=comment_line,
                diff_hunk=diff_hunk,
            )

            input_text = self._build_input(
                path=path,
                language=language,
                diff=processed_diff,
            )

            sample = InstructionSample(
                instruction=self.system_prompt,
                input=input_text,
                output=body,
                metadata={
                    "repo": repo,
                    "pr_number": pr_number,
                    "file_path": path,
                    "language": language,
                    "comment_line": comment_line,
                },
            )
            samples.append(sample)

        return samples

    def _build_input(self, path: str, language: str, diff: str) -> str:
        """Build the input text combining file path, language, and diff."""
        parts = [
            f"File: {path}",
            f"Language: {language}",
            "",
            "Diff:",
            "```diff",
            diff,
            "```",
        ]
        return "\n".join(parts)

    def _truncate_diff(
        self,
        diff: str,
        comment_line: int | None,
        diff_hunk: str,
    ) -> str:
        """Truncate a long diff while keeping relevant context around the comment.

        Strategy:
        1. If diff is short enough, return as-is.
        2. Try to locate the comment position in the diff.
        3. Keep `context_lines` lines above and below the comment location.
        4. If comment position can't be determined, keep the beginning of the diff.
        """
        if len(diff) <= self.max_diff_chars:
            return diff

        self._stats.truncated_diffs += 1
        lines = diff.split("\n")

        # Try to find the comment location
        target_line_idx = self._find_comment_position(lines, comment_line, diff_hunk)

        if target_line_idx is not None:
            start = max(0, target_line_idx - self.context_lines)
            end = min(len(lines), target_line_idx + self.context_lines + 1)

            # Include the nearest hunk header above the context window
            hunk_header_idx = self._find_nearest_hunk_header(lines, start)
            if hunk_header_idx is not None and hunk_header_idx < start:
                start = hunk_header_idx

            truncated_lines = lines[start:end]

            # Add truncation markers
            result_parts: list[str] = []
            if start > 0:
                result_parts.append(f"... ({start} lines above truncated) ...")
            result_parts.extend(truncated_lines)
            if end < len(lines):
                result_parts.append(f"... ({len(lines) - end} lines below truncated) ...")

            result = "\n".join(result_parts)
        else:
            # Fallback: keep lines from the beginning up to the char limit
            result = self._truncate_by_chars(diff)

        return result

    def _find_comment_position(
        self,
        diff_lines: list[str],
        comment_line: int | None,
        diff_hunk: str,
    ) -> int | None:
        """Find the index in diff_lines closest to the comment location.

        Uses two strategies:
        1. Match the diff_hunk text in the diff.
        2. Match by line number from hunk headers.
        """
        # Strategy 1: Match diff_hunk
        if diff_hunk:
            hunk_lines = diff_hunk.strip().split("\n")
            if hunk_lines:
                last_hunk_line = hunk_lines[-1].strip()
                for i, line in enumerate(diff_lines):
                    if line.strip() == last_hunk_line:
                        return i

        # Strategy 2: Match by line number in hunk headers
        if comment_line is not None:
            best_idx: int | None = None
            current_new_line = 0

            for i, line in enumerate(diff_lines):
                hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
                if hunk_match:
                    current_new_line = int(hunk_match.group(1))
                    continue

                if line.startswith("-"):
                    continue

                if current_new_line == comment_line:
                    best_idx = i
                    break

                if not line.startswith("-"):
                    current_new_line += 1

            return best_idx

        return None

    @staticmethod
    def _find_nearest_hunk_header(lines: list[str], before_idx: int) -> int | None:
        """Find the nearest @@ hunk header at or before the given index."""
        for i in range(before_idx, -1, -1):
            if lines[i].startswith("@@"):
                return i
        return None

    def _truncate_by_chars(self, diff: str) -> str:
        """Simple character-based truncation keeping the beginning of the diff."""
        truncated = diff[: self.max_diff_chars]
        # Try to cut at a line boundary
        last_newline = truncated.rfind("\n")
        if last_newline > self.max_diff_chars * 0.5:
            truncated = truncated[:last_newline]

        remaining_chars = len(diff) - len(truncated)
        return truncated + f"\n... ({remaining_chars} characters truncated) ..."

    @staticmethod
    def _detect_language(path: str) -> str:
        """Detect programming language from file extension."""
        ext_map: dict[str, str] = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".jsx": "JavaScript",
            ".java": "Java",
            ".kt": "Kotlin",
            ".kts": "Kotlin",
            ".go": "Go",
            ".rs": "Rust",
            ".rb": "Ruby",
            ".php": "PHP",
            ".cs": "C#",
            ".cpp": "C++",
            ".cc": "C++",
            ".c": "C",
            ".h": "C",
            ".hpp": "C++",
            ".swift": "Swift",
            ".scala": "Scala",
            ".r": "R",
            ".R": "R",
            ".sh": "Shell",
            ".bash": "Shell",
            ".zsh": "Shell",
            ".yaml": "YAML",
            ".yml": "YAML",
            ".json": "JSON",
            ".xml": "XML",
            ".html": "HTML",
            ".css": "CSS",
            ".scss": "SCSS",
            ".less": "Less",
            ".sql": "SQL",
            ".md": "Markdown",
            ".dockerfile": "Dockerfile",
            ".tf": "Terraform",
            ".hcl": "HCL",
            ".vue": "Vue",
            ".svelte": "Svelte",
            ".dart": "Dart",
            ".ex": "Elixir",
            ".exs": "Elixir",
            ".erl": "Erlang",
            ".hs": "Haskell",
            ".lua": "Lua",
            ".pl": "Perl",
            ".pm": "Perl",
        }

        # Handle Dockerfile explicitly
        lower_path = path.lower()
        if lower_path.endswith("dockerfile") or "/dockerfile" in lower_path:
            return "Dockerfile"

        # Extract extension
        dot_idx = path.rfind(".")
        if dot_idx == -1:
            return "Unknown"

        ext = path[dot_idx:]
        return ext_map.get(ext, ext_map.get(ext.lower(), "Unknown"))
