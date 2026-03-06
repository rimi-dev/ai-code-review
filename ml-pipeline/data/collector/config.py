"""GitHub PR 데이터 수집 파이프라인 설정 모듈.

환경변수 및 기본값을 통한 설정 관리를 제공한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MongoConfig:
    """MongoDB 연결 설정."""

    uri: str = "mongodb://localhost:27017"
    database: str = "ai_code_review"
    training_prs_collection: str = "training_prs"
    checkpoints_collection: str = "collection_checkpoints"

    @classmethod
    def from_env(cls) -> MongoConfig:
        """환경변수에서 MongoDB 설정을 로드한다."""
        return cls(
            uri=os.getenv("MONGO_URI", cls.uri),
            database=os.getenv("MONGO_DATABASE", cls.database),
            training_prs_collection=os.getenv("MONGO_TRAINING_PRS_COLLECTION", cls.training_prs_collection),
            checkpoints_collection=os.getenv("MONGO_CHECKPOINTS_COLLECTION", cls.checkpoints_collection),
        )


@dataclass(frozen=True, slots=True)
class GitHubConfig:
    """GitHub API 설정."""

    base_url: str = "https://api.github.com"
    graphql_url: str = "https://api.github.com/graphql"
    tokens: list[str] = field(default_factory=list)
    max_retries: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    request_timeout_seconds: float = 30.0
    per_page: int = 100

    @classmethod
    def from_env(cls) -> GitHubConfig:
        """환경변수에서 GitHub 설정을 로드한다.

        GITHUB_TOKENS 환경변수에서 쉼표로 구분된 토큰 목록을 읽는다.
        """
        tokens_raw = os.getenv("GITHUB_TOKENS", "")
        tokens = [t.strip() for t in tokens_raw.split(",") if t.strip()]
        return cls(
            base_url=os.getenv("GITHUB_BASE_URL", cls.base_url),
            graphql_url=os.getenv("GITHUB_GRAPHQL_URL", cls.graphql_url),
            tokens=tokens,
            max_retries=int(os.getenv("GITHUB_MAX_RETRIES", str(cls.max_retries))),
            base_backoff_seconds=float(os.getenv("GITHUB_BASE_BACKOFF", str(cls.base_backoff_seconds))),
            max_backoff_seconds=float(os.getenv("GITHUB_MAX_BACKOFF", str(cls.max_backoff_seconds))),
            request_timeout_seconds=float(os.getenv("GITHUB_TIMEOUT", str(cls.request_timeout_seconds))),
            per_page=int(os.getenv("GITHUB_PER_PAGE", str(cls.per_page))),
        )


@dataclass(frozen=True, slots=True)
class CollectorConfig:
    """PR 수집기 설정."""

    max_repos: int = 50
    max_prs_per_repo: int = 200
    min_stars: int = 1000
    languages: list[str] = field(default_factory=lambda: ["Python", "Java", "Kotlin", "TypeScript", "Go"])
    min_review_comments: int = 1
    concurrency_limit: int = 5

    @classmethod
    def from_env(cls) -> CollectorConfig:
        """환경변수에서 수집기 설정을 로드한다."""
        languages_raw = os.getenv("COLLECTOR_LANGUAGES", "")
        languages = (
            [lang.strip() for lang in languages_raw.split(",") if lang.strip()]
            if languages_raw
            else cls.languages
        )
        return cls(
            max_repos=int(os.getenv("COLLECTOR_MAX_REPOS", str(cls.max_repos))),
            max_prs_per_repo=int(os.getenv("COLLECTOR_MAX_PRS_PER_REPO", str(cls.max_prs_per_repo))),
            min_stars=int(os.getenv("COLLECTOR_MIN_STARS", str(cls.min_stars))),
            languages=languages,
            min_review_comments=int(os.getenv("COLLECTOR_MIN_REVIEW_COMMENTS", str(cls.min_review_comments))),
            concurrency_limit=int(os.getenv("COLLECTOR_CONCURRENCY_LIMIT", str(cls.concurrency_limit))),
        )


# 우수한 코드 리뷰 문화를 가진 잘 알려진 OSS 저장소 목록
TARGET_REPOS: list[str] = [
    # Python
    "python/cpython",
    "django/django",
    "pallets/flask",
    "fastapi/fastapi",
    "psf/requests",
    "encode/httpx",
    "pydantic/pydantic",
    "tiangolo/sqlmodel",
    "apache/airflow",
    "celery/celery",
    # Java
    "spring-projects/spring-boot",
    "spring-projects/spring-framework",
    "google/guava",
    "elastic/elasticsearch",
    "apache/kafka",
    "ReactiveX/RxJava",
    "square/retrofit",
    "netty/netty",
    # Kotlin
    "JetBrains/kotlin",
    "square/okhttp",
    "square/leakcanary",
    "InsertKoinIO/koin",
    "ktorio/ktor",
    "detekt/detekt",
    # TypeScript
    "microsoft/TypeScript",
    "microsoft/vscode",
    "angular/angular",
    "vercel/next.js",
    "facebook/react",
    "sveltejs/svelte",
    "nestjs/nest",
    "prisma/prisma",
    # Go
    "golang/go",
    "kubernetes/kubernetes",
    "moby/moby",
    "gin-gonic/gin",
    "gofiber/fiber",
    "hashicorp/terraform",
    "prometheus/prometheus",
    "grafana/grafana",
]


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """전체 파이프라인 설정을 통합 관리한다."""

    mongo: MongoConfig = field(default_factory=MongoConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    collector: CollectorConfig = field(default_factory=CollectorConfig)

    @classmethod
    def from_env(cls) -> PipelineConfig:
        """모든 설정을 환경변수에서 로드한다."""
        return cls(
            mongo=MongoConfig.from_env(),
            github=GitHubConfig.from_env(),
            collector=CollectorConfig.from_env(),
        )
