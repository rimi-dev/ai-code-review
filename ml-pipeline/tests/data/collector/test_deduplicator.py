"""PR 중복 제거 모듈 단위 테스트.

SHA-256 해시 기반 중복 감지 로직과 MongoDB 배치 삽입을 검증한다.
"""

from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from pymongo.errors import BulkWriteError, DuplicateKeyError

from data.collector.deduplicator import (
    batch_insert_deduplicated,
    compute_pr_hash,
    ensure_unique_index,
    insert_if_not_duplicate,
    is_duplicate,
    prepare_document_with_hash,
)


# ---------------------------------------------------------------------------
# compute_pr_hash 테스트
# ---------------------------------------------------------------------------

class TestComputePrHash:
    """compute_pr_hash 함수의 단위 테스트."""

    def test_consistent_hash(self) -> None:
        """동일한 입력에 대해 일관된 해시를 생성하는지 검증한다."""
        hash1 = compute_pr_hash("owner/repo", 42)
        hash2 = compute_pr_hash("owner/repo", 42)
        assert hash1 == hash2

    def test_different_repo_different_hash(self) -> None:
        """다른 저장소에 대해 다른 해시를 생성하는지 검증한다."""
        hash1 = compute_pr_hash("owner/repo1", 42)
        hash2 = compute_pr_hash("owner/repo2", 42)
        assert hash1 != hash2

    def test_different_pr_number_different_hash(self) -> None:
        """다른 PR 번호에 대해 다른 해시를 생성하는지 검증한다."""
        hash1 = compute_pr_hash("owner/repo", 1)
        hash2 = compute_pr_hash("owner/repo", 2)
        assert hash1 != hash2

    def test_hash_is_sha256_hex(self) -> None:
        """SHA-256 hex 형식의 해시를 생성하는지 검증한다."""
        result = compute_pr_hash("owner/repo", 42)
        assert len(result) == 64  # SHA-256 hex length
        assert all(c in "0123456789abcdef" for c in result)

    def test_hash_matches_manual_calculation(self) -> None:
        """수동 계산 결과와 일치하는지 검증한다."""
        expected = hashlib.sha256("owner/repo#42".encode("utf-8")).hexdigest()
        result = compute_pr_hash("owner/repo", 42)
        assert result == expected

    def test_special_characters_in_repo_name(self) -> None:
        """저장소 이름에 특수 문자가 포함된 경우를 검증한다."""
        hash1 = compute_pr_hash("org-name/repo.js", 1)
        hash2 = compute_pr_hash("org-name/repo.js", 1)
        assert hash1 == hash2
        assert len(hash1) == 64


# ---------------------------------------------------------------------------
# ensure_unique_index 테스트
# ---------------------------------------------------------------------------

class TestEnsureUniqueIndex:
    """ensure_unique_index 함수의 단위 테스트."""

    def test_creates_index_when_not_exists(self) -> None:
        """인덱스가 없을 때 생성하는지 검증한다."""
        mock_collection = MagicMock()
        mock_collection.list_indexes.return_value = [
            {"name": "_id_"},
        ]
        mock_collection.name = "training_prs"

        ensure_unique_index(mock_collection)

        mock_collection.create_indexes.assert_called_once()
        call_args = mock_collection.create_indexes.call_args[0][0]
        assert len(call_args) == 1

    def test_skips_when_index_exists(self) -> None:
        """인덱스가 이미 존재할 때 생성을 건너뛰는지 검증한다."""
        mock_collection = MagicMock()
        mock_collection.list_indexes.return_value = [
            {"name": "_id_"},
            {"name": "idx_dedup_hash_unique"},
        ]
        mock_collection.name = "training_prs"

        ensure_unique_index(mock_collection)

        mock_collection.create_indexes.assert_not_called()


# ---------------------------------------------------------------------------
# is_duplicate 테스트
# ---------------------------------------------------------------------------

class TestIsDuplicate:
    """is_duplicate 함수의 단위 테스트."""

    def test_returns_true_for_existing(self) -> None:
        """기존 문서가 있으면 True를 반환하는지 검증한다."""
        mock_collection = MagicMock()
        mock_collection.count_documents.return_value = 1

        result = is_duplicate(mock_collection, "owner/repo", 42)

        assert result is True
        expected_hash = compute_pr_hash("owner/repo", 42)
        mock_collection.count_documents.assert_called_once_with(
            {"_dedup_hash": expected_hash}, limit=1
        )

    def test_returns_false_for_new(self) -> None:
        """새 문서이면 False를 반환하는지 검증한다."""
        mock_collection = MagicMock()
        mock_collection.count_documents.return_value = 0

        result = is_duplicate(mock_collection, "owner/repo", 42)

        assert result is False


# ---------------------------------------------------------------------------
# insert_if_not_duplicate 테스트
# ---------------------------------------------------------------------------

class TestInsertIfNotDuplicate:
    """insert_if_not_duplicate 함수의 단위 테스트."""

    def test_insert_success(self) -> None:
        """새 문서를 정상적으로 삽입하는지 검증한다."""
        mock_collection = MagicMock()
        document: dict[str, Any] = {"title": "Test PR", "pr_number": 42}

        result = insert_if_not_duplicate(mock_collection, document, "owner/repo", 42)

        assert result is True
        mock_collection.insert_one.assert_called_once()
        inserted_doc = mock_collection.insert_one.call_args[0][0]
        assert "_dedup_hash" in inserted_doc
        assert inserted_doc["_dedup_hash"] == compute_pr_hash("owner/repo", 42)

    def test_duplicate_returns_false(self) -> None:
        """중복 문서 삽입 시 False를 반환하는지 검증한다."""
        mock_collection = MagicMock()
        mock_collection.insert_one.side_effect = DuplicateKeyError("duplicate key")
        document: dict[str, Any] = {"title": "Test PR", "pr_number": 42}

        result = insert_if_not_duplicate(mock_collection, document, "owner/repo", 42)

        assert result is False

    def test_hash_added_to_document(self) -> None:
        """삽입 시 해시 필드가 문서에 추가되는지 검증한다."""
        mock_collection = MagicMock()
        document: dict[str, Any] = {"title": "Test PR"}

        insert_if_not_duplicate(mock_collection, document, "owner/repo", 42)

        assert document["_dedup_hash"] == compute_pr_hash("owner/repo", 42)


# ---------------------------------------------------------------------------
# batch_insert_deduplicated 테스트
# ---------------------------------------------------------------------------

class TestBatchInsertDeduplicated:
    """batch_insert_deduplicated 함수의 단위 테스트."""

    def test_empty_batch(self) -> None:
        """빈 배치에서 (0, 0)을 반환하는지 검증한다."""
        mock_collection = MagicMock()
        inserted, skipped = batch_insert_deduplicated(mock_collection, [])
        assert inserted == 0
        assert skipped == 0
        mock_collection.insert_many.assert_not_called()

    def test_all_inserted_successfully(self) -> None:
        """모든 문서가 정상 삽입되는 경우를 검증한다."""
        mock_collection = MagicMock()
        mock_result = MagicMock()
        mock_result.inserted_ids = ["id1", "id2", "id3"]
        mock_collection.insert_many.return_value = mock_result

        docs = [
            {"_dedup_hash": "hash1", "data": "a"},
            {"_dedup_hash": "hash2", "data": "b"},
            {"_dedup_hash": "hash3", "data": "c"},
        ]

        inserted, skipped = batch_insert_deduplicated(mock_collection, docs)

        assert inserted == 3
        assert skipped == 0

    def test_partial_duplicates(self) -> None:
        """일부 중복이 있는 배치를 처리하는지 검증한다."""
        mock_collection = MagicMock()
        bulk_error = BulkWriteError(
            {
                "nInserted": 2,
                "writeErrors": [
                    {"code": 11000, "errmsg": "duplicate key", "index": 1},
                ],
            }
        )
        mock_collection.insert_many.side_effect = bulk_error

        docs = [
            {"_dedup_hash": "hash1", "data": "a"},
            {"_dedup_hash": "hash_dup", "data": "b"},
            {"_dedup_hash": "hash3", "data": "c"},
        ]

        inserted, skipped = batch_insert_deduplicated(mock_collection, docs)

        assert inserted == 2
        assert skipped == 1

    def test_non_duplicate_error_raises(self) -> None:
        """중복이 아닌 오류가 발생하면 예외를 전파하는지 검증한다."""
        mock_collection = MagicMock()
        bulk_error = BulkWriteError(
            {
                "nInserted": 0,
                "writeErrors": [
                    {"code": 12345, "errmsg": "some other error", "index": 0},
                ],
            }
        )
        mock_collection.insert_many.side_effect = bulk_error

        docs = [{"_dedup_hash": "hash1", "data": "a"}]

        with pytest.raises(BulkWriteError):
            batch_insert_deduplicated(mock_collection, docs)

    def test_missing_hash_raises(self) -> None:
        """_dedup_hash 필드가 없는 문서에서 ValueError를 발생시키는지 검증한다."""
        mock_collection = MagicMock()
        docs = [{"data": "a"}]

        with pytest.raises(ValueError, match="_dedup_hash"):
            batch_insert_deduplicated(mock_collection, docs)

    def test_ordered_false(self) -> None:
        """insert_many가 ordered=False로 호출되는지 검증한다."""
        mock_collection = MagicMock()
        mock_result = MagicMock()
        mock_result.inserted_ids = ["id1"]
        mock_collection.insert_many.return_value = mock_result

        docs = [{"_dedup_hash": "hash1", "data": "a"}]
        batch_insert_deduplicated(mock_collection, docs)

        mock_collection.insert_many.assert_called_once_with(docs, ordered=False)


# ---------------------------------------------------------------------------
# prepare_document_with_hash 테스트
# ---------------------------------------------------------------------------

class TestPrepareDocumentWithHash:
    """prepare_document_with_hash 함수의 단위 테스트."""

    def test_adds_hash_to_document(self) -> None:
        """문서에 해시 필드를 추가하는지 검증한다."""
        doc: dict[str, Any] = {"title": "Test", "pr_number": 10}
        result = prepare_document_with_hash(doc, "owner/repo", 10)

        assert "_dedup_hash" in result
        assert result["_dedup_hash"] == compute_pr_hash("owner/repo", 10)

    def test_returns_same_document_reference(self) -> None:
        """원본 문서와 동일한 참조를 반환하는지 검증한다."""
        doc: dict[str, Any] = {"title": "Test"}
        result = prepare_document_with_hash(doc, "owner/repo", 1)
        assert result is doc

    def test_overwrites_existing_hash(self) -> None:
        """기존 해시가 있으면 덮어쓰는지 검증한다."""
        doc: dict[str, Any] = {"_dedup_hash": "old_hash", "title": "Test"}
        result = prepare_document_with_hash(doc, "owner/repo", 1)
        assert result["_dedup_hash"] != "old_hash"
        assert result["_dedup_hash"] == compute_pr_hash("owner/repo", 1)
