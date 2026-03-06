"""Main preprocessing orchestrator for the AI Code Review Bot ML pipeline.

Reads raw PR data from MongoDB, runs the cleaning -> formatting -> tokenization ->
export pipeline, with CLI support, progress tracking, and batch processing.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection

from data.preprocessor.cleaner import ReviewCleaner
from data.preprocessor.exporter import DatasetExporter
from data.preprocessor.formatter import InstructionFormatter, InstructionSample
from data.preprocessor.tokenizer import TokenManager

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for the preprocessing pipeline."""

    # MongoDB
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "ai_code_review"
    mongo_collection: str = "training_prs"

    # Cleaning
    min_review_tokens: int = 20

    # Formatting
    system_prompt: str = ""
    max_diff_chars: int = 8000
    context_lines: int = 30

    # Tokenization
    max_input_tokens: int = 2048
    max_output_tokens: int = 512
    encoding_name: str = "cl100k_base"

    # Export
    output_dir: str = "./output/preprocessed"
    train_ratio: float = 0.8
    val_ratio: float = 0.1
    test_ratio: float = 0.1
    seed: int = 42

    # Processing
    batch_size: int = 100
    limit: int = 0  # 0 = no limit
    log_level: str = "INFO"


@dataclass
class PipelineResult:
    """Result of a preprocessing pipeline run."""

    total_prs_read: int = 0
    cleaning_stats: dict[str, Any] = field(default_factory=dict)
    formatting_stats: dict[str, Any] = field(default_factory=dict)
    token_stats: dict[str, Any] = field(default_factory=dict)
    export_stats: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_prs_read": self.total_prs_read,
            "cleaning_stats": self.cleaning_stats,
            "formatting_stats": self.formatting_stats,
            "token_stats": self.token_stats,
            "export_stats": self.export_stats,
            "duration_seconds": round(self.duration_seconds, 2),
        }


class PreprocessingPipeline:
    """Orchestrates the full data preprocessing pipeline.

    Pipeline stages:
    1. Read raw PR data from MongoDB (batch by batch)
    2. Clean: filter bots, trivial reviews, excluded files, normalize text
    3. Format: convert to instruction-tuning triples
    4. Tokenize: enforce token limits, truncate as needed
    5. Export: save to parquet + JSONL with train/val/test splits
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self._cleaner = ReviewCleaner(min_review_tokens=config.min_review_tokens)
        self._formatter = InstructionFormatter(
            system_prompt=config.system_prompt or InstructionFormatter.__init__.__defaults__[0],  # type: ignore[index]
            max_diff_chars=config.max_diff_chars,
            context_lines=config.context_lines,
        )
        self._tokenizer = TokenManager(
            max_input_tokens=config.max_input_tokens,
            max_output_tokens=config.max_output_tokens,
            encoding_name=config.encoding_name,
        )
        self._exporter = DatasetExporter(
            output_dir=config.output_dir,
            train_ratio=config.train_ratio,
            val_ratio=config.val_ratio,
            test_ratio=config.test_ratio,
            seed=config.seed,
        )

    def run(self) -> PipelineResult:
        """Execute the full preprocessing pipeline.

        Returns:
            PipelineResult with statistics from each stage.
        """
        start_time = time.monotonic()
        result = PipelineResult()

        logger.info("Starting preprocessing pipeline")
        logger.info("Config: batch_size=%d, limit=%d", self.config.batch_size, self.config.limit)

        # Stage 1: Read from MongoDB and process in batches
        all_cleaned_comments: list[dict[str, Any]] = []
        all_formatted_samples: list[InstructionSample] = []
        total_prs = 0

        try:
            collection = self._get_collection()
            cursor = collection.find({})
            if self.config.limit > 0:
                cursor = cursor.limit(self.config.limit)

            batch: list[dict[str, Any]] = []
            for doc in cursor:
                batch.append(doc)
                if len(batch) >= self.config.batch_size:
                    cleaned, formatted = self._process_batch(batch, total_prs)
                    all_cleaned_comments.extend(cleaned)
                    all_formatted_samples.extend(formatted)
                    total_prs += len(batch)
                    batch = []

            # Process remaining batch
            if batch:
                cleaned, formatted = self._process_batch(batch, total_prs)
                all_cleaned_comments.extend(cleaned)
                all_formatted_samples.extend(formatted)
                total_prs += len(batch)

        except Exception:
            logger.exception("Error reading from MongoDB")
            raise

        result.total_prs_read = total_prs
        logger.info("Read %d PRs total, produced %d formatted samples", total_prs, len(all_formatted_samples))

        # Stage 3: Tokenization
        logger.info("Stage 3: Token management")
        sample_dicts = [s.to_dict() for s in all_formatted_samples]
        tokenized_samples = self._tokenizer.process_batch(sample_dicts)
        result.token_stats = self._tokenizer.stats.to_dict()
        logger.info("After tokenization: %d samples", len(tokenized_samples))

        # Stage 4: Export
        logger.info("Stage 4: Exporting data")
        self._exporter.export(
            samples=tokenized_samples,
            cleaning_stats=self._cleaner.stats.to_dict(),
            formatting_stats=self._formatter.stats.to_dict(),
            token_stats=result.token_stats,
        )
        result.export_stats = self._exporter.stats.to_dict()

        # Aggregate stats
        result.cleaning_stats = self._cleaner.stats.to_dict()
        result.formatting_stats = self._formatter.stats.to_dict()
        result.duration_seconds = time.monotonic() - start_time

        logger.info("Pipeline complete in %.2f seconds", result.duration_seconds)
        return result

    def run_from_data(self, prs: list[dict[str, Any]]) -> PipelineResult:
        """Run the pipeline from in-memory data instead of MongoDB.

        Useful for testing or when data is already loaded.
        """
        start_time = time.monotonic()
        result = PipelineResult(total_prs_read=len(prs))

        logger.info("Starting preprocessing pipeline from in-memory data (%d PRs)", len(prs))

        # Process in batches
        all_formatted_samples: list[InstructionSample] = []

        for batch_start in range(0, len(prs), self.config.batch_size):
            batch = prs[batch_start : batch_start + self.config.batch_size]
            _, formatted = self._process_batch(batch, batch_start)
            all_formatted_samples.extend(formatted)

        # Tokenization
        sample_dicts = [s.to_dict() for s in all_formatted_samples]
        tokenized_samples = self._tokenizer.process_batch(sample_dicts)
        result.token_stats = self._tokenizer.stats.to_dict()

        # Export
        self._exporter.export(
            samples=tokenized_samples,
            cleaning_stats=self._cleaner.stats.to_dict(),
            formatting_stats=self._formatter.stats.to_dict(),
            token_stats=result.token_stats,
        )
        result.export_stats = self._exporter.stats.to_dict()

        # Aggregate
        result.cleaning_stats = self._cleaner.stats.to_dict()
        result.formatting_stats = self._formatter.stats.to_dict()
        result.duration_seconds = time.monotonic() - start_time

        return result

    def _process_batch(
        self, prs: list[dict[str, Any]], offset: int
    ) -> tuple[list[dict[str, Any]], list[InstructionSample]]:
        """Process a batch of PRs through cleaning and formatting.

        Returns:
            Tuple of (cleaned_comments, formatted_samples)
        """
        logger.info("Processing batch of %d PRs (offset %d)", len(prs), offset)

        # Stage 1: Clean comments within each PR
        for pr in prs:
            comments = pr.get("comments", [])
            cleaned_comments = self._cleaner.clean_batch(comments)
            pr["comments"] = cleaned_comments

        # Stage 2: Format into instruction-tuning pairs
        formatted = self._formatter.format_batch(prs)

        # Extract cleaned comments for tracking
        cleaned = []
        for pr in prs:
            cleaned.extend(pr.get("comments", []))

        return cleaned, formatted

    def _get_collection(self) -> Collection:
        """Get the MongoDB collection handle."""
        client: MongoClient = MongoClient(self.config.mongo_uri)
        db = client[self.config.mongo_db]
        return db[self.config.mongo_collection]


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="AI Code Review Bot - Data Preprocessing Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # MongoDB options
    mongo_group = parser.add_argument_group("MongoDB")
    mongo_group.add_argument("--mongo-uri", default="mongodb://localhost:27017", help="MongoDB connection URI")
    mongo_group.add_argument("--mongo-db", default="ai_code_review", help="MongoDB database name")
    mongo_group.add_argument("--mongo-collection", default="training_prs", help="MongoDB collection name")

    # Cleaning options
    clean_group = parser.add_argument_group("Cleaning")
    clean_group.add_argument("--min-review-tokens", type=int, default=20, help="Minimum tokens for non-trivial review")

    # Formatting options
    fmt_group = parser.add_argument_group("Formatting")
    fmt_group.add_argument("--system-prompt", default="", help="Custom system prompt (empty = default)")
    fmt_group.add_argument("--max-diff-chars", type=int, default=8000, help="Max diff characters before truncation")
    fmt_group.add_argument("--context-lines", type=int, default=30, help="Context lines around comment in truncation")

    # Tokenization options
    tok_group = parser.add_argument_group("Tokenization")
    tok_group.add_argument("--max-input-tokens", type=int, default=2048, help="Max tokens for instruction + input")
    tok_group.add_argument("--max-output-tokens", type=int, default=512, help="Max tokens for output")
    tok_group.add_argument("--encoding", default="cl100k_base", help="tiktoken encoding name")

    # Export options
    export_group = parser.add_argument_group("Export")
    export_group.add_argument("--output-dir", default="./output/preprocessed", help="Output directory")
    export_group.add_argument("--train-ratio", type=float, default=0.8, help="Training set ratio")
    export_group.add_argument("--val-ratio", type=float, default=0.1, help="Validation set ratio")
    export_group.add_argument("--test-ratio", type=float, default=0.1, help="Test set ratio")
    export_group.add_argument("--seed", type=int, default=42, help="Random seed for reproducible splits")

    # Processing options
    proc_group = parser.add_argument_group("Processing")
    proc_group.add_argument("--batch-size", type=int, default=100, help="Batch size for processing")
    proc_group.add_argument("--limit", type=int, default=0, help="Max PRs to process (0 = no limit)")
    proc_group.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")

    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for the preprocessing pipeline."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = PipelineConfig(
        mongo_uri=args.mongo_uri,
        mongo_db=args.mongo_db,
        mongo_collection=args.mongo_collection,
        min_review_tokens=args.min_review_tokens,
        system_prompt=args.system_prompt,
        max_diff_chars=args.max_diff_chars,
        context_lines=args.context_lines,
        max_input_tokens=args.max_input_tokens,
        max_output_tokens=args.max_output_tokens,
        encoding_name=args.encoding,
        output_dir=args.output_dir,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        test_ratio=args.test_ratio,
        seed=args.seed,
        batch_size=args.batch_size,
        limit=args.limit,
        log_level=args.log_level,
    )

    pipeline = PreprocessingPipeline(config)

    try:
        result = pipeline.run()
        logger.info("Pipeline result: %s", result.to_dict())
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
