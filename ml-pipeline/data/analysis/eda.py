"""Exploratory Data Analysis script for the AI Code Review Bot training data.

Generates a comprehensive markdown report with:
- Token length distributions (input/output)
- Language distribution
- Review comment quality metrics
- Data size statistics
- Distribution percentiles and outlier analysis

Usage:
    python -m data.analysis.eda \
        --dataset-path ./output/preprocessed/parquet \
        --output-dir ./output/analysis
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from datasets import DatasetDict, load_dataset

logger = logging.getLogger(__name__)


@dataclass
class DistributionStats:
    """Statistical summary of a numeric distribution."""

    count: int = 0
    mean: float = 0.0
    median: float = 0.0
    std: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    p5: float = 0.0
    p25: float = 0.0
    p75: float = 0.0
    p95: float = 0.0
    p99: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "count": self.count,
            "mean": round(self.mean, 2),
            "median": round(self.median, 2),
            "std": round(self.std, 2),
            "min": round(self.min_val, 2),
            "max": round(self.max_val, 2),
            "p5": round(self.p5, 2),
            "p25": round(self.p25, 2),
            "p75": round(self.p75, 2),
            "p95": round(self.p95, 2),
            "p99": round(self.p99, 2),
        }


@dataclass
class EDAResult:
    """Complete EDA analysis results."""

    # Dataset sizes
    total_samples: int = 0
    train_samples: int = 0
    val_samples: int = 0
    test_samples: int = 0

    # Token distributions
    input_token_stats: DistributionStats = field(default_factory=DistributionStats)
    output_token_stats: DistributionStats = field(default_factory=DistributionStats)

    # Text length distributions (characters)
    input_char_stats: DistributionStats = field(default_factory=DistributionStats)
    output_char_stats: DistributionStats = field(default_factory=DistributionStats)

    # Language distribution
    language_counts: dict[str, int] = field(default_factory=dict)

    # Review quality metrics
    avg_output_words: float = 0.0
    output_word_stats: DistributionStats = field(default_factory=DistributionStats)

    # Per-language token stats
    per_language_input_tokens: dict[str, DistributionStats] = field(default_factory=dict)
    per_language_output_tokens: dict[str, DistributionStats] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_samples": self.total_samples,
            "train_samples": self.train_samples,
            "val_samples": self.val_samples,
            "test_samples": self.test_samples,
            "input_token_stats": self.input_token_stats.to_dict(),
            "output_token_stats": self.output_token_stats.to_dict(),
            "input_char_stats": self.input_char_stats.to_dict(),
            "output_char_stats": self.output_char_stats.to_dict(),
            "language_counts": self.language_counts,
            "output_word_stats": self.output_word_stats.to_dict(),
        }


def compute_distribution(values: list[float | int]) -> DistributionStats:
    """Compute comprehensive distribution statistics.

    Args:
        values: List of numeric values.

    Returns:
        DistributionStats with percentiles and summary statistics.
    """
    if not values:
        return DistributionStats()

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    # Standard deviation
    std_val = statistics.stdev(sorted_vals) if n > 1 else 0.0

    def percentile(p: float) -> float:
        idx = int(n * p / 100)
        idx = min(idx, n - 1)
        return float(sorted_vals[idx])

    return DistributionStats(
        count=n,
        mean=statistics.mean(sorted_vals),
        median=statistics.median(sorted_vals),
        std=std_val,
        min_val=float(sorted_vals[0]),
        max_val=float(sorted_vals[-1]),
        p5=percentile(5),
        p25=percentile(25),
        p75=percentile(75),
        p95=percentile(95),
        p99=percentile(99),
    )


class DataAnalyzer:
    """Analyzes the preprocessed code review dataset.

    Args:
        output_dir: Directory to save analysis results.
    """

    def __init__(self, output_dir: str = "./output/analysis") -> None:
        self.output_dir = Path(output_dir)

    def analyze(self, dataset_dict: DatasetDict) -> EDAResult:
        """Run full exploratory data analysis on the dataset.

        Args:
            dataset_dict: HuggingFace DatasetDict with train/validation/test splits.

        Returns:
            EDAResult with comprehensive statistics.
        """
        result = EDAResult()

        # Dataset sizes
        result.train_samples = len(dataset_dict.get("train", []))
        result.val_samples = len(dataset_dict.get("validation", []))
        result.test_samples = len(dataset_dict.get("test", []))
        result.total_samples = result.train_samples + result.val_samples + result.test_samples

        logger.info(
            "Dataset sizes: train=%d, val=%d, test=%d, total=%d",
            result.train_samples, result.val_samples, result.test_samples, result.total_samples,
        )

        # Collect all samples across splits
        all_samples: list[dict[str, Any]] = []
        for split_name, ds in dataset_dict.items():
            for sample in ds:
                all_samples.append(dict(sample))

        if not all_samples:
            logger.warning("No samples found in dataset")
            return result

        # Token distributions
        input_tokens: list[int] = []
        output_tokens: list[int] = []
        input_chars: list[int] = []
        output_chars: list[int] = []
        output_words: list[int] = []
        languages: list[str] = []
        per_lang_input: dict[str, list[int]] = defaultdict(list)
        per_lang_output: dict[str, list[int]] = defaultdict(list)

        for sample in all_samples:
            input_text = sample.get("input", "")
            output_text = sample.get("output", "")
            language = sample.get("language", "Unknown")

            # Character lengths
            input_chars.append(len(input_text))
            output_chars.append(len(output_text))

            # Word count for output
            words = len(output_text.split())
            output_words.append(words)

            # Token counts (if pre-computed)
            if "input_tokens" in sample:
                it = int(sample["input_tokens"])
                input_tokens.append(it)
                per_lang_input[language].append(it)
            if "output_tokens" in sample:
                ot = int(sample["output_tokens"])
                output_tokens.append(ot)
                per_lang_output[language].append(ot)

            languages.append(language)

        # If token counts not pre-computed, estimate from characters
        if not input_tokens:
            logger.info("Token counts not pre-computed, estimating from character lengths (~4 chars/token)")
            input_tokens = [max(1, c // 4) for c in input_chars]
            output_tokens = [max(1, c // 4) for c in output_chars]

        # Compute distributions
        result.input_token_stats = compute_distribution(input_tokens)
        result.output_token_stats = compute_distribution(output_tokens)
        result.input_char_stats = compute_distribution(input_chars)
        result.output_char_stats = compute_distribution(output_chars)
        result.output_word_stats = compute_distribution(output_words)

        # Language distribution
        lang_counter = Counter(languages)
        result.language_counts = dict(lang_counter.most_common())

        # Per-language stats
        for lang, tokens in per_lang_input.items():
            result.per_language_input_tokens[lang] = compute_distribution(tokens)
        for lang, tokens in per_lang_output.items():
            result.per_language_output_tokens[lang] = compute_distribution(tokens)

        logger.info("Analysis complete: %d total samples analyzed", result.total_samples)
        return result

    def generate_report(self, result: EDAResult) -> Path:
        """Generate a markdown EDA report.

        Args:
            result: EDAResult from analysis.

        Returns:
            Path to the generated report file.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.output_dir / "eda_report.md"

        sections: list[str] = []

        # Header
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        sections.append(f"""# AI Code Review Bot - Data Analysis Report

**Generated:** {timestamp}

---""")

        # Dataset Overview
        sections.append(self._section_dataset_overview(result))

        # Token Length Distributions
        sections.append(self._section_token_distributions(result))

        # Character Length Distributions
        sections.append(self._section_char_distributions(result))

        # Language Distribution
        sections.append(self._section_language_distribution(result))

        # Review Quality Metrics
        sections.append(self._section_review_quality(result))

        # Per-Language Breakdown
        if result.per_language_input_tokens:
            sections.append(self._section_per_language_breakdown(result))

        # Recommendations
        sections.append(self._section_recommendations(result))

        report_content = "\n\n".join(sections)

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)

        # Also save raw stats as JSON
        stats_path = self.output_dir / "eda_stats.json"
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info("EDA report saved to %s", report_path)
        logger.info("EDA stats saved to %s", stats_path)
        return report_path

    def _section_dataset_overview(self, result: EDAResult) -> str:
        return f"""## Dataset Overview

| Split | Samples | Percentage |
|-------|---------|------------|
| Train | {result.train_samples:,} | {100 * result.train_samples / max(result.total_samples, 1):.1f}% |
| Validation | {result.val_samples:,} | {100 * result.val_samples / max(result.total_samples, 1):.1f}% |
| Test | {result.test_samples:,} | {100 * result.test_samples / max(result.total_samples, 1):.1f}% |
| **Total** | **{result.total_samples:,}** | **100%** |"""

    def _section_token_distributions(self, result: EDAResult) -> str:
        inp = result.input_token_stats
        out = result.output_token_stats
        return f"""## Token Length Distributions

### Input Tokens (Instruction + Code Diff)

| Statistic | Value |
|-----------|-------|
| Count | {inp.count:,} |
| Mean | {inp.mean:.0f} |
| Median | {inp.median:.0f} |
| Std Dev | {inp.std:.0f} |
| Min | {inp.min_val:.0f} |
| P5 | {inp.p5:.0f} |
| P25 | {inp.p25:.0f} |
| P75 | {inp.p75:.0f} |
| P95 | {inp.p95:.0f} |
| P99 | {inp.p99:.0f} |
| Max | {inp.max_val:.0f} |

### Output Tokens (Review Comment)

| Statistic | Value |
|-----------|-------|
| Count | {out.count:,} |
| Mean | {out.mean:.0f} |
| Median | {out.median:.0f} |
| Std Dev | {out.std:.0f} |
| Min | {out.min_val:.0f} |
| P5 | {out.p5:.0f} |
| P25 | {out.p25:.0f} |
| P75 | {out.p75:.0f} |
| P95 | {out.p95:.0f} |
| P99 | {out.p99:.0f} |
| Max | {out.max_val:.0f} |"""

    def _section_char_distributions(self, result: EDAResult) -> str:
        inp = result.input_char_stats
        out = result.output_char_stats
        return f"""## Character Length Distributions

| Metric | Input | Output |
|--------|-------|--------|
| Mean | {inp.mean:,.0f} | {out.mean:,.0f} |
| Median | {inp.median:,.0f} | {out.median:,.0f} |
| Std Dev | {inp.std:,.0f} | {out.std:,.0f} |
| Min | {inp.min_val:,.0f} | {out.min_val:,.0f} |
| Max | {inp.max_val:,.0f} | {out.max_val:,.0f} |
| P95 | {inp.p95:,.0f} | {out.p95:,.0f} |"""

    def _section_language_distribution(self, result: EDAResult) -> str:
        total = max(result.total_samples, 1)
        lines = ["## Language Distribution", ""]
        lines.append("| Language | Samples | Percentage |")
        lines.append("|----------|---------|------------|")

        for lang, count in sorted(result.language_counts.items(), key=lambda x: -x[1]):
            pct = 100 * count / total
            bar = "#" * int(pct / 2)  # Simple text-based bar
            lines.append(f"| {lang} | {count:,} | {pct:.1f}% {bar} |")

        return "\n".join(lines)

    def _section_review_quality(self, result: EDAResult) -> str:
        ws = result.output_word_stats
        return f"""## Review Comment Quality Metrics

### Word Count Distribution (Output)

| Statistic | Value |
|-----------|-------|
| Mean words | {ws.mean:.1f} |
| Median words | {ws.median:.1f} |
| Min words | {ws.min_val:.0f} |
| Max words | {ws.max_val:.0f} |
| P25 words | {ws.p25:.0f} |
| P75 words | {ws.p75:.0f} |
| P95 words | {ws.p95:.0f} |

### Quality Indicators

- **Very short reviews** (< 10 words): Potential low-quality samples
- **Long reviews** (> 200 words): May contain excessive context or multiple issues
- **Target range** (20-150 words): Typical high-quality review comment length"""

    def _section_per_language_breakdown(self, result: EDAResult) -> str:
        lines = ["## Per-Language Token Statistics", ""]
        lines.append("| Language | Input Mean | Input Median | Input P95 | Output Mean | Output Median | Output P95 |")
        lines.append("|----------|-----------|-------------|----------|------------|--------------|-----------|")

        for lang in sorted(result.per_language_input_tokens.keys()):
            inp = result.per_language_input_tokens.get(lang, DistributionStats())
            out = result.per_language_output_tokens.get(lang, DistributionStats())
            lines.append(
                f"| {lang} | {inp.mean:.0f} | {inp.median:.0f} | {inp.p95:.0f} "
                f"| {out.mean:.0f} | {out.median:.0f} | {out.p95:.0f} |"
            )

        return "\n".join(lines)

    def _section_recommendations(self, result: EDAResult) -> str:
        lines = ["## Recommendations", ""]

        inp = result.input_token_stats
        out = result.output_token_stats

        # Check if max_seq_length is sufficient
        if inp.p95 + out.p95 > 4096:
            lines.append(
                f"- **Warning:** P95 combined token length ({inp.p95 + out.p95:.0f}) exceeds "
                f"max_seq_length (4096). Consider increasing max_seq_length or more aggressive truncation."
            )

        # Check for extreme outliers
        if inp.max_val > 3 * inp.p95:
            lines.append(
                f"- **Outlier Alert:** Maximum input tokens ({inp.max_val:.0f}) is >3x P95 ({inp.p95:.0f}). "
                f"Consider additional filtering for extreme outliers."
            )

        # Check language balance
        if result.language_counts:
            counts = list(result.language_counts.values())
            if max(counts) > 5 * min(counts):
                dominant = max(result.language_counts, key=result.language_counts.get)
                lines.append(
                    f"- **Imbalanced Languages:** '{dominant}' dominates the dataset. "
                    f"Consider language-stratified sampling for balanced evaluation."
                )

        # Check output length
        if out.median < 30:
            lines.append(
                "- **Short Outputs:** Median output is less than 30 tokens. "
                "Reviews may be too brief. Consider filtering or augmentation."
            )

        if not lines[2:]:
            lines.append("- No significant concerns identified. Dataset appears well-prepared.")

        return "\n".join(lines)


def load_dataset_for_analysis(dataset_path: str) -> DatasetDict:
    """Load dataset from various formats for analysis.

    Args:
        dataset_path: Path to parquet directory, HF disk, or Hub ID.

    Returns:
        DatasetDict with available splits.
    """
    path = Path(dataset_path)

    if path.is_dir():
        parquet_files = list(path.glob("*.parquet"))
        if parquet_files:
            logger.info("Loading from parquet directory: %s", path)
            data_files = {}
            for pf in parquet_files:
                data_files[pf.stem] = str(pf)
            return load_dataset("parquet", data_files=data_files)

        if (path / "dataset_dict.json").exists():
            logger.info("Loading HuggingFace dataset from disk: %s", path)
            return DatasetDict.load_from_disk(str(path))

    logger.info("Loading from HuggingFace Hub: %s", dataset_path)
    return load_dataset(dataset_path)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Exploratory Data Analysis for AI Code Review Bot training data",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dataset-path",
        type=str,
        required=True,
        help="Path to the preprocessed dataset (parquet dir, HF disk, or Hub ID)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output/analysis",
        help="Directory to save analysis report and statistics",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for EDA."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logger.info("Loading dataset from %s", args.dataset_path)
    dataset_dict = load_dataset_for_analysis(args.dataset_path)

    logger.info("Running exploratory data analysis")
    analyzer = DataAnalyzer(output_dir=args.output_dir)
    result = analyzer.analyze(dataset_dict)
    report_path = analyzer.generate_report(result)

    logger.info("EDA complete. Report: %s", report_path)


if __name__ == "__main__":
    main()
