from __future__ import annotations

from datetime import timedelta

import pytest

from ai_repo_radar.feedback import (
    apply_feedback_events,
    create_feedback_event,
    create_feedback_retraction,
)
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


def test_feedback_retraction_is_append_only_next_day_and_idempotent(sample_fixture) -> None:
    event = create_feedback_event(
        repo_full_name="langchain-ai/langgraph",
        action=FeedbackAction.MORE_LIKE,
        topics=["agents", "llm"],
        created_at=sample_fixture.generated_at,
        report_date=sample_fixture.report_date,
    )
    retraction = create_feedback_retraction(
        event,
        created_at=sample_fixture.generated_at + timedelta(hours=1),
    )

    applied = apply_feedback_events(
        InterestProfile(),
        [event],
        effective_on=event.effective_date,
    )
    withdrawn = apply_feedback_events(
        applied,
        [event, retraction],
        effective_on=retraction.effective_date,
    )
    repeated = apply_feedback_events(
        withdrawn,
        [event, retraction],
        effective_on=retraction.effective_date + timedelta(days=1),
    )

    assert retraction.action == FeedbackAction.REVOKE
    assert retraction.reverts_event_id == event.event_id
    assert retraction.topics == event.topics
    assert retraction.effective_date == retraction.created_at.date() + timedelta(days=1)
    assert withdrawn.weights == {"agents": 0.0, "llm": 0.0}
    assert set(withdrawn.applied_event_ids) == {event.event_id, retraction.event_id}
    assert repeated == withdrawn

    with pytest.raises(ValueError, match="create_feedback_retraction"):
        create_feedback_event(
            repo_full_name=event.repo_full_name,
            action=FeedbackAction.REVOKE,
            topics=event.topics,
            created_at=sample_fixture.generated_at,
        )
    with pytest.raises(ValueError, match="cannot retract another retraction"):
        create_feedback_retraction(retraction)
