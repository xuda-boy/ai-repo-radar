from __future__ import annotations

from datetime import timedelta

from ai_repo_radar.feedback import apply_feedback_events, create_feedback_event
from ai_repo_radar.models import FeedbackAction, InterestProfile


def test_feedback_is_next_day_and_idempotent(sample_fixture) -> None:
    event = create_feedback_event(
        repo_full_name="nova-labs/agent-forge",
        action=FeedbackAction.MORE_LIKE,
        topics=["Agents", "llm", "agents"],
        created_at=sample_fixture.generated_at,
        report_date=sample_fixture.report_date,
    )

    same_day = apply_feedback_events(
        InterestProfile(),
        [event],
        effective_on=sample_fixture.report_date,
    )
    next_day = apply_feedback_events(
        same_day,
        [event, event],
        effective_on=sample_fixture.report_date + timedelta(days=1),
    )
    repeated = apply_feedback_events(
        next_day,
        [event],
        effective_on=sample_fixture.report_date + timedelta(days=2),
    )

    assert event.effective_date == sample_fixture.report_date + timedelta(days=1)
    assert same_day.weights == {}
    assert next_day.weights == {"agents": 0.12, "llm": 0.12}
    assert repeated == next_day


def test_negative_feedback_is_bounded(sample_fixture) -> None:
    events = [
        create_feedback_event(
            repo_full_name=f"example/repo-{index}",
            action=FeedbackAction.IRRELEVANT,
            topics=["agents"],
            created_at=sample_fixture.generated_at + timedelta(seconds=index),
        )
        for index in range(12)
    ]

    profile = apply_feedback_events(
        InterestProfile(),
        events,
        effective_on=sample_fixture.report_date + timedelta(days=1),
    )

    assert profile.weights["agents"] == -1.0
