"""ROUGE-L metric computation for code review evaluation.

Computes ROUGE-L precision, recall, and F1 scores using the rouge-score
library, with per-sample and aggregate statistics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from rouge_score import rouge_scorer

logger = logging.getLogger(__name__)


@dataclass
class ROUGEScores:
    """ROUGE scores for a single sample or aggregate."""

    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0


@dataclass
class ROUGEResult:
    """Complete ROUGE-L evaluation results."""

    # Aggregate (mean) scores
    mean_precision: float = 0.0
    mean_recall: float = 0.0
    mean_f1: float = 0.0

    # Per-sample F1 scores for distribution analysis
    per_sample_f1: list[float] = field(default_factory=list)

    # Distribution statistics on F1
    median_f1: float = 0.0
    min_f1: float = 0.0
    max_f1: float = 0.0
    std_f1: float = 0.0

    num_samples: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean_precision": round(self.mean_precision, 4),
            "mean_recall": round(self.mean_recall, 4),
            "mean_f1": round(self.mean_f1, 4),
            "median_f1": round(self.median_f1, 4),
            "min_f1": round(self.min_f1, 4),
            "max_f1": round(self.max_f1, 4),
            "std_f1": round(self.std_f1, 4),
            "num_samples": self.num_samples,
        }


class ROUGEMetric:
    """ROUGE-L metric evaluator for code review text.

    Computes ROUGE-L (Longest Common Subsequence) which is well-suited for
    evaluating text where word order matters but exact n-gram matching is too strict.

    Args:
        use_stemmer: Whether to apply Porter stemmer before comparison.
            Recommended True for English text to handle morphological variations.
    """

    def __init__(self, use_stemmer: bool = True) -> None:
        self.use_stemmer = use_stemmer
        self._scorer = rouge_scorer.RougeScorer(
            rouge_types=["rougeL"],
            use_stemmer=self.use_stemmer,
        )

    def compute(
        self,
        predictions: list[str],
        references: list[str],
    ) -> ROUGEResult:
        """Compute ROUGE-L scores across all prediction-reference pairs.

        Args:
            predictions: List of model-generated review comments.
            references: List of ground-truth review comments.

        Returns:
            ROUGEResult with aggregate and per-sample scores.

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
            return ROUGEResult()

        num_samples = len(predictions)
        logger.info("Computing ROUGE-L for %d samples", num_samples)

        precisions: list[float] = []
        recalls: list[float] = []
        f1_scores: list[float] = []

        for pred, ref in zip(predictions, references):
            scores = self._score_single(pred, ref)
            precisions.append(scores.precision)
            recalls.append(scores.recall)
            f1_scores.append(scores.f1)

        # Compute aggregate statistics
        mean_p = sum(precisions) / num_samples
        mean_r = sum(recalls) / num_samples
        mean_f1 = sum(f1_scores) / num_samples

        sorted_f1 = sorted(f1_scores)
        median_f1 = sorted_f1[num_samples // 2] if num_samples > 0 else 0.0

        # Standard deviation
        if num_samples > 1:
            variance = sum((x - mean_f1) ** 2 for x in f1_scores) / (num_samples - 1)
            std_f1 = variance ** 0.5
        else:
            std_f1 = 0.0

        result = ROUGEResult(
            mean_precision=mean_p,
            mean_recall=mean_r,
            mean_f1=mean_f1,
            per_sample_f1=f1_scores,
            median_f1=median_f1,
            min_f1=sorted_f1[0] if sorted_f1 else 0.0,
            max_f1=sorted_f1[-1] if sorted_f1 else 0.0,
            std_f1=std_f1,
            num_samples=num_samples,
        )

        logger.info(
            "ROUGE-L results: P=%.4f, R=%.4f, F1=%.4f (median=%.4f, std=%.4f)",
            result.mean_precision,
            result.mean_recall,
            result.mean_f1,
            result.median_f1,
            result.std_f1,
        )
        return result

    def _score_single(self, prediction: str, reference: str) -> ROUGEScores:
        """Score a single prediction-reference pair.

        Args:
            prediction: Model-generated review comment.
            reference: Ground-truth review comment.

        Returns:
            ROUGEScores with precision, recall, and F1.
        """
        if not prediction.strip() or not reference.strip():
            return ROUGEScores()

        scores = self._scorer.score(target=reference, prediction=prediction)
        rouge_l = scores["rougeL"]

        return ROUGEScores(
            precision=rouge_l.precision,
            recall=rouge_l.recall,
            f1=rouge_l.fmeasure,
        )

    def compute_single(self, prediction: str, reference: str) -> ROUGEScores:
        """Public interface for scoring a single pair.

        Args:
            prediction: Model-generated review comment.
            reference: Ground-truth review comment.

        Returns:
            ROUGEScores with precision, recall, and F1 for ROUGE-L.
        """
        return self._score_single(prediction, reference)
