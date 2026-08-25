from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from ai_repo_radar.models import (
    EvidenceKind,
    GrowthSignal,
    Repository,
    RepositorySnapshot,
    StarPoint,
)


def _ensure_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _daily_points(
    snapshots: list[RepositorySnapshot],
    current: RepositorySnapshot,
) -> list[RepositorySnapshot]:
    by_day: dict[date, RepositorySnapshot] = {}
    for snapshot in [*snapshots, current]:
        if snapshot.repo_full_name != current.repo_full_name:
            continue
        existing = by_day.get(snapshot.observed_at.date())
        if existing is None or snapshot.observed_at > existing.observed_at:
            by_day[snapshot.observed_at.date()] = snapshot
    return [by_day[key] for key in sorted(by_day)]


def _baseline(
    points: list[RepositorySnapshot],
    target: datetime,
    *,
    tolerance: timedelta,
) -> RepositorySnapshot | None:
    eligible = [point for point in points if point.observed_at <= target]
    if not eligible:
        return None
    candidate = max(eligible, key=lambda item: item.observed_at)
    if target - candidate.observed_at > tolerance:
        return None
    return candidate


def compute_growth_signal(
    repository: Repository,
    historical: list[RepositorySnapshot],
    *,
    observed_at: datetime | None = None,
    low_base_star_floor: int = 50,
) -> GrowthSignal:
    observed = _ensure_aware(observed_at or datetime.now(UTC))
    current = RepositorySnapshot(
        observed_at=observed,
        repo_full_name=repository.full_name,
        stars=repository.stars,
        pushed_at=repository.pushed_at,
        latest_release_tag=repository.latest_release_tag,
    )
    points = _daily_points(historical, current)
    previous_points = [point for point in points if point.observed_at < observed]

    baseline_24h = _baseline(
        previous_points,
        observed - timedelta(days=1),
        tolerance=timedelta(hours=18),
    )
    baseline_7d = _baseline(
        previous_points,
        observed - timedelta(days=7),
        tolerance=timedelta(days=2),
    )
    delta_24h = repository.stars - baseline_24h.stars if baseline_24h else None
    delta_7d = repository.stars - baseline_7d.stars if baseline_7d else None
    relative_7d = None
    if baseline_7d and delta_7d is not None:
        relative_7d = delta_7d / max(baseline_7d.stars, low_base_star_floor)

    age_days = max(1, (observed.date() - repository.created_at.date()).days)
    stars_per_day = repository.stars / age_days
    recent_activity_days = max(0, (observed.date() - repository.pushed_at.date()).days)
    activity_factor = max(0.0, 1.0 - min(recent_activity_days, 30) / 30)
    proxy_score = min(1.0, (stars_per_day / 35.0) * 0.7 + activity_factor * 0.3)

    accelerated = False
    if delta_24h is not None and delta_7d is not None:
        earlier_six_days = max(0, delta_7d - delta_24h)
        average_previous_day = earlier_six_days / 6
        accelerated = delta_24h >= 5 and delta_24h > max(average_previous_day * 1.8, 5)

    history = [
        StarPoint(observed_on=point.observed_at.date(), stars=point.stars)
        for point in points[-8:]
    ]
    return GrowthSignal(
        delta_24h=delta_24h,
        delta_7d=delta_7d,
        relative_7d=relative_7d,
        proxy_score=proxy_score,
        evidence=EvidenceKind.MEASURED if baseline_7d else EvidenceKind.ESTIMATED,
        accelerated=accelerated,
        history=history,
    )
