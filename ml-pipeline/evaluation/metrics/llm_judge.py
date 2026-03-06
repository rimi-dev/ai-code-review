"""LLM-as-Judge evaluation using Claude API for code review quality assessment.

Rates model-generated code reviews on 5 quality dimensions using Claude as
an automated evaluator, with rate limiting, batching, and detailed scoring.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

# Evaluation dimensions and their descriptions
EVALUATION_DIMENSIONS: dict[str, str] = {
    "accuracy": (
        "Is the review technically correct? Does it accurately identify real issues "
        "in the code, or does it contain false positives or incorrect claims?"
    ),
    "helpfulness": (
        "Is the review helpful to the developer? Does it provide useful information "
        "that would improve the code or the developer's understanding?"
    ),
    "specificity": (
        "Is the review specific and concrete? Does it point to exact lines, patterns, "
        "or issues rather than making vague or generic statements?"
    ),
    "code_awareness": (
        "Does the review demonstrate understanding of the code context? Does it "
        "consider the programming language, framework conventions, and the broader "
        "codebase context?"
    ),
    "actionability": (
        "Is the review actionable? Does it provide clear guidance on what should be "
        "changed and how, rather than just identifying problems?"
    ),
}

# The evaluation prompt template
_JUDGE_SYSTEM_PROMPT = """You are an expert evaluator of automated code review quality.
You will be given a code diff and two code reviews: a reference review (human-written) and a candidate review (model-generated).

Rate the CANDIDATE review on these 5 dimensions using a 1-5 scale:

**Dimensions:**
{dimensions}

**Rating Scale:**
1 = Very Poor: Completely misses the point, incorrect, or unhelpful
2 = Poor: Has major issues, largely unhelpful
3 = Adequate: Somewhat useful but has notable gaps
4 = Good: Mostly accurate and helpful with minor issues
5 = Excellent: Highly accurate, specific, and actionable

Respond ONLY with a JSON object in this exact format:
{{
  "accuracy": <1-5>,
  "helpfulness": <1-5>,
  "specificity": <1-5>,
  "code_awareness": <1-5>,
  "actionability": <1-5>,
  "overall_reasoning": "<brief explanation of your ratings>"
}}"""

_JUDGE_USER_TEMPLATE = """## Code Diff
```
{diff}
```

## Reference Review (Human)
{reference}

## Candidate Review (Model)
{candidate}

Rate the candidate review on the 5 dimensions (1-5 scale). Respond with JSON only."""


@dataclass
class SampleScore:
    """Evaluation scores for a single sample."""

    sample_idx: int
    accuracy: int = 0
    helpfulness: int = 0
    specificity: int = 0
    code_awareness: int = 0
    actionability: int = 0
    overall_reasoning: str = ""
    mean_score: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_idx": self.sample_idx,
            "accuracy": self.accuracy,
            "helpfulness": self.helpfulness,
            "specificity": self.specificity,
            "code_awareness": self.code_awareness,
            "actionability": self.actionability,
            "mean_score": round(self.mean_score, 2),
            "overall_reasoning": self.overall_reasoning,
            "error": self.error,
        }


@dataclass
class JudgeResult:
    """Aggregated LLM judge evaluation results."""

    per_sample_scores: list[SampleScore] = field(default_factory=list)

    # Mean scores per dimension
    mean_accuracy: float = 0.0
    mean_helpfulness: float = 0.0
    mean_specificity: float = 0.0
    mean_code_awareness: float = 0.0
    mean_actionability: float = 0.0
    overall_mean: float = 0.0

    num_samples: int = 0
    num_errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean_accuracy": round(self.mean_accuracy, 3),
            "mean_helpfulness": round(self.mean_helpfulness, 3),
            "mean_specificity": round(self.mean_specificity, 3),
            "mean_code_awareness": round(self.mean_code_awareness, 3),
            "mean_actionability": round(self.mean_actionability, 3),
            "overall_mean": round(self.overall_mean, 3),
            "num_samples": self.num_samples,
            "num_errors": self.num_errors,
        }


class LLMJudge:
    """Uses Claude API to evaluate code review quality on multiple dimensions.

    Sends each (diff, reference, candidate) triple to Claude for evaluation,
    with rate limiting to stay within API quotas and retry logic for transient errors.

    Args:
        model: Claude model identifier to use as judge.
        api_key: Anthropic API key. If None, reads from ANTHROPIC_API_KEY env var.
        max_tokens: Maximum tokens for the judge response.
        requests_per_minute: Rate limit for API calls.
        max_retries: Maximum retry attempts for failed API calls.
        retry_base_delay: Base delay in seconds for exponential backoff.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        max_tokens: int = 1024,
        requests_per_minute: int = 30,
        max_retries: int = 3,
        retry_base_delay: float = 2.0,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.requests_per_minute = requests_per_minute
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay

        self._client = anthropic.Anthropic(api_key=api_key)
        self._min_interval = 60.0 / requests_per_minute
        self._last_request_time: float = 0.0

        # Build system prompt with dimension descriptions
        dims_text = "\n".join(
            f"- **{name.replace('_', ' ').title()}**: {desc}"
            for name, desc in EVALUATION_DIMENSIONS.items()
        )
        self._system_prompt = _JUDGE_SYSTEM_PROMPT.format(dimensions=dims_text)

    def evaluate_batch(
        self,
        diffs: list[str],
        references: list[str],
        candidates: list[str],
    ) -> JudgeResult:
        """Evaluate a batch of code review samples using Claude as judge.

        Args:
            diffs: List of code diffs that were reviewed.
            references: List of human-written reference reviews.
            candidates: List of model-generated candidate reviews.

        Returns:
            JudgeResult with per-sample and aggregate scores.

        Raises:
            ValueError: If input lists have different lengths.
        """
        if not (len(diffs) == len(references) == len(candidates)):
            msg = (
                f"All input lists must have the same length, "
                f"got diffs={len(diffs)}, references={len(references)}, candidates={len(candidates)}"
            )
            raise ValueError(msg)

        num_samples = len(diffs)
        logger.info("Starting LLM judge evaluation for %d samples (rate limit: %d RPM)",
                     num_samples, self.requests_per_minute)

        scores: list[SampleScore] = []
        num_errors = 0

        for idx in range(num_samples):
            score = self._evaluate_single(
                sample_idx=idx,
                diff=diffs[idx],
                reference=references[idx],
                candidate=candidates[idx],
            )
            scores.append(score)
            if score.error:
                num_errors += 1

            if (idx + 1) % 10 == 0:
                logger.info("  Evaluated %d/%d samples (%d errors)", idx + 1, num_samples, num_errors)

        result = self._aggregate_scores(scores, num_errors)
        logger.info(
            "LLM judge complete: %d samples, overall_mean=%.2f, errors=%d",
            num_samples, result.overall_mean, num_errors,
        )
        return result

    def _evaluate_single(
        self,
        sample_idx: int,
        diff: str,
        reference: str,
        candidate: str,
    ) -> SampleScore:
        """Evaluate a single sample with retry logic and rate limiting.

        Args:
            sample_idx: Index of the sample in the batch.
            diff: Code diff text.
            reference: Human-written reference review.
            candidate: Model-generated candidate review.

        Returns:
            SampleScore with ratings or error information.
        """
        # Truncate diff if too long to keep within context window
        max_diff_chars = 6000
        if len(diff) > max_diff_chars:
            diff = diff[:max_diff_chars] + "\n... [truncated]"

        user_message = _JUDGE_USER_TEMPLATE.format(
            diff=diff,
            reference=reference,
            candidate=candidate,
        )

        for attempt in range(self.max_retries):
            try:
                # Rate limiting
                self._wait_for_rate_limit()

                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=self._system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                )

                self._last_request_time = time.monotonic()

                # Parse response
                response_text = response.content[0].text.strip()
                return self._parse_response(sample_idx, response_text)

            except anthropic.RateLimitError:
                wait_time = self.retry_base_delay * (2 ** attempt)
                logger.warning(
                    "Rate limited on sample %d, waiting %.1fs (attempt %d/%d)",
                    sample_idx, wait_time, attempt + 1, self.max_retries,
                )
                time.sleep(wait_time)

            except anthropic.APIError as e:
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_base_delay * (2 ** attempt)
                    logger.warning(
                        "API error on sample %d: %s, retrying in %.1fs (attempt %d/%d)",
                        sample_idx, str(e), wait_time, attempt + 1, self.max_retries,
                    )
                    time.sleep(wait_time)
                else:
                    logger.error("API error on sample %d after %d retries: %s",
                                 sample_idx, self.max_retries, str(e))
                    return SampleScore(sample_idx=sample_idx, error=str(e))

            except Exception as e:
                logger.error("Unexpected error on sample %d: %s", sample_idx, str(e))
                return SampleScore(sample_idx=sample_idx, error=str(e))

        return SampleScore(sample_idx=sample_idx, error="Max retries exceeded")

    def _wait_for_rate_limit(self) -> None:
        """Wait if necessary to respect rate limiting."""
        if self._last_request_time > 0:
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self._min_interval:
                sleep_time = self._min_interval - elapsed
                time.sleep(sleep_time)

    def _parse_response(self, sample_idx: int, response_text: str) -> SampleScore:
        """Parse the JSON response from Claude into a SampleScore.

        Handles various JSON formatting quirks (code blocks, extra text).

        Args:
            sample_idx: Index of the sample.
            response_text: Raw text response from Claude.

        Returns:
            Parsed SampleScore.
        """
        # Strip markdown code block if present
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse JSON for sample %d: %s", sample_idx, str(e))
            return SampleScore(sample_idx=sample_idx, error=f"JSON parse error: {e}")

        # Extract and validate scores
        dimensions = ["accuracy", "helpfulness", "specificity", "code_awareness", "actionability"]
        scores: dict[str, int] = {}

        for dim in dimensions:
            raw_value = data.get(dim, 0)
            try:
                value = int(raw_value)
                value = max(1, min(5, value))  # Clamp to 1-5
            except (TypeError, ValueError):
                value = 0
            scores[dim] = value

        mean_score = sum(scores.values()) / len(dimensions) if all(scores.values()) else 0.0

        return SampleScore(
            sample_idx=sample_idx,
            accuracy=scores["accuracy"],
            helpfulness=scores["helpfulness"],
            specificity=scores["specificity"],
            code_awareness=scores["code_awareness"],
            actionability=scores["actionability"],
            overall_reasoning=data.get("overall_reasoning", ""),
            mean_score=mean_score,
        )

    @staticmethod
    def _aggregate_scores(scores: list[SampleScore], num_errors: int) -> JudgeResult:
        """Aggregate per-sample scores into overall results.

        Args:
            scores: List of per-sample scores.
            num_errors: Count of samples with errors.

        Returns:
            JudgeResult with aggregate statistics.
        """
        valid_scores = [s for s in scores if s.error is None and s.mean_score > 0]
        n = len(valid_scores)

        if n == 0:
            return JudgeResult(
                per_sample_scores=scores,
                num_samples=len(scores),
                num_errors=num_errors,
            )

        return JudgeResult(
            per_sample_scores=scores,
            mean_accuracy=sum(s.accuracy for s in valid_scores) / n,
            mean_helpfulness=sum(s.helpfulness for s in valid_scores) / n,
            mean_specificity=sum(s.specificity for s in valid_scores) / n,
            mean_code_awareness=sum(s.code_awareness for s in valid_scores) / n,
            mean_actionability=sum(s.actionability for s in valid_scores) / n,
            overall_mean=sum(s.mean_score for s in valid_scores) / n,
            num_samples=len(scores),
            num_errors=num_errors,
        )

    def save_scores(self, result: JudgeResult, output_path: str | Path) -> None:
        """Save detailed per-sample scores to a JSON file.

        Args:
            result: JudgeResult to save.
            output_path: Path to the output JSON file.
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "summary": result.to_dict(),
            "per_sample": [s.to_dict() for s in result.per_sample_scores],
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("LLM judge scores saved to %s", path)
