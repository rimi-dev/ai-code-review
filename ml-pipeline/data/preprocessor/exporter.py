"""Export processed data to HuggingFace datasets format and JSONL.

Handles train/val/test splitting, parquet/JSONL export, and metadata generation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from datasets import Dataset, DatasetDict

logger = logging.getLogger(__name__)

# Default split ratios
DEFAULT_TRAIN_RATIO = 0.8
DEFAULT_VAL_RATIO = 0.1
DEFAULT_TEST_RATIO = 0.1

# Default random seed for reproducibility
DEFAULT_SEED = 42


@dataclass
class ExportStats:
    """Statistics from the export process."""

    total_samples: int = 0
    train_samples: int = 0
    val_samples: int = 0
    test_samples: int = 0
    output_dir: str = ""
    parquet_files: list[str] = field(default_factory=list)
    jsonl_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_samples": self.total_samples,
            "train_samples": self.train_samples,
            "val_samples": self.val_samples,
            "test_samples": self.test_samples,
            "output_dir": self.output_dir,
            "parquet_files": self.parquet_files,
            "jsonl_files": self.jsonl_files,
        }


class DatasetExporter:
    """Exports processed instruction-tuning data to various formats.

    Produces:
    - HuggingFace Datasets (parquet) with train/val/test splits
    - JSONL files for human inspection
    - Metadata JSON with statistics
    """

    def __init__(
        self,
        output_dir: str | Path,
        train_ratio: float = DEFAULT_TRAIN_RATIO,
        val_ratio: float = DEFAULT_VAL_RATIO,
        test_ratio: float = DEFAULT_TEST_RATIO,
        seed: int = DEFAULT_SEED,
    ) -> None:
        # Validate split ratios
        total_ratio = train_ratio + val_ratio + test_ratio
        if abs(total_ratio - 1.0) > 1e-6:
            msg = f"Split ratios must sum to 1.0, got {total_ratio}"
            raise ValueError(msg)

        self.output_dir = Path(output_dir)
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.test_ratio = test_ratio
        self.seed = seed
        self._stats = ExportStats(output_dir=str(self.output_dir))

    @property
    def stats(self) -> ExportStats:
        return self._stats

    def export(
        self,
        samples: list[dict[str, Any]],
        cleaning_stats: dict[str, Any] | None = None,
        formatting_stats: dict[str, Any] | None = None,
        token_stats: dict[str, Any] | None = None,
    ) -> DatasetDict:
        """Export samples to parquet and JSONL formats with train/val/test splits.

        Args:
            samples: List of processed instruction-tuning sample dicts.
            cleaning_stats: Optional cleaning statistics to include in metadata.
            formatting_stats: Optional formatting statistics to include in metadata.
            token_stats: Optional token statistics to include in metadata.

        Returns:
            HuggingFace DatasetDict with train/val/test splits.
        """
        self._stats = ExportStats(
            total_samples=len(samples),
            output_dir=str(self.output_dir),
        )

        if not samples:
            logger.warning("No samples to export")
            return DatasetDict()

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Split data
        dataset_dict = self._create_splits(samples)

        self._stats.train_samples = len(dataset_dict["train"])
        self._stats.val_samples = len(dataset_dict["validation"])
        self._stats.test_samples = len(dataset_dict["test"])

        # Export to parquet
        self._export_parquet(dataset_dict)

        # Export to JSONL
        self._export_jsonl(dataset_dict)

        # Export metadata
        self._export_metadata(
            cleaning_stats=cleaning_stats,
            formatting_stats=formatting_stats,
            token_stats=token_stats,
        )

        logger.info(
            "Export complete: %d total -> train=%d, val=%d, test=%d at %s",
            self._stats.total_samples,
            self._stats.train_samples,
            self._stats.val_samples,
            self._stats.test_samples,
            self.output_dir,
        )

        return dataset_dict

    def _create_splits(self, samples: list[dict[str, Any]]) -> DatasetDict:
        """Create reproducible train/val/test splits."""
        # Select only the columns we want in the dataset
        export_columns = ["instruction", "input", "output"]
        optional_columns = [
            "input_tokens", "output_tokens", "repo", "pr_number",
            "file_path", "language", "comment_line",
        ]

        # Determine which optional columns are present in the data
        present_columns = list(export_columns)
        if samples:
            for col in optional_columns:
                if col in samples[0]:
                    present_columns.append(col)

        # Build records with only present columns
        records = []
        for s in samples:
            record = {col: s.get(col, "") for col in present_columns}
            records.append(record)

        df = pd.DataFrame(records)

        # Create HuggingFace dataset
        full_dataset = Dataset.from_pandas(df)

        # Perform train / (val+test) split
        val_test_ratio = self.val_ratio + self.test_ratio
        train_rest = full_dataset.train_test_split(
            test_size=val_test_ratio,
            seed=self.seed,
        )

        # Split the rest into val / test
        relative_test_ratio = self.test_ratio / val_test_ratio if val_test_ratio > 0 else 0.5
        val_test = train_rest["test"].train_test_split(
            test_size=relative_test_ratio,
            seed=self.seed,
        )

        return DatasetDict({
            "train": train_rest["train"],
            "validation": val_test["train"],
            "test": val_test["test"],
        })

    def _export_parquet(self, dataset_dict: DatasetDict) -> None:
        """Save splits as parquet files."""
        parquet_dir = self.output_dir / "parquet"
        parquet_dir.mkdir(parents=True, exist_ok=True)

        for split_name, dataset in dataset_dict.items():
            file_path = parquet_dir / f"{split_name}.parquet"
            dataset.to_parquet(str(file_path))
            self._stats.parquet_files.append(str(file_path))
            logger.info("Saved %s split (%d samples) to %s", split_name, len(dataset), file_path)

    def _export_jsonl(self, dataset_dict: DatasetDict) -> None:
        """Save splits as JSONL files for human inspection."""
        jsonl_dir = self.output_dir / "jsonl"
        jsonl_dir.mkdir(parents=True, exist_ok=True)

        for split_name, dataset in dataset_dict.items():
            file_path = jsonl_dir / f"{split_name}.jsonl"
            with open(file_path, "w", encoding="utf-8") as f:
                for row in dataset:
                    json.dump(row, f, ensure_ascii=False)
                    f.write("\n")
            self._stats.jsonl_files.append(str(file_path))
            logger.info("Saved %s split (%d samples) to %s", split_name, len(dataset), file_path)

    def _export_metadata(
        self,
        cleaning_stats: dict[str, Any] | None = None,
        formatting_stats: dict[str, Any] | None = None,
        token_stats: dict[str, Any] | None = None,
    ) -> None:
        """Save pipeline metadata and statistics."""
        metadata = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "seed": self.seed,
            "split_ratios": {
                "train": self.train_ratio,
                "validation": self.val_ratio,
                "test": self.test_ratio,
            },
            "export_stats": self._stats.to_dict(),
        }

        if cleaning_stats is not None:
            metadata["cleaning_stats"] = cleaning_stats
        if formatting_stats is not None:
            metadata["formatting_stats"] = formatting_stats
        if token_stats is not None:
            metadata["token_stats"] = token_stats

        metadata_path = self.output_dir / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        logger.info("Saved metadata to %s", metadata_path)
