"""Tests for the ReviewCleaner module."""

from __future__ import annotations

import pytest

from data.preprocessor.cleaner import ReviewCleaner, CleaningStats


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cleaner() -> ReviewCleaner:
    """Return a default ReviewCleaner instance."""
    return ReviewCleaner()


def _make_review(
    author: str = "human-dev",
    body: str = "This function has a potential null pointer dereference on line 42. You should add a null check before accessing the property.",
    path: str = "src/main.py",
    **kwargs,
) -> dict:
    return {"author": author, "body": body, "path": path, **kwargs}


# ---------------------------------------------------------------------------
# Bot comment filtering
# ---------------------------------------------------------------------------

class TestBotFiltering:
    """Tests for bot account detection and filtering."""

    @pytest.mark.parametrize(
        "author",
        [
            "dependabot[bot]",
            "renovate[bot]",
            "github-actions[bot]",
            "codecov[bot]",
            "sonarcloud[bot]",
            "snyk[bot]",
            "greenkeeper[bot]",
            "imgbot[bot]",
            "mergify[bot]",
            "pre-commit-ci[bot]",
            "semantic-release-bot[bot]",
            "release-please[bot]",
            "dependabot",
            "renovate",
            "github-actions",
        ],
    )
    def test_removes_known_bot_accounts(self, cleaner: ReviewCleaner, author: str) -> None:
        reviews = [_make_review(author=author)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 0
        assert cleaner.stats.removed_bot == 1

    @pytest.mark.parametrize(
        "author",
        [
            "some-random[bot]",
            "mybot[bot]",
        ],
    )
    def test_removes_generic_bot_suffix(self, cleaner: ReviewCleaner, author: str) -> None:
        reviews = [_make_review(author=author)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 0

    @pytest.mark.parametrize(
        "author",
        [
            "john-doe",
            "alice",
            "bob123",
            "the-developer",
        ],
    )
    def test_keeps_human_authors(self, cleaner: ReviewCleaner, author: str) -> None:
        reviews = [_make_review(author=author)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 1

    def test_bot_removal_stats(self, cleaner: ReviewCleaner) -> None:
        reviews = [
            _make_review(author="dependabot[bot]"),
            _make_review(author="renovate[bot]"),
            _make_review(author="human-dev"),
        ]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 1
        assert cleaner.stats.removed_bot == 2
        assert cleaner.stats.total_input == 3
        assert cleaner.stats.total_output == 1


# ---------------------------------------------------------------------------
# Trivial review filtering
# ---------------------------------------------------------------------------

class TestTrivialFiltering:
    """Tests for trivial/short comment detection and filtering."""

    @pytest.mark.parametrize(
        "body",
        [
            "LGTM",
            "lgtm",
            "LGTM.",
            "Looks good",
            "looks good to me",
            "Looks good to me.",
            "+1",
            "-1",
            "nit",
            "nit.",
            "nice",
            "thanks",
            "Thank you",
            "great",
            "ship it",
            ":shipit:",
            ":thumbsup:",
            ":+1:",
            "approved",
            "done",
            "fixed",
            "ok",
            "ack",
        ],
    )
    def test_removes_trivial_patterns(self, cleaner: ReviewCleaner, body: str) -> None:
        reviews = [_make_review(body=body)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 0, f"Expected '{body}' to be filtered as trivial"

    def test_removes_short_comments(self, cleaner: ReviewCleaner) -> None:
        # A comment with fewer than 20 tokens and fewer than 80 chars
        reviews = [_make_review(body="Fix this line please.")]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 0
        assert cleaner.stats.removed_trivial == 1

    def test_keeps_substantive_comments(self, cleaner: ReviewCleaner) -> None:
        body = (
            "This function has a potential null pointer dereference on line 42. "
            "You should add a null check before accessing the property to prevent "
            "runtime errors in production."
        )
        reviews = [_make_review(body=body)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 1

    def test_custom_min_tokens(self) -> None:
        cleaner = ReviewCleaner(min_review_tokens=5)
        reviews = [_make_review(body="Fix the null check here please.")]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 1

    def test_trivial_removal_stats(self, cleaner: ReviewCleaner) -> None:
        reviews = [
            _make_review(body="LGTM"),
            _make_review(body="+1"),
            _make_review(
                body="This is a real review comment with enough tokens to pass the filter threshold for meaningful content in the review."
            ),
        ]
        result = cleaner.clean_batch(reviews)
        assert cleaner.stats.removed_trivial == 2  # "LGTM" + "+1"
        assert len(result) == 1


# ---------------------------------------------------------------------------
# File pattern filtering
# ---------------------------------------------------------------------------

class TestFilePatternFiltering:
    """Tests for excluded file pattern detection."""

    @pytest.mark.parametrize(
        "path",
        [
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "Gemfile.lock",
            "Pipfile.lock",
            "poetry.lock",
            "composer.lock",
            "Cargo.lock",
            "go.sum",
        ],
    )
    def test_removes_lock_files(self, cleaner: ReviewCleaner, path: str) -> None:
        reviews = [_make_review(path=path)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 0, f"Expected '{path}' to be filtered as lock file"
        assert cleaner.stats.removed_file_pattern == 1

    @pytest.mark.parametrize(
        "path",
        [
            "dist/bundle.min.js",
            "build/app.min.css",
            "src/generated.ts",
            "types/__generated__/schema.ts",
            "proto/service.pb.go",
            "proto/service_pb2.py",
        ],
    )
    def test_removes_generated_files(self, cleaner: ReviewCleaner, path: str) -> None:
        reviews = [_make_review(path=path)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 0, f"Expected '{path}' to be filtered as generated file"

    @pytest.mark.parametrize(
        "path",
        [
            "assets/logo.png",
            "images/banner.jpg",
            "fonts/roboto.woff2",
            "docs/manual.pdf",
            "archive/backup.zip",
            "lib/native.so",
        ],
    )
    def test_removes_binary_files(self, cleaner: ReviewCleaner, path: str) -> None:
        reviews = [_make_review(path=path)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 0, f"Expected '{path}' to be filtered as binary file"

    @pytest.mark.parametrize(
        "path",
        [
            "node_modules/express/index.js",
            "vendor/autoload.php",
            ".next/static/chunk.js",
            ".idea/workspace.xml",
            ".vscode/settings.json",
            "coverage/lcov.info",
            "__pycache__/module.cpython-312.pyc",
        ],
    )
    def test_removes_vendor_and_ide_files(self, cleaner: ReviewCleaner, path: str) -> None:
        reviews = [_make_review(path=path)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 0, f"Expected '{path}' to be filtered"

    @pytest.mark.parametrize(
        "path",
        [
            "src/main.py",
            "lib/utils.ts",
            "app/controllers/user_controller.rb",
            "cmd/server/main.go",
            "src/main/kotlin/App.kt",
            "package.json",
            "requirements.txt",
            "README.md",
        ],
    )
    def test_keeps_normal_source_files(self, cleaner: ReviewCleaner, path: str) -> None:
        reviews = [_make_review(path=path)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 1, f"Expected '{path}' to be kept"


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

class TestNormalization:
    """Tests for text normalization."""

    def test_normalizes_whitespace(self, cleaner: ReviewCleaner) -> None:
        body = "This   has    extra   spaces   and   a   lot   of   words   to   pass   the   twenty   token   minimum   filter   threshold   for   review   comments."
        reviews = [_make_review(body=body)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 1
        # Body should be preserved (whitespace within lines is kept)
        assert "  " in result[0]["body"]  # spaces within lines are kept

    def test_normalizes_line_endings(self, cleaner: ReviewCleaner) -> None:
        body = "This line has windows endings\r\nand another line\r\nand one more for good measure\r\nwith enough tokens to pass the filter threshold for review comments."
        reviews = [_make_review(body=body)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 1
        assert "\r\n" not in result[0]["body"]
        assert "\r" not in result[0]["body"]

    def test_removes_null_bytes(self, cleaner: ReviewCleaner) -> None:
        body = "This has null\x00 bytes in it and needs to be cleaned up so that the text is valid and passes the minimum token threshold for reviews."
        reviews = [_make_review(body=body)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 1
        assert "\x00" not in result[0]["body"]

    def test_collapses_multiple_blank_lines(self, cleaner: ReviewCleaner) -> None:
        body = "First paragraph with enough words to be meaningful.\n\n\n\n\nSecond paragraph also with enough words to pass the minimum token threshold for non-trivial review comments."
        reviews = [_make_review(body=body)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 1
        assert "\n\n\n" not in result[0]["body"]

    def test_empty_body_after_normalization(self, cleaner: ReviewCleaner) -> None:
        reviews = [_make_review(body="\x00\x01\x02")]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 0
        assert cleaner.stats.removed_empty_after_normalize == 1


# ---------------------------------------------------------------------------
# Language filtering
# ---------------------------------------------------------------------------

class TestLanguageFiltering:
    """Tests for language detection filtering."""

    def test_keeps_english_comments(self, cleaner: ReviewCleaner) -> None:
        body = "This function should handle the edge case where the input array is empty, otherwise it will throw an IndexOutOfBoundsException at runtime."
        reviews = [_make_review(body=body)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 1

    def test_keeps_korean_comments(self, cleaner: ReviewCleaner) -> None:
        body = "이 함수는 입력 배열이 비어있는 경우의 엣지 케이스를 처리해야 합니다. 그렇지 않으면 런타임에 IndexOutOfBoundsException이 발생합니다. 반드시 수정이 필요합니다."
        reviews = [_make_review(body=body)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 1

    def test_keeps_mixed_english_korean(self, cleaner: ReviewCleaner) -> None:
        body = "이 부분은 null check가 필요합니다. Otherwise it will crash. 반드시 확인해주세요. Please add proper error handling here."
        reviews = [_make_review(body=body)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 1

    def test_keeps_comments_with_code_blocks(self, cleaner: ReviewCleaner) -> None:
        body = "You should use a guard clause here with enough explanation to make this a substantive review:\n```python\nif x is None:\n    return\n```\nThis would be much cleaner."
        reviews = [_make_review(body=body)]
        result = cleaner.clean_batch(reviews)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Integration: Stats
# ---------------------------------------------------------------------------

class TestCleaningStats:
    """Tests for cleaning statistics tracking."""

    def test_stats_to_dict(self) -> None:
        stats = CleaningStats(total_input=100, total_output=60, removed_bot=10, removed_trivial=20)
        d = stats.to_dict()
        assert d["total_input"] == 100
        assert d["total_output"] == 60
        assert d["removed_bot"] == 10
        assert d["removed_trivial"] == 20
        assert d["removal_rate"] == 0.4

    def test_comprehensive_stats(self, cleaner: ReviewCleaner) -> None:
        reviews = [
            _make_review(author="dependabot[bot]"),  # bot
            _make_review(path="package-lock.json"),  # file pattern
            _make_review(body="LGTM"),  # trivial (pattern match)
            _make_review(body="Short."),  # too short (fails both token and char thresholds)
            _make_review(  # valid
                body="This function has a potential memory leak because the file handle is never closed after reading. Consider using a context manager."
            ),
        ]
        result = cleaner.clean_batch(reviews)
        stats = cleaner.stats.to_dict()

        assert stats["total_input"] == 5
        assert stats["total_output"] == 1
        assert stats["removed_bot"] == 1
        assert stats["removed_file_pattern"] == 1
        assert stats["removed_trivial"] == 2  # "LGTM" + "Short."
        assert "removal_reasons" in stats
