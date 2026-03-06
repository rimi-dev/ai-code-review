"""Main training script for QLoRA fine-tuning of the code review model.

Orchestrates the full training pipeline:
1. Load configuration from YAML
2. Load and prepare the base model with QLoRA
3. Load and format the dataset
4. Initialize SFTTrainer with MLflow tracking
5. Train, save adapter weights, and optionally merge into base model

Usage:
    python -m training.train --config training/config/base_config.yaml \
        --dataset-path ./output/preprocessed/parquet \
        --output-dir ./output/training
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mlflow
import torch
from datasets import DatasetDict, load_dataset, load_from_disk
from peft import PeftModel, get_peft_model
from trl import SFTTrainer

from training.callbacks import (
    CustomLoggingCallback,
    EarlyStoppingCallback,
    MLflowMetricsCallback,
)
from training.lora_config import (
    FullConfig,
    build_lora_config,
    build_training_arguments,
    load_base_model,
    load_config,
    load_tokenizer,
    prepare_model_for_qlora,
)

logger = logging.getLogger(__name__)

# System prompt matching the one used in preprocessing
DEFAULT_SYSTEM_PROMPT = (
    "You are an expert code reviewer. Analyze the given code diff and provide a constructive, "
    "specific, and actionable review comment. Focus on code quality, potential bugs, performance, "
    "security, and best practices. Be concise but thorough."
)


def build_chat_template_formatter(
    tokenizer: Any,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    max_seq_length: int = 4096,
) -> callable:
    """Build a formatting function that converts instruction samples to chat format.

    Uses the tokenizer's chat template if available, otherwise falls back to
    a standard ChatML-style template.

    Args:
        tokenizer: The model tokenizer with apply_chat_template support.
        system_prompt: System prompt for the code reviewer role.
        max_seq_length: Maximum sequence length for truncation.

    Returns:
        A callable that formats a single dataset row into a text string.
    """

    def format_sample(sample: dict[str, Any]) -> dict[str, str]:
        """Format a single sample into chat template text.

        Expected sample keys: instruction, input, output
        """
        instruction = sample.get("instruction", system_prompt)
        user_input = sample.get("input", "")
        assistant_output = sample.get("output", "")

        # Build messages in chat format
        messages = [
            {"role": "system", "content": instruction},
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": assistant_output},
        ]

        # Apply chat template if available
        if hasattr(tokenizer, "apply_chat_template"):
            try:
                text = tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=False,
                )
            except Exception:
                logger.debug("Chat template failed, using fallback format")
                text = _fallback_format(instruction, user_input, assistant_output)
        else:
            text = _fallback_format(instruction, user_input, assistant_output)

        return {"text": text}

    return format_sample


def _fallback_format(instruction: str, user_input: str, assistant_output: str) -> str:
    """Fallback ChatML-style formatting when tokenizer template is unavailable."""
    return (
        f"<|im_start|>system\n{instruction}<|im_end|>\n"
        f"<|im_start|>user\n{user_input}<|im_end|>\n"
        f"<|im_start|>assistant\n{assistant_output}<|im_end|>"
    )


def load_training_dataset(
    dataset_path: str,
    config: FullConfig,
    tokenizer: Any,
) -> DatasetDict:
    """Load and prepare the training dataset.

    Supports loading from:
    - Parquet directory (with train/validation/test splits)
    - HuggingFace datasets directory (saved with save_to_disk)
    - HuggingFace Hub dataset identifier

    Args:
        dataset_path: Path to the dataset directory or HF Hub identifier.
        config: Full training configuration.
        tokenizer: Tokenizer for formatting.

    Returns:
        DatasetDict with formatted text column ready for SFTTrainer.
    """
    path = Path(dataset_path)
    dataset_dict: DatasetDict

    if path.is_dir():
        # Check for parquet files
        parquet_files = list(path.glob("*.parquet"))
        if parquet_files:
            logger.info("Loading dataset from parquet files in %s", path)
            data_files = {}
            for pf in parquet_files:
                split_name = pf.stem  # e.g., "train", "validation", "test"
                data_files[split_name] = str(pf)
            dataset_dict = load_dataset("parquet", data_files=data_files)
        elif (path / "dataset_dict.json").exists():
            logger.info("Loading HuggingFace dataset from disk: %s", path)
            dataset_dict = DatasetDict.load_from_disk(str(path))
        else:
            msg = f"No recognized dataset format found in {path}"
            raise FileNotFoundError(msg)
    else:
        # Assume HuggingFace Hub identifier
        logger.info("Loading dataset from HuggingFace Hub: %s", dataset_path)
        dataset_dict = load_dataset(dataset_path)

    # Log dataset sizes
    for split_name, ds in dataset_dict.items():
        logger.info("  %s: %d samples", split_name, len(ds))

    # Format samples with chat template
    formatter = build_chat_template_formatter(
        tokenizer=tokenizer,
        max_seq_length=config.sft.max_seq_length,
    )

    logger.info("Applying chat template formatting to all splits")
    formatted_dict = DatasetDict()
    for split_name, ds in dataset_dict.items():
        formatted_dict[split_name] = ds.map(
            formatter,
            desc=f"Formatting {split_name}",
            num_proc=min(os.cpu_count() or 1, 8),
        )

    return formatted_dict


def setup_mlflow(config: FullConfig) -> str:
    """Configure MLflow tracking for the training run.

    Args:
        config: Full configuration containing MLflow settings.

    Returns:
        The MLflow run ID.
    """
    mlflow_cfg = config.mlflow
    mlflow.set_tracking_uri(mlflow_cfg.tracking_uri)
    mlflow.set_experiment(mlflow_cfg.experiment_name)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_name = f"{mlflow_cfg.run_name_prefix}-{timestamp}"

    # Enable autologging for transformers
    mlflow.transformers.autolog(
        log_models=mlflow_cfg.log_model,
        log_input_examples=False,
        log_model_signatures=False,
    )

    run = mlflow.start_run(run_name=run_name, tags=mlflow_cfg.tags)
    run_id = run.info.run_id

    # Log full configuration as parameters
    mlflow.log_params({
        "model_name": config.model.name,
        "lora_r": config.lora.r,
        "lora_alpha": config.lora.lora_alpha,
        "lora_dropout": config.lora.lora_dropout,
        "learning_rate": config.training.learning_rate,
        "num_epochs": config.training.num_train_epochs,
        "batch_size": config.training.per_device_train_batch_size,
        "grad_accum_steps": config.training.gradient_accumulation_steps,
        "max_seq_length": config.sft.max_seq_length,
        "warmup_ratio": config.training.warmup_ratio,
        "quant_type": config.quantization.bnb_4bit_quant_type,
        "double_quant": config.quantization.bnb_4bit_use_double_quant,
        "neftune_alpha": config.sft.neftune_noise_alpha,
    })

    logger.info("MLflow tracking started: experiment=%s, run=%s (%s)",
                mlflow_cfg.experiment_name, run_name, run_id)
    return run_id


def save_adapter(
    model: PeftModel,
    tokenizer: Any,
    config: FullConfig,
) -> Path:
    """Save the trained LoRA adapter weights.

    Args:
        model: The PEFT model with trained adapter.
        tokenizer: The tokenizer to save alongside.
        config: Configuration for save paths.

    Returns:
        Path to the saved adapter directory.
    """
    save_dir = Path(config.adapter.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Saving LoRA adapter to %s", save_dir)
    model.save_pretrained(str(save_dir))
    tokenizer.save_pretrained(str(save_dir))

    # Log adapter as MLflow artifact
    try:
        mlflow.log_artifacts(str(save_dir), artifact_path="adapter")
    except Exception:
        logger.warning("Failed to log adapter to MLflow artifacts", exc_info=True)

    logger.info("Adapter saved successfully to %s", save_dir)
    return save_dir


def merge_and_save(
    model: PeftModel,
    tokenizer: Any,
    config: FullConfig,
) -> Path:
    """Merge LoRA adapter into base model and save the full model.

    This produces a standalone model that can be loaded without PEFT,
    suitable for deployment with vLLM or other inference servers.

    Args:
        model: The PEFT model with trained adapter.
        tokenizer: The tokenizer to save alongside.
        config: Configuration for save paths.

    Returns:
        Path to the merged model directory.
    """
    merged_dir = Path(config.adapter.merged_dir)
    merged_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Merging LoRA adapter into base model")
    merged_model = model.merge_and_unload()

    logger.info("Saving merged model to %s", merged_dir)
    merged_model.save_pretrained(
        str(merged_dir),
        safe_serialization=True,
        max_shard_size="4GB",
    )
    tokenizer.save_pretrained(str(merged_dir))

    logger.info("Merged model saved successfully to %s", merged_dir)
    return merged_dir


def train(config: FullConfig, dataset_path: str, output_dir: str | None = None) -> None:
    """Execute the full QLoRA training pipeline.

    Args:
        config: Complete training configuration.
        dataset_path: Path to the preprocessed dataset.
        output_dir: Override for the training output directory.
    """
    start_time = time.monotonic()

    # Override output dir if provided
    if output_dir:
        config.training.output_dir = output_dir
        config.adapter.save_dir = str(Path(output_dir) / "adapter")
        config.adapter.merged_dir = str(Path(output_dir) / "merged_model")

    # Step 1: Setup MLflow
    logger.info("=" * 70)
    logger.info("Starting QLoRA fine-tuning pipeline")
    logger.info("=" * 70)

    run_id = setup_mlflow(config)

    try:
        # Step 2: Load tokenizer
        logger.info("[Step 1/6] Loading tokenizer")
        tokenizer = load_tokenizer(config.model)

        # Step 3: Load and format dataset
        logger.info("[Step 2/6] Loading and formatting dataset")
        dataset_dict = load_training_dataset(dataset_path, config, tokenizer)

        train_dataset = dataset_dict.get("train")
        eval_dataset = dataset_dict.get("validation")

        if train_dataset is None:
            msg = "No 'train' split found in the dataset"
            raise ValueError(msg)

        logger.info("Training samples: %d", len(train_dataset))
        if eval_dataset:
            logger.info("Evaluation samples: %d", len(eval_dataset))

        # Step 4: Load and prepare model
        logger.info("[Step 3/6] Loading base model with quantization")
        model = load_base_model(config.model, config.quantization)
        model = prepare_model_for_qlora(model)

        # Step 5: Attach LoRA adapter
        logger.info("[Step 4/6] Attaching LoRA adapter")
        lora_cfg = build_lora_config(config.lora)
        model = get_peft_model(model, lora_cfg)
        model.print_trainable_parameters()

        # Step 6: Build training arguments
        training_args = build_training_arguments(config.training)

        # Step 7: Initialize callbacks
        callbacks = [
            MLflowMetricsCallback(),
            CustomLoggingCallback(),
        ]
        if eval_dataset is not None:
            callbacks.append(
                EarlyStoppingCallback(
                    patience=config.early_stopping.patience,
                    threshold=config.early_stopping.threshold,
                )
            )

        # Step 8: Initialize SFTTrainer
        logger.info("[Step 5/6] Initializing SFTTrainer")
        trainer = SFTTrainer(
            model=model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=eval_dataset,
            processing_class=tokenizer,
            max_seq_length=config.sft.max_seq_length,
            packing=config.sft.packing,
            dataset_text_field=config.sft.dataset_text_field,
            neftune_noise_alpha=config.sft.neftune_noise_alpha,
            callbacks=callbacks,
        )

        # Step 9: Train
        logger.info("[Step 6/6] Starting training")
        train_result = trainer.train()

        # Log final training metrics
        metrics = train_result.metrics
        metrics["train_runtime_minutes"] = metrics.get("train_runtime", 0) / 60
        metrics["train_samples"] = len(train_dataset)
        trainer.log_metrics("train", metrics)
        trainer.save_metrics("train", metrics)

        mlflow.log_metrics({
            f"final_{k}": v for k, v in metrics.items()
            if isinstance(v, (int, float))
        })

        # Run final evaluation
        if eval_dataset is not None:
            logger.info("Running final evaluation")
            eval_metrics = trainer.evaluate()
            trainer.log_metrics("eval", eval_metrics)
            trainer.save_metrics("eval", eval_metrics)

            mlflow.log_metrics({
                f"final_eval_{k}": v for k, v in eval_metrics.items()
                if isinstance(v, (int, float))
            })

        # Save adapter weights
        logger.info("Saving adapter weights")
        save_adapter(model, tokenizer, config)

        # Merge and save full model
        logger.info("Merging adapter and saving full model")
        merge_and_save(model, tokenizer, config)

        # Log total training time
        elapsed = time.monotonic() - start_time
        mlflow.log_metric("total_pipeline_minutes", elapsed / 60)

        logger.info("=" * 70)
        logger.info("Training complete in %.1f minutes", elapsed / 60)
        logger.info("Adapter saved to: %s", config.adapter.save_dir)
        logger.info("Merged model saved to: %s", config.adapter.merged_dir)
        logger.info("MLflow run ID: %s", run_id)
        logger.info("=" * 70)

    except Exception:
        logger.exception("Training pipeline failed")
        mlflow.log_param("status", "FAILED")
        raise
    finally:
        mlflow.end_run()


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="QLoRA Fine-tuning for AI Code Review Bot",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(_DEFAULT_CONFIG := Path(__file__).parent / "config" / "base_config.yaml"),
        help="Path to the YAML configuration file",
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
        default=None,
        help="Override output directory for checkpoints and model saves",
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
    """CLI entry point for the training script."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("training.log", mode="a", encoding="utf-8"),
        ],
    )

    # Suppress overly verbose loggers
    logging.getLogger("transformers").setLevel(logging.WARNING)
    logging.getLogger("datasets").setLevel(logging.WARNING)
    logging.getLogger("accelerate").setLevel(logging.WARNING)

    config = load_config(args.config)
    train(config=config, dataset_path=args.dataset_path, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
