from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from ai_repo_radar.models import (
    FeedbackAction,
    FeedbackEvent,
    InterestProfile,
    SyncStatus,
)

ACTION_DELTAS = {
    FeedbackAction.MORE_LIKE: 0.12,
    FeedbackAction.SAVE: 0.05,
    FeedbackAction.IRRELEVANT: -0.12,
    FeedbackAction.KNOWN: 0.0,
}


def create_feedback_event(
    *,
    repo_full_name: str,
    action: FeedbackAction,
    topics: list[str],
    report_date: date | None = None,
    created_at: datetime | None = None,
) -> FeedbackEvent:
    if action == FeedbackAction.REVOKE:
        raise ValueError("use create_feedback_retraction to revoke feedback")
    created = created_at or datetime.now(UTC)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return FeedbackEvent(
        event_id=uuid4(),
        repo_full_name=repo_full_name,
        action=action,
        topics=sorted({topic.strip().lower() for topic in topics if topic.strip()}),
        created_at=created,
        effective_date=created.date() + timedelta(days=1),
        report_date=report_date,
        sync_status=SyncStatus.LOCAL,
    )


def create_feedback_retraction(
    target: FeedbackEvent,
    *,
    created_at: datetime | None = None,
) -> FeedbackEvent:
    if target.action == FeedbackAction.REVOKE:
        raise ValueError("a feedback retraction cannot retract another retraction")
    created = created_at or datetime.now(UTC)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return FeedbackEvent(
        event_id=uuid4(),
        repo_full_name=target.repo_full_name,
        action=FeedbackAction.REVOKE,
        topics=target.topics,
        created_at=created,
        effective_date=created.date() + timedelta(days=1),
        report_date=target.report_date,
        sync_status=SyncStatus.LOCAL,
        reverts_event_id=target.event_id,
    )


def apply_feedback_events(
    profile: InterestProfile,
    events: list[FeedbackEvent],
    *,
    effective_on: date,
    per_event_cap: float = 0.12,
) -> InterestProfile:
    weights = dict(profile.weights)
    applied = set(profile.applied_event_ids)
    eligible = sorted(
        events,
        key=lambda event: (event.effective_date, event.created_at, str(event.event_id)),
    )
    events_by_id = {event.event_id: event for event in events}

    latest_update = profile.updated_at
    for event in eligible:
        if event.event_id in applied or event.effective_date > effective_on:
            continue
        target = events_by_id.get(event.reverts_event_id) if event.reverts_event_id else None
        if event.action == FeedbackAction.REVOKE:
            if target is None or target.action == FeedbackAction.REVOKE:
                continue
            raw_delta = -ACTION_DELTAS[target.action]
            topics = target.topics
        else:
            raw_delta = ACTION_DELTAS[event.action]
            topics = event.topics
        delta = max(-per_event_cap, min(per_event_cap, raw_delta))
        for topic in topics:
            weights[topic] = round(max(-1.0, min(1.0, weights.get(topic, 0.0) + delta)), 6)
        applied.add(event.event_id)
        if latest_update is None or event.created_at > latest_update:
            latest_update = event.created_at

    return InterestProfile(
        weights=weights,
        applied_event_ids=sorted(applied, key=str),
        updated_at=latest_update,
    )


def rebuild_interest_profile(events: list[FeedbackEvent], *, effective_on: date) -> InterestProfile:
    return apply_feedback_events(InterestProfile(), events, effective_on=effective_on)
