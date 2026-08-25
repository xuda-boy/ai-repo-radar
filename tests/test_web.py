from __future__ import annotations

from fastapi.testclient import TestClient

from ai_repo_radar.cache import rebuild_cache
from ai_repo_radar.pipeline import FixtureEnhancer, run_pipeline
from ai_repo_radar.web import create_app


def _client(sample_fixture, data_store, radar_config, tmp_path) -> TestClient:
    data_store.append_snapshots(sample_fixture.historical_snapshots)
    run_pipeline(
        sample_fixture.repositories,
        store=data_store,
        config=radar_config,
        report_date=sample_fixture.report_date,
        readmes=sample_fixture.readmes,
        enhancer=FixtureEnhancer(),
        generated_at=sample_fixture.generated_at,
    )
    database = rebuild_cache(data_store, tmp_path / "web.sqlite3")
    return TestClient(create_app(data_root=data_store.root, database_path=database))


def test_dashboard_reads_today_history_and_partial_views(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)

    today = client.get("/")
    history = client.get("/history")
    partial = client.get(
        "/partials/recommendation",
        params={"repo": "vectorwave/rapid-infer"},
        headers={"HX-Request": "true"},
    )

    assert today.status_code == 200
    assert "nova-labs/agent-forge" in today.text
    assert "七日 Star 信号" in today.text
    assert today.headers["x-frame-options"] == "DENY"
    assert history.status_code == 200
    assert "2026 年 08 月 25 日" in history.text
    assert partial.status_code == 200
    assert "vectorwave/rapid-infer" in partial.text
    assert "Fast rising" in partial.text


def test_feedback_is_saved_locally_and_immediately_visible_in_saved_page(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)
    token = client.app.state.csrf_token
    payload = {
        "csrf_token": token,
        "repo_full_name": "nova-labs/agent-forge",
        "report_date": sample_fixture.report_date.isoformat(),
        "action": "save",
    }

    response = client.post(
        "/feedback",
        data=payload,
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )
    saved = client.get("/saved")

    assert response.status_code == 200
    assert 'aria-pressed="true"' in response.text
    assert "radar:feedbackSaved" in response.headers["HX-Trigger"]
    assert len(data_store.pending_feedback_events()) == 1
    assert saved.status_code == 200
    assert "nova-labs/agent-forge" in saved.text
    assert "查看 GitHub" in saved.text


def test_feedback_rejects_bad_token_without_writing(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)

    response = client.post(
        "/feedback",
        data={
            "csrf_token": "wrong",
            "repo_full_name": "nova-labs/agent-forge",
            "report_date": sample_fixture.report_date.isoformat(),
            "action": "save",
        },
        headers={"Origin": "http://127.0.0.1:8765"},
    )

    assert response.status_code == 403
    assert data_store.pending_feedback_events() == []
