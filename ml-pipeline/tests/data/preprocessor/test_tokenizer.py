"""Tests for the TokenManager module."""

from __future__ import annotations

import pytest

from data.preprocessor.tokenizer import TokenManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def token_manager() -> TokenManager:
    return TokenManager(max_input_tokens=2048, max_output_tokens=512)


@pytest.fixture
def small_token_manager() -> TokenManager:
    """A token manager with small limits for testing truncation."""
    return TokenManager(max_input_tokens=100, max_output_tokens=50, truncation_context_lines=3)


def _make_sample(
    instruction: str = "You are a code reviewer.",
    input_text: str = "File: src/main.py\nLanguage: Python\n\nDiff:\n```diff\n@@ -1,3 +1,4 @@\n def foo():\n     x = 1\n+    y = 2\n     return x\n```",
    output_text: str = "Consider returning y as well since you just assigned it.",
    comment_line: int | None = 3,
) -> dict:
    sample: dict = {
        "instruction": instruction,
        "input": input_text,
        "output": output_text,
    }
    if comment_line is not None:
        sample["comment_line"] = comment_line
    return sample


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

class TestTokenCounting:
    """Tests for basic token counting functionality."""

    def test_count_empty_string(self, token_manager: TokenManager) -> None:
        assert token_manager.count_tokens("") == 0

    def test_count_simple_text(self, token_manager: TokenManager) -> None:
        count = token_manager.count_tokens("Hello, world!")
        assert count > 0
        assert count < 10  # Should be a few tokens

    def test_count_code_text(self, token_manager: TokenManager) -> None:
        code = "def fibonacci(n: int) -> int:\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)"
        count = token_manager.count_tokens(code)
        assert count > 10

    def test_count_consistency(self, token_manager: TokenManager) -> None:
        text = "The quick brown fox jumps over the lazy dog."
        count1 = token_manager.count_tokens(text)
        count2 = token_manager.count_tokens(text)
        assert count1 == count2

    def test_longer_text_has_more_tokens(self, token_manager: TokenManager) -> None:
        short = "Hello"
        long = "Hello, this is a much longer text with many more words in it."
        assert token_manager.count_tokens(long) > token_manager.count_tokens(short)


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

class TestBatchProcessing:
    """Tests for batch processing with token limits."""

    def test_process_within_limits(self, token_manager: TokenManager) -> None:
        samples = [_make_sample()]
        result = token_manager.process_batch(samples)
        assert len(result) == 1
        assert "input_tokens" in result[0]
        assert "output_tokens" in result[0]
        assert result[0]["input_tokens"] <= 2048
        assert result[0]["output_tokens"] <= 512

    def test_process_empty_batch(self, token_manager: TokenManager) -> None:
        result = token_manager.process_batch([])
        assert len(result) == 0

    def test_token_counts_are_positive(self, token_manager: TokenManager) -> None:
        samples = [_make_sample()]
        result = token_manager.process_batch(samples)
        assert result[0]["input_tokens"] > 0
        assert result[0]["output_tokens"] > 0

    def test_multiple_samples(self, token_manager: TokenManager) -> None:
        samples = [_make_sample() for _ in range(5)]
        result = token_manager.process_batch(samples)
        assert len(result) == 5

    def test_stats_tracking(self, token_manager: TokenManager) -> None:
        samples = [_make_sample() for _ in range(3)]
        token_manager.process_batch(samples)
        stats = token_manager.stats.to_dict()

        assert stats["total_samples"] == 3
        assert stats["input_tokens"]["count"] == 3
        assert stats["output_tokens"]["count"] == 3
        assert stats["input_tokens"]["mean"] > 0
        assert stats["output_tokens"]["mean"] > 0


# ---------------------------------------------------------------------------
# Truncation logic
# ---------------------------------------------------------------------------

class TestTruncation:
    """Tests for input and output truncation."""

    def test_long_input_gets_truncated(self, small_token_manager: TokenManager) -> None:
        # Create a very long input that exceeds the 100-token limit
        long_lines = "\n".join([f"+line {i}: some repetitive code here" for i in range(200)])
        long_input = f"File: src/main.py\nLanguage: Python\n\nDiff:\n```diff\n@@ -1,200 +1,200 @@\n{long_lines}\n```"
        sample = _make_sample(input_text=long_input)

        result = small_token_manager.process_batch([sample])
        assert len(result) == 1
        assert result[0]["input_tokens"] <= 100
        assert small_token_manager.stats.truncated_inputs == 1

    def test_long_output_gets_truncated(self, small_token_manager: TokenManager) -> None:
        long_output = " ".join(["This is a very long review comment."] * 50)
        sample = _make_sample(output_text=long_output)

        result = small_token_manager.process_batch([sample])
        assert len(result) == 1
        assert result[0]["output_tokens"] <= 50
        assert small_token_manager.stats.truncated_outputs == 1

    def test_truncated_output_has_marker(self, small_token_manager: TokenManager) -> None:
        long_output = " ".join(["This is a repetitive review comment sentence."] * 50)
        sample = _make_sample(output_text=long_output)

        result = small_token_manager.process_batch([sample])
        assert "[truncated]" in result[0]["output"]

    def test_truncation_preserves_diff_structure(self, small_token_manager: TokenManager) -> None:
        """Truncated input should still contain the diff markers."""
        long_lines = "\n".join([f"+line {i}" for i in range(200)])
        long_input = f"File: src/main.py\nLanguage: Python\n\nDiff:\n```diff\n@@ -1,200 +1,200 @@\n{long_lines}\n```"
        sample = _make_sample(input_text=long_input)

        result = small_token_manager.process_batch([sample])
        assert len(result) == 1
        # Should still have file header
        assert "File: src/main.py" in result[0]["input"]

    def test_truncation_keeps_context_around_comment_line(self) -> None:
        """When comment_line is provided, truncation should keep that area."""
        # Use a generous enough budget that the sample won't be dropped
        tm = TokenManager(max_input_tokens=300, max_output_tokens=512, truncation_context_lines=5)

        lines = []
        for i in range(1, 101):
            lines.append(f"+line {i}: code content")
        diff_text = "@@ -1,100 +1,100 @@\n" + "\n".join(lines)
        input_text = f"File: src/main.py\nLanguage: Python\n\nDiff:\n```diff\n{diff_text}\n```"

        sample = _make_sample(input_text=input_text, comment_line=50)
        result = tm.process_batch([sample])

        assert len(result) == 1
        # The area around line 50 should be preserved
        output_input = result[0]["input"]
        assert "+line 50" in output_input
        assert tm.stats.truncated_inputs == 1

    def test_sample_dropped_when_instruction_too_long(self) -> None:
        """If instruction alone exceeds max, sample should be dropped."""
        tm = TokenManager(max_input_tokens=10, max_output_tokens=512)
        long_instruction = " ".join(["word"] * 100)
        sample = _make_sample(instruction=long_instruction)

        result = tm.process_batch([sample])
        assert len(result) == 0
        assert tm.stats.dropped_samples == 1

    def test_stats_distribution(self, token_manager: TokenManager) -> None:
        samples = [_make_sample() for _ in range(10)]
        token_manager.process_batch(samples)
        stats = token_manager.stats.to_dict()

        input_dist = stats["input_tokens"]
        output_dist = stats["output_tokens"]

        assert input_dist["count"] == 10
        assert input_dist["min"] > 0
        assert input_dist["max"] >= input_dist["min"]
        assert input_dist["mean"] > 0
        assert input_dist["median"] > 0
        assert input_dist["p95"] >= input_dist["median"]
        assert input_dist["p99"] >= input_dist["p95"]

        assert output_dist["count"] == 10
