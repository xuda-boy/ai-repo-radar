from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date

from ai_repo_radar.config import RadarConfig
from ai_repo_radar.models import (
    DailyReport,
    GrowthSignal,
    InterestProfile,
    Recommendation,
    RecommendationKind,
    Repository,
    ScoreBreakdown,
    ScoredRepository,
)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def quality_score(repository: Repository) -> float:
    star_signal = min(1.0, math.log10(repository.stars + 1) / 4.6)
    description_signal = 1.0 if (repository.description or "").strip() else 0.0
    readme_signal = 1.0 if repository.has_readme else 0.0
    license_signal = 1.0 if repository.license_spdx else 0.45
    issue_ratio = repository.open_issues / max(repository.stars, 1)
    maintenance_signal = 1.0 - min(1.0, issue_ratio * 15)
    return _clamp(
        star_signal * 0.43
        + description_signal * 0.17
        + readme_signal * 0.18
        + license_signal * 0.10
        + maintenance_signal * 0.12
    )


def health_score(repository: Repository, *, today: date) -> float:
    days = max(0, (today - repository.pushed_at.date()).days)
    if days <= 7:
        return 1.0
    if days <= 30:
        return 0.85
    if days <= 90:
        return 0.63
    if days <= 180:
        return 0.38
    return 0.0


def interest_score(repository: Repository, profile: InterestProfile) -> tuple[float, list[str]]:
    matches = sorted(topic for topic in repository.topics if topic in profile.weights)
    if not matches:
        return 0.0, []
    values = [profile.weights[topic] for topic in matches]
    positive = sum(max(0.0, value) for value in values)
    negative = sum(abs(min(0.0, value)) for value in values)
    return _clamp(positive / max(1, len(matches)) - negative / max(1, len(matches))), matches


def growth_score(signal: GrowthSignal) -> float:
    if signal.delta_7d is None:
        return signal.proxy_score
    absolute_7d = _clamp(math.log1p(max(0, signal.delta_7d)) / math.log1p(3000))
    absolute_24h = _clamp(math.log1p(max(0, signal.delta_24h or 0)) / math.log1p(500))
    relative = _clamp(max(0.0, signal.relative_7d or 0.0))
    return _clamp(absolute_7d * 0.45 + absolute_24h * 0.35 + relative * 0.20)


def _latest_history(reports: Iterable[DailyReport]) -> dict[str, Recommendation]:
    result: dict[str, tuple[date, Recommendation]] = {}
    for report in reports:
        for recommendation in report.recommendations:
            previous = result.get(recommendation.repository.full_name)
            if previous is None or report.report_date > previous[0]:
                result[recommendation.repository.full_name] = (report.report_date, recommendation)
    return {key: value[1] for key, value in result.items()}


def _latest_dates(reports: Iterable[DailyReport]) -> dict[str, date]:
    result: dict[str, date] = {}
    for report in reports:
        for recommendation in report.recommendations:
            name = recommendation.repository.full_name
            if name not in result or report.report_date > result[name]:
                result[name] = report.report_date
    return result


def repeat_is_allowed(
    repository: Repository,
    growth: GrowthSignal,
    *,
    today: date,
    previous_reports: list[DailyReport],
    interval_days: int,
) -> bool:
    dates = _latest_dates(previous_reports)
    last_date = dates.get(repository.full_name)
    if last_date is None:
        return True
    if (today - last_date).days < interval_days:
        return False
    previous = _latest_history(previous_reports).get(repository.full_name)
    release_changed = bool(
        repository.latest_release_tag
        and previous
        and repository.latest_release_tag != previous.repository.latest_release_tag
    )
    return growth.accelerated or release_changed


def score_repository(
    repository: Repository,
    growth: GrowthSignal,
    profile: InterestProfile,
    config: RadarConfig,
    *,
    today: date,
    previous_reports: list[DailyReport],
) -> ScoredRepository:
    quality = quality_score(repository)
    interest, matched = interest_score(repository, profile)
    growth_value = growth_score(growth)
    health = health_score(repository, today=today)
    novelty = 1.0 if repeat_is_allowed(
        repository,
        growth,
        today=today,
        previous_reports=previous_reports,
        interval_days=config.repeat_interval_days,
    ) else 0.0
    weights = config.scoring
    total = (
        quality * weights.quality_weight
        + interest * weights.interest_weight
        + growth_value * weights.growth_weight
        + health * weights.health_weight
        + novelty * weights.novelty_weight
    )
    codes: list[str] = []
    if matched:
        codes.append("topic_match")
    if growth_value >= 0.55:
        codes.append("strong_growth")
    if health >= 0.85:
        codes.append("active_maintenance")
    if growth.accelerated:
        codes.append("growth_reaccelerated")
    if novelty == 0.0:
        codes.append("repeat_blocked")
    return ScoredRepository(
        repository=repository,
        growth=growth,
        score=ScoreBreakdown(
            quality=round(quality, 6),
            interest=round(interest, 6),
            growth=round(growth_value, 6),
            health=round(health, 6),
            novelty=round(novelty, 6),
            total=round(total, 6),
            matched_topics=matched,
            explanation_codes=codes,
        ),
    )


def _ranking_key(item: ScoredRepository) -> tuple[float, float, float, str]:
    return (-item.score.total, -item.score.quality, -item.score.growth, item.repository.full_name)


def _reason(item: ScoredRepository, kind: RecommendationKind, *, cold_start: bool) -> str:
    if cold_start and kind == RecommendationKind.INTEREST:
        return "冷启动阶段：该项目同时具备较好的基础质量、维护活跃度和 AI 主题相关性。"
    if kind == RecommendationKind.INTEREST:
        topics = "、".join(item.score.matched_topics[:3]) or "相关 AI 主题"
        return f"你的显式反馈对 {topics} 给出了正向权重；该项目的质量与维护信号也通过门槛。"
    if kind == RecommendationKind.RISING:
        if item.growth.delta_7d is not None:
            return f"该项目 7 天 Star 增长 {item.growth.delta_7d:+d}，绝对增长和低基数保护后的相对增长均较突出。"
        return "快照尚不足，但创建时间、当前 Star 与近期活跃度形成了较强的早期增长代理信号。"
    return "这是今日的探索位置：项目质量通过门槛，同时与当前已知兴趣保持一定距离。"


def _to_recommendation(
    item: ScoredRepository,
    kind: RecommendationKind,
    *,
    cold_start: bool,
) -> Recommendation:
    return Recommendation(
        repository=item.repository,
        kind=kind,
        growth=item.growth,
        score=item.score,
        recommendation_reason=_reason(item, kind, cold_start=cold_start),
    )


def select_recommendations(
    scored: list[ScoredRepository],
    config: RadarConfig,
    *,
    day_number: int,
) -> list[Recommendation]:
    eligible = [
        item
        for item in scored
        if item.score.quality >= config.minimum_quality_score and item.score.novelty > 0
    ]
    eligible.sort(key=_ranking_key)
    cold_start = day_number <= config.cold_start_days
    selected: list[tuple[ScoredRepository, RecommendationKind]] = []
    selected_names: set[str] = set()

    def take(pool: list[ScoredRepository], limit: int, kind: RecommendationKind) -> None:
        for item in pool:
            if len([entry for entry in selected if entry[1] == kind]) >= limit:
                break
            if item.repository.full_name in selected_names:
                continue
            selected.append((item, kind))
            selected_names.add(item.repository.full_name)

    rising_pool = sorted(
        [
            item
            for item in eligible
            if item.repository.stars >= config.scoring.low_base_star_floor * 10
        ],
        key=lambda item: (-item.score.growth, *_ranking_key(item)),
    )
    exploration_pool = sorted(
        eligible,
        key=lambda item: (
            item.score.interest,
            -item.repository.created_at.timestamp(),
            -item.score.quality,
            item.repository.full_name,
        ),
    )

    if cold_start:
        take(exploration_pool, min(1, config.quota.exploration), RecommendationKind.EXPLORATION)
        cold_start_rising = [item for item in rising_pool if item.score.growth >= 0.80]
        take(cold_start_rising, min(2, config.quota.rising), RecommendationKind.RISING)
        remaining = config.max_daily_recommendations - len(selected)
        take(eligible, remaining, RecommendationKind.INTEREST)
    else:
        interest_pool = [item for item in eligible if item.score.interest > 0]
        take(interest_pool, config.quota.interest, RecommendationKind.INTEREST)
        take(rising_pool, config.quota.rising, RecommendationKind.RISING)
        take(exploration_pool, config.quota.exploration, RecommendationKind.EXPLORATION)

    order = {
        RecommendationKind.INTEREST: 0,
        RecommendationKind.RISING: 1,
        RecommendationKind.EXPLORATION: 2,
    }
    selected.sort(key=lambda entry: (order[entry[1]], _ranking_key(entry[0])))
    return [
        _to_recommendation(item, kind, cold_start=cold_start)
        for item, kind in selected[: config.max_daily_recommendations]
    ]
