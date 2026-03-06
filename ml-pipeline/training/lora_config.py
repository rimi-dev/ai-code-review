"""QLoRA configuration module for AI Code Review Bot fine-tuning.

Loads training configuration from YAML and builds all necessary objects for
QLoRA training: BitsAndBytesConfig, LoraConfig, TrainingArguments, and
the base model with quantization applied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import torch
import yaml
from peft import LoraConfig, TaskType, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    PreTrainedModel,
    PreTrainedTokenizerBase,
    TrainingArguments,
)

logger = logging.getLogger(__name__)

# Default config path relative to this file
_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config" / "base_config.yaml"

# Mapping from string dtype names to torch dtypes
_DTYPE_MAP: dict[str, torch.dtype] = {
    "float16": torch.float16,
    "bfloat16": torch.bfloat16,
    "float32": torch.float32,
}


@dataclass
class ModelConfig:
    """Base model configuration."""

    name: str = "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct"
    revision: str = "main"
    trust_remote_code: bool = True
    torch_dtype: str = "bfloat16"


@dataclass
class QuantizationConfig:
    """BitsAndBytes 4-bit quantization configuration."""

    load_in_4bit: bool = True
    bnb_4bit_quant_type: str = "nf4"
    bnb_4bit_use_double_quant: bool = True
    bnb_4bit_compute_dtype: str = "bfloat16"


@dataclass
class LoraHyperparams:
    """LoRA adapter hyperparameters."""

    r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    bias: str = "none"
    task_type: str = "CAUSAL_LM"
    target_modules: list[str] = field(
        default_factory=lambda: [
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ]
    )


@dataclass
class TrainingHyperparams:
    """Training arguments configuration."""

    output_dir: str = "./output/checkpoints"
    num_train_epochs: int = 3
    per_device_train_batch_size: int = 4
    per_device_eval_batch_size: int = 4
    gradient_accumulation_steps: int = 8
    learning_rate: float = 2e-4
    weight_decay: float = 0.01
    warmup_ratio: float = 0.03
    lr_scheduler_type: str = "cosine"
    max_grad_norm: float = 0.3
    bf16: bool = True
    fp16: bool = False
    gradient_checkpointing: bool = True
    gradient_checkpointing_kwargs: dict[str, Any] = field(
        default_factory=lambda: {"use_reentrant": False}
    )
    optim: str = "paged_adamw_32bit"
    logging_steps: int = 10
    save_steps: int = 100
    save_total_limit: int = 3
    eval_strategy: str = "steps"
    eval_steps: int = 100
    load_best_model_at_end: bool = True
    metric_for_best_model: str = "eval_loss"
    greater_is_better: bool = False
    report_to: str = "mlflow"
    dataloader_num_workers: int = 4
    dataloader_pin_memory: bool = True
    remove_unused_columns: bool = False
    seed: int = 42
    data_seed: int = 42


@dataclass
class SFTConfig:
    """Supervised Fine-Tuning specific configuration."""

    max_seq_length: int = 4096
    packing: bool = False
    dataset_text_field: str = "text"
    neftune_noise_alpha: float = 5.0


@dataclass
class MLflowConfig:
    """MLflow tracking configuration."""

    experiment_name: str = "ai-code-review-finetune"
    tracking_uri: str = "http://localhost:5000"
    run_name_prefix: str = "qlora-deepseek-coder"
    log_model: bool = False
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class EarlyStoppingConfig:
    """Early stopping configuration."""

    patience: int = 3
    threshold: float = 0.001


@dataclass
class AdapterConfig:
    """Adapter saving and merging configuration."""

    save_dir: str = "./output/adapter"
    merged_dir: str = "./output/merged_model"
    push_to_hub: bool = False
    hub_model_id: str = ""


@dataclass
class FullConfig:
    """Complete training configuration aggregating all sub-configs."""

    model: ModelConfig = field(default_factory=ModelConfig)
    quantization: QuantizationConfig = field(default_factory=QuantizationConfig)
    lora: LoraHyperparams = field(default_factory=LoraHyperparams)
    training: TrainingHyperparams = field(default_factory=TrainingHyperparams)
    sft: SFTConfig = field(default_factory=SFTConfig)
    mlflow: MLflowConfig = field(default_factory=MLflowConfig)
    early_stopping: EarlyStoppingConfig = field(default_factory=EarlyStoppingConfig)
    adapter: AdapterConfig = field(default_factory=AdapterConfig)


def load_config(config_path: str | Path | None = None) -> FullConfig:
    """Load training configuration from a YAML file.

    Args:
        config_path: Path to the YAML config file. Uses default if None.

    Returns:
        FullConfig dataclass with all configuration sections populated.

    Raises:
        FileNotFoundError: If the config file does not exist.
        yaml.YAMLError: If the YAML is malformed.
    """
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH

    if not path.exists():
        msg = f"Configuration file not found: {path}"
        raise FileNotFoundError(msg)

    logger.info("Loading configuration from %s", path)
    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    config = FullConfig(
        model=ModelConfig(**raw.get("model", {})),
        quantization=QuantizationConfig(**raw.get("quantization", {})),
        lora=LoraHyperparams(**raw.get("lora", {})),
        training=TrainingHyperparams(**raw.get("training", {})),
        sft=SFTConfig(**raw.get("sft", {})),
        mlflow=MLflowConfig(**raw.get("mlflow", {})),
        early_stopping=EarlyStoppingConfig(**raw.get("early_stopping", {})),
        adapter=AdapterConfig(**raw.get("adapter", {})),
    )

    logger.info(
        "Configuration loaded: model=%s, LoRA r=%d alpha=%d, lr=%.2e, epochs=%d",
        config.model.name,
        config.lora.r,
        config.lora.lora_alpha,
        config.training.learning_rate,
        config.training.num_train_epochs,
    )
    return config


def build_bnb_config(config: QuantizationConfig) -> BitsAndBytesConfig:
    """Build BitsAndBytesConfig for 4-bit quantization.

    Args:
        config: Quantization configuration parameters.

    Returns:
        Configured BitsAndBytesConfig instance.
    """
    compute_dtype = _DTYPE_MAP.get(config.bnb_4bit_compute_dtype, torch.bfloat16)

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=config.load_in_4bit,
        bnb_4bit_quant_type=config.bnb_4bit_quant_type,
        bnb_4bit_use_double_quant=config.bnb_4bit_use_double_quant,
        bnb_4bit_compute_dtype=compute_dtype,
    )

    logger.info(
        "BitsAndBytesConfig: 4-bit=%s, quant_type=%s, double_quant=%s, compute_dtype=%s",
        bnb_config.load_in_4bit,
        bnb_config.bnb_4bit_quant_type,
        bnb_config.bnb_4bit_use_double_quant,
        compute_dtype,
    )
    return bnb_config


def build_lora_config(config: LoraHyperparams) -> LoraConfig:
    """Build PEFT LoraConfig from hyperparameters.

    Args:
        config: LoRA hyperparameters.

    Returns:
        Configured LoraConfig instance.
    """
    task_type_map: dict[str, TaskType] = {
        "CAUSAL_LM": TaskType.CAUSAL_LM,
        "SEQ_2_SEQ_LM": TaskType.SEQ_2_SEQ_LM,
        "TOKEN_CLS": TaskType.TOKEN_CLS,
        "SEQ_CLS": TaskType.SEQ_CLS,
    }
    task = task_type_map.get(config.task_type, TaskType.CAUSAL_LM)

    lora_cfg = LoraConfig(
        r=config.r,
        lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout,
        bias=config.bias,
        task_type=task,
        target_modules=config.target_modules,
    )

    logger.info(
        "LoraConfig: r=%d, alpha=%d, dropout=%.3f, targets=%s",
        lora_cfg.r,
        lora_cfg.lora_alpha,
        lora_cfg.lora_dropout,
        lora_cfg.target_modules,
    )
    return lora_cfg


def build_training_arguments(config: TrainingHyperparams) -> TrainingArguments:
    """Build HuggingFace TrainingArguments from configuration.

    Args:
        config: Training hyperparameters.

    Returns:
        Configured TrainingArguments instance.
    """
    args = TrainingArguments(
        output_dir=config.output_dir,
        num_train_epochs=config.num_train_epochs,
        per_device_train_batch_size=config.per_device_train_batch_size,
        per_device_eval_batch_size=config.per_device_eval_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        learning_rate=config.learning_rate,
        weight_decay=config.weight_decay,
        warmup_ratio=config.warmup_ratio,
        lr_scheduler_type=config.lr_scheduler_type,
        max_grad_norm=config.max_grad_norm,
        bf16=config.bf16,
        fp16=config.fp16,
        gradient_checkpointing=config.gradient_checkpointing,
        gradient_checkpointing_kwargs=config.gradient_checkpointing_kwargs,
        optim=config.optim,
        logging_steps=config.logging_steps,
        save_steps=config.save_steps,
        save_total_limit=config.save_total_limit,
        eval_strategy=config.eval_strategy,
        eval_steps=config.eval_steps,
        load_best_model_at_end=config.load_best_model_at_end,
        metric_for_best_model=config.metric_for_best_model,
        greater_is_better=config.greater_is_better,
        report_to=config.report_to,
        dataloader_num_workers=config.dataloader_num_workers,
        dataloader_pin_memory=config.dataloader_pin_memory,
        remove_unused_columns=config.remove_unused_columns,
        seed=config.seed,
        data_seed=config.data_seed,
    )

    effective_batch = (
        config.per_device_train_batch_size * config.gradient_accumulation_steps
    )
    logger.info(
        "TrainingArguments: epochs=%d, effective_batch=%d, lr=%.2e, warmup=%.2f",
        config.num_train_epochs,
        effective_batch,
        config.learning_rate,
        config.warmup_ratio,
    )
    return args


def load_base_model(
    model_config: ModelConfig,
    quantization_config: QuantizationConfig,
    device_map: str | dict[str, Any] = "auto",
) -> PreTrainedModel:
    """Load the base model with 4-bit quantization applied.

    Args:
        model_config: Model identification and loading parameters.
        quantization_config: Quantization settings for BitsAndBytes.
        device_map: Device placement strategy. Defaults to "auto".

    Returns:
        Quantized PreTrainedModel ready for LoRA adapter attachment.
    """
    bnb_config = build_bnb_config(quantization_config)
    compute_dtype = _DTYPE_MAP.get(model_config.torch_dtype, torch.bfloat16)

    logger.info("Loading base model: %s (revision: %s)", model_config.name, model_config.revision)

    model = AutoModelForCausalLM.from_pretrained(
        model_config.name,
        revision=model_config.revision,
        quantization_config=bnb_config,
        device_map=device_map,
        torch_dtype=compute_dtype,
        trust_remote_code=model_config.trust_remote_code,
        attn_implementation="flash_attention_2",
    )

    # Disable cache for gradient checkpointing compatibility
    model.config.use_cache = False
    model.config.pretraining_tp = 1

    logger.info(
        "Model loaded: %s, parameters=%d, dtype=%s",
        model_config.name,
        sum(p.numel() for p in model.parameters()),
        compute_dtype,
    )
    return model


def prepare_model_for_qlora(model: PreTrainedModel) -> PreTrainedModel:
    """Prepare a quantized model for QLoRA training.

    Applies PEFT's prepare_model_for_kbit_training which handles:
    - Freezing base model parameters
    - Casting layer norms to float32
    - Enabling gradient computation for LoRA-compatible layers

    Args:
        model: The quantized base model.

    Returns:
        Model prepared for QLoRA fine-tuning.
    """
    logger.info("Preparing model for QLoRA (kbit training)")
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    # Log trainable parameter statistics
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    all_params = sum(p.numel() for p in model.parameters())
    trainable_pct = 100 * trainable_params / all_params if all_params > 0 else 0

    logger.info(
        "Model prepared: trainable=%d / %d (%.2f%%)",
        trainable_params,
        all_params,
        trainable_pct,
    )
    return model


def load_tokenizer(model_config: ModelConfig) -> PreTrainedTokenizerBase:
    """Load and configure the tokenizer for the base model.

    Ensures padding token is set (required for batch training) and
    configures left-padding for causal LM generation compatibility.

    Args:
        model_config: Model identification parameters.

    Returns:
        Configured tokenizer instance.
    """
    logger.info("Loading tokenizer for %s", model_config.name)

    tokenizer = AutoTokenizer.from_pretrained(
        model_config.name,
        revision=model_config.revision,
        trust_remote_code=model_config.trust_remote_code,
    )

    # Ensure pad token is set
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        tokenizer.pad_token_id = tokenizer.eos_token_id
        logger.info("Set pad_token to eos_token: %s", tokenizer.pad_token)

    # Use left padding for generation compatibility with causal LMs
    tokenizer.padding_side = "right"

    logger.info(
        "Tokenizer loaded: vocab_size=%d, pad_token=%s, padding_side=%s",
        tokenizer.vocab_size,
        tokenizer.pad_token,
        tokenizer.padding_side,
    )
    return tokenizer
