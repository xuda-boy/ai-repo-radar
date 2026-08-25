from __future__ import annotations

from datetime import timedelta

from ai_repo_radar.feedback import create_feedback_event
from ai_repo_radar.models import FeedbackAction, RecommendationKind
from ai_repo_radar.pipeline import FixtureEnhancer, run_pipeline


def _run_sample(sample_fixture, data_store, radar_config, *, report_date=None):
    data_store.append_snapshots(sample_fixture.historical_snapshots)
    return run_pipeline(
        sample_fixture.repositories,
        store=data_store,
        config=radar_config,
        report_date=report_date or sample_fixture.report_date,
        readmes=sample_fixture.readmes,
        enhancer=FixtureEnhancer(sample_fixture.enhancements),
        generated_at=sample_fixture.generated_at,
    ).report


def test_cold_start_has_deterministic_quality_rising_exploration_mix(
    sample_fixture,
    data_store,
    radar_config,
) -> None:
    report = _run_sample(sample_fixture, data_store, radar_config)

    assert [item.kind for item in report.recommendations] == [
        RecommendationKind.INTEREST,
        RecommendationKind.INTEREST,
        RecommendationKind.INTEREST,
        RecommendationKind.INTEREST,
        RecommendationKind.INTEREST,
        RecommendationKind.INTEREST,
        RecommendationKind.RISING,
        RecommendationKind.EXPLORATION,
    ]
    assert report.recommendations[0].repository.full_name == "langchain-ai/langgraph"
    assert report.recommendations[-2].repository.full_name == "vllm-project/vllm"
    assert report.recommendations[-1].repository.full_name == "confident-ai/deepeval"


def test_day_eight_enforces_five_two_one_without_backfill(
    sample_fixture,
    data_store,
    radar_config,
) -> None:
    event = create_feedback_event(
        repo_full_name="langchain-ai/langgraph",
        action=FeedbackAction.MORE_LIKE,
        topics=["llm", "ai-agent", "evaluation", "inference", "observability"],
        created_at=sample_fixture.generated_at - timedelta(days=8),
        report_date=sample_fixture.report_date - timedelta(days=8),
    )
    data_store.write_feedback_event(event, to_outbox=False)
    data_store.append_snapshots(sample_fixture.historical_snapshots)

    # Day number is based on prior reports; use seven immutable placeholder runs on shifted dates.
    for days_before in range(7, 0, -1):
        shifted_date = sample_fixture.report_date - timedelta(days=days_before)
        generated = sample_fixture.generated_at - timedelta(days=days_before)
        run_pipeline(
            [],
            store=data_store,
            config=radar_config,
            report_date=shifted_date,
            generated_at=generated,
        )

    report = run_pipeline(
        sample_fixture.repositories,
        store=data_store,
        config=radar_config,
        report_date=sample_fixture.report_date,
        readmes=sample_fixture.readmes,
        enhancer=FixtureEnhancer(sample_fixture.enhancements),
        generated_at=sample_fixture.generated_at,
    ).report
    counts = {
        kind: sum(item.kind == kind for item in report.recommendations)
        for kind in RecommendationKind
    }

    assert counts == {
        RecommendationKind.INTEREST: 5,
        RecommendationKind.RISING: 2,
        RecommendationKind.EXPLORATION: 1,
    }
