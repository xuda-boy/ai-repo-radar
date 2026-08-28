from __future__ import annotations

import base64
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from ai_repo_radar.config import GitHubConfig, RadarConfig
from ai_repo_radar.models import Repository


class GitHubAPIError(RuntimeError):
    pass


class GitHubNotFoundError(GitHubAPIError):
    pass


class GitHubRateLimitError(GitHubAPIError):
    pass


@dataclass(frozen=True)
class SearchSpec:
    query: str
    source: str
    sort: str = "stars"
    order: str = "desc"


@dataclass(frozen=True)
class GitHubCollection:
    repositories: list[Repository]
    readmes: dict[str, str]


def default_searches(today: date) -> list[SearchSpec]:
    active_cutoff = today - timedelta(days=30)
    created_cutoff = today - timedelta(days=45)
    return [
        SearchSpec("topic:artificial-intelligence stars:>=10", "ai-topic"),
        SearchSpec("topic:llm stars:>=10", "llm-topic"),
        SearchSpec("topic:ai-agent stars:>=10", "agent-topic"),
        SearchSpec(
            f"rag in:name,description stars:>=10 pushed:>={active_cutoff.isoformat()}",
            "recently-active",
            sort="updated",
        ),
        SearchSpec(
            f"ai in:name,description stars:>=10 created:>={created_cutoff.isoformat()}",
            "recently-created",
            sort="stars",
        ),
    ]


class GitHubClient:
    def __init__(
        self,
        token: str | None,
        config: GitHubConfig,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": config.api_version,
            "User-Agent": "ai-repo-radar/0.2.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.config = config
        self._client = client or httpx.Client(
            base_url=config.api_url,
            headers=headers,
            timeout=config.timeout_seconds,
            follow_redirects=True,
        )
        self._owns_client = client is None
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(60.0, max(0.0, float(retry_after)))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    return min(60.0, max(0.0, retry_at.timestamp() - time.time()))
                except (TypeError, ValueError):
                    pass
        reset = response.headers.get("X-RateLimit-Reset")
        if reset and response.headers.get("X-RateLimit-Remaining") == "0":
            try:
                return min(60.0, max(0.0, float(reset) - time.time()))
            except ValueError:
                pass
        return min(8.0, 2.0**attempt)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str | None = None,
    ) -> httpx.Response:
        headers = {"Accept": accept} if accept else None
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._client.request(method, path, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                last_error = error
                if attempt >= self.config.max_retries:
                    break
                self._sleep(min(8.0, 2.0**attempt))
                continue

            if response.status_code == 404:
                raise GitHubNotFoundError(path)
            if response.status_code in {403, 429}:
                if attempt >= self.config.max_retries:
                    raise GitHubRateLimitError(
                        f"GitHub API rate/abuse limit reached for {path}; retry later"
                    )
                self._sleep(self._retry_delay(response, attempt))
                continue
            if response.status_code >= 500:
                if attempt >= self.config.max_retries:
                    raise GitHubAPIError(
                        f"GitHub API returned {response.status_code} for {path}"
                    )
                self._sleep(min(8.0, 2.0**attempt))
                continue
            if response.status_code >= 400:
                message = response.text[:300].replace("\n", " ")
                raise GitHubAPIError(
                    f"GitHub API returned {response.status_code} for {path}: {message}"
                )
            return response
        raise GitHubAPIError(f"GitHub API request failed for {path}: {type(last_error).__name__}")

    @staticmethod
    def _map_repository(raw: dict[str, Any], source: str) -> Repository:
        license_value = raw.get("license") or {}
        return Repository(
            full_name=raw["full_name"],
            owner=raw["owner"]["login"],
            name=raw["name"],
            html_url=raw["html_url"],
            description=raw.get("description"),
            stars=raw.get("stargazers_count", 0),
            forks=raw.get("forks_count", 0),
            open_issues=raw.get("open_issues_count", 0),
            language=raw.get("language"),
            topics=raw.get("topics") or [],
            created_at=raw["created_at"],
            updated_at=raw["updated_at"],
            pushed_at=raw["pushed_at"],
            archived=raw.get("archived", False),
            disabled=raw.get("disabled", False),
            fork=raw.get("fork", False),
            is_mirror=bool(raw.get("mirror_url")),
            has_readme=False,
            license_spdx=license_value.get("spdx_id") if license_value else None,
            default_branch=raw.get("default_branch") or "main",
            discovery_sources=[source],
        )

    def discover(
        self,
        *,
        today: date,
        candidate_limit: int,
        searches: list[SearchSpec] | None = None,
    ) -> list[Repository]:
        specs = searches or default_searches(today)
        per_source = max(1, math.ceil(candidate_limit / len(specs)))
        by_name: dict[str, Repository] = {}
        for spec in specs:
            pages = math.ceil(per_source / 100)
            collected_for_source = 0
            for page in range(1, pages + 1):
                per_page = min(100, per_source - collected_for_source)
                response = self._request(
                    "GET",
                    "/search/repositories",
                    params={
                        "q": spec.query,
                        "sort": spec.sort,
                        "order": spec.order,
                        "page": page,
                        "per_page": per_page,
                    },
                )
                items = response.json().get("items", [])
                for raw in items:
                    repository = self._map_repository(raw, spec.source)
                    existing = by_name.get(repository.full_name)
                    if existing:
                        sources = sorted({*existing.discovery_sources, spec.source})
                        by_name[repository.full_name] = existing.model_copy(
                            update={"discovery_sources": sources}
                        )
                    else:
                        by_name[repository.full_name] = repository
                    collected_for_source += 1
                    if collected_for_source >= per_source:
                        break
                if len(items) < per_page or collected_for_source >= per_source:
                    break
        return sorted(by_name.values(), key=lambda item: (-item.stars, item.full_name))[
            :candidate_limit
        ]

    def _readme(self, full_name: str, *, include_content: bool) -> tuple[bool, str]:
        try:
            response = self._request("GET", f"/repos/{full_name}/readme")
        except GitHubNotFoundError:
            return False, ""
        if not include_content:
            return True, ""
        payload = response.json()
        content = payload.get("content")
        if not content:
            return True, ""
        try:
            decoded = base64.b64decode(content, validate=False).decode(
                "utf-8", errors="replace"
            )
            return True, decoded
        except (ValueError, TypeError):
            return True, ""

    def attach_readmes(
        self,
        repositories: list[Repository],
        *,
        excerpt_chars: int,
        content_limit: int | None = None,
    ) -> tuple[list[Repository], dict[str, str]]:
        updated: list[Repository] = []
        readmes: dict[str, str] = {}
        limit = len(repositories) if content_limit is None else max(0, content_limit)
        content_names = {repository.full_name for repository in repositories[:limit]}
        for repository in repositories:
            has_readme, readme = self._readme(
                repository.full_name,
                include_content=repository.full_name in content_names,
            )
            updated.append(repository.model_copy(update={"has_readme": has_readme}))
            if has_readme and readme:
                readmes[repository.full_name] = readme[:excerpt_chars]
        return updated, readmes

    def _latest_release(self, full_name: str) -> tuple[str | None, str | None]:
        try:
            response = self._request("GET", f"/repos/{full_name}/releases/latest")
        except GitHubNotFoundError:
            return None, None
        payload = response.json()
        return payload.get("tag_name"), payload.get("published_at")

    def attach_latest_releases(
        self,
        repositories: list[Repository],
        *,
        limit: int,
    ) -> list[Repository]:
        priority = {repository.full_name for repository in repositories[:limit]}
        updated = []
        for repository in repositories:
            if repository.full_name not in priority:
                updated.append(repository)
                continue
            tag, published_at = self._latest_release(repository.full_name)
            parsed_published_at = (
                datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                if published_at
                else None
            )
            updated.append(
                repository.model_copy(
                    update={
                        "latest_release_tag": tag,
                        "latest_release_at": parsed_published_at,
                    }
                )
            )
        return updated

    def collect(self, *, today: date, radar: RadarConfig) -> GitHubCollection:
        repositories = self.discover(
            today=today,
            candidate_limit=radar.candidate_limit,
        )
        repositories, readmes = self.attach_readmes(
            repositories,
            excerpt_chars=radar.github.readme_excerpt_chars,
            content_limit=radar.readme_rank_limit,
        )
        repositories = self.attach_latest_releases(
            repositories,
            limit=radar.readme_rank_limit,
        )
        return GitHubCollection(repositories=repositories, readmes=readmes)
