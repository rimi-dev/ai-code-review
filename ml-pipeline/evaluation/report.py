"""Evaluation report generator for the AI Code Review Bot.

Produces a comprehensive markdown report with:
- Overall metrics comparison table
- Per-language breakdown
- Example predictions (best and worst)
- Side-by-side comparison (base vs fine-tuned vs Claude judge scores)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from evaluation.evaluate import EvaluationResult

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates markdown evaluation reports with detailed analysis.

    Args:
        output_dir: Directory to save the report file.
        max_examples: Maximum number of best/worst examples to include.
    """

    def __init__(self, output_dir: str = "./output/evaluation", max_examples: int = 5) -> None:
        self.output_dir = Path(output_dir)
        self.max_examples = max_examples

    def generate(
        self,
        finetuned_result: EvaluationResult,
        base_result: EvaluationResult | None = None,
    ) -> Path:
        """Generate the full evaluation report.

        Args:
            finetuned_result: Evaluation results from the fine-tuned model.
            base_result: Optional evaluation results from the base model.

        Returns:
            Path to the generated markdown report file.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.output_dir / "evaluation_report.md"

        sections: list[str] = []

        # Header
        sections.append(self._generate_header(finetuned_result))

        # Overall metrics table
        sections.append(self._generate_metrics_table(finetuned_result, base_result))

        # LLM Judge results
        if finetuned_result.llm_judge:
            sections.append(self._generate_llm_judge_section(finetuned_result, base_result))

        # Per-language breakdown
        sections.append(self._generate_language_breakdown(finetuned_result, base_result))

        # Example predictions
        sections.append(self._generate_examples(finetuned_result, base_result))

        # Side-by-side comparison
        if base_result:
            sections.append(self._generate_side_by_side(finetuned_result, base_result))

        report_content = "\n\n".join(sections)

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)

        logger.info("Evaluation report saved to %s", report_path)
        return report_path

    def _generate_header(self, result: EvaluationResult) -> str:
        """Generate the report header."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return f"""# AI Code Review Bot - Evaluation Report

**Generated:** {timestamp}
**Model:** `{result.model_name}`
**Test Samples:** {result.num_samples}
**Inference Time:** {result.inference_time_seconds:.1f}s ({result.num_samples / max(result.inference_time_seconds, 0.01):.1f} samples/s)

---"""

    def _generate_metrics_table(
        self,
        finetuned: EvaluationResult,
        base: EvaluationResult | None,
    ) -> str:
        """Generate the overall metrics comparison table."""
        lines = ["## Overall Metrics", ""]

        if base:
            lines.append("| Metric | Base Model | Fine-tuned | Delta |")
            lines.append("|--------|-----------|------------|-------|")

            rows = self._build_comparison_rows(finetuned, base)
            for row in rows:
                lines.append(row)
        else:
            lines.append("| Metric | Score |")
            lines.append("|--------|-------|")

            rows = self._build_single_model_rows(finetuned)
            for row in rows:
                lines.append(row)

        return "\n".join(lines)

    def _build_comparison_rows(
        self,
        finetuned: EvaluationResult,
        base: EvaluationResult,
    ) -> list[str]:
        """Build comparison table rows for two models."""
        rows: list[str] = []

        # BLEU scores
        ft_bleu = finetuned.bleu
        bs_bleu = base.bleu
        if ft_bleu and bs_bleu:
            delta = ft_bleu.corpus_bleu - bs_bleu.corpus_bleu
            sign = "+" if delta >= 0 else ""
            rows.append(
                f"| BLEU-4 (Corpus) | {bs_bleu.corpus_bleu:.2f} | {ft_bleu.corpus_bleu:.2f} | {sign}{delta:.2f} |"
            )
            delta = ft_bleu.mean_sentence_bleu - bs_bleu.mean_sentence_bleu
            sign = "+" if delta >= 0 else ""
            rows.append(
                f"| BLEU-4 (Sentence Mean) | {bs_bleu.mean_sentence_bleu:.2f} | {ft_bleu.mean_sentence_bleu:.2f} | {sign}{delta:.2f} |"
            )

        # ROUGE scores
        ft_rouge = finetuned.rouge
        bs_rouge = base.rouge
        if ft_rouge and bs_rouge:
            delta = ft_rouge.mean_f1 - bs_rouge.mean_f1
            sign = "+" if delta >= 0 else ""
            rows.append(
                f"| ROUGE-L (F1) | {bs_rouge.mean_f1:.4f} | {ft_rouge.mean_f1:.4f} | {sign}{delta:.4f} |"
            )
            delta = ft_rouge.mean_precision - bs_rouge.mean_precision
            sign = "+" if delta >= 0 else ""
            rows.append(
                f"| ROUGE-L (Precision) | {bs_rouge.mean_precision:.4f} | {ft_rouge.mean_precision:.4f} | {sign}{delta:.4f} |"
            )
            delta = ft_rouge.mean_recall - bs_rouge.mean_recall
            sign = "+" if delta >= 0 else ""
            rows.append(
                f"| ROUGE-L (Recall) | {bs_rouge.mean_recall:.4f} | {ft_rouge.mean_recall:.4f} | {sign}{delta:.4f} |"
            )

        return rows

    def _build_single_model_rows(self, result: EvaluationResult) -> list[str]:
        """Build table rows for a single model."""
        rows: list[str] = []

        if result.bleu:
            rows.append(f"| BLEU-4 (Corpus) | {result.bleu.corpus_bleu:.2f} |")
            rows.append(f"| BLEU-4 (Sentence Mean) | {result.bleu.mean_sentence_bleu:.2f} |")
            rows.append(f"| BLEU-4 (Median) | {result.bleu.median_sentence_bleu:.2f} |")

        if result.rouge:
            rows.append(f"| ROUGE-L (F1) | {result.rouge.mean_f1:.4f} |")
            rows.append(f"| ROUGE-L (Precision) | {result.rouge.mean_precision:.4f} |")
            rows.append(f"| ROUGE-L (Recall) | {result.rouge.mean_recall:.4f} |")

        return rows

    def _generate_llm_judge_section(
        self,
        finetuned: EvaluationResult,
        base: EvaluationResult | None,
    ) -> str:
        """Generate the LLM-as-Judge evaluation section."""
        lines = ["## LLM-as-Judge Evaluation (Claude)", ""]

        ft_judge = finetuned.llm_judge
        bs_judge = base.llm_judge if base else None

        dimensions = [
            ("Accuracy", "mean_accuracy"),
            ("Helpfulness", "mean_helpfulness"),
            ("Specificity", "mean_specificity"),
            ("Code Awareness", "mean_code_awareness"),
            ("Actionability", "mean_actionability"),
            ("**Overall**", "overall_mean"),
        ]

        if bs_judge:
            lines.append("| Dimension | Base Model | Fine-tuned | Delta |")
            lines.append("|-----------|-----------|------------|-------|")
            for name, attr in dimensions:
                ft_val = getattr(ft_judge, attr, 0)
                bs_val = getattr(bs_judge, attr, 0)
                delta = ft_val - bs_val
                sign = "+" if delta >= 0 else ""
                lines.append(f"| {name} | {bs_val:.2f} | {ft_val:.2f} | {sign}{delta:.2f} |")
        else:
            lines.append("| Dimension | Score (1-5) |")
            lines.append("|-----------|-------------|")
            for name, attr in dimensions:
                ft_val = getattr(ft_judge, attr, 0)
                lines.append(f"| {name} | {ft_val:.2f} |")

        if ft_judge:
            lines.append("")
            lines.append(f"*Evaluated {ft_judge.num_samples} samples, {ft_judge.num_errors} errors*")

        return "\n".join(lines)

    def _generate_language_breakdown(
        self,
        finetuned: EvaluationResult,
        base: EvaluationResult | None,
    ) -> str:
        """Generate per-language metric breakdown."""
        lines = ["## Per-Language Breakdown", ""]

        if not finetuned.languages:
            lines.append("*No language information available*")
            return "\n".join(lines)

        # Group samples by language
        lang_groups: dict[str, list[int]] = defaultdict(list)
        for idx, lang in enumerate(finetuned.languages):
            lang_groups[lang].append(idx)

        # Compute per-language metrics
        bleu_metric = None
        rouge_metric = None

        if finetuned.bleu:
            from evaluation.metrics.bleu_metric import BLEUMetric
            bleu_metric = BLEUMetric()
        if finetuned.rouge:
            from evaluation.metrics.rouge_metric import ROUGEMetric
            rouge_metric = ROUGEMetric()

        lines.append("| Language | Samples | BLEU-4 | ROUGE-L F1 |")
        lines.append("|----------|---------|--------|------------|")

        for lang in sorted(lang_groups.keys()):
            indices = lang_groups[lang]
            count = len(indices)

            preds = [finetuned.predictions[i] for i in indices]
            refs = [finetuned.references[i] for i in indices]

            bleu_score = "-"
            rouge_score = "-"

            if bleu_metric and preds:
                try:
                    bleu_result = bleu_metric.compute(preds, refs)
                    bleu_score = f"{bleu_result.corpus_bleu:.2f}"
                except Exception:
                    pass

            if rouge_metric and preds:
                try:
                    rouge_result = rouge_metric.compute(preds, refs)
                    rouge_score = f"{rouge_result.mean_f1:.4f}"
                except Exception:
                    pass

            lines.append(f"| {lang} | {count} | {bleu_score} | {rouge_score} |")

        return "\n".join(lines)

    def _generate_examples(
        self,
        finetuned: EvaluationResult,
        base: EvaluationResult | None,
    ) -> str:
        """Generate best and worst example predictions."""
        lines = ["## Example Predictions", ""]

        if not finetuned.rouge or not finetuned.rouge.per_sample_f1:
            lines.append("*No per-sample scores available for example selection*")
            return "\n".join(lines)

        f1_scores = finetuned.rouge.per_sample_f1
        indexed_scores = list(enumerate(f1_scores))
        sorted_by_score = sorted(indexed_scores, key=lambda x: x[1], reverse=True)

        # Best examples
        lines.append("### Best Predictions (Highest ROUGE-L F1)")
        lines.append("")
        for rank, (idx, score) in enumerate(sorted_by_score[: self.max_examples], 1):
            lines.append(self._format_example(rank, idx, score, finetuned, base))
            lines.append("")

        # Worst examples
        lines.append("### Worst Predictions (Lowest ROUGE-L F1)")
        lines.append("")
        for rank, (idx, score) in enumerate(reversed(sorted_by_score[-self.max_examples:]), 1):
            lines.append(self._format_example(rank, idx, score, finetuned, base))
            lines.append("")

        return "\n".join(lines)

    def _format_example(
        self,
        rank: int,
        idx: int,
        score: float,
        finetuned: EvaluationResult,
        base: EvaluationResult | None,
    ) -> str:
        """Format a single example prediction."""
        language = finetuned.languages[idx] if idx < len(finetuned.languages) else "Unknown"
        input_text = finetuned.inputs[idx] if idx < len(finetuned.inputs) else ""
        reference = finetuned.references[idx] if idx < len(finetuned.references) else ""
        prediction = finetuned.predictions[idx] if idx < len(finetuned.predictions) else ""

        # Truncate input for readability
        max_input_display = 500
        display_input = input_text[:max_input_display]
        if len(input_text) > max_input_display:
            display_input += "\n... [truncated]"

        parts = [
            f"**Example {rank}** (ROUGE-L F1: {score:.4f}, Language: {language})",
            "",
            "<details>",
            f"<summary>Input (sample #{idx})</summary>",
            "",
            "```",
            display_input,
            "```",
            "</details>",
            "",
            "**Reference (Human):**",
            f"> {reference}",
            "",
            "**Fine-tuned Model:**",
            f"> {prediction}",
        ]

        if base and idx < len(base.predictions):
            base_pred = base.predictions[idx]
            parts.extend([
                "",
                "**Base Model:**",
                f"> {base_pred}",
            ])

        return "\n".join(parts)

    def _generate_side_by_side(
        self,
        finetuned: EvaluationResult,
        base: EvaluationResult,
    ) -> str:
        """Generate side-by-side comparison section."""
        lines = [
            "## Side-by-Side Comparison Summary",
            "",
            "### Automatic Metrics",
            "",
        ]

        # Summary comparison
        improvements = []
        if finetuned.bleu and base.bleu:
            delta = finetuned.bleu.corpus_bleu - base.bleu.corpus_bleu
            direction = "improved" if delta > 0 else "declined"
            improvements.append(f"- BLEU-4: {direction} by {abs(delta):.2f} points")

        if finetuned.rouge and base.rouge:
            delta = finetuned.rouge.mean_f1 - base.rouge.mean_f1
            direction = "improved" if delta > 0 else "declined"
            improvements.append(f"- ROUGE-L F1: {direction} by {abs(delta):.4f}")

        if finetuned.llm_judge and base.llm_judge:
            delta = finetuned.llm_judge.overall_mean - base.llm_judge.overall_mean
            direction = "improved" if delta > 0 else "declined"
            improvements.append(f"- LLM Judge Overall: {direction} by {abs(delta):.2f}")

        lines.extend(improvements if improvements else ["No automatic metrics to compare."])

        # Inference speed comparison
        lines.extend([
            "",
            "### Inference Speed",
            "",
            f"- Base model: {base.inference_time_seconds:.1f}s "
            f"({base.num_samples / max(base.inference_time_seconds, 0.01):.1f} samples/s)",
            f"- Fine-tuned: {finetuned.inference_time_seconds:.1f}s "
            f"({finetuned.num_samples / max(finetuned.inference_time_seconds, 0.01):.1f} samples/s)",
        ])

        return "\n".join(lines)
