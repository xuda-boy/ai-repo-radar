from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from ai_repo_radar.config import RadarConfig
from ai_repo_radar.models import FilterDecision, Repository

ARCHIVED = "archived"
DISABLED = "disabled"
FORK = "fork"
MIRROR = "mirror"
INACTIVE = "inactive_over_limit"
MISSING_DESCRIPTION = "missing_description"
MISSING_README = "missing_readme"
BELOW_MIN_STARS = "below_min_stars"


def quality_filter(
    repository: Repository,
    config: RadarConfig,
    *,
    now: datetime | None = None,
) -> FilterDecision:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)

    reasons: list[str] = []
    if repository.archived:
        reasons.append(ARCHIVED)
    if repository.disabled:
        reasons.append(DISABLED)
    if repository.fork:
        reasons.append(FORK)
    if repository.is_mirror:
        reasons.append(MIRROR)
    if repository.pushed_at < current - timedelta(days=config.max_inactive_days):
        reasons.append(INACTIVE)
    if not (repository.description or "").strip():
        reasons.append(MISSING_DESCRIPTION)
    if not repository.has_readme:
        reasons.append(MISSING_README)
    if repository.stars < config.min_stars:
        reasons.append(BELOW_MIN_STARS)
    return FilterDecision(
        repo_full_name=repository.full_name,
        passed=not reasons,
        reasons=reasons,
    )


def filter_repositories(
    repositories: list[Repository],
    config: RadarConfig,
    *,
    now: datetime | None = None,
) -> tuple[list[Repository], list[FilterDecision], dict[str, int]]:
    decisions = [quality_filter(repository, config, now=now) for repository in repositories]
    passed_names = {decision.repo_full_name for decision in decisions if decision.passed}
    passed = [repository for repository in repositories if repository.full_name in passed_names]
    counts = Counter(reason for decision in decisions for reason in decision.reasons)
    return passed, decisions, dict(sorted(counts.items()))
