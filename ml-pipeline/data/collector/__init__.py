"""GitHub PR 데이터 수집 모듈.

GitHub REST/GraphQL API를 통해 고품질 OSS 저장소에서
코드 리뷰가 포함된 PR 데이터를 수집한다.
"""

from data.collector.config import CollectorConfig, GitHubConfig, MongoConfig, PipelineConfig
from data.collector.deduplicator import compute_pr_hash, ensure_unique_index
from data.collector.github_client import GitHubClient
from data.collector.pr_collector import PRCollector

__all__ = [
    "CollectorConfig",
    "GitHubClient",
    "GitHubConfig",
    "MongoConfig",
    "PipelineConfig",
    "PRCollector",
    "compute_pr_hash",
    "ensure_unique_index",
]
