"""Main evaluation script for the AI Code Review Bot fine-tuned model.

Orchestrates:
1. Loading the fine-tuned model (or base model for comparison)
2. Running inference on the test set
3. Computing all metrics (BLEU, ROUGE-L, LLM Judge)
4. Generating a comparison report

Usage:
    python -m evaluation.evaluate \
        --model-path ./output/merged_model \
        --dataset-path ./output/preprocessed/parquet/test.parquet \
        --output-dir ./output/evaluation \
        --run-llm-judge
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import torch
from datasets import Dataset, load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, PreTrainedModel, PreTrainedTokenizerBase

from evaluation.metrics.bleu_metric import BLEUMetric, BLEUResult
from evaluation.metrics.llm_judge import JudgeResult, LLMJudge
from evaluation.metrics.rouge_metric import ROUGEMetric, ROUGEResult
from evaluation.report import ReportGenerator

logger = logging.getLogger(__name__)

# Default generation parameters
DEFAULT_MAX_NEW_TOKENS = 512
DEFAULT_TEMPERATURE = 0.1
DEFAULT_TOP_P = 0.95
DEFAULT_REPETITION_PENALTY = 1.1

# System prompt (must match training)
DEFAULT_SYSTEM_PROMPT = (
    "You are an expert code reviewer. Analyze the given code diff and provide a constructive, "
    "specific, and actionable review comment. Focus on code quality, potential bugs, performance, "
    "security, and best practices. Be concise but thorough."
)


@dataclass
class InferenceConfig:
    """Configuration for model inference."""

    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    top_p: float = DEFAULT_TOP_P
    repetition_penalty: float = DEFAULT_REPETITION_PENALTY
    do_sample: bool = True
    num_beams: int = 1


@dataclass
class EvaluationResult:
    """Complete evaluation results."""

    bleu: BLEUResult | None = None
    rouge: ROUGEResult | None = None
    llm_judge: JudgeResult | None = None
    predictions: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    inference_time_seconds: float = 0.0
    num_samples: int = 0
    model_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "model_name": self.model_name,
            "num_samples": self.num_samples,
            "inference_time_seconds": round(self.inference_time_seconds, 2),
        }
        if self.bleu:
            result["bleu"] = self.bleu.to_dict()
        if self.rouge:
            result["rouge"] = self.rouge.to_dict()
        if self.llm_judge:
            result["llm_judge"] = self.llm_judge.to_dict()
        return result


class ModelEvaluator:
    """Evaluates a code review model on the test set with multiple metrics.

    Supports evaluating:
    - A fine-tuned merged model
    - The base model (for comparison)
    - Any HuggingFace causal LM model

    Args:
        model_path: Path to the model directory or HF Hub identifier.
        device: Device to run inference on.
        inference_config: Generation parameters.
        trust_remote_code: Whether to trust remote code in model loading.
    """

    def __init__(
        self,
        model_path: str,
        device: str = "auto",
        inference_config: InferenceConfig | None = None,
        trust_remote_code: bool = True,
    ) -> None:
        self.model_path = model_path
        self.device = device
        self.inference_config = inference_config or InferenceConfig()
        self.trust_remote_code = trust_remote_code

        self._model: PreTrainedModel | None = None
        self._tokenizer: PreTrainedTokenizerBase | None = None

    def load_model(self) -> None:
        """Load the model and tokenizer from the specified path."""
        logger.info("Loading model from %s", self.model_path)

        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_path,
            trust_remote_code=self.trust_remote_code,
        )

        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token
            self._tokenizer.pad_token_id = self._tokenizer.eos_token_id

        # Determine dtype and device
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            torch_dtype=dtype,
            device_map=self.device,
            trust_remote_code=self.trust_remote_code,
        )
        self._model.eval()

        num_params = sum(p.numel() for p in self._model.parameters())
        logger.info("Model loaded: %s (%d parameters)", self.model_path, num_params)

    def generate_review(self, code_input: str, instruction: str = DEFAULT_SYSTEM_PROMPT) -> str:
        """Generate a code review comment for a single input.

        Args:
            code_input: The formatted code diff input.
            instruction: System instruction for the reviewer.

        Returns:
            Generated review comment text.
        """
        if self._model is None or self._tokenizer is None:
            msg = "Model not loaded. Call load_model() first."
            raise RuntimeError(msg)

        messages = [
            {"role": "system", "content": instruction},
            {"role": "user", "content": code_input},
        ]

        # Apply chat template
        if hasattr(self._tokenizer, "apply_chat_template"):
            try:
                prompt = self._tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
            except Exception:
                prompt = self._build_fallback_prompt(instruction, code_input)
        else:
            prompt = self._build_fallback_prompt(instruction, code_input)

        inputs = self._tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=4096 - self.inference_config.max_new_tokens,
        ).to(self._model.device)

        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=self.inference_config.max_new_tokens,
                temperature=self.inference_config.temperature,
                top_p=self.inference_config.top_p,
                repetition_penalty=self.inference_config.repetition_penalty,
                do_sample=self.inference_config.do_sample,
                num_beams=self.inference_config.num_beams,
                pad_token_id=self._tokenizer.pad_token_id,
                eos_token_id=self._tokenizer.eos_token_id,
            )

        # Decode only the generated tokens (exclude the prompt)
        prompt_length = inputs["input_ids"].shape[1]
        generated_ids = outputs[0][prompt_length:]
        generated_text = self._tokenizer.decode(generated_ids, skip_special_tokens=True)

        return generated_text.strip()

    @staticmethod
    def _build_fallback_prompt(instruction: str, code_input: str) -> str:
        """Build a ChatML-style prompt as fallback."""
        return (
            f"<|im_start|>system\n{instruction}<|im_end|>\n"
            f"<|im_start|>user\n{code_input}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

    def evaluate(
        self,
        dataset: Dataset,
        run_llm_judge: bool = False,
        llm_judge_model: str = "claude-sonnet-4-20250514",
        max_samples: int | None = None,
    ) -> EvaluationResult:
        """Run full evaluation on a dataset.

        Args:
            dataset: HuggingFace Dataset with 'input', 'output', and optional 'language' columns.
            run_llm_judge: Whether to run LLM-as-judge evaluation.
            llm_judge_model: Claude model for LLM judge.
            max_samples: Limit number of samples to evaluate.

        Returns:
            EvaluationResult with all metrics and predictions.
        """
        if self._model is None:
            self.load_model()

        samples = list(dataset)
        if max_samples and max_samples < len(samples):
            samples = samples[:max_samples]

        num_samples = len(samples)
        logger.info("Evaluating %d samples", num_samples)

        # Run inference
        predictions: list[str] = []
        references: list[str] = []
        inputs: list[str] = []
        languages: list[str] = []

        start_time = time.monotonic()

        for idx, sample in enumerate(samples):
            input_text = sample.get("input", "")
            reference = sample.get("output", "")
            instruction = sample.get("instruction", DEFAULT_SYSTEM_PROMPT)
            language = sample.get("language", "Unknown")

            prediction = self.generate_review(input_text, instruction)

            predictions.append(prediction)
            references.append(reference)
            inputs.append(input_text)
            languages.append(language)

            if (idx + 1) % 10 == 0:
                elapsed = time.monotonic() - start_time
                rate = (idx + 1) / elapsed if elapsed > 0 else 0
                eta = (num_samples - idx - 1) / rate if rate > 0 else 0
                logger.info(
                    "  Inference: %d/%d (%.1f samples/s, ETA: %.0fs)",
                    idx + 1, num_samples, rate, eta,
                )

        inference_time = time.monotonic() - start_time
        logger.info("Inference complete: %d samples in %.1fs", num_samples, inference_time)

        # Compute BLEU
        logger.info("Computing BLEU-4 scores")
        bleu_metric = BLEUMetric()
        bleu_result = bleu_metric.compute(predictions, references)

        # Compute ROUGE-L
        logger.info("Computing ROUGE-L scores")
        rouge_metric = ROUGEMetric()
        rouge_result = rouge_metric.compute(predictions, references)

        # LLM Judge (optional)
        judge_result: JudgeResult | None = None
        if run_llm_judge:
            logger.info("Running LLM-as-Judge evaluation")
            judge = LLMJudge(model=llm_judge_model)

            # Extract diffs from inputs for the judge
            diffs = [self._extract_diff_from_input(inp) for inp in inputs]
            judge_result = judge.evaluate_batch(diffs, references, predictions)

        return EvaluationResult(
            bleu=bleu_result,
            rouge=rouge_result,
            llm_judge=judge_result,
            predictions=predictions,
            references=references,
            inputs=inputs,
            languages=languages,
            inference_time_seconds=inference_time,
            num_samples=num_samples,
            model_name=self.model_path,
        )

    @staticmethod
    def _extract_diff_from_input(input_text: str) -> str:
        """Extract the diff portion from a formatted input text.

        The input format is:
            File: path
            Language: lang

            Diff:
            ```diff
            ...actual diff...
            ```
        """
        lines = input_text.split("\n")
        in_diff = False
        diff_lines: list[str] = []

        for line in lines:
            if line.strip() == "```diff":
                in_diff = True
                continue
            if in_diff and line.strip() == "```":
                break
            if in_diff:
                diff_lines.append(line)

        return "\n".join(diff_lines) if diff_lines else input_text


def load_test_dataset(dataset_path: str) -> Dataset:
    """Load the test dataset from various formats.

    Args:
        dataset_path: Path to parquet file, HF dataset dir, or Hub ID.

    Returns:
        HuggingFace Dataset object.
    """
    path = Path(dataset_path)

    if path.is_file() and path.suffix == ".parquet":
        logger.info("Loading test dataset from parquet: %s", path)
        return load_dataset("parquet", data_files=str(path), split="train")

    if path.is_dir():
        test_parquet = path / "test.parquet"
        if test_parquet.exists():
            logger.info("Loading test split from parquet dir: %s", test_parquet)
            return load_dataset("parquet", data_files=str(test_parquet), split="train")

        if (path / "dataset_dict.json").exists():
            from datasets import DatasetDict
            dd = DatasetDict.load_from_disk(str(path))
            if "test" in dd:
                return dd["test"]

    # Try HuggingFace Hub
    logger.info("Loading test dataset from Hub: %s", dataset_path)
    return load_dataset(dataset_path, split="test")


def run_comparison(
    finetuned_result: EvaluationResult,
    base_result: EvaluationResult | None = None,
    output_dir: str = "./output/evaluation",
) -> None:
    """Generate comparison report between fine-tuned and base model.

    Args:
        finetuned_result: Evaluation results from the fine-tuned model.
        base_result: Optional evaluation results from the base model.
        output_dir: Directory to save the report.
    """
    report_gen = ReportGenerator(output_dir=output_dir)
    report_gen.generate(
        finetuned_result=finetuned_result,
        base_result=base_result,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Evaluate the AI Code Review fine-tuned model",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Model
    parser.add_argument(
        "--model-path",
        type=str,
        required=True,
        help="Path to the fine-tuned (merged) model directory",
    )
    parser.add_argument(
        "--base-model-path",
        type=str,
        default=None,
        help="Path to the base model for comparison (optional)",
    )
    parser.add_argument(
        "--trust-remote-code",
        action="store_true",
        default=True,
        help="Trust remote code when loading model",
    )

    # Dataset
    parser.add_argument(
        "--dataset-path",
        type=str,
        required=True,
        help="Path to the test dataset (parquet file, HF dir, or Hub ID)",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Maximum number of samples to evaluate (None = all)",
    )

    # Output
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output/evaluation",
        help="Directory to save evaluation results and reports",
    )

    # LLM Judge
    parser.add_argument(
        "--run-llm-judge",
        action="store_true",
        default=False,
        help="Run LLM-as-judge evaluation using Claude",
    )
    parser.add_argument(
        "--llm-judge-model",
        type=str,
        default="claude-sonnet-4-20250514",
        help="Claude model to use as LLM judge",
    )

    # Inference
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=DEFAULT_MAX_NEW_TOKENS,
        help="Maximum tokens to generate per sample",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="Sampling temperature for generation",
    )

    # Logging
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for evaluation."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("evaluation.log", mode="a", encoding="utf-8"),
        ],
    )
    logging.getLogger("transformers").setLevel(logging.WARNING)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load test dataset
    test_dataset = load_test_dataset(args.dataset_path)
    logger.info("Test dataset loaded: %d samples", len(test_dataset))

    # Inference config
    inference_cfg = InferenceConfig(
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
    )

    # Evaluate fine-tuned model
    logger.info("=" * 70)
    logger.info("Evaluating fine-tuned model: %s", args.model_path)
    logger.info("=" * 70)

    evaluator = ModelEvaluator(
        model_path=args.model_path,
        inference_config=inference_cfg,
        trust_remote_code=args.trust_remote_code,
    )
    finetuned_result = evaluator.evaluate(
        dataset=test_dataset,
        run_llm_judge=args.run_llm_judge,
        llm_judge_model=args.llm_judge_model,
        max_samples=args.max_samples,
    )

    # Save raw results
    results_path = output_dir / "finetuned_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(finetuned_result.to_dict(), f, indent=2, ensure_ascii=False)
    logger.info("Fine-tuned results saved to %s", results_path)

    # Optionally evaluate base model
    base_result: EvaluationResult | None = None
    if args.base_model_path:
        logger.info("=" * 70)
        logger.info("Evaluating base model: %s", args.base_model_path)
        logger.info("=" * 70)

        base_evaluator = ModelEvaluator(
            model_path=args.base_model_path,
            inference_config=inference_cfg,
            trust_remote_code=args.trust_remote_code,
        )
        base_result = base_evaluator.evaluate(
            dataset=test_dataset,
            run_llm_judge=args.run_llm_judge,
            llm_judge_model=args.llm_judge_model,
            max_samples=args.max_samples,
        )

        base_results_path = output_dir / "base_results.json"
        with open(base_results_path, "w", encoding="utf-8") as f:
            json.dump(base_result.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info("Base model results saved to %s", base_results_path)

    # Save LLM judge scores if available
    if finetuned_result.llm_judge:
        judge = LLMJudge()
        judge.save_scores(finetuned_result.llm_judge, output_dir / "finetuned_llm_judge_scores.json")

    if base_result and base_result.llm_judge:
        judge = LLMJudge()
        judge.save_scores(base_result.llm_judge, output_dir / "base_llm_judge_scores.json")

    # Generate comparison report
    logger.info("Generating evaluation report")
    run_comparison(finetuned_result, base_result, str(output_dir))

    logger.info("=" * 70)
    logger.info("Evaluation complete. Results at: %s", output_dir)
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
