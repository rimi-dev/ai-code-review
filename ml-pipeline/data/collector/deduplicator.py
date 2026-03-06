"""PR 데이터 중복 제거 모듈.

SHA-256 해시를 기반으로 중복 PR 데이터를 감지하고 제거한다.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from pymongo import IndexModel, ASCENDING
from pymongo.collection import Collection
from pymongo.errors import BulkWriteError, DuplicateKeyError

logger = logging.getLogger(__name__)


def compute_pr_hash(repo_full_name: str, pr_number: int) -> str:
    """PR의 고유 해시를 계산한다.

    (repo_full_name, pr_number) 조합에 대한 SHA-256 해시를 생성한다.

    Args:
        repo_full_name: 저장소 전체 이름 (예: owner/repo).
        pr_number: PR 번호.

    Returns:
        SHA-256 해시 문자열 (hex).
    """
    composite_key = f"{repo_full_name}#{pr_number}"
    return hashlib.sha256(composite_key.encode("utf-8")).hexdigest()


def ensure_unique_index(collection: Collection[dict[str, Any]]) -> None:
    """MongoDB 컬렉션에 중복 방지 유니크 인덱스를 생성한다.

    _dedup_hash 필드에 고유 인덱스를 생성하여
    동일한 PR이 중복 저장되는 것을 방지한다.

    Args:
        collection: MongoDB 컬렉션.
    """
    index = IndexModel(
        [("_dedup_hash", ASCENDING)],
        unique=True,
        name="idx_dedup_hash_unique",
        background=True,
    )
    existing_indexes = {idx["name"] for idx in collection.list_indexes()}
    if "idx_dedup_hash_unique" not in existing_indexes:
        collection.create_indexes([index])
        logger.info("유니크 인덱스 생성 완료: collection=%s", collection.name)
    else:
        logger.debug("유니크 인덱스 이미 존재: collection=%s", collection.name)


def is_duplicate(collection: Collection[dict[str, Any]], repo_full_name: str, pr_number: int) -> bool:
    """해당 PR이 이미 저장되어 있는지 확인한다.

    Args:
        collection: MongoDB 컬렉션.
        repo_full_name: 저장소 전체 이름.
        pr_number: PR 번호.

    Returns:
        중복이면 True, 아니면 False.
    """
    dedup_hash = compute_pr_hash(repo_full_name, pr_number)
    return collection.count_documents({"_dedup_hash": dedup_hash}, limit=1) > 0


def insert_if_not_duplicate(
    collection: Collection[dict[str, Any]],
    document: dict[str, Any],
    repo_full_name: str,
    pr_number: int,
) -> bool:
    """중복이 아닌 경우에만 문서를 삽입한다.

    Args:
        collection: MongoDB 컬렉션.
        document: 삽입할 문서.
        repo_full_name: 저장소 전체 이름.
        pr_number: PR 번호.

    Returns:
        삽입 성공이면 True, 중복이면 False.
    """
    dedup_hash = compute_pr_hash(repo_full_name, pr_number)
    document["_dedup_hash"] = dedup_hash

    try:
        collection.insert_one(document)
        return True
    except DuplicateKeyError:
        logger.debug("중복 PR 스킵: repo=%s, pr=#%d", repo_full_name, pr_number)
        return False


def batch_insert_deduplicated(
    collection: Collection[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> tuple[int, int]:
    """배치 삽입 시 중복을 자동으로 건너뛴다.

    각 문서에는 이미 _dedup_hash 필드가 설정되어 있어야 한다.
    유니크 인덱스 위반 시 해당 문서만 건너뛰고 나머지는 삽입한다.

    Args:
        collection: MongoDB 컬렉션.
        documents: 삽입할 문서 리스트 (_dedup_hash 필드 포함).

    Returns:
        (삽입 성공 수, 중복 스킵 수) 튜플.
    """
    if not documents:
        return 0, 0

    # 해시가 없는 문서 검증
    for doc in documents:
        if "_dedup_hash" not in doc:
            raise ValueError("모든 문서에 _dedup_hash 필드가 필요합니다. compute_pr_hash()로 설정하세요.")

    try:
        result = collection.insert_many(documents, ordered=False)
        inserted = len(result.inserted_ids)
        skipped = len(documents) - inserted
        logger.info("배치 삽입 완료: inserted=%d, skipped=%d", inserted, skipped)
        return inserted, skipped
    except BulkWriteError as e:
        # DuplicateKeyError(code 11000)만 허용하고 나머지는 재발생
        write_errors = e.details.get("writeErrors", [])
        duplicate_errors = [err for err in write_errors if err.get("code") == 11000]
        other_errors = [err for err in write_errors if err.get("code") != 11000]

        if other_errors:
            logger.error("배치 삽입 중 예상치 못한 오류 발생: %s", other_errors)
            raise

        inserted = e.details.get("nInserted", 0)
        skipped = len(duplicate_errors)
        logger.info("배치 삽입 완료 (중복 포함): inserted=%d, skipped=%d", inserted, skipped)
        return inserted, skipped


def prepare_document_with_hash(
    document: dict[str, Any],
    repo_full_name: str,
    pr_number: int,
) -> dict[str, Any]:
    """문서에 중복 감지용 해시를 추가한다.

    Args:
        document: 원본 문서.
        repo_full_name: 저장소 전체 이름.
        pr_number: PR 번호.

    Returns:
        _dedup_hash가 추가된 문서.
    """
    document["_dedup_hash"] = compute_pr_hash(repo_full_name, pr_number)
    return document
