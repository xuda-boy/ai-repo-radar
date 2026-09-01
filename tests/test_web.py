from __future__ import annotations

import json
import subprocess
import threading
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

import ai_repo_radar.web as web_module
from ai_repo_radar.cache import rebuild_cache
from ai_repo_radar.models import FeedbackAction
from ai_repo_radar.pipeline import FixtureEnhancer, run_pipeline
from ai_repo_radar.sync import PRIVATE_REPOSITORY_SENTINEL, SyncResult
from ai_repo_radar.web import create_app


def _client(sample_fixture, data_store, radar_config, tmp_path) -> TestClient:
    data_store.append_snapshots(sample_fixture.historical_snapshots)
    run_pipeline(
        sample_fixture.repositories,
        store=data_store,
        config=radar_config,
        report_date=sample_fixture.report_date,
        readmes=sample_fixture.readmes,
        enhancer=FixtureEnhancer(sample_fixture.enhancements),
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
        params={"repo": "vllm-project/vllm"},
        headers={"HX-Request": "true"},
    )

    assert today.status_code == 200
    assert "langchain-ai/langgraph" in today.text
    assert "七日 Star 信号" in today.text
    assert today.headers["x-frame-options"] == "DENY"
    assert history.status_code == 200
    assert "2026 年 08 月 25 日" in history.text
    assert 'href="https://github.com/vllm-project/vllm"' in history.text
    assert "github.com/example" not in history.text
    assert "样例" in history.text
    assert partial.status_code == 200
    assert "vllm-project/vllm" in partial.text
    assert "Fast rising" in partial.text
    assert "样例" in partial.text
    assert "项目简介" in partial.text
    assert "AI 中文概览" in partial.text
    assert "GitHub 原始简介" in partial.text
    assert "高吞吐和显存效率" in partial.text
    assert "确认硬件兼容" in partial.text
    assert "A high-throughput, memory-efficient inference" in partial.text


def test_dashboard_uses_confirmed_modern_discovery_shell_on_all_pages(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)

    pages = {
        "today": client.get("/"),
        "history": client.get("/history"),
        "saved": client.get("/saved"),
        "feedback": client.get("/feedback"),
    }

    for page, response in pages.items():
        assert response.status_code == 200
        assert 'class="app-sidebar"' in response.text
        assert 'class="mobile-nav"' in response.text
        assert f'data-page="{page}"' in response.text

    today = pages["today"].text
    assert 'class="daily-overview metric-overview"' in today
    assert "24h 新增 Star" in today
    assert "+1,098" in today
    assert "推荐结构" in today
    assert "AI 中文增强" in today
    assert "100%" in today
    assert 'class="recommendation-card' in today
    assert 'class="project-detail-card' in today
    assert 'id="visible-project-count"' in today
    assert 'data-kind-filter="rising"' in today
    assert 'data-project-kind="exploration"' in today
    assert 'id="mobile-status"' in today
    assert 'aria-controls="status-popover"' in today

    assert 'class="history-overview metric-overview"' in pages["history"].text
    assert 'class="saved-overview metric-overview"' in pages["saved"].text
    assert 'class="feedback-overview ledger-summary metric-overview"' in pages["feedback"].text


def test_dashboard_explains_fixture_freshness_and_disables_auto_update(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)

    today = client.get("/")
    status = client.get("/data-status").json()

    assert "固定样例" in today.text
    assert "不会自动更新" in today.text
    assert "自动更新不可用" in today.text
    assert status["report_date"] == sample_fixture.report_date.isoformat()
    assert status["tone"] == "sample"
    assert status["configured"] is False


def test_data_freshness_distinguishes_today_waiting_and_expired(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    _client(sample_fixture, data_store, radar_config, tmp_path)
    fixture_report = data_store.load_reports()[0]
    real_recommendations = [
        recommendation.model_copy(
            update={
                "repository": recommendation.repository.model_copy(
                    update={"discovery_sources": ["github-search"]}
                )
            }
        )
        for recommendation in fixture_report.recommendations
    ]
    real_report = fixture_report.model_copy(update={"recommendations": real_recommendations})
    now = datetime(2026, 8, 27, 1, 0, tzinfo=UTC)

    today = real_report.model_copy(
        update={"report_date": sample_fixture.report_date + timedelta(days=2)}
    )
    yesterday = real_report.model_copy(
        update={"report_date": sample_fixture.report_date + timedelta(days=1)}
    )

    assert web_module._data_freshness(today, configured=True, now=now)["tone"] == "success"
    assert web_module._data_freshness(yesterday, configured=True, now=now)["tone"] == "warning"
    expired = web_module._data_freshness(real_report, configured=True, now=now)
    assert expired["tone"] == "error"
    assert expired["label"] == "数据已过期 2 天"


def test_manual_data_refresh_reports_no_change(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)
    client.app.state.sync_configured = True
    monkeypatch.setattr(
        web_module,
        "pull_private_data_safely",
        lambda _store: SyncResult(
            success=True,
            synced_events=0,
            branch="main",
            changed=False,
        ),
    )

    response = client.post(
        "/refresh-data",
        data={"csrf_token": client.app.state.csrf_token},
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )
    trigger = json.loads(response.headers["HX-Trigger"])["radar:dataUpdated"]

    assert response.status_code == 200
    assert "当前没有新日报" in response.text
    assert response.headers.get("HX-Refresh") is None
    assert trigger["changed"] is False


def test_manual_data_refresh_rebuilds_cache_and_requests_reload(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)
    client.app.state.sync_configured = True
    current = data_store.load_reports()[0]
    next_report = current.model_copy(
        update={
            "report_date": current.report_date + timedelta(days=1),
            "generated_at": current.generated_at + timedelta(days=1),
        }
    )

    def fake_pull(store):
        store.write_report(next_report)
        return SyncResult(
            success=True,
            synced_events=0,
            branch="main",
            changed=True,
        )

    monkeypatch.setattr(web_module, "pull_private_data_safely", fake_pull)
    response = client.post(
        "/refresh-data",
        data={"csrf_token": client.app.state.csrf_token},
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )

    assert response.status_code == 200
    assert response.headers["HX-Refresh"] == "true"
    assert next_report.report_date.isoformat() in response.text
    assert client.get("/data-status").json()["report_date"] == next_report.report_date.isoformat()


def test_manual_data_refresh_rebuilds_cache_after_external_pull(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)
    client.app.state.sync_configured = True
    current = data_store.load_reports()[0]
    next_report = current.model_copy(
        update={
            "report_date": current.report_date + timedelta(days=1),
            "generated_at": current.generated_at + timedelta(days=1),
        }
    )
    data_store.write_report(next_report)
    monkeypatch.setattr(
        web_module,
        "pull_private_data_safely",
        lambda _store: SyncResult(
            success=True,
            synced_events=0,
            branch="main",
            changed=False,
        ),
    )

    response = client.post(
        "/refresh-data",
        data={"csrf_token": client.app.state.csrf_token},
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )

    assert response.status_code == 200
    assert response.headers["HX-Refresh"] == "true"
    assert client.get("/data-status").json()["report_date"] == next_report.report_date.isoformat()


def test_manual_data_refresh_hides_raw_git_error(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)
    client.app.state.sync_configured = True
    monkeypatch.setattr(
        web_module,
        "pull_private_data_safely",
        lambda _store: SyncResult(
            success=False,
            synced_events=0,
            branch=None,
            error_category="git_error",
            message=r"C:\private\repo and credential helper output",
        ),
    )

    response = client.post(
        "/refresh-data",
        data={"csrf_token": client.app.state.csrf_token},
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )

    assert response.status_code == 200
    assert "当前数据没有被覆盖" in response.text
    assert "C:\\private" not in response.text


def test_private_dashboard_runs_periodic_pull_worker(tmp_path, monkeypatch) -> None:
    repository = tmp_path / "private"
    repository.mkdir()
    subprocess.run(
        ["git", "-C", str(repository), "init", "-b", "main"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Test User"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
        check=True,
    )
    (repository / PRIVATE_REPOSITORY_SENTINEL).write_text("version=1\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repository), "add", PRIVATE_REPOSITORY_SENTINEL],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "initialize private data"],
        check=True,
        capture_output=True,
    )
    called = threading.Event()

    def fake_pull(_store):
        called.set()
        return SyncResult(success=True, synced_events=0, branch="main", changed=False)

    monkeypatch.setattr(web_module, "pull_private_data_safely", fake_pull)
    app = create_app(
        data_root=repository / "data",
        database_path=repository / ".cache" / "radar.sqlite3",
        auto_sync_interval_seconds=0.02,
    )

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert called.wait(timeout=1)

    called.clear()
    disabled_app = create_app(
        data_root=repository / "data",
        database_path=repository / ".cache" / "disabled.sqlite3",
        auto_sync_interval_seconds=0,
    )
    with TestClient(disabled_app) as client:
        assert 'data-auto-sync="false"' in client.get("/").text
        assert disabled_app.state.auto_refresh_thread is None
        assert called.is_set() is False


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
        "repo_full_name": "langchain-ai/langgraph",
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
    assert "langchain-ai/langgraph" in saved.text
    assert 'href="https://github.com/langchain-ai/langgraph"' in saved.text
    assert "查看 GitHub" in saved.text


def test_repeating_selected_feedback_cancels_without_duplicate_event(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)
    payload = {
        "csrf_token": client.app.state.csrf_token,
        "repo_full_name": "langchain-ai/langgraph",
        "report_date": sample_fixture.report_date.isoformat(),
        "action": "save",
    }
    headers = {"HX-Request": "true", "Origin": "http://127.0.0.1:8765"}

    first = client.post("/feedback", data=payload, headers=headers)
    second = client.post("/feedback", data=payload, headers=headers)

    events = data_store.load_feedback_events()
    originals = [event for event in events if event.action != FeedbackAction.REVOKE]
    retractions = [event for event in events if event.action == FeedbackAction.REVOKE]
    trigger = json.loads(second.headers["HX-Trigger"])["radar:feedbackRevoked"]

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(originals) == 1
    assert len(retractions) == 1
    assert retractions[0].reverts_event_id == originals[0].event_id
    assert client.app.state.cache.feedback_for_report(sample_fixture.report_date) == {}
    assert 'aria-pressed="true"' not in second.text
    assert "反馈已取消" in trigger["message"]
    assert "还没有收藏项目" in client.get("/saved").text


def test_selecting_different_feedback_replaces_previous_active_choice(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)
    token = client.app.state.csrf_token
    headers = {"HX-Request": "true", "Origin": "http://127.0.0.1:8765"}
    base_payload = {
        "csrf_token": token,
        "repo_full_name": "langchain-ai/langgraph",
        "report_date": sample_fixture.report_date.isoformat(),
    }

    client.post(
        "/feedback",
        data={**base_payload, "action": "more_like"},
        headers=headers,
    )
    response = client.post(
        "/feedback",
        data={**base_payload, "action": "irrelevant"},
        headers=headers,
    )

    events = data_store.load_feedback_events()
    originals = [event for event in events if event.action != FeedbackAction.REVOKE]
    retractions = [event for event in events if event.action == FeedbackAction.REVOKE]
    active = client.app.state.cache.feedback_for_report(sample_fixture.report_date)
    trigger = json.loads(response.headers["HX-Trigger"])["radar:feedbackSaved"]

    assert response.status_code == 200
    assert [event.action for event in originals] == [
        FeedbackAction.MORE_LIKE,
        FeedbackAction.IRRELEVANT,
    ]
    assert len(retractions) == 1
    assert retractions[0].reverts_event_id == originals[0].event_id
    assert active["langchain-ai/langgraph"].action == FeedbackAction.IRRELEVANT
    assert response.text.count('aria-pressed="true"') == 1
    assert "反馈已切换为“不相关”" in trigger["message"]


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
            "repo_full_name": "langchain-ai/langgraph",
            "report_date": sample_fixture.report_date.isoformat(),
            "action": "save",
        },
        headers={"Origin": "http://127.0.0.1:8765"},
    )

    assert response.status_code == 403
    assert data_store.pending_feedback_events() == []


def test_feedback_ledger_shows_actions_timing_and_sync_status(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)
    token = client.app.state.csrf_token
    client.post(
        "/feedback",
        data={
            "csrf_token": token,
            "repo_full_name": "langchain-ai/langgraph",
            "report_date": sample_fixture.report_date.isoformat(),
            "action": "more_like",
        },
        headers={"Origin": "http://127.0.0.1:8765"},
    )

    response = client.get("/feedback")

    assert response.status_code == 200
    assert 'aria-current="page"' in response.text
    assert "操作明细" in response.text
    assert "langchain-ai/langgraph" in response.text
    assert "更多此类" in response.text
    assert "本地待同步" in response.text
    assert "次日生效" in response.text
    assert "撤回反馈" in response.text
    assert "hx-confirm=" in response.text


def test_feedback_can_be_revoked_without_deleting_original_event(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)
    token = client.app.state.csrf_token
    client.post(
        "/feedback",
        data={
            "csrf_token": token,
            "repo_full_name": "langchain-ai/langgraph",
            "report_date": sample_fixture.report_date.isoformat(),
            "action": "save",
        },
        headers={"Origin": "http://127.0.0.1:8765"},
    )
    original = data_store.pending_feedback_events()[0]

    response = client.post(
        f"/feedback/{original.event_id}/revoke",
        data={"csrf_token": token},
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )
    trigger = json.loads(response.headers["HX-Trigger"])["radar:feedbackRevoked"]
    events = data_store.load_feedback_events()
    saved = client.get("/saved")
    sync_panel = client.get("/")
    repeated = client.post(
        f"/feedback/{original.event_id}/revoke",
        data={"csrf_token": token},
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )

    assert response.status_code == 200
    assert "撤回待生效" in response.text
    assert "撤回 · 本地待同步" in response.text
    assert trigger["pending"] == 2
    assert len(events) == 2
    assert original.event_id in {event.event_id for event in events}
    retraction = next(event for event in events if event.action == FeedbackAction.REVOKE)
    assert retraction.reverts_event_id == original.event_id
    assert "还没有收藏项目" in saved.text
    assert 'href="https://github.com/langchain-ai/langgraph"' not in saved.text
    assert "撤回反馈" in sync_panel.text
    assert repeated.status_code == 409


def test_feedback_revoke_rejects_bad_token_without_writing(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)
    token = client.app.state.csrf_token
    client.post(
        "/feedback",
        data={
            "csrf_token": token,
            "repo_full_name": "langchain-ai/langgraph",
            "report_date": sample_fixture.report_date.isoformat(),
            "action": "known",
        },
        headers={"Origin": "http://127.0.0.1:8765"},
    )
    original = data_store.pending_feedback_events()[0]

    response = client.post(
        f"/feedback/{original.event_id}/revoke",
        data={"csrf_token": "wrong"},
        headers={"Origin": "http://127.0.0.1:8765"},
    )

    assert response.status_code == 403
    assert data_store.load_feedback_events() == [original]


def test_sample_feedback_is_clearly_marked_local_only(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)
    token = client.app.state.csrf_token
    payload = {
        "csrf_token": token,
        "repo_full_name": "langchain-ai/langgraph",
        "report_date": sample_fixture.report_date.isoformat(),
        "action": "more_like",
    }
    client.post(
        "/feedback",
        data=payload,
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )

    today = client.get("/")
    sync = client.post(
        "/sync-feedback",
        data={"csrf_token": token},
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )

    assert "固定样例" in today.text
    assert "1 条仅本地" in today.text
    assert "当前使用的是样例或普通数据目录" in today.text
    assert "当前为仅本地模式" in today.text
    assert sync.status_code == 200
    assert "当前数据目录未连接私人 Git 仓" in sync.text
    assert len(data_store.pending_feedback_events()) == 1


def test_manual_feedback_sync_updates_panel_and_global_status(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)
    token = client.app.state.csrf_token
    client.post(
        "/feedback",
        data={
            "csrf_token": token,
            "repo_full_name": "langchain-ai/langgraph",
            "report_date": sample_fixture.report_date.isoformat(),
            "action": "save",
        },
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )
    client.app.state.sync_configured = True

    def fake_private_sync(store):
        pending = store.pending_feedback_events()
        for event in pending:
            store.stage_synced_feedback(event)
            store.remove_from_outbox(event.event_id)
        return SyncResult(success=True, synced_events=len(pending), branch="main")

    monkeypatch.setattr(web_module, "sync_private_data_safely", fake_private_sync)
    response = client.post(
        "/sync-feedback",
        data={"csrf_token": token},
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )
    trigger = json.loads(response.headers["HX-Trigger"])["radar:syncUpdated"]

    assert response.status_code == 200
    assert "已同步 1 条反馈到私人数据仓" in response.text
    assert "当前没有待同步反馈" in response.text
    assert "无需同步" in response.text
    assert trigger == {
        "message": "已同步 1 条反馈到私人数据仓。",
        "pending": 0,
        "configured": True,
        "label": "数据已同步",
    }
    assert data_store.pending_feedback_events() == []


def test_manual_feedback_sync_keeps_outbox_and_hides_raw_git_error(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)
    token = client.app.state.csrf_token
    client.post(
        "/feedback",
        data={
            "csrf_token": token,
            "repo_full_name": "langchain-ai/langgraph",
            "report_date": sample_fixture.report_date.isoformat(),
            "action": "known",
        },
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )
    client.app.state.sync_configured = True
    monkeypatch.setattr(
        web_module,
        "sync_private_data_safely",
        lambda _store: SyncResult(
            success=False,
            synced_events=0,
            branch=None,
            error_category="git_error",
            message=r"C:\private\path and remote details",
        ),
    )

    response = client.post(
        "/sync-feedback",
        data={"csrf_token": token},
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )

    assert response.status_code == 200
    assert "同步未完成，反馈仍安全保存在本机" in response.text
    assert "C:\\private" not in response.text
    assert len(data_store.pending_feedback_events()) == 1


def test_manual_feedback_sync_rejects_bad_token(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    client = _client(sample_fixture, data_store, radar_config, tmp_path)

    response = client.post(
        "/sync-feedback",
        data={"csrf_token": "wrong"},
        headers={"HX-Request": "true", "Origin": "http://127.0.0.1:8765"},
    )

    assert response.status_code == 403
