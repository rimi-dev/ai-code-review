"""비동기 GitHub REST/GraphQL API 클라이언트.

토큰 로테이션, 지수 백오프, 페이지네이션을 지원하는 프로덕션 수준 클라이언트이다.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any
from urllib.parse import urlparse, parse_qs

import httpx

from data.collector.config import GitHubConfig

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """GitHub API 속도 제한 초과 시 발생하는 예외."""

    def __init__(self, reset_at: float, message: str = "Rate limit exceeded"):
        self.reset_at = reset_at
        super().__init__(message)


class GitHubAPIError(Exception):
    """GitHub API 일반 오류."""

    def __init__(self, status_code: int, message: str, response_body: str = ""):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(f"GitHub API error {status_code}: {message}")


class TokenRotator:
    """GitHub 토큰 로테이션을 관리한다.

    각 토큰의 남은 요청 수와 리셋 시간을 추적하여
    가장 적합한 토큰을 자동으로 선택한다.
    """

    def __init__(self, tokens: list[str]) -> None:
        if not tokens:
            raise ValueError("최소 하나의 GitHub 토큰이 필요합니다.")
        self._tokens = tokens
        self._token_state: dict[str, dict[str, float]] = {
            token: {"remaining": 5000.0, "reset_at": 0.0}
            for token in tokens
        }
        self._current_index = 0

    @property
    def token_count(self) -> int:
        """사용 가능한 토큰 수를 반환한다."""
        return len(self._tokens)

    def get_token(self) -> str:
        """가장 많은 잔여 요청을 가진 토큰을 반환한다.

        모든 토큰이 소진된 경우, 가장 빨리 리셋되는 토큰을 반환한다.
        """
        now = time.time()

        # 잔여 요청이 있는 토큰 중 가장 많은 것을 선택
        available = [
            (token, state)
            for token, state in self._token_state.items()
            if state["remaining"] > 0 or state["reset_at"] <= now
        ]

        if available:
            best_token = max(available, key=lambda x: x[1]["remaining"])[0]
            return best_token

        # 모든 토큰이 소진된 경우 가장 빨리 리셋되는 토큰 반환
        earliest = min(self._token_state.items(), key=lambda x: x[1]["reset_at"])
        return earliest[0]

    def update_limits(self, token: str, remaining: int, reset_at: float) -> None:
        """응답 헤더에서 추출한 속도 제한 정보를 업데이트한다."""
        if token in self._token_state:
            self._token_state[token]["remaining"] = float(remaining)
            self._token_state[token]["reset_at"] = reset_at

    def get_earliest_reset(self) -> float:
        """가장 빠른 리셋 시간을 반환한다."""
        return min(state["reset_at"] for state in self._token_state.values())

    def get_remaining(self, token: str) -> float:
        """특정 토큰의 잔여 요청 수를 반환한다."""
        return self._token_state.get(token, {}).get("remaining", 0.0)


class GitHubClient:
    """비동기 GitHub API 클라이언트.

    REST API와 GraphQL API를 모두 지원하며, 토큰 로테이션과
    지수 백오프를 통해 안정적인 API 호출을 보장한다.
    """

    def __init__(self, config: GitHubConfig | None = None) -> None:
        self._config = config or GitHubConfig.from_env()
        self._rotator = TokenRotator(self._config.tokens)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> GitHubClient:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._config.request_timeout_seconds),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _build_headers(self, token: str) -> dict[str, str]:
        """API 요청 헤더를 생성한다."""
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _extract_rate_limit_info(self, headers: httpx.Headers) -> tuple[int, float]:
        """응답 헤더에서 속도 제한 정보를 추출한다."""
        remaining = int(headers.get("x-ratelimit-remaining", "5000"))
        reset_at = float(headers.get("x-ratelimit-reset", "0"))
        return remaining, reset_at

    def _parse_link_header(self, link_header: str) -> dict[str, str]:
        """Link 헤더를 파싱하여 다음/이전 페이지 URL을 추출한다."""
        links: dict[str, str] = {}
        if not link_header:
            return links

        for part in link_header.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                url_part, rel_part = part.split(";", 1)
                url = url_part.strip().strip("<>")
                rel = rel_part.strip().split("=")[1].strip('"')
                links[rel] = url
            except (ValueError, IndexError):
                continue
        return links

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        accept: str | None = None,
    ) -> httpx.Response:
        """지수 백오프와 토큰 로테이션을 적용한 HTTP 요청을 수행한다.

        Args:
            method: HTTP 메서드 (GET, POST 등).
            url: 요청 URL.
            params: 쿼리 파라미터.
            json_body: JSON 요청 본문.
            accept: Accept 헤더 오버라이드.

        Returns:
            httpx.Response: 성공 응답.

        Raises:
            GitHubAPIError: 재시도 후에도 실패한 경우.
            RateLimitError: 모든 토큰이 속도 제한에 도달한 경우.
        """
        if not self._client:
            raise RuntimeError("클라이언트가 초기화되지 않았습니다. async with 구문을 사용하세요.")

        last_exception: Exception | None = None

        for attempt in range(self._config.max_retries):
            token = self._rotator.get_token()
            headers = self._build_headers(token)
            if accept:
                headers["Accept"] = accept

            try:
                response = await self._client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                )

                # 속도 제한 정보 업데이트
                remaining, reset_at = self._extract_rate_limit_info(response.headers)
                self._rotator.update_limits(token, remaining, reset_at)

                if response.status_code == 200:
                    return response

                if response.status_code == 403 and remaining == 0:
                    # 속도 제한 도달 - 다음 토큰으로 전환 후 재시도
                    wait_time = max(reset_at - time.time(), 0)
                    logger.warning(
                        "속도 제한 도달: token=***%s, reset_in=%.1fs, attempt=%d/%d",
                        token[-4:],
                        wait_time,
                        attempt + 1,
                        self._config.max_retries,
                    )

                    # 다른 토큰이 사용 가능한지 확인
                    other_token = self._rotator.get_token()
                    if other_token != token and self._rotator.get_remaining(other_token) > 0:
                        continue  # 다른 토큰으로 즉시 재시도

                    # 모든 토큰 소진 시 대기
                    if wait_time > 0:
                        sleep_time = min(wait_time + 1, self._config.max_backoff_seconds)
                        await asyncio.sleep(sleep_time)
                    continue

                if response.status_code in (403, 429):
                    # 일반 속도 제한 (Abuse detection 등)
                    retry_after = response.headers.get("retry-after")
                    if retry_after:
                        await asyncio.sleep(float(retry_after))
                    else:
                        backoff = self._calculate_backoff(attempt)
                        await asyncio.sleep(backoff)
                    continue

                if response.status_code >= 500:
                    # 서버 오류 - 지수 백오프 후 재시도
                    backoff = self._calculate_backoff(attempt)
                    logger.warning(
                        "서버 오류: status=%d, attempt=%d/%d, backoff=%.1fs",
                        response.status_code,
                        attempt + 1,
                        self._config.max_retries,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

                if response.status_code == 404:
                    raise GitHubAPIError(404, "리소스를 찾을 수 없습니다", response.text)

                if response.status_code == 422:
                    raise GitHubAPIError(422, "유효하지 않은 요청", response.text)

                raise GitHubAPIError(response.status_code, "예상치 못한 응답", response.text)

            except httpx.TimeoutException as e:
                last_exception = e
                backoff = self._calculate_backoff(attempt)
                logger.warning(
                    "요청 타임아웃: url=%s, attempt=%d/%d, backoff=%.1fs",
                    url,
                    attempt + 1,
                    self._config.max_retries,
                    backoff,
                )
                await asyncio.sleep(backoff)
                continue

            except httpx.ConnectError as e:
                last_exception = e
                backoff = self._calculate_backoff(attempt)
                logger.warning(
                    "연결 오류: url=%s, attempt=%d/%d, backoff=%.1fs",
                    url,
                    attempt + 1,
                    self._config.max_retries,
                    backoff,
                )
                await asyncio.sleep(backoff)
                continue

        raise GitHubAPIError(
            0,
            f"최대 재시도 횟수 {self._config.max_retries}회 초과",
            str(last_exception) if last_exception else "",
        )

    def _calculate_backoff(self, attempt: int) -> float:
        """지터가 포함된 지수 백오프 시간을 계산한다."""
        base = self._config.base_backoff_seconds * (2 ** attempt)
        jitter = random.uniform(0, base * 0.5)
        return min(base + jitter, self._config.max_backoff_seconds)

    async def _paginate(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        max_items: int | None = None,
        accept: str | None = None,
    ) -> list[dict[str, Any]]:
        """Link 헤더 기반 페이지네이션으로 모든 결과를 수집한다.

        Args:
            url: 시작 URL.
            params: 쿼리 파라미터.
            max_items: 최대 수집 항목 수.
            accept: Accept 헤더 오버라이드.

        Returns:
            수집된 전체 결과 리스트.
        """
        all_items: list[dict[str, Any]] = []
        current_url: str | None = url
        current_params = dict(params) if params else {}

        if "per_page" not in current_params:
            current_params["per_page"] = self._config.per_page

        while current_url:
            response = await self._request(
                "GET", current_url, params=current_params if current_params else None, accept=accept,
            )
            data = response.json()

            # 검색 API는 items 키 사용
            items = data.get("items", data) if isinstance(data, dict) else data

            if isinstance(items, list):
                all_items.extend(items)
            else:
                all_items.append(items)

            if max_items and len(all_items) >= max_items:
                return all_items[:max_items]

            # Link 헤더에서 다음 페이지 URL 추출
            link_header = response.headers.get("link", "")
            links = self._parse_link_header(link_header)
            next_url = links.get("next")

            if next_url:
                current_url = next_url
                # 다음 페이지 URL에 이미 파라미터가 포함되어 있으므로 None 설정
                # httpx는 params={}일 때 URL의 기존 쿼리 파라미터를 제거하므로
                # params=None으로 설정하여 URL의 쿼리 파라미터를 보존한다
                current_params = None
            else:
                current_url = None

        return all_items

    async def search_repos(
        self,
        *,
        language: str,
        min_stars: int = 1000,
        sort: str = "stars",
        order: str = "desc",
        max_results: int = 30,
    ) -> list[dict[str, Any]]:
        """GitHub 저장소를 검색한다.

        Args:
            language: 프로그래밍 언어 필터.
            min_stars: 최소 스타 수.
            sort: 정렬 기준 (stars, forks, updated).
            order: 정렬 순서 (asc, desc).
            max_results: 최대 결과 수.

        Returns:
            저장소 정보 리스트.
        """
        query = f"language:{language} stars:>={min_stars}"
        url = f"{self._config.base_url}/search/repositories"
        params = {
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": min(self._config.per_page, max_results),
        }

        logger.info("저장소 검색: language=%s, min_stars=%d", language, min_stars)
        results = await self._paginate(url, params, max_items=max_results)
        logger.info("저장소 검색 완료: %d개 발견", len(results))
        return results

    async def list_pull_requests(
        self,
        repo_full_name: str,
        *,
        state: str = "closed",
        sort: str = "updated",
        direction: str = "desc",
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        """저장소의 풀 리퀘스트 목록을 조회한다.

        병합된 PR만 필터링하며, 리뷰 코멘트가 있는 것만 반환한다.

        Args:
            repo_full_name: 저장소 전체 이름 (예: owner/repo).
            state: PR 상태 (closed 상태에서 merged 필터링).
            sort: 정렬 기준.
            direction: 정렬 방향.
            max_results: 최대 결과 수.

        Returns:
            병합된 PR 정보 리스트 (리뷰 코멘트 포함).
        """
        url = f"{self._config.base_url}/repos/{repo_full_name}/pulls"
        params = {
            "state": state,
            "sort": sort,
            "direction": direction,
        }

        logger.info("PR 목록 조회: repo=%s", repo_full_name)
        all_prs = await self._paginate(url, params, max_items=max_results * 3)

        # 병합된 PR만 필터링 (merged_at이 있는 것)
        merged_prs = [pr for pr in all_prs if pr.get("merged_at")]

        # 리뷰 코멘트가 있는 PR만 필터링
        reviewed_prs = [pr for pr in merged_prs if pr.get("review_comments", 0) > 0]

        logger.info(
            "PR 필터링 완료: repo=%s, total=%d, merged=%d, reviewed=%d",
            repo_full_name,
            len(all_prs),
            len(merged_prs),
            len(reviewed_prs),
        )
        return reviewed_prs[:max_results]

    async def get_pr_diff(self, repo_full_name: str, pr_number: int) -> str:
        """PR의 diff를 조회한다.

        Args:
            repo_full_name: 저장소 전체 이름.
            pr_number: PR 번호.

        Returns:
            diff 문자열.
        """
        url = f"{self._config.base_url}/repos/{repo_full_name}/pulls/{pr_number}"
        response = await self._request(
            "GET",
            url,
            accept="application/vnd.github.diff",
        )
        return response.text

    async def get_pr_review_comments(
        self,
        repo_full_name: str,
        pr_number: int,
        *,
        max_results: int = 500,
    ) -> list[dict[str, Any]]:
        """PR의 리뷰 코멘트를 조회한다.

        Args:
            repo_full_name: 저장소 전체 이름.
            pr_number: PR 번호.
            max_results: 최대 코멘트 수.

        Returns:
            리뷰 코멘트 리스트.
        """
        url = f"{self._config.base_url}/repos/{repo_full_name}/pulls/{pr_number}/comments"
        comments = await self._paginate(url, max_items=max_results)
        return comments

    async def get_pr_reviews(
        self,
        repo_full_name: str,
        pr_number: int,
    ) -> list[dict[str, Any]]:
        """PR의 리뷰 목록을 조회한다.

        Args:
            repo_full_name: 저장소 전체 이름.
            pr_number: PR 번호.

        Returns:
            리뷰 리스트.
        """
        url = f"{self._config.base_url}/repos/{repo_full_name}/pulls/{pr_number}/reviews"
        reviews = await self._paginate(url)
        return reviews

    async def graphql_query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """GraphQL API를 호출한다.

        Args:
            query: GraphQL 쿼리 문자열.
            variables: 쿼리 변수.

        Returns:
            GraphQL 응답 데이터.

        Raises:
            GitHubAPIError: GraphQL 오류 발생 시.
        """
        json_body: dict[str, Any] = {"query": query}
        if variables:
            json_body["variables"] = variables

        response = await self._request(
            "POST",
            self._config.graphql_url,
            json_body=json_body,
        )
        result = response.json()

        if "errors" in result:
            error_messages = "; ".join(e.get("message", "Unknown") for e in result["errors"])
            raise GitHubAPIError(200, f"GraphQL 오류: {error_messages}")

        return result.get("data", {})

    async def graphql_batch_prs(
        self,
        repo_owner: str,
        repo_name: str,
        *,
        first: int = 50,
        after: str | None = None,
    ) -> dict[str, Any]:
        """GraphQL을 사용하여 PR 정보를 배치로 효율적으로 조회한다.

        PR 본문, 리뷰, 코멘트를 한 번의 요청으로 가져온다.

        Args:
            repo_owner: 저장소 소유자.
            repo_name: 저장소 이름.
            first: 조회할 PR 수.
            after: 페이지네이션 커서.

        Returns:
            GraphQL 응답 데이터.
        """
        query = """
        query($owner: String!, $name: String!, $first: Int!, $after: String) {
            repository(owner: $owner, name: $name) {
                pullRequests(
                    states: MERGED,
                    first: $first,
                    after: $after,
                    orderBy: {field: UPDATED_AT, direction: DESC}
                ) {
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                    nodes {
                        number
                        title
                        body
                        createdAt
                        mergedAt
                        additions
                        deletions
                        changedFiles
                        author {
                            login
                        }
                        mergedBy {
                            login
                        }
                        baseRefName
                        headRefName
                        reviews(first: 20) {
                            nodes {
                                author {
                                    login
                                }
                                state
                                body
                                submittedAt
                            }
                        }
                        reviewThreads(first: 50) {
                            nodes {
                                isResolved
                                comments(first: 20) {
                                    nodes {
                                        author {
                                            login
                                        }
                                        body
                                        path
                                        line
                                        createdAt
                                        diffHunk
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        variables: dict[str, Any] = {
            "owner": repo_owner,
            "name": repo_name,
            "first": first,
        }
        if after:
            variables["after"] = after

        return await self.graphql_query(query, variables)
