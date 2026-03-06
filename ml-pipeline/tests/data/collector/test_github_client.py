"""GitHub API 클라이언트 단위 테스트.

respx를 사용하여 httpx 요청을 모킹하고,
토큰 로테이션, 속도 제한 처리, 페이지네이션을 검증한다.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx

from data.collector.config import GitHubConfig
from data.collector.github_client import (
    GitHubAPIError,
    GitHubClient,
    RateLimitError,
    TokenRotator,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def github_config() -> GitHubConfig:
    """테스트용 GitHub 설정을 생성한다."""
    return GitHubConfig(
        base_url="https://api.github.com",
        graphql_url="https://api.github.com/graphql",
        tokens=["token_aaa", "token_bbb", "token_ccc"],
        max_retries=3,
        base_backoff_seconds=0.01,
        max_backoff_seconds=0.05,
        request_timeout_seconds=5.0,
        per_page=30,
    )


@pytest.fixture
def single_token_config() -> GitHubConfig:
    """단일 토큰 테스트용 설정을 생성한다."""
    return GitHubConfig(
        base_url="https://api.github.com",
        graphql_url="https://api.github.com/graphql",
        tokens=["token_single"],
        max_retries=3,
        base_backoff_seconds=0.01,
        max_backoff_seconds=0.05,
        request_timeout_seconds=5.0,
        per_page=30,
    )


def _rate_limit_headers(remaining: int = 4999, reset_at: float | None = None) -> dict[str, str]:
    """속도 제한 응답 헤더를 생성한다."""
    if reset_at is None:
        reset_at = time.time() + 3600
    return {
        "x-ratelimit-remaining": str(remaining),
        "x-ratelimit-reset": str(int(reset_at)),
    }


# ---------------------------------------------------------------------------
# TokenRotator 테스트
# ---------------------------------------------------------------------------

class TestTokenRotator:
    """TokenRotator 클래스의 단위 테스트."""

    def test_init_with_tokens(self) -> None:
        """토큰 목록으로 초기화를 검증한다."""
        rotator = TokenRotator(["a", "b", "c"])
        assert rotator.token_count == 3

    def test_init_without_tokens_raises(self) -> None:
        """빈 토큰 목록으로 초기화 시 ValueError를 발생시킨다."""
        with pytest.raises(ValueError, match="최소 하나의 GitHub 토큰"):
            TokenRotator([])

    def test_get_token_returns_best_remaining(self) -> None:
        """잔여 요청이 가장 많은 토큰을 반환한다."""
        rotator = TokenRotator(["a", "b"])
        rotator.update_limits("a", 100, time.time() + 3600)
        rotator.update_limits("b", 500, time.time() + 3600)
        assert rotator.get_token() == "b"

    def test_get_token_switches_on_exhaustion(self) -> None:
        """토큰이 소진되면 다른 토큰으로 전환한다."""
        rotator = TokenRotator(["a", "b"])
        rotator.update_limits("a", 0, time.time() + 3600)
        rotator.update_limits("b", 100, time.time() + 3600)
        assert rotator.get_token() == "b"

    def test_get_token_all_exhausted_returns_earliest_reset(self) -> None:
        """모든 토큰 소진 시 가장 빨리 리셋되는 토큰을 반환한다."""
        rotator = TokenRotator(["a", "b"])
        future = time.time() + 3600
        rotator.update_limits("a", 0, future + 100)
        rotator.update_limits("b", 0, future)
        assert rotator.get_token() == "b"

    def test_update_limits(self) -> None:
        """속도 제한 정보 업데이트를 검증한다."""
        rotator = TokenRotator(["a"])
        rotator.update_limits("a", 42, 1234567890.0)
        assert rotator.get_remaining("a") == 42.0

    def test_get_earliest_reset(self) -> None:
        """가장 빠른 리셋 시간을 반환하는지 검증한다."""
        rotator = TokenRotator(["a", "b"])
        rotator.update_limits("a", 100, 2000.0)
        rotator.update_limits("b", 100, 1000.0)
        assert rotator.get_earliest_reset() == 1000.0


# ---------------------------------------------------------------------------
# GitHubClient 테스트 - 기본 요청
# ---------------------------------------------------------------------------

class TestGitHubClientBasicRequests:
    """GitHubClient의 기본 API 요청 테스트."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_search_repos_success(self, github_config: GitHubConfig) -> None:
        """저장소 검색이 정상적으로 작동하는지 검증한다."""
        mock_data = {
            "total_count": 2,
            "items": [
                {"full_name": "owner/repo1", "stargazers_count": 5000},
                {"full_name": "owner/repo2", "stargazers_count": 3000},
            ],
        }

        respx.get("https://api.github.com/search/repositories").mock(
            return_value=httpx.Response(
                200,
                json=mock_data,
                headers=_rate_limit_headers(),
            )
        )

        async with GitHubClient(github_config) as client:
            repos = await client.search_repos(language="Python", min_stars=1000, max_results=10)

        assert len(repos) == 2
        assert repos[0]["full_name"] == "owner/repo1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_pull_requests_filters_merged(self, github_config: GitHubConfig) -> None:
        """병합된 PR만 필터링하는지 검증한다."""
        mock_prs = [
            {"number": 1, "merged_at": "2024-01-01T00:00:00Z", "review_comments": 3},
            {"number": 2, "merged_at": None, "review_comments": 1},
            {"number": 3, "merged_at": "2024-01-02T00:00:00Z", "review_comments": 0},
            {"number": 4, "merged_at": "2024-01-03T00:00:00Z", "review_comments": 5},
        ]

        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(
                200,
                json=mock_prs,
                headers=_rate_limit_headers(),
            )
        )

        async with GitHubClient(github_config) as client:
            prs = await client.list_pull_requests("owner/repo", max_results=10)

        # 병합되고 리뷰 코멘트가 있는 PR만 반환
        assert len(prs) == 2
        assert prs[0]["number"] == 1
        assert prs[1]["number"] == 4

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_pr_diff(self, github_config: GitHubConfig) -> None:
        """PR diff를 정상적으로 가져오는지 검증한다."""
        diff_text = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"

        respx.get("https://api.github.com/repos/owner/repo/pulls/42").mock(
            return_value=httpx.Response(
                200,
                text=diff_text,
                headers=_rate_limit_headers(),
            )
        )

        async with GitHubClient(github_config) as client:
            result = await client.get_pr_diff("owner/repo", 42)

        assert result == diff_text

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_pr_review_comments(self, github_config: GitHubConfig) -> None:
        """PR 리뷰 코멘트를 정상적으로 가져오는지 검증한다."""
        mock_comments = [
            {"id": 1, "body": "LGTM", "path": "file.py", "line": 10},
            {"id": 2, "body": "Fix this", "path": "file.py", "line": 20},
        ]

        respx.get("https://api.github.com/repos/owner/repo/pulls/42/comments").mock(
            return_value=httpx.Response(
                200,
                json=mock_comments,
                headers=_rate_limit_headers(),
            )
        )

        async with GitHubClient(github_config) as client:
            comments = await client.get_pr_review_comments("owner/repo", 42)

        assert len(comments) == 2
        assert comments[0]["body"] == "LGTM"


# ---------------------------------------------------------------------------
# GitHubClient 테스트 - 속도 제한 처리
# ---------------------------------------------------------------------------

class TestGitHubClientRateLimitHandling:
    """속도 제한 처리 관련 테스트."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_rate_limit_triggers_token_rotation(self, github_config: GitHubConfig) -> None:
        """속도 제한 도달 시 다른 토큰으로 전환하는지 검증한다."""
        call_count = 0

        def side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # 첫 번째 토큰 - 속도 제한
                return httpx.Response(
                    403,
                    json={"message": "API rate limit exceeded"},
                    headers=_rate_limit_headers(remaining=0, reset_at=time.time() + 3600),
                )
            else:
                # 두 번째 토큰 - 성공
                return httpx.Response(
                    200,
                    json=[{"id": 1}],
                    headers=_rate_limit_headers(remaining=4999),
                )

        respx.get("https://api.github.com/repos/owner/repo/pulls/1/comments").mock(
            side_effect=side_effect
        )

        async with GitHubClient(github_config) as client:
            result = await client.get_pr_review_comments("owner/repo", 1)

        assert len(result) == 1
        assert call_count >= 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_retry_after_header_respected(self, github_config: GitHubConfig) -> None:
        """retry-after 헤더를 존중하는지 검증한다."""
        call_count = 0

        def side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                return httpx.Response(
                    429,
                    json={"message": "Too many requests"},
                    headers={
                        **_rate_limit_headers(remaining=10),
                        "retry-after": "0.01",
                    },
                )
            return httpx.Response(
                200,
                json={"items": [{"full_name": "owner/repo"}]},
                headers=_rate_limit_headers(),
            )

        respx.get("https://api.github.com/search/repositories").mock(
            side_effect=side_effect
        )

        async with GitHubClient(github_config) as client:
            repos = await client.search_repos(language="Python", max_results=1)

        assert len(repos) == 1
        assert call_count == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_server_error_retries_with_backoff(self, github_config: GitHubConfig) -> None:
        """서버 오류 시 지수 백오프로 재시도하는지 검증한다."""
        call_count = 0

        def side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1

            if call_count <= 2:
                return httpx.Response(
                    500,
                    json={"message": "Internal Server Error"},
                    headers=_rate_limit_headers(),
                )
            return httpx.Response(
                200,
                json=[{"id": 1}],
                headers=_rate_limit_headers(),
            )

        respx.get("https://api.github.com/repos/owner/repo/pulls/1/reviews").mock(
            side_effect=side_effect
        )

        async with GitHubClient(github_config) as client:
            reviews = await client.get_pr_reviews("owner/repo", 1)

        assert len(reviews) == 1
        assert call_count == 3

    @respx.mock
    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises(self, github_config: GitHubConfig) -> None:
        """최대 재시도 횟수 초과 시 예외를 발생시키는지 검증한다."""
        respx.get("https://api.github.com/repos/owner/repo/pulls/1/reviews").mock(
            return_value=httpx.Response(
                500,
                json={"message": "Internal Server Error"},
                headers=_rate_limit_headers(),
            )
        )

        async with GitHubClient(github_config) as client:
            with pytest.raises(GitHubAPIError, match="최대 재시도 횟수"):
                await client.get_pr_reviews("owner/repo", 1)

    @respx.mock
    @pytest.mark.asyncio
    async def test_404_raises_immediately(self, github_config: GitHubConfig) -> None:
        """404 오류 시 즉시 예외를 발생시키는지 검증한다."""
        respx.get("https://api.github.com/repos/owner/nonexistent/pulls/1/comments").mock(
            return_value=httpx.Response(
                404,
                json={"message": "Not Found"},
                headers=_rate_limit_headers(),
            )
        )

        async with GitHubClient(github_config) as client:
            with pytest.raises(GitHubAPIError) as exc_info:
                await client.get_pr_review_comments("owner/nonexistent", 1)
            assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# GitHubClient 테스트 - 페이지네이션
# ---------------------------------------------------------------------------

class TestGitHubClientPagination:
    """Link 헤더 기반 페이지네이션 테스트."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_single_page(self, github_config: GitHubConfig) -> None:
        """단일 페이지 응답을 정상 처리하는지 검증한다."""
        respx.get("https://api.github.com/repos/owner/repo/pulls/1/comments").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": 1}, {"id": 2}],
                headers=_rate_limit_headers(),
            )
        )

        async with GitHubClient(github_config) as client:
            comments = await client.get_pr_review_comments("owner/repo", 1)

        assert len(comments) == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_multi_page_pagination(self, github_config: GitHubConfig) -> None:
        """여러 페이지에 걸친 페이지네이션을 정상 처리하는지 검증한다."""
        base_url = "https://api.github.com/repos/owner/repo/pulls/1/comments"
        page2_url = f"{base_url}?page=2"
        page3_url = f"{base_url}?page=3"

        call_count = 0

        def _get_page_param(url_str: str) -> str | None:
            """URL에서 page 쿼리 파라미터 값을 추출한다."""
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url_str)
            params = parse_qs(parsed.query)
            page_values = params.get("page", [])
            return page_values[0] if page_values else None

        def side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            url_str = str(request.url)
            page = _get_page_param(url_str)

            if page == "3":
                # 페이지 3 (마지막)
                return httpx.Response(
                    200,
                    json=[{"id": 5}],
                    headers=_rate_limit_headers(),
                )
            elif page == "2":
                # 페이지 2
                return httpx.Response(
                    200,
                    json=[{"id": 3}, {"id": 4}],
                    headers={
                        **_rate_limit_headers(),
                        "link": f'<{page3_url}>; rel="next"',
                    },
                )
            else:
                # 페이지 1
                return httpx.Response(
                    200,
                    json=[{"id": 1}, {"id": 2}],
                    headers={
                        **_rate_limit_headers(),
                        "link": f'<{page2_url}>; rel="next", <{page3_url}>; rel="last"',
                    },
                )

        respx.get(base_url).mock(side_effect=side_effect)

        async with GitHubClient(github_config) as client:
            comments = await client.get_pr_review_comments("owner/repo", 1)

        assert len(comments) == 5
        assert [c["id"] for c in comments] == [1, 2, 3, 4, 5]
        assert call_count == 3

    @respx.mock
    @pytest.mark.asyncio
    async def test_pagination_respects_max_items(self, github_config: GitHubConfig) -> None:
        """max_items 제한을 준수하는지 검증한다."""
        base_url = "https://api.github.com/repos/owner/repo/pulls/1/comments"
        page2_url = f"{base_url}?page=2"

        def side_effect(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "page=2" in url_str:
                return httpx.Response(
                    200,
                    json=[{"id": i} for i in range(31, 61)],
                    headers=_rate_limit_headers(),
                )
            return httpx.Response(
                200,
                json=[{"id": i} for i in range(1, 31)],
                headers={
                    **_rate_limit_headers(),
                    "link": f'<{page2_url}>; rel="next"',
                },
            )

        respx.get(base_url).mock(side_effect=side_effect)

        async with GitHubClient(github_config) as client:
            # max_results=20으로 제한
            comments = await client.get_pr_review_comments("owner/repo", 1, max_results=20)

        assert len(comments) == 20


# ---------------------------------------------------------------------------
# GitHubClient 테스트 - 토큰 로테이션
# ---------------------------------------------------------------------------

class TestGitHubClientTokenRotation:
    """API 호출 시 토큰 로테이션 테스트."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_uses_authorization_header(self, single_token_config: GitHubConfig) -> None:
        """Authorization 헤더에 토큰이 올바르게 설정되는지 검증한다."""
        captured_headers: list[str] = []

        def side_effect(request: httpx.Request) -> httpx.Response:
            captured_headers.append(request.headers.get("authorization", ""))
            return httpx.Response(
                200,
                json=[],
                headers=_rate_limit_headers(),
            )

        respx.get("https://api.github.com/repos/owner/repo/pulls/1/comments").mock(
            side_effect=side_effect
        )

        async with GitHubClient(single_token_config) as client:
            await client.get_pr_review_comments("owner/repo", 1)

        assert len(captured_headers) == 1
        assert captured_headers[0] == "Bearer token_single"

    @respx.mock
    @pytest.mark.asyncio
    async def test_rate_limit_updates_token_state(self, github_config: GitHubConfig) -> None:
        """응답 헤더의 속도 제한 정보가 토큰 상태에 반영되는지 검증한다."""
        reset_time = time.time() + 1800

        respx.get("https://api.github.com/repos/owner/repo/pulls/1/comments").mock(
            return_value=httpx.Response(
                200,
                json=[],
                headers={
                    "x-ratelimit-remaining": "42",
                    "x-ratelimit-reset": str(int(reset_time)),
                },
            )
        )

        async with GitHubClient(github_config) as client:
            await client.get_pr_review_comments("owner/repo", 1)
            # 사용된 토큰의 잔여 요청 수가 42로 업데이트되었는지 확인
            # 어느 토큰이 사용되었는지 확인
            found_42 = any(
                client._rotator.get_remaining(t) == 42.0
                for t in ["token_aaa", "token_bbb", "token_ccc"]
            )
            assert found_42, "토큰 상태가 업데이트되지 않았습니다"

    @respx.mock
    @pytest.mark.asyncio
    async def test_token_rotation_on_consecutive_rate_limits(self, github_config: GitHubConfig) -> None:
        """연속 속도 제한 시 여러 토큰으로 교대하는지 검증한다."""
        used_tokens: list[str] = []

        def side_effect(request: httpx.Request) -> httpx.Response:
            auth = request.headers.get("authorization", "")
            used_tokens.append(auth)

            if len(used_tokens) <= 2:
                return httpx.Response(
                    403,
                    json={"message": "rate limit"},
                    headers=_rate_limit_headers(remaining=0, reset_at=time.time() + 3600),
                )
            return httpx.Response(
                200,
                json=[{"id": 1}],
                headers=_rate_limit_headers(remaining=4999),
            )

        respx.get("https://api.github.com/repos/owner/repo/pulls/1/comments").mock(
            side_effect=side_effect
        )

        async with GitHubClient(github_config) as client:
            result = await client.get_pr_review_comments("owner/repo", 1)

        assert len(result) == 1
        assert len(used_tokens) == 3
        # 적어도 2개의 다른 토큰이 사용되었는지 확인
        unique_tokens = set(used_tokens)
        assert len(unique_tokens) >= 2, f"단일 토큰만 사용됨: {used_tokens}"


# ---------------------------------------------------------------------------
# GitHubClient 테스트 - GraphQL
# ---------------------------------------------------------------------------

class TestGitHubClientGraphQL:
    """GraphQL API 호출 테스트."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_graphql_query_success(self, github_config: GitHubConfig) -> None:
        """GraphQL 쿼리가 정상적으로 작동하는지 검증한다."""
        mock_response = {
            "data": {
                "repository": {
                    "pullRequests": {
                        "nodes": [{"number": 1, "title": "Test PR"}],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }

        respx.post("https://api.github.com/graphql").mock(
            return_value=httpx.Response(
                200,
                json=mock_response,
                headers=_rate_limit_headers(),
            )
        )

        async with GitHubClient(github_config) as client:
            result = await client.graphql_query(
                "query { repository(owner: $owner, name: $name) { ... } }",
                {"owner": "test", "name": "repo"},
            )

        assert "repository" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_graphql_error_raises(self, github_config: GitHubConfig) -> None:
        """GraphQL 오류 시 예외를 발생시키는지 검증한다."""
        mock_response = {
            "errors": [{"message": "Field 'invalid' not found"}],
        }

        respx.post("https://api.github.com/graphql").mock(
            return_value=httpx.Response(
                200,
                json=mock_response,
                headers=_rate_limit_headers(),
            )
        )

        async with GitHubClient(github_config) as client:
            with pytest.raises(GitHubAPIError, match="GraphQL 오류"):
                await client.graphql_query("{ invalid }")

    @respx.mock
    @pytest.mark.asyncio
    async def test_graphql_batch_prs(self, github_config: GitHubConfig) -> None:
        """GraphQL 배치 PR 조회가 정상적으로 작동하는지 검증한다."""
        mock_response = {
            "data": {
                "repository": {
                    "pullRequests": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor123"},
                        "nodes": [
                            {
                                "number": 100,
                                "title": "Feature PR",
                                "body": "Adds feature X",
                                "createdAt": "2024-01-01T00:00:00Z",
                                "mergedAt": "2024-01-02T00:00:00Z",
                                "additions": 50,
                                "deletions": 10,
                                "changedFiles": 3,
                                "author": {"login": "dev1"},
                                "mergedBy": {"login": "maintainer"},
                                "baseRefName": "main",
                                "headRefName": "feature-x",
                                "reviews": {"nodes": []},
                                "reviewThreads": {"nodes": []},
                            }
                        ],
                    }
                }
            }
        }

        respx.post("https://api.github.com/graphql").mock(
            return_value=httpx.Response(
                200,
                json=mock_response,
                headers=_rate_limit_headers(),
            )
        )

        async with GitHubClient(github_config) as client:
            result = await client.graphql_batch_prs("owner", "repo", first=10)

        prs = result["repository"]["pullRequests"]
        assert prs["pageInfo"]["hasNextPage"] is True
        assert len(prs["nodes"]) == 1
        assert prs["nodes"][0]["number"] == 100

    @respx.mock
    @pytest.mark.asyncio
    async def test_graphql_sends_post_with_json(self, github_config: GitHubConfig) -> None:
        """GraphQL 요청이 POST + JSON으로 전송되는지 검증한다."""
        captured_body: list[dict[str, Any]] = []

        def side_effect(request: httpx.Request) -> httpx.Response:
            import json
            captured_body.append(json.loads(request.content.decode()))
            return httpx.Response(
                200,
                json={"data": {"viewer": {"login": "test"}}},
                headers=_rate_limit_headers(),
            )

        respx.post("https://api.github.com/graphql").mock(side_effect=side_effect)

        async with GitHubClient(github_config) as client:
            await client.graphql_query("{ viewer { login } }", {"key": "val"})

        assert len(captured_body) == 1
        assert "query" in captured_body[0]
        assert captured_body[0]["variables"] == {"key": "val"}


# ---------------------------------------------------------------------------
# GitHubClient 테스트 - 에러 핸들링
# ---------------------------------------------------------------------------

class TestGitHubClientErrorHandling:
    """에러 핸들링 관련 테스트."""

    @pytest.mark.asyncio
    async def test_client_not_initialized_raises(self, github_config: GitHubConfig) -> None:
        """컨텍스트 매니저 없이 사용 시 RuntimeError를 발생시키는지 검증한다."""
        client = GitHubClient(github_config)
        with pytest.raises(RuntimeError, match="클라이언트가 초기화되지 않았습니다"):
            await client.get_pr_review_comments("owner/repo", 1)

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_retries(self, github_config: GitHubConfig) -> None:
        """타임아웃 발생 시 재시도하는지 검증한다."""
        call_count = 0

        def side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise httpx.TimeoutException("Connection timed out")
            return httpx.Response(
                200,
                json=[{"id": 1}],
                headers=_rate_limit_headers(),
            )

        respx.get("https://api.github.com/repos/owner/repo/pulls/1/comments").mock(
            side_effect=side_effect
        )

        async with GitHubClient(github_config) as client:
            result = await client.get_pr_review_comments("owner/repo", 1)

        assert len(result) == 1
        assert call_count == 3

    @respx.mock
    @pytest.mark.asyncio
    async def test_connection_error_retries(self, github_config: GitHubConfig) -> None:
        """연결 오류 시 재시도하는지 검증한다."""
        call_count = 0

        def side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("Connection refused")
            return httpx.Response(
                200,
                json=[{"id": 1}],
                headers=_rate_limit_headers(),
            )

        respx.get("https://api.github.com/repos/owner/repo/pulls/1/comments").mock(
            side_effect=side_effect
        )

        async with GitHubClient(github_config) as client:
            result = await client.get_pr_review_comments("owner/repo", 1)

        assert len(result) == 1
        assert call_count == 2

    def test_no_tokens_raises(self) -> None:
        """토큰 없이 클라이언트 생성 시 예외를 발생시키는지 검증한다."""
        config = GitHubConfig(tokens=[])
        with pytest.raises(ValueError):
            GitHubClient(config)

    @respx.mock
    @pytest.mark.asyncio
    async def test_422_raises_immediately(self, github_config: GitHubConfig) -> None:
        """422 오류 시 즉시 예외를 발생시키는지 검증한다."""
        respx.get("https://api.github.com/search/repositories").mock(
            return_value=httpx.Response(
                422,
                json={"message": "Validation Failed"},
                headers=_rate_limit_headers(),
            )
        )

        async with GitHubClient(github_config) as client:
            with pytest.raises(GitHubAPIError) as exc_info:
                await client.search_repos(language="InvalidLang")
            assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Link 헤더 파싱 테스트
# ---------------------------------------------------------------------------

class TestLinkHeaderParsing:
    """Link 헤더 파싱 관련 테스트."""

    def test_parse_link_header_with_next_and_last(self, github_config: GitHubConfig) -> None:
        """next와 last가 포함된 Link 헤더를 파싱한다."""
        client = GitHubClient(github_config)
        header = '<https://api.github.com/repos/o/r/pulls?page=2>; rel="next", <https://api.github.com/repos/o/r/pulls?page=5>; rel="last"'
        links = client._parse_link_header(header)
        assert links["next"] == "https://api.github.com/repos/o/r/pulls?page=2"
        assert links["last"] == "https://api.github.com/repos/o/r/pulls?page=5"

    def test_parse_empty_link_header(self, github_config: GitHubConfig) -> None:
        """빈 Link 헤더를 파싱한다."""
        client = GitHubClient(github_config)
        links = client._parse_link_header("")
        assert links == {}

    def test_parse_link_header_with_only_prev(self, github_config: GitHubConfig) -> None:
        """prev만 있는 Link 헤더를 파싱한다."""
        client = GitHubClient(github_config)
        header = '<https://api.github.com/repos/o/r/pulls?page=1>; rel="prev"'
        links = client._parse_link_header(header)
        assert "prev" in links
        assert "next" not in links

    def test_parse_link_header_with_malformed_input(self, github_config: GitHubConfig) -> None:
        """잘못된 형식의 Link 헤더를 안전하게 처리한다."""
        client = GitHubClient(github_config)
        links = client._parse_link_header("not a valid link header")
        assert isinstance(links, dict)
