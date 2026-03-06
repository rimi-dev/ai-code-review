"""BLEU-4 metric computation for code review evaluation.

Computes sentence-level and corpus-level BLEU scores using sacrebleu,
with smoothing for short text handling common in review comments.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import sacrebleu
from sacrebleu.metrics import BLEU

logger = logging.getLogger(__name__)


@dataclass
class BLEUResult:
    """Results from BLEU evaluation."""

    corpus_bleu: float = 0.0
    sentence_bleu_scores: list[float] = field(default_factory=list)
    mean_sentence_bleu: float = 0.0
    median_sentence_bleu: float = 0.0
    min_sentence_bleu: float = 0.0
    max_sentence_bleu: float = 0.0
    brevity_penalty: float = 0.0
    num_samples: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_bleu": round(self.corpus_bleu, 4),
            "mean_sentence_bleu": round(self.mean_sentence_bleu, 4),
            "median_sentence_bleu": round(self.median_sentence_bleu, 4),
            "min_sentence_bleu": round(self.min_sentence_bleu, 4),
            "max_sentence_bleu": round(self.max_sentence_bleu, 4),
            "brevity_penalty": round(self.brevity_penalty, 4),
            "num_samples": self.num_samples,
        }


class BLEUMetric:
    """BLEU-4 metric evaluator for code review text.

    Uses sacrebleu for standardized BLEU computation with configurable
    smoothing methods appropriate for short text segments.

    Args:
        smooth_method: Smoothing method for sentence-level BLEU.
            Options: 'floor', 'add-k', 'exp', 'none'.
            'exp' (exponential decay) works well for short texts.
        smooth_value: Smoothing parameter value. For 'floor', this is the
            floor value; for 'add-k', this is k.
        lowercase: Whether to lowercase all text before scoring.
        max_ngram_order: Maximum n-gram order for BLEU (default 4 for BLEU-4).
    """

    def __init__(
        self,
        smooth_method: str = "exp",
        smooth_value: float | None = None,
        lowercase: bool = True,
        max_ngram_order: int = 4,
    ) -> None:
        self.smooth_method = smooth_method
        self.smooth_value = smooth_value
        self.lowercase = lowercase
        self.max_ngram_order = max_ngram_order

        # Corpus-level BLEU scorer (standard, no smoothing needed)
        self._corpus_scorer = BLEU(
            lowercase=self.lowercase,
            max_ngram_order=self.max_ngram_order,
        )

        # Sentence-level BLEU scorer (with smoothing for short texts)
        self._sentence_scorer = BLEU(
            lowercase=self.lowercase,
            max_ngram_order=self.max_ngram_order,
            smooth_method=self.smooth_method,
            smooth_value=self.smooth_value,
        )

    def compute(
        self,
        predictions: list[str],
        references: list[str],
    ) -> BLEUResult:
        """Compute BLEU-4 scores at both corpus and sentence level.

        Args:
            predictions: List of model-generated review comments.
            references: List of ground-truth review comments.

        Returns:
            BLEUResult with corpus-level and per-sentence scores.

        Raises:
            ValueError: If predictions and references have different lengths.
        """
        if len(predictions) != len(references):
            msg = (
                f"Predictions and references must have the same length, "
                f"got {len(predictions)} and {len(references)}"
            )
            raise ValueError(msg)

        if not predictions:
            logger.warning("Empty predictions list, returning zero scores")
            return BLEUResult()

        num_samples = len(predictions)
        logger.info("Computing BLEU-4 for %d samples", num_samples)

        # Corpus-level BLEU: references must be wrapped in a list (one reference per hypothesis)
        refs_wrapped = [references]
        corpus_result = self._corpus_scorer.corpus_score(predictions, refs_wrapped)
        corpus_bleu = corpus_result.score

        # Sentence-level BLEU with smoothing
        sentence_scores: list[float] = []
        for pred, ref in zip(predictions, references):
            if not pred.strip() or not ref.strip():
                sentence_scores.append(0.0)
                continue
            sent_result = self._sentence_scorer.sentence_score(pred, [ref])
            sentence_scores.append(sent_result.score)

        # Compute statistics
        sorted_scores = sorted(sentence_scores)
        n = len(sorted_scores)
        mean_bleu = sum(sorted_scores) / n if n > 0 else 0.0
        median_bleu = sorted_scores[n // 2] if n > 0 else 0.0

        result = BLEUResult(
            corpus_bleu=corpus_bleu,
            sentence_bleu_scores=sentence_scores,
            mean_sentence_bleu=mean_bleu,
            median_sentence_bleu=median_bleu,
            min_sentence_bleu=sorted_scores[0] if sorted_scores else 0.0,
            max_sentence_bleu=sorted_scores[-1] if sorted_scores else 0.0,
            brevity_penalty=corpus_result.bp,
            num_samples=num_samples,
        )

        logger.info(
            "BLEU-4 results: corpus=%.2f, mean_sentence=%.2f, median=%.2f, BP=%.4f",
            result.corpus_bleu,
            result.mean_sentence_bleu,
            result.median_sentence_bleu,
            result.brevity_penalty,
        )
        return result

    def compute_smoothed_sentence(self, prediction: str, reference: str) -> float:
        """Compute smoothed BLEU for a single prediction-reference pair.

        This is optimized for short texts like code review comments where
        standard BLEU tends to give zero scores due to n-gram sparsity.

        Args:
            prediction: Model-generated review comment.
            reference: Ground-truth review comment.

        Returns:
            Smoothed BLEU-4 score (0-100 scale).
        """
        if not prediction.strip() or not reference.strip():
            return 0.0

        result = self._sentence_scorer.sentence_score(prediction, [reference])
        return result.score
