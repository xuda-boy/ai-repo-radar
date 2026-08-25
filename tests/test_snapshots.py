from __future__ import annotations

from datetime import timedelta

import pytest

from ai_repo_radar.models import EvidenceKind, RepositorySnapshot
from ai_repo_radar.snapshots import compute_growth_signal


def test_measured_growth_uses_daily_and_seven_day_baselines(sample_fixture) -> None:
    repository = sample_fixture.repositories[0]
    history = [
        snapshot
        for snapshot in sample_fixture.historical_snapshots
        if snapshot.repo_full_name == repository.full_name
    ]

    signal = compute_growth_signal(
        repository,
        history,
        observed_at=sample_fixture.generated_at,
        low_base_star_floor=50,
    )

    assert signal.evidence == EvidenceKind.MEASURED
    assert signal.delta_24h == 214
    assert signal.delta_7d == 1160
    assert signal.relative_7d == pytest.approx(1160 / 11640)
    assert len(signal.history) == 8


def test_relative_growth_has_low_base_protection(sample_fixture) -> None:
    repository = sample_fixture.repositories[2].model_copy(update={"stars": 40})
    baseline = RepositorySnapshot(
        observed_at=sample_fixture.generated_at - timedelta(days=7),
        repo_full_name=repository.full_name,
        stars=10,
        pushed_at=repository.pushed_at,
    )

    signal = compute_growth_signal(
        repository,
        [baseline],
        observed_at=sample_fixture.generated_at,
        low_base_star_floor=50,
    )

    assert signal.delta_7d == 30
    assert signal.relative_7d == pytest.approx(0.6)


def test_missing_history_is_explicitly_estimated(sample_fixture) -> None:
    signal = compute_growth_signal(
        sample_fixture.repositories[0],
        [],
        observed_at=sample_fixture.generated_at,
    )

    assert signal.evidence == EvidenceKind.ESTIMATED
    assert signal.delta_7d is None
    assert signal.proxy_score > 0
