from __future__ import annotations

import json

import httpx

from ai_repo_radar.config import MiniMaxConfig
from ai_repo_radar.pipeline import FixtureEnhancer, run_pipeline
from ai_repo_radar.providers.minimax import MiniMaxClient


def _recommendation(sample_fixture, data_store, radar_config):
    data_store.append_snapshots(sample_fixture.historical_snapshots)
    report = run_pipeline(
        sample_fixture.repositories,
        store=data_store,
        config=radar_config,
        report_date=sample_fixture.report_date,
        readmes=sample_fixture.readmes,
        enhancer=FixtureEnhancer(),
        generated_at=sample_fixture.generated_at,
    ).report
    return report.recommendations[0]


def test_minimax_receives_only_public_repository_context(
    sample_fixture,
    data_store,
    radar_config,
) -> None:
    recommendation = _recommendation(sample_fixture, data_store, radar_config)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        content = json.dumps(
            {
                "repositories": [
                    {
                        "full_name": recommendation.repository.full_name,
                        "summary_zh": "一个用于编排 AI 代理工作流的开源项目。",
                        "quick_start": "先阅读公开 README 中的安装与示例。",
                    }
                ]
            },
            ensure_ascii=False,
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = MiniMaxClient(
        "test-key",
        MiniMaxConfig(max_retries=0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.enhance(
        [recommendation],
        {recommendation.repository.full_name: "PUBLIC README"},
    )
    user_payload = json.loads(captured["messages"][1]["content"])
    sent = user_payload["repositories"][0]

    assert captured["model"] == "MiniMax-M3"
    assert set(sent) == {"full_name", "description", "language", "topics", "readme_excerpt"}
    assert "score" not in captured["messages"][1]["content"]
    assert "recommendation_reason" not in captured["messages"][1]["content"]
    assert result.error_category is None
    assert result.enhancements[0].full_name == recommendation.repository.full_name


def test_minimax_missing_key_degrades_without_network() -> None:
    client = MiniMaxClient(None, MiniMaxConfig(max_retries=0))

    result = client.enhance([], {})

    assert result.error_category == "missing_api_key"
    assert result.enhancements == []
    client.close()
