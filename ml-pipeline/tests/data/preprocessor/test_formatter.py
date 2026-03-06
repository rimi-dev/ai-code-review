"""Tests for the InstructionFormatter module."""

from __future__ import annotations

import pytest

from data.preprocessor.formatter import InstructionFormatter, InstructionSample, DEFAULT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def formatter() -> InstructionFormatter:
    return InstructionFormatter()


def _make_pr(
    repo: str = "owner/repo",
    pr_number: int = 42,
    files: list[dict] | None = None,
    comments: list[dict] | None = None,
) -> dict:
    return {
        "repo": repo,
        "pr_number": pr_number,
        "title": "Fix null check",
        "files": files or [],
        "comments": comments or [],
    }


def _make_file(
    path: str = "src/main.py",
    language: str = "Python",
    diff: str = "@@ -10,6 +10,8 @@\n def foo():\n     x = 1\n+    if x is None:\n+        return\n     return x\n",
) -> dict:
    return {"path": path, "language": language, "diff": diff}


def _make_comment(
    path: str = "src/main.py",
    body: str = "Good null check addition.",
    line: int = 12,
    diff_hunk: str = "@@ -10,6 +10,8 @@\n def foo():\n     x = 1\n+    if x is None:",
) -> dict:
    return {"author": "reviewer", "body": body, "path": path, "line": line, "diff_hunk": diff_hunk}


# ---------------------------------------------------------------------------
# Instruction format conversion
# ---------------------------------------------------------------------------

class TestInstructionFormat:
    """Tests for instruction-tuning format conversion."""

    def test_basic_format_conversion(self, formatter: InstructionFormatter) -> None:
        pr = _make_pr(
            files=[_make_file()],
            comments=[_make_comment()],
        )
        samples = formatter.format_batch([pr])

        assert len(samples) == 1
        sample = samples[0]
        assert isinstance(sample, InstructionSample)
        assert sample.instruction == DEFAULT_SYSTEM_PROMPT
        assert "File: src/main.py" in sample.input
        assert "Language: Python" in sample.input
        assert "```diff" in sample.input
        assert sample.output == "Good null check addition."

    def test_custom_system_prompt(self) -> None:
        custom_prompt = "You are a security-focused code reviewer."
        formatter = InstructionFormatter(system_prompt=custom_prompt)
        pr = _make_pr(files=[_make_file()], comments=[_make_comment()])
        samples = formatter.format_batch([pr])

        assert samples[0].instruction == custom_prompt

    def test_metadata_included(self, formatter: InstructionFormatter) -> None:
        pr = _make_pr(
            repo="test-org/test-repo",
            pr_number=99,
            files=[_make_file()],
            comments=[_make_comment(line=15)],
        )
        samples = formatter.format_batch([pr])

        assert samples[0].metadata["repo"] == "test-org/test-repo"
        assert samples[0].metadata["pr_number"] == 99
        assert samples[0].metadata["file_path"] == "src/main.py"
        assert samples[0].metadata["language"] == "Python"
        assert samples[0].metadata["comment_line"] == 15

    def test_to_dict(self, formatter: InstructionFormatter) -> None:
        pr = _make_pr(files=[_make_file()], comments=[_make_comment()])
        samples = formatter.format_batch([pr])
        d = samples[0].to_dict()

        assert "instruction" in d
        assert "input" in d
        assert "output" in d
        assert "repo" in d  # metadata flattened

    def test_language_detection_from_path(self, formatter: InstructionFormatter) -> None:
        """When file has no explicit language, detect from extension."""
        file_data = _make_file(path="src/utils.ts", language="")
        # Remove explicit language to trigger detection
        del file_data["language"]
        pr = _make_pr(
            files=[file_data],
            comments=[_make_comment(path="src/utils.ts")],
        )
        samples = formatter.format_batch([pr])
        assert samples[0].metadata["language"] == "TypeScript"


# ---------------------------------------------------------------------------
# Diff-to-review pairing
# ---------------------------------------------------------------------------

class TestDiffReviewPairing:
    """Tests for mapping comments to their corresponding diffs."""

    def test_multi_file_pr_generates_per_file_pairs(self, formatter: InstructionFormatter) -> None:
        pr = _make_pr(
            files=[
                _make_file(path="src/a.py", language="Python"),
                _make_file(path="src/b.ts", language="TypeScript"),
            ],
            comments=[
                _make_comment(path="src/a.py", body="Fix error handling in this Python file with proper try/except."),
                _make_comment(path="src/b.ts", body="Add type annotation to this TypeScript function parameter."),
            ],
        )
        samples = formatter.format_batch([pr])

        assert len(samples) == 2
        paths = {s.metadata["file_path"] for s in samples}
        assert paths == {"src/a.py", "src/b.ts"}

    def test_multiple_comments_on_same_file(self, formatter: InstructionFormatter) -> None:
        pr = _make_pr(
            files=[_make_file()],
            comments=[
                _make_comment(body="First comment about this code.", line=12),
                _make_comment(body="Second comment about that code.", line=15),
            ],
        )
        samples = formatter.format_batch([pr])
        assert len(samples) == 2

    def test_comment_without_matching_file_is_skipped(self, formatter: InstructionFormatter) -> None:
        pr = _make_pr(
            files=[_make_file(path="src/a.py")],
            comments=[_make_comment(path="src/b.py", body="Orphan comment.")],
        )
        samples = formatter.format_batch([pr])
        assert len(samples) == 0
        assert formatter.stats.skipped_no_comment_mapping == 1

    def test_comment_on_file_without_diff_is_skipped(self, formatter: InstructionFormatter) -> None:
        file_data = _make_file(path="src/main.py", diff="")
        pr = _make_pr(
            files=[file_data],
            comments=[_make_comment(path="src/main.py")],
        )
        samples = formatter.format_batch([pr])
        assert len(samples) == 0
        assert formatter.stats.skipped_no_diff == 1

    def test_empty_pr(self, formatter: InstructionFormatter) -> None:
        pr = _make_pr(files=[], comments=[])
        samples = formatter.format_batch([pr])
        assert len(samples) == 0

    def test_multiple_prs(self, formatter: InstructionFormatter) -> None:
        prs = [
            _make_pr(pr_number=1, files=[_make_file()], comments=[_make_comment()]),
            _make_pr(pr_number=2, files=[_make_file()], comments=[_make_comment()]),
        ]
        samples = formatter.format_batch(prs)
        assert len(samples) == 2
        assert formatter.stats.total_prs == 2

    def test_uses_patch_field_when_diff_missing(self, formatter: InstructionFormatter) -> None:
        file_data = {"path": "src/main.py", "language": "Python", "patch": "@@ -1,3 +1,4 @@\n+new line\n context"}
        pr = _make_pr(
            files=[file_data],
            comments=[_make_comment()],
        )
        samples = formatter.format_batch([pr])
        assert len(samples) == 1
        assert "+new line" in samples[0].input


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

class TestTruncation:
    """Tests for diff truncation behavior."""

    def test_short_diff_not_truncated(self, formatter: InstructionFormatter) -> None:
        short_diff = "@@ -1,3 +1,4 @@\n context\n+added\n context"
        pr = _make_pr(
            files=[_make_file(diff=short_diff)],
            comments=[_make_comment()],
        )
        samples = formatter.format_batch([pr])
        assert "truncated" not in samples[0].input.lower()

    def test_long_diff_gets_truncated(self) -> None:
        formatter = InstructionFormatter(max_diff_chars=200, context_lines=5)
        # Create a long diff
        lines = ["@@ -1,100 +1,100 @@"]
        for i in range(100):
            lines.append(f"+line {i}: some code content here that takes up space")
        long_diff = "\n".join(lines)

        pr = _make_pr(
            files=[_make_file(diff=long_diff)],
            comments=[_make_comment(line=50)],
        )
        samples = formatter.format_batch([pr])
        assert len(samples) == 1
        assert formatter.stats.truncated_diffs == 1

    def test_truncation_preserves_context_around_comment(self) -> None:
        formatter = InstructionFormatter(max_diff_chars=300, context_lines=3)
        lines = ["@@ -1,50 +1,50 @@"]
        for i in range(1, 51):
            lines.append(f"+line {i}")
        long_diff = "\n".join(lines)

        pr = _make_pr(
            files=[_make_file(diff=long_diff)],
            comments=[_make_comment(line=25, diff_hunk="@@ -1,50 +1,50 @@\n+line 25")],
        )
        samples = formatter.format_batch([pr])

        # The truncated diff should contain the area around line 25
        assert "+line 25" in samples[0].input

    def test_formatting_stats(self, formatter: InstructionFormatter) -> None:
        prs = [
            _make_pr(
                files=[_make_file()],
                comments=[_make_comment(), _make_comment(body="Another comment on the same file.")],
            ),
        ]
        formatter.format_batch(prs)
        stats = formatter.stats.to_dict()

        assert stats["total_prs"] == 1
        assert stats["total_comments"] == 2
        assert stats["total_pairs_generated"] == 2
