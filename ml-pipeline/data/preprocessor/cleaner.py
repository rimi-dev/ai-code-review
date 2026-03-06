"""Data cleaning module for filtering and normalizing PR review data.

Removes bot-generated reviews, trivial comments, reviews on non-reviewable files,
normalizes text encoding/whitespace, and filters by language.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Bot accounts to filter out
BOT_PATTERNS: list[str] = [
    "dependabot",
    "renovate",
    "github-actions",
    "codecov",
    "sonarcloud",
    "snyk",
    "greenkeeper",
    "imgbot",
    "stale",
    "mergify",
    "allcontributors",
    "depfu",
    "whitesource",
    "mend-bolt",
    "lgtm-com",
    "codeclimate",
    "deepsource",
    "restyled",
    "pre-commit-ci",
    "semantic-release-bot",
    "release-please",
]

# Compiled bot pattern for efficient matching
_BOT_REGEX = re.compile(
    r"(?i)\[bot\]$|^(" + "|".join(re.escape(p) for p in BOT_PATTERNS) + r")(\[bot\])?$"
)

# Trivial review patterns (case-insensitive)
TRIVIAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)^\s*lgtm\.?\s*$"),
    re.compile(r"(?i)^\s*looks?\s+good(\s+to\s+me)?\.?\s*$"),
    re.compile(r"(?i)^\s*\+1\s*$"),
    re.compile(r"(?i)^\s*-1\s*$"),
    re.compile(r"(?i)^\s*nit\.?\s*$"),
    re.compile(r"(?i)^\s*nice\.?\s*$"),
    re.compile(r"(?i)^\s*thanks?\.?\s*$"),
    re.compile(r"(?i)^\s*thank\s+you\.?\s*$"),
    re.compile(r"(?i)^\s*great\.?\s*$"),
    re.compile(r"(?i)^\s*ship\s*it\.?\s*$"),
    re.compile(r"(?i)^\s*:shipit:\s*$"),
    re.compile(r"(?i)^\s*:thumbsup:\s*$"),
    re.compile(r"(?i)^\s*:?\+1:?\s*$"),
    re.compile(r"(?i)^\s*\U0001f44d\s*$"),
    re.compile(r"(?i)^\s*approved\.?\s*$"),
    re.compile(r"(?i)^\s*done\.?\s*$"),
    re.compile(r"(?i)^\s*fixed\.?\s*$"),
    re.compile(r"(?i)^\s*ok\.?\s*$"),
    re.compile(r"(?i)^\s*ack\.?\s*$"),
    re.compile(r"(?i)^\s*acknowledged?\.?\s*$"),
    re.compile(r"(?i)^\s*r\s*=\s*me\.?\s*$"),
]

# File patterns to exclude from reviews
EXCLUDED_FILE_PATTERNS: list[re.Pattern[str]] = [
    # Lock files
    re.compile(r"(?i)package-lock\.json$"),
    re.compile(r"(?i)yarn\.lock$"),
    re.compile(r"(?i)pnpm-lock\.yaml$"),
    re.compile(r"(?i)Gemfile\.lock$"),
    re.compile(r"(?i)Pipfile\.lock$"),
    re.compile(r"(?i)poetry\.lock$"),
    re.compile(r"(?i)composer\.lock$"),
    re.compile(r"(?i)Cargo\.lock$"),
    re.compile(r"(?i)go\.sum$"),
    re.compile(r"(?i)gradle\.lockfile$"),
    # Generated files
    re.compile(r"(?i)\.min\.(js|css)$"),
    re.compile(r"(?i)\.bundle\.(js|css)$"),
    re.compile(r"(?i)\.generated\.\w+$"),
    re.compile(r"(?i)(^|/)generated\.\w+$"),
    re.compile(r"(?i)\.g\.\w+$"),
    re.compile(r"(?i)__generated__"),
    re.compile(r"(?i)\.pb\.go$"),
    re.compile(r"(?i)_pb2\.py$"),
    re.compile(r"(?i)\.swagger\.json$"),
    re.compile(r"(?i)openapi\.json$"),
    re.compile(r"(?i)\.graphql\.ts$"),
    re.compile(r"(?i)schema\.graphql$"),
    # Binary files
    re.compile(r"(?i)\.(png|jpg|jpeg|gif|ico|svg|bmp|webp|tiff?)$"),
    re.compile(r"(?i)\.(woff2?|ttf|eot|otf)$"),
    re.compile(r"(?i)\.(pdf|doc|docx|xls|xlsx|ppt|pptx)$"),
    re.compile(r"(?i)\.(zip|tar|gz|bz2|7z|rar)$"),
    re.compile(r"(?i)\.(exe|dll|so|dylib|a|o|class|pyc)$"),
    re.compile(r"(?i)\.(mp3|mp4|avi|mov|wmv|flv|wav)$"),
    # Vendor / dependency directories
    re.compile(r"(?i)(^|/)node_modules/"),
    re.compile(r"(?i)(^|/)vendor/"),
    re.compile(r"(?i)(^|/)dist/"),
    re.compile(r"(?i)(^|/)build/"),
    re.compile(r"(?i)(^|/)\.next/"),
    re.compile(r"(?i)(^|/)\.nuxt/"),
    re.compile(r"(?i)(^|/)coverage/"),
    re.compile(r"(?i)(^|/)__pycache__/"),
    # IDE / config files with no reviewable content
    re.compile(r"(?i)(^|/)\.idea/"),
    re.compile(r"(?i)(^|/)\.vscode/"),
    re.compile(r"(?i)\.DS_Store$"),
    re.compile(r"(?i)Thumbs\.db$"),
]

# Minimum token count for non-trivial reviews (whitespace-split tokens)
MIN_REVIEW_TOKENS = 20

# Minimum character count as an alternative threshold.
# Korean and other CJK text can have fewer whitespace-split tokens but many characters.
# 80 characters is roughly equivalent to 20 English words worth of content.
MIN_REVIEW_CHARS = 80

# Language detection: allow English and Korean
# Simple heuristic: check character ranges
_KOREAN_RANGE = re.compile(r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F\uA960-\uA97F\uD7B0-\uD7FF]")
_CJK_NON_KOREAN = re.compile(r"[\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF]")  # Chinese + Japanese
_CYRILLIC = re.compile(r"[\u0400-\u04FF]")
_ARABIC = re.compile(r"[\u0600-\u06FF]")
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_THAI = re.compile(r"[\u0E00-\u0E7F]")


@dataclass
class CleaningStats:
    """Statistics collected during the cleaning process."""

    total_input: int = 0
    removed_bot: int = 0
    removed_trivial: int = 0
    removed_file_pattern: int = 0
    removed_language: int = 0
    removed_empty_after_normalize: int = 0
    total_output: int = 0
    _reasons: dict[str, int] = field(default_factory=dict)

    def record_removal(self, reason: str) -> None:
        self._reasons[reason] = self._reasons.get(reason, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_input": self.total_input,
            "removed_bot": self.removed_bot,
            "removed_trivial": self.removed_trivial,
            "removed_file_pattern": self.removed_file_pattern,
            "removed_language": self.removed_language,
            "removed_empty_after_normalize": self.removed_empty_after_normalize,
            "total_output": self.total_output,
            "removal_rate": round(1 - self.total_output / max(self.total_input, 1), 4),
            "removal_reasons": dict(self._reasons),
        }


class ReviewCleaner:
    """Cleans and filters raw PR review data for training quality.

    Applies a multi-stage filtering pipeline:
    1. Bot review removal
    2. Excluded file pattern filtering
    3. Text normalization
    4. Empty body removal
    5. Trivial comment removal
    6. Language filtering (English/Korean only)
    """

    def __init__(
        self,
        min_review_tokens: int = MIN_REVIEW_TOKENS,
        min_review_chars: int = MIN_REVIEW_CHARS,
        bot_patterns: list[str] | None = None,
        excluded_file_patterns: list[re.Pattern[str]] | None = None,
    ) -> None:
        self.min_review_tokens = min_review_tokens
        self.min_review_chars = min_review_chars
        self._bot_regex = (
            re.compile(
                r"(?i)\[bot\]$|^(" + "|".join(re.escape(p) for p in bot_patterns) + r")(\[bot\])?$"
            )
            if bot_patterns is not None
            else _BOT_REGEX
        )
        self._excluded_file_patterns = excluded_file_patterns or EXCLUDED_FILE_PATTERNS
        self._stats = CleaningStats()

    @property
    def stats(self) -> CleaningStats:
        return self._stats

    def clean_batch(self, reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Clean a batch of review records.

        Each review dict is expected to have at minimum:
        - author (str): GitHub username of the reviewer
        - body (str): The review comment text
        - path (str): File path the comment is on

        Returns:
            Filtered and normalized list of review dicts.
        """
        self._stats = CleaningStats(total_input=len(reviews))
        cleaned: list[dict[str, Any]] = []

        for review in reviews:
            result = self._clean_single(review)
            if result is not None:
                cleaned.append(result)

        self._stats.total_output = len(cleaned)
        logger.info(
            "Cleaning complete: %d -> %d records (%.1f%% removed)",
            self._stats.total_input,
            self._stats.total_output,
            (1 - self._stats.total_output / max(self._stats.total_input, 1)) * 100,
        )
        return cleaned

    def _clean_single(self, review: dict[str, Any]) -> dict[str, Any] | None:
        """Apply all cleaning steps to a single review record."""
        author = review.get("author", "")
        body = review.get("body", "")
        path = review.get("path", "")

        # Step 1: Bot filtering
        if self._is_bot(author):
            self._stats.removed_bot += 1
            self._stats.record_removal(f"bot:{author}")
            return None

        # Step 2: File pattern filtering
        if self._is_excluded_file(path):
            self._stats.removed_file_pattern += 1
            self._stats.record_removal(f"file_pattern:{path}")
            return None

        # Step 3: Normalize text
        normalized_body = self._normalize_text(body)

        # Step 4: Empty after normalization
        if not normalized_body.strip():
            self._stats.removed_empty_after_normalize += 1
            self._stats.record_removal("empty_after_normalize")
            return None

        # Step 5: Trivial review filtering
        if self._is_trivial(normalized_body):
            self._stats.removed_trivial += 1
            self._stats.record_removal("trivial")
            return None

        # Step 6: Language filtering
        if not self._is_allowed_language(normalized_body):
            self._stats.removed_language += 1
            self._stats.record_removal("language")
            return None

        # Return cleaned review with normalized body
        cleaned = dict(review)
        cleaned["body"] = normalized_body
        return cleaned

    def _is_bot(self, author: str) -> bool:
        """Check if the author is a known bot account."""
        if not author:
            return False
        return bool(self._bot_regex.search(author))

    def _is_excluded_file(self, path: str) -> bool:
        """Check if the file path matches any excluded pattern."""
        if not path:
            return False
        return any(pattern.search(path) for pattern in self._excluded_file_patterns)

    def _is_trivial(self, body: str) -> bool:
        """Check if the review body is trivial (too short or matches trivial patterns).

        Uses a dual threshold: whitespace-split token count AND character count.
        Text must exceed at least one threshold to be considered non-trivial.
        This handles languages like Korean where whitespace tokenization is coarse.
        """
        # Check against trivial patterns first
        for pattern in TRIVIAL_PATTERNS:
            if pattern.match(body):
                return True

        # Check both token count and character count
        tokens = body.split()
        char_count = len(body.strip())

        # Text is trivial if it fails BOTH thresholds
        if len(tokens) < self.min_review_tokens and char_count < self.min_review_chars:
            return True

        return False

    def _is_allowed_language(self, text: str) -> bool:
        """Check if text is primarily English or Korean.

        Uses a character-range heuristic: if a significant portion of non-ASCII
        characters belong to non-Korean CJK, Cyrillic, Arabic, etc., reject it.
        English text (ASCII) and Korean text are allowed.
        """
        # Strip code blocks and inline code before language detection
        text_for_detection = re.sub(r"```[\s\S]*?```", "", text)
        text_for_detection = re.sub(r"`[^`]+`", "", text_for_detection)
        # Strip URLs
        text_for_detection = re.sub(r"https?://\S+", "", text_for_detection)

        if not text_for_detection.strip():
            return True  # All code / URLs -> allow

        # Count non-Korean foreign script characters
        non_korean_foreign = (
            len(_CJK_NON_KOREAN.findall(text_for_detection))
            + len(_CYRILLIC.findall(text_for_detection))
            + len(_ARABIC.findall(text_for_detection))
            + len(_DEVANAGARI.findall(text_for_detection))
            + len(_THAI.findall(text_for_detection))
        )

        korean_chars = len(_KOREAN_RANGE.findall(text_for_detection))

        # If there are meaningful non-Korean foreign characters, check ratio
        # Count all alpha characters plus Korean characters for the denominator
        alpha_chars = sum(1 for c in text_for_detection if c.isalpha())
        if alpha_chars == 0:
            return True  # No alpha characters (all symbols/numbers) -> allow

        # Reject if >30% of alphabetic chars are from non-Korean foreign scripts
        if non_korean_foreign / alpha_chars > 0.3:
            return False

        return True

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize whitespace, encoding, and control characters."""
        if not text:
            return ""

        # Unicode NFC normalization
        text = unicodedata.normalize("NFC", text)

        # Remove null bytes and other control characters (except newline, tab)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

        # Normalize different line endings to \n
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Collapse multiple blank lines into at most two newlines
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Strip trailing whitespace on each line
        text = "\n".join(line.rstrip() for line in text.split("\n"))

        # Strip leading/trailing whitespace from entire text
        text = text.strip()

        return text
