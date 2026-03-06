"""GitHub PR 데이터 수집 오케스트레이터.

고품질 OSS 저장소에서 병합된 PR과 리뷰 코멘트를 수집하여
MongoDB에 저장한다. 체크포인트 기반 재개를 지원한다.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection

from data.collector.config import (
    CollectorConfig,
    GitHubConfig,
    MongoConfig,
    PipelineConfig,
    TARGET_REPOS,
)
from data.collector.deduplicator import (
    compute_pr_hash,
    ensure_unique_index,
    insert_if_not_duplicate,
)
from data.collector.github_client import GitHubClient, GitHubAPIError

logger = logging.getLogger(__name__)


class CheckpointManager:
    """수집 체크포인트를 관리한다.

    각 저장소별로 마지막으로 수집한 PR 정보를 추적하여
    중단 후 재개 시 이미 수집한 데이터를 건너뛸 수 있도록 한다.
    """

    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection
        self._collection.create_index("repo_full_name", unique=True)

    def get_checkpoint(self, repo_full_name: str) -> dict[str, Any] | None:
        """저장소의 마지막 체크포인트를 조회한다.

        Args:
            repo_full_name: 저장소 전체 이름.

        Returns:
            체크포인트 문서 또는 None.
        """
        return self._collection.find_one({"repo_full_name": repo_full_name})

    def save_checkpoint(
        self,
        repo_full_name: str,
        last_pr_number: int,
        last_pr_updated_at: str,
        collected_count: int,
    ) -> None:
        """체크포인트를 저장 또는 업데이트한다.

        Args:
            repo_full_name: 저장소 전체 이름.
            last_pr_number: 마지막으로 수집한 PR 번호.
            last_pr_updated_at: 마지막 PR의 업데이트 시각.
            collected_count: 해당 저장소에서 수집한 총 PR 수.
        """
        self._collection.update_one(
            {"repo_full_name": repo_full_name},
            {
                "$set": {
                    "last_pr_number": last_pr_number,
                    "last_pr_updated_at": last_pr_updated_at,
                    "collected_count": collected_count,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            upsert=True,
        )

    def get_collected_count(self, repo_full_name: str) -> int:
        """저장소에서 이미 수집한 PR 수를 반환한다.

        Args:
            repo_full_name: 저장소 전체 이름.

        Returns:
            수집된 PR 수 (체크포인트가 없으면 0).
        """
        checkpoint = self.get_checkpoint(repo_full_name)
        return checkpoint.get("collected_count", 0) if checkpoint else 0


class PRCollector:
    """PR 데이터 수집 오케스트레이터.

    GitHub API를 통해 고품질 OSS 저장소에서 코드 리뷰가 있는
    병합된 PR 데이터를 수집하고 MongoDB에 저장한다.
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self._config = config or PipelineConfig.from_env()
        self._mongo_client: MongoClient[dict[str, Any]] | None = None
        self._training_prs: Collection[dict[str, Any]] | None = None
        self._checkpoint_mgr: CheckpointManager | None = None

    def _init_mongodb(self) -> None:
        """MongoDB 연결을 초기화하고 인덱스를 설정한다."""
        mongo_cfg = self._config.mongo
        self._mongo_client = MongoClient(mongo_cfg.uri)
        db = self._mongo_client[mongo_cfg.database]
        self._training_prs = db[mongo_cfg.training_prs_collection]
        checkpoints_col = db[mongo_cfg.checkpoints_collection]
        self._checkpoint_mgr = CheckpointManager(checkpoints_col)

        # 중복 방지 유니크 인덱스 생성
        ensure_unique_index(self._training_prs)

        # 추가 인덱스
        self._training_prs.create_index("repo_full_name")
        self._training_prs.create_index("pr_number")
        self._training_prs.create_index("collected_at")

        logger.info(
            "MongoDB 연결 완료: uri=%s, db=%s",
            mongo_cfg.uri,
            mongo_cfg.database,
        )

    def _close_mongodb(self) -> None:
        """MongoDB 연결을 종료한다."""
        if self._mongo_client:
            self._mongo_client.close()
            self._mongo_client = None

    async def _collect_pr_details(
        self,
        client: GitHubClient,
        repo_full_name: str,
        pr: dict[str, Any],
    ) -> dict[str, Any] | None:
        """단일 PR의 상세 정보(diff, 리뷰 코멘트)를 수집한다.

        Args:
            client: GitHub API 클라이언트.
            repo_full_name: 저장소 전체 이름.
            pr: PR 기본 정보.

        Returns:
            수집된 PR 문서 또는 None (오류 발생 시).
        """
        pr_number = pr["number"]

        try:
            # diff와 리뷰 코멘트를 병렬로 수집
            diff_task = client.get_pr_diff(repo_full_name, pr_number)
            comments_task = client.get_pr_review_comments(repo_full_name, pr_number)
            reviews_task = client.get_pr_reviews(repo_full_name, pr_number)

            diff, comments, reviews = await asyncio.gather(
                diff_task, comments_task, reviews_task,
                return_exceptions=True,
            )

            # 예외 처리
            if isinstance(diff, BaseException):
                logger.warning("diff 수집 실패: repo=%s, pr=#%d, error=%s", repo_full_name, pr_number, diff)
                diff = ""
            if isinstance(comments, BaseException):
                logger.warning("코멘트 수집 실패: repo=%s, pr=#%d, error=%s", repo_full_name, pr_number, comments)
                comments = []
            if isinstance(reviews, BaseException):
                logger.warning("리뷰 수집 실패: repo=%s, pr=#%d, error=%s", repo_full_name, pr_number, reviews)
                reviews = []

            # 리뷰 코멘트가 없으면 스킵
            if not comments:
                logger.debug("리뷰 코멘트 없음 - 스킵: repo=%s, pr=#%d", repo_full_name, pr_number)
                return None

            document: dict[str, Any] = {
                "repo_full_name": repo_full_name,
                "pr_number": pr_number,
                "title": pr.get("title", ""),
                "body": pr.get("body", "") or "",
                "state": pr.get("state", ""),
                "merged_at": pr.get("merged_at"),
                "created_at": pr.get("created_at"),
                "updated_at": pr.get("updated_at"),
                "user": {
                    "login": pr.get("user", {}).get("login", ""),
                },
                "base": {
                    "ref": pr.get("base", {}).get("ref", ""),
                    "sha": pr.get("base", {}).get("sha", ""),
                },
                "head": {
                    "ref": pr.get("head", {}).get("ref", ""),
                    "sha": pr.get("head", {}).get("sha", ""),
                },
                "diff": diff,
                "review_comments": [
                    {
                        "id": c.get("id"),
                        "user": c.get("user", {}).get("login", ""),
                        "body": c.get("body", ""),
                        "path": c.get("path", ""),
                        "line": c.get("line"),
                        "original_line": c.get("original_line"),
                        "side": c.get("side", ""),
                        "diff_hunk": c.get("diff_hunk", ""),
                        "created_at": c.get("created_at"),
                        "in_reply_to_id": c.get("in_reply_to_id"),
                    }
                    for c in comments
                ],
                "reviews": [
                    {
                        "id": r.get("id"),
                        "user": r.get("user", {}).get("login", ""),
                        "state": r.get("state", ""),
                        "body": r.get("body", ""),
                        "submitted_at": r.get("submitted_at"),
                    }
                    for r in reviews
                ],
                "additions": pr.get("additions"),
                "deletions": pr.get("deletions"),
                "changed_files": pr.get("changed_files"),
                "review_comments_count": len(comments),
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }

            return document

        except GitHubAPIError as e:
            logger.error(
                "PR 상세 정보 수집 오류: repo=%s, pr=#%d, status=%d, error=%s",
                repo_full_name,
                pr_number,
                e.status_code,
                str(e),
            )
            return None
        except Exception as e:
            logger.error(
                "PR 상세 정보 수집 중 예상치 못한 오류: repo=%s, pr=#%d, error=%s",
                repo_full_name,
                pr_number,
                str(e),
            )
            return None

    async def _collect_repo(
        self,
        client: GitHubClient,
        repo_full_name: str,
        max_prs: int,
    ) -> int:
        """단일 저장소에서 PR 데이터를 수집한다.

        Args:
            client: GitHub API 클라이언트.
            repo_full_name: 저장소 전체 이름.
            max_prs: 최대 수집 PR 수.

        Returns:
            수집된 PR 수.
        """
        assert self._training_prs is not None
        assert self._checkpoint_mgr is not None

        # 체크포인트 확인
        already_collected = self._checkpoint_mgr.get_collected_count(repo_full_name)
        if already_collected >= max_prs:
            logger.info(
                "이미 충분히 수집됨 - 스킵: repo=%s, collected=%d, max=%d",
                repo_full_name,
                already_collected,
                max_prs,
            )
            return 0

        remaining = max_prs - already_collected
        logger.info(
            "저장소 수집 시작: repo=%s, already_collected=%d, remaining=%d",
            repo_full_name,
            already_collected,
            remaining,
        )

        # PR 목록 조회 (여유 있게 더 많이 가져옴)
        try:
            prs = await client.list_pull_requests(
                repo_full_name,
                max_results=remaining * 2,
            )
        except GitHubAPIError as e:
            logger.error("PR 목록 조회 실패: repo=%s, error=%s", repo_full_name, str(e))
            return 0

        collected = 0
        semaphore = asyncio.Semaphore(self._config.collector.concurrency_limit)

        async def _collect_with_semaphore(pr: dict[str, Any]) -> dict[str, Any] | None:
            async with semaphore:
                return await self._collect_pr_details(client, repo_full_name, pr)

        # PR 상세 정보를 병렬 수집
        tasks = [_collect_with_semaphore(pr) for pr in prs[:remaining * 2]]

        for coro in asyncio.as_completed(tasks):
            if collected >= remaining:
                break

            document = await coro
            if document is None:
                continue

            # 중복 확인 후 저장
            pr_number = document["pr_number"]
            inserted = insert_if_not_duplicate(
                self._training_prs,
                document,
                repo_full_name,
                pr_number,
            )

            if inserted:
                collected += 1
                total_collected = already_collected + collected

                # 체크포인트 업데이트 (10개마다)
                if collected % 10 == 0:
                    self._checkpoint_mgr.save_checkpoint(
                        repo_full_name=repo_full_name,
                        last_pr_number=pr_number,
                        last_pr_updated_at=document.get("updated_at", ""),
                        collected_count=total_collected,
                    )

                if collected % 20 == 0:
                    logger.info(
                        "수집 진행 중: repo=%s, collected=%d/%d",
                        repo_full_name,
                        total_collected,
                        max_prs,
                    )

        # 최종 체크포인트 저장
        if collected > 0:
            self._checkpoint_mgr.save_checkpoint(
                repo_full_name=repo_full_name,
                last_pr_number=prs[-1]["number"] if prs else 0,
                last_pr_updated_at=prs[-1].get("updated_at", "") if prs else "",
                collected_count=already_collected + collected,
            )

        logger.info(
            "저장소 수집 완료: repo=%s, new_collected=%d, total=%d",
            repo_full_name,
            collected,
            already_collected + collected,
        )
        return collected

    async def _discover_repos(
        self,
        client: GitHubClient,
    ) -> list[str]:
        """수집 대상 저장소를 탐색한다.

        설정된 TARGET_REPOS 목록과 검색 API를 결합하여
        고품질 저장소 목록을 구성한다.

        Args:
            client: GitHub API 클라이언트.

        Returns:
            저장소 전체 이름 리스트.
        """
        collector_cfg = self._config.collector
        repos: list[str] = list(TARGET_REPOS)

        # 추가 저장소를 검색으로 탐색
        remaining = collector_cfg.max_repos - len(repos)
        if remaining > 0:
            for language in collector_cfg.languages:
                try:
                    per_lang = max(remaining // len(collector_cfg.languages), 5)
                    search_results = await client.search_repos(
                        language=language,
                        min_stars=collector_cfg.min_stars,
                        max_results=per_lang,
                    )
                    for repo in search_results:
                        full_name = repo.get("full_name", "")
                        if full_name and full_name not in repos:
                            repos.append(full_name)
                except GitHubAPIError as e:
                    logger.warning("저장소 검색 실패: language=%s, error=%s", language, str(e))

        # 최대 개수 제한
        repos = repos[: collector_cfg.max_repos]
        logger.info("수집 대상 저장소: %d개", len(repos))
        return repos

    async def run(self) -> None:
        """전체 수집 파이프라인을 실행한다."""
        self._init_mongodb()

        try:
            async with GitHubClient(self._config.github) as client:
                # 대상 저장소 탐색
                repos = await self._discover_repos(client)

                total_collected = 0
                for i, repo_full_name in enumerate(repos, 1):
                    logger.info(
                        "===== [%d/%d] 저장소 처리: %s =====",
                        i,
                        len(repos),
                        repo_full_name,
                    )

                    collected = await self._collect_repo(
                        client,
                        repo_full_name,
                        self._config.collector.max_prs_per_repo,
                    )
                    total_collected += collected

                    logger.info(
                        "전체 진행 상황: repos=%d/%d, total_prs=%d",
                        i,
                        len(repos),
                        total_collected,
                    )

                logger.info("===== 수집 완료: 총 %d개 PR =====", total_collected)

        finally:
            self._close_mongodb()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI 인자를 파싱한다.

    Args:
        argv: 명령행 인자 리스트 (기본값: sys.argv[1:]).

    Returns:
        파싱된 인자 네임스페이스.
    """
    parser = argparse.ArgumentParser(
        description="GitHub PR 데이터 수집 파이프라인",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--max-repos",
        type=int,
        default=50,
        help="수집 대상 최대 저장소 수",
    )
    parser.add_argument(
        "--max-prs-per-repo",
        type=int,
        default=200,
        help="저장소별 최대 PR 수집 수",
    )
    parser.add_argument(
        "--min-stars",
        type=int,
        default=1000,
        help="저장소 최소 스타 수",
    )
    parser.add_argument(
        "--languages",
        type=str,
        nargs="+",
        default=["Python", "Java", "Kotlin", "TypeScript", "Go"],
        help="대상 프로그래밍 언어",
    )
    parser.add_argument(
        "--mongo-uri",
        type=str,
        default=None,
        help="MongoDB 연결 URI (기본값: 환경변수 MONGO_URI)",
    )
    parser.add_argument(
        "--mongo-database",
        type=str,
        default=None,
        help="MongoDB 데이터베이스 이름",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="동시 수집 작업 수",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="로그 레벨",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI 진입점.

    Args:
        argv: 명령행 인자 리스트.
    """
    args = parse_args(argv)

    # 로깅 설정
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 설정 구성
    mongo_config = MongoConfig.from_env()
    if args.mongo_uri:
        mongo_config = MongoConfig(
            uri=args.mongo_uri,
            database=args.mongo_database or mongo_config.database,
        )
    elif args.mongo_database:
        mongo_config = MongoConfig(
            uri=mongo_config.uri,
            database=args.mongo_database,
        )

    github_config = GitHubConfig.from_env()

    collector_config = CollectorConfig(
        max_repos=args.max_repos,
        max_prs_per_repo=args.max_prs_per_repo,
        min_stars=args.min_stars,
        languages=args.languages,
        concurrency_limit=args.concurrency,
    )

    pipeline_config = PipelineConfig(
        mongo=mongo_config,
        github=github_config,
        collector=collector_config,
    )

    if not github_config.tokens:
        logger.error("GitHub 토큰이 설정되지 않았습니다. GITHUB_TOKENS 환경변수를 확인하세요.")
        sys.exit(1)

    logger.info("수집 파이프라인 시작")
    logger.info("  저장소: 최대 %d개", args.max_repos)
    logger.info("  PR/저장소: 최대 %d개", args.max_prs_per_repo)
    logger.info("  최소 스타: %d", args.min_stars)
    logger.info("  언어: %s", ", ".join(args.languages))
    logger.info("  동시성: %d", args.concurrency)

    collector = PRCollector(pipeline_config)
    asyncio.run(collector.run())


if __name__ == "__main__":
    main()
