"""Custom training callbacks for the QLoRA fine-tuning pipeline.

Provides:
- MLflowMetricsCallback: Logs detailed per-step metrics to MLflow
- EarlyStoppingCallback: Stops training when eval loss plateaus
- CustomLoggingCallback: Rich console logging with ETA and throughput
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import mlflow
from transformers import TrainerCallback, TrainerControl, TrainerState, TrainingArguments

logger = logging.getLogger(__name__)


class MLflowMetricsCallback(TrainerCallback):
    """Logs granular per-step metrics to MLflow.

    Captures training loss, learning rate, gradient norm, and epoch
    at every logging step. Also logs evaluation metrics when available.
    """

    def __init__(self) -> None:
        super().__init__()
        self._step_count: int = 0

    def on_log(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        logs: dict | None = None,
        **kwargs,
    ) -> None:
        """Log metrics to MLflow at each logging step."""
        if logs is None:
            return

        self._step_count += 1
        step = state.global_step

        metrics_to_log: dict[str, float] = {}

        # Training metrics
        if "loss" in logs:
            metrics_to_log["train/loss"] = logs["loss"]
        if "learning_rate" in logs:
            metrics_to_log["train/learning_rate"] = logs["learning_rate"]
        if "grad_norm" in logs:
            metrics_to_log["train/grad_norm"] = float(logs["grad_norm"])
        if "epoch" in logs:
            metrics_to_log["train/epoch"] = logs["epoch"]

        # Evaluation metrics
        if "eval_loss" in logs:
            metrics_to_log["eval/loss"] = logs["eval_loss"]
        if "eval_runtime" in logs:
            metrics_to_log["eval/runtime"] = logs["eval_runtime"]
        if "eval_samples_per_second" in logs:
            metrics_to_log["eval/samples_per_second"] = logs["eval_samples_per_second"]

        if metrics_to_log:
            try:
                mlflow.log_metrics(metrics_to_log, step=step)
            except Exception:
                logger.debug("Failed to log metrics to MLflow at step %d", step, exc_info=True)

    def on_evaluate(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        metrics: dict | None = None,
        **kwargs,
    ) -> None:
        """Log evaluation metrics to MLflow."""
        if metrics is None:
            return

        step = state.global_step
        eval_metrics = {
            f"eval/{k.replace('eval_', '')}": v
            for k, v in metrics.items()
            if isinstance(v, (int, float))
        }

        if eval_metrics:
            try:
                mlflow.log_metrics(eval_metrics, step=step)
            except Exception:
                logger.debug("Failed to log eval metrics to MLflow at step %d", step, exc_info=True)

    def on_train_end(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        **kwargs,
    ) -> None:
        """Log final summary metrics to MLflow."""
        try:
            mlflow.log_metric("total_training_steps", state.global_step)
            if state.best_metric is not None:
                mlflow.log_metric("best_eval_metric", state.best_metric)
            if state.best_model_checkpoint:
                mlflow.log_param("best_checkpoint", state.best_model_checkpoint)
        except Exception:
            logger.debug("Failed to log final metrics to MLflow", exc_info=True)


@dataclass
class _EarlyStoppingState:
    """Internal state for early stopping tracking."""

    best_metric: float | None = None
    patience_counter: int = 0
    best_step: int = 0


class EarlyStoppingCallback(TrainerCallback):
    """Early stopping based on evaluation loss with configurable patience.

    Monitors eval_loss and stops training if it does not improve by at least
    `threshold` for `patience` consecutive evaluations.

    Args:
        patience: Number of evaluations to wait for improvement.
        threshold: Minimum improvement to reset patience counter.
    """

    def __init__(self, patience: int = 3, threshold: float = 0.001) -> None:
        super().__init__()
        self.patience = patience
        self.threshold = threshold
        self._state = _EarlyStoppingState()

    def on_evaluate(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        metrics: dict | None = None,
        **kwargs,
    ) -> None:
        """Check if training should be stopped early."""
        if metrics is None:
            return

        eval_loss = metrics.get("eval_loss")
        if eval_loss is None:
            return

        current_step = state.global_step

        if self._state.best_metric is None or eval_loss < self._state.best_metric - self.threshold:
            # Improvement found
            logger.info(
                "Early stopping: eval_loss improved from %.6f to %.6f at step %d",
                self._state.best_metric or float("inf"),
                eval_loss,
                current_step,
            )
            self._state.best_metric = eval_loss
            self._state.patience_counter = 0
            self._state.best_step = current_step
        else:
            # No improvement
            self._state.patience_counter += 1
            logger.info(
                "Early stopping: no improvement for %d/%d evaluations "
                "(best=%.6f at step %d, current=%.6f at step %d)",
                self._state.patience_counter,
                self.patience,
                self._state.best_metric,
                self._state.best_step,
                eval_loss,
                current_step,
            )

            if self._state.patience_counter >= self.patience:
                logger.warning(
                    "Early stopping triggered: no improvement for %d evaluations. "
                    "Best eval_loss=%.6f at step %d",
                    self.patience,
                    self._state.best_metric,
                    self._state.best_step,
                )
                control.should_training_stop = True

                # Log early stopping event to MLflow
                try:
                    mlflow.log_params({
                        "early_stopping_triggered": True,
                        "early_stopping_step": current_step,
                        "early_stopping_best_step": self._state.best_step,
                    })
                    mlflow.log_metric("early_stopping_best_loss", self._state.best_metric)
                except Exception:
                    logger.debug("Failed to log early stopping to MLflow", exc_info=True)


@dataclass
class _ThroughputState:
    """Internal state for throughput and ETA tracking."""

    train_start_time: float = 0.0
    total_steps: int = 0
    last_log_time: float = 0.0
    last_log_step: int = 0
    samples_seen: int = 0
    log_history: list[dict[str, float]] = field(default_factory=list)


class CustomLoggingCallback(TrainerCallback):
    """Rich console logging with ETA estimation and throughput metrics.

    Logs at each logging step:
    - Current step / total steps with progress percentage
    - Estimated time remaining (ETA)
    - Samples per second (throughput)
    - Current loss and learning rate
    - GPU memory usage (if available)
    """

    def __init__(self) -> None:
        super().__init__()
        self._state = _ThroughputState()

    def on_train_begin(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        **kwargs,
    ) -> None:
        """Record training start time and total steps."""
        self._state.train_start_time = time.monotonic()
        self._state.last_log_time = time.monotonic()
        self._state.total_steps = state.max_steps

        logger.info(
            "Training started: %d total steps, %d epochs",
            state.max_steps,
            args.num_train_epochs,
        )

    def on_log(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        logs: dict | None = None,
        **kwargs,
    ) -> None:
        """Log rich progress information."""
        if logs is None:
            return

        current_step = state.global_step
        total_steps = self._state.total_steps or state.max_steps
        now = time.monotonic()

        # Calculate progress
        progress_pct = 100 * current_step / total_steps if total_steps > 0 else 0

        # Calculate throughput
        elapsed_since_last = now - self._state.last_log_time
        steps_since_last = current_step - self._state.last_log_step
        if elapsed_since_last > 0 and steps_since_last > 0:
            steps_per_sec = steps_since_last / elapsed_since_last
            samples_per_sec = steps_per_sec * args.per_device_train_batch_size * args.gradient_accumulation_steps
        else:
            steps_per_sec = 0
            samples_per_sec = 0

        # Estimate ETA
        elapsed_total = now - self._state.train_start_time
        if current_step > 0:
            avg_step_time = elapsed_total / current_step
            remaining_steps = total_steps - current_step
            eta_seconds = avg_step_time * remaining_steps
            eta_str = _format_duration(eta_seconds)
        else:
            eta_str = "calculating..."

        # Extract key metrics
        loss = logs.get("loss", logs.get("eval_loss", float("nan")))
        lr = logs.get("learning_rate", 0)
        grad_norm = logs.get("grad_norm", None)
        epoch = logs.get("epoch", 0)

        # GPU memory info
        gpu_mem_str = ""
        try:
            import torch
            if torch.cuda.is_available():
                allocated = torch.cuda.memory_allocated() / 1024**3
                reserved = torch.cuda.memory_reserved() / 1024**3
                gpu_mem_str = f" | GPU mem: {allocated:.1f}/{reserved:.1f} GB"
        except ImportError:
            pass

        # Build log message
        grad_str = f" | grad_norm: {grad_norm:.4f}" if grad_norm is not None else ""
        logger.info(
            "[Step %d/%d (%.1f%%)] loss: %.4f | lr: %.2e%s | "
            "throughput: %.1f samples/s | ETA: %s | epoch: %.2f%s",
            current_step,
            total_steps,
            progress_pct,
            loss,
            lr,
            grad_str,
            samples_per_sec,
            eta_str,
            epoch,
            gpu_mem_str,
        )

        # Update state
        self._state.last_log_time = now
        self._state.last_log_step = current_step

    def on_train_end(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        **kwargs,
    ) -> None:
        """Log training completion summary."""
        elapsed = time.monotonic() - self._state.train_start_time
        logger.info(
            "Training completed: %d steps in %s",
            state.global_step,
            _format_duration(elapsed),
        )

    def on_evaluate(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        metrics: dict | None = None,
        **kwargs,
    ) -> None:
        """Log evaluation results."""
        if metrics is None:
            return

        eval_loss = metrics.get("eval_loss", float("nan"))
        eval_runtime = metrics.get("eval_runtime", 0)
        eval_samples_per_sec = metrics.get("eval_samples_per_second", 0)

        logger.info(
            "[Eval @ step %d] eval_loss: %.4f | runtime: %.1fs | throughput: %.1f samples/s",
            state.global_step,
            eval_loss,
            eval_runtime,
            eval_samples_per_sec,
        )

    def on_save(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        **kwargs,
    ) -> None:
        """Log checkpoint save events."""
        logger.info(
            "Checkpoint saved at step %d (best metric: %s)",
            state.global_step,
            state.best_metric,
        )


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like '2h 15m 30s' or '5m 12s'.
    """
    if seconds < 0:
        return "0s"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or hours > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")

    return " ".join(parts)
