from __future__ import annotations

from datetime import timedelta

import pytest

from ai_repo_radar.cache import CacheRepository, rebuild_cache
from ai_repo_radar.feedback import create_feedback_event
from ai_repo_radar.models import FeedbackAction
from ai_repo_radar.pipeline import FixtureEnhancer, run_pipeline
from ai_repo_radar.storage import ReportAlreadyExistsError


def test_json_facts_rebuild_sqlite_and_saved_view(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    data_store.append_snapshots(sample_fixture.historical_snapshots)
    result = run_pipeline(
        sample_fixture.repositories,
        store=data_store,
        config=radar_config,
        report_date=sample_fixture.report_date,
        readmes=sample_fixture.readmes,
        enhancer=FixtureEnhancer(sample_fixture.enhancements),
        generated_at=sample_fixture.generated_at,
    )
    selected = result.report.recommendations[0]
    event = create_feedback_event(
        repo_full_name=selected.repository.full_name,
        action=FeedbackAction.SAVE,
        topics=selected.repository.topics,
        created_at=sample_fixture.generated_at,
        report_date=result.report.report_date,
    )
    data_store.write_feedback_event(event)

    database = rebuild_cache(data_store, tmp_path / "cache.sqlite3")
    repository = CacheRepository(database)

    assert repository.latest_report() == result.report
    assert repository.list_reports()[0].saved_count == 1
    assert repository.list_saved()[0].recommendation == selected
    assert repository.sync_counts()["local"] == 1


def test_rebuild_maps_legacy_fixture_save_without_rewriting_event(
    sample_fixture,
    data_store,
    radar_config,
    tmp_path,
) -> None:
    result = run_pipeline(
        sample_fixture.repositories,
        store=data_store,
        config=radar_config,
        report_date=sample_fixture.report_date,
        readmes=sample_fixture.readmes,
        enhancer=FixtureEnhancer(sample_fixture.enhancements),
        generated_at=sample_fixture.generated_at,
    )
    event = create_feedback_event(
        repo_full_name="nova-labs/agent-forge",
        action=FeedbackAction.SAVE,
        topics=["agents", "llm"],
        created_at=sample_fixture.generated_at,
        report_date=result.report.report_date,
    )
    data_store.write_feedback_event(event)

    database = rebuild_cache(data_store, tmp_path / "cache.sqlite3")
    repository = CacheRepository(database)
    saved = repository.list_saved()[0]

    assert saved.repo_full_name == "langchain-ai/langgraph"
    assert saved.recommendation is not None
    assert saved.recommendation.repository.full_name == "langchain-ai/langgraph"
    assert data_store.pending_feedback_events()[0].repo_full_name == "nova-labs/agent-forge"
    assert "langchain-ai/langgraph" in repository.feedback_for_report(result.report.report_date)


def test_normal_daily_report_is_immutable_by_default(
    sample_fixture,
    data_store,
    radar_config,
) -> None:
    result = run_pipeline(
        sample_fixture.repositories,
        store=data_store,
        config=radar_config,
        report_date=sample_fixture.report_date,
        readmes=sample_fixture.readmes,
        generated_at=sample_fixture.generated_at,
    )
    changed = result.report.model_copy(
        update={"generated_at": sample_fixture.generated_at + timedelta(seconds=1)}
    )

    with pytest.raises(ReportAlreadyExistsError):
        data_store.write_report(changed)
