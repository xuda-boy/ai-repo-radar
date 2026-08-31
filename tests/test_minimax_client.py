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
        enhancer=FixtureEnhancer(sample_fixture.enhancements),
        generated_at=sample_fixture.generated_at,
    ).report
    return report.recommendations[0]


def _recommendations(sample_fixture, data_store, radar_config, count: int = 2):
    data_store.append_snapshots(sample_fixture.historical_snapshots)
    report = run_pipeline(
        sample_fixture.repositories,
        store=data_store,
        config=radar_config,
        report_date=sample_fixture.report_date,
        readmes=sample_fixture.readmes,
        enhancer=FixtureEnhancer(sample_fixture.enhancements),
        generated_at=sample_fixture.generated_at,
    ).report
    return report.recommendations[:count]


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
    assert "禁止多条摘要复用同一结尾" in captured["messages"][0]["content"]
    assert "不能统一写成阅读 README" in captured["messages"][0]["content"]
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


def test_minimax_retries_an_invalid_response_and_recovers(
    sample_fixture,
    data_store,
    radar_config,
) -> None:
    recommendation = _recommendation(sample_fixture, data_store, radar_config)
    calls = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={"choices": [{"finish_reason": "length", "message": {"content": "{"}}]},
            )
        content = json.dumps(
            {
                "repositories": [
                    {
                        "full_name": recommendation.repository.full_name,
                        "summary_zh": "该项目用于构建可恢复的 AI 代理工作流。",
                        "quick_start": "先运行官方最小示例验证状态流转。",
                    }
                ]
            },
            ensure_ascii=False,
        )
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]},
        )

    client = MiniMaxClient(
        "test-key",
        MiniMaxConfig(max_retries=1),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )

    result = client.enhance([recommendation], {})

    assert calls == 2
    assert sleeps == [1.0]
    assert result.error_category is None
    assert result.enhancements[0].full_name == recommendation.repository.full_name


def test_minimax_retries_only_missing_repositories(
    sample_fixture,
    data_store,
    radar_config,
) -> None:
    recommendations = _recommendations(sample_fixture, data_store, radar_config)
    requested_batches: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requested = json.loads(body["messages"][1]["content"])["repositories"]
        requested_names = [item["full_name"] for item in requested]
        requested_batches.append(requested_names)
        selected = requested[:1] if len(requested_batches) == 1 else requested
        content = json.dumps(
            {
                "repositories": [
                    {
                        "full_name": item["full_name"],
                        "summary_zh": f"{item['full_name']} 的中文功能摘要。",
                        "quick_start": "先按照官方文档运行最小示例。",
                    }
                    for item in selected
                ]
            },
            ensure_ascii=False,
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = MiniMaxClient(
        "test-key",
        MiniMaxConfig(max_retries=1),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _seconds: None,
    )

    result = client.enhance(recommendations, {})

    assert requested_batches == [
        [item.repository.full_name for item in recommendations],
        [recommendations[1].repository.full_name],
    ]
    assert result.error_category is None
    assert [item.full_name for item in result.enhancements] == [
        item.repository.full_name for item in recommendations
    ]


def test_minimax_splits_an_invalid_batch_before_retrying(
    sample_fixture,
    data_store,
    radar_config,
) -> None:
    recommendations = _recommendations(sample_fixture, data_store, radar_config, count=4)
    requested_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requested = json.loads(body["messages"][1]["content"])["repositories"]
        requested_sizes.append(len(requested))
        if len(requested_sizes) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "{"}}]})
        content = json.dumps(
            {
                "repositories": [
                    {
                        "full_name": item["full_name"],
                        "summary_zh": f"{item['full_name']} 的中文功能摘要。",
                        "quick_start": "先运行该仓库的最小示例。",
                    }
                    for item in requested
                ]
            },
            ensure_ascii=False,
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = MiniMaxClient(
        "test-key",
        MiniMaxConfig(max_retries=1),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _seconds: None,
    )

    result = client.enhance(recommendations, {})

    assert requested_sizes == [4, 2, 2]
    assert result.error_category is None
    assert len(result.enhancements) == 4


def test_minimax_accepts_text_content_blocks(
    sample_fixture,
    data_store,
    radar_config,
) -> None:
    recommendation = _recommendation(sample_fixture, data_store, radar_config)
    content = json.dumps(
        {
            "repositories": [
                {
                    "full_name": recommendation.repository.full_name,
                    "summary_zh": "用于构建可恢复代理工作流的框架。",
                    "quick_start": "先运行官方最小示例。",
                }
            ]
        },
        ensure_ascii=False,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "reasoning", "text": "internal reasoning"},
                                {"type": "text", "text": f"```json\n{content}\n```"},
                            ]
                        }
                    }
                ]
            },
        )

    client = MiniMaxClient(
        "test-key",
        MiniMaxConfig(max_retries=0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.enhance([recommendation], {})

    assert result.error_category is None
    assert result.enhancements[0].summary_zh == "用于构建可恢复代理工作流的框架。"


def test_minimax_retries_an_english_only_summary(
    sample_fixture,
    data_store,
    radar_config,
) -> None:
    recommendation = _recommendation(sample_fixture, data_store, radar_config)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        summary = (
            "A framework for durable agent workflows."
            if calls == 1
            else "用于构建可恢复代理工作流的框架。"
        )
        content = json.dumps(
            {
                "repositories": [
                    {
                        "full_name": recommendation.repository.full_name,
                        "summary_zh": summary,
                        "quick_start": "先运行官方最小示例。",
                    }
                ]
            },
            ensure_ascii=False,
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = MiniMaxClient(
        "test-key",
        MiniMaxConfig(max_retries=1),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _seconds: None,
    )

    result = client.enhance([recommendation], {})

    assert calls == 2
    assert result.error_category is None
    assert result.enhancements[0].summary_zh == "用于构建可恢复代理工作流的框架。"


def test_minimax_reports_safe_diagnostics_after_retry_exhaustion(
    sample_fixture,
    data_store,
    radar_config,
) -> None:
    recommendation = _recommendation(sample_fixture, data_store, radar_config)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "length", "message": {"content": "{"}}]},
        )

    client = MiniMaxClient(
        "test-key",
        MiniMaxConfig(max_retries=2),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _seconds: None,
    )

    result = client.enhance([recommendation], {})

    assert calls == 3
    assert result.error_category == "invalid_response"
    assert "已自动重试 2 次" in (result.message or "")
    assert "输出截断" in (result.message or "")
    assert result.enhancements == []
