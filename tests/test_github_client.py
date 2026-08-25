from __future__ import annotations

import base64
from datetime import date

import httpx

from ai_repo_radar.config import GitHubConfig
from ai_repo_radar.providers.github import GitHubClient, SearchSpec


def _raw_repository() -> dict:
    return {
        "full_name": "open/example-ai",
        "owner": {"login": "open"},
        "name": "example-ai",
        "html_url": "https://github.com/open/example-ai",
        "description": "An example AI repository",
        "stargazers_count": 1234,
        "forks_count": 12,
        "open_issues_count": 3,
        "language": "Python",
        "topics": ["llm"],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-08-24T00:00:00Z",
        "pushed_at": "2026-08-24T00:00:00Z",
        "archived": False,
        "disabled": False,
        "fork": False,
        "mirror_url": None,
        "license": {"spdx_id": "MIT"},
        "default_branch": "main",
    }


def test_github_discovery_readme_and_release_mapping() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/search/repositories":
            return httpx.Response(200, json={"items": [_raw_repository()]})
        if request.url.path.endswith("/readme"):
            content = base64.b64encode(b"# Public README\nInstall safely.").decode()
            return httpx.Response(200, json={"content": content})
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(
                200,
                json={"tag_name": "v1.2.3", "published_at": "2026-08-20T12:00:00Z"},
            )
        raise AssertionError(request.url)

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://api.github.test")
    client = GitHubClient(None, GitHubConfig(max_retries=0), client=http_client)

    discovered = client.discover(
        today=date(2026, 8, 25),
        candidate_limit=1,
        searches=[SearchSpec("topic:llm", "test-source")],
    )
    with_readme, readmes = client.attach_readmes(discovered, excerpt_chars=12)
    with_release = client.attach_latest_releases(with_readme, limit=1)

    assert with_release[0].has_readme is True
    assert readmes["open/example-ai"] == "# Public REA"
    assert with_release[0].latest_release_tag == "v1.2.3"
    assert with_release[0].latest_release_at.isoformat() == "2026-08-20T12:00:00+00:00"
    assert calls == [
        "/search/repositories",
        "/repos/open/example-ai/readme",
        "/repos/open/example-ai/releases/latest",
    ]


def test_missing_readme_is_not_a_transport_failure() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(404))
    http_client = httpx.Client(transport=transport, base_url="https://api.github.test")
    client = GitHubClient(None, GitHubConfig(max_retries=0), client=http_client)
    repository = client._map_repository(_raw_repository(), "fixture")

    updated, readmes = client.attach_readmes([repository], excerpt_chars=100)

    assert updated[0].has_readme is False
    assert readmes == {}


def test_non_priority_readme_is_checked_but_not_decoded() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"content": "not valid base64"})
    )
    http_client = httpx.Client(transport=transport, base_url="https://api.github.test")
    client = GitHubClient(None, GitHubConfig(max_retries=0), client=http_client)
    repository = client._map_repository(_raw_repository(), "fixture")

    updated, readmes = client.attach_readmes(
        [repository],
        excerpt_chars=100,
        content_limit=0,
    )

    assert updated[0].has_readme is True
    assert readmes == {}
