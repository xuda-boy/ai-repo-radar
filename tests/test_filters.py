from __future__ import annotations

from ai_repo_radar.filters import ARCHIVED, MISSING_README, filter_repositories, quality_filter


def test_quality_filter_lists_every_rejection_reason(sample_fixture, radar_config) -> None:
    archived = next(
        repository
        for repository in sample_fixture.repositories
        if repository.full_name == "fixture/archived-ai-demo"
    )

    decision = quality_filter(archived, radar_config, now=sample_fixture.generated_at)

    assert decision.passed is False
    assert ARCHIVED in decision.reasons


def test_filter_repositories_returns_stable_counts(sample_fixture, radar_config) -> None:
    passed, decisions, counts = filter_repositories(
        sample_fixture.repositories,
        radar_config,
        now=sample_fixture.generated_at,
    )

    assert len(decisions) == len(sample_fixture.repositories)
    assert len(passed) == 10
    assert counts[ARCHIVED] == 1
    assert counts[MISSING_README] == 1
    assert all(repository.has_readme for repository in passed)
