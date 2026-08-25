from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

from ai_repo_radar.config import RadarConfig
from ai_repo_radar.feedback import rebuild_interest_profile
from ai_repo_radar.filters import filter_repositories
from ai_repo_radar.models import (
    DailyReport,
    ModelStatus,
    Recommendation,
    ReportStats,
    ReportStatus,
    Repository,
    RepositoryEnhancement,
    RepositorySnapshot,
)
from ai_repo_radar.scoring import score_repository, select_recommendations
from ai_repo_radar.snapshots import compute_growth_signal
from ai_repo_radar.storage import JsonDataStore


@dataclass(frozen=True)
class EnhancementResult:
    enhancements: list[RepositoryEnhancement]
    error_category: str | None = None
    message: str | None = None


class ContentEnhancer(Protocol):
    def enhance(
        self,
        recommendations: list[Recommendation],
        readmes: Mapping[str, str],
    ) -> EnhancementResult: ...


class FixtureEnhancer:
    """Deterministic content for examples and end-to-end tests; never used in live runs."""

    def enhance(
        self,
        recommendations: list[Recommendation],
        readmes: Mapping[str, str],
    ) -> EnhancementResult:
        enhancements = []
        for recommendation in recommendations:
            repo = recommendation.repository
            summary = f"{repo.description or repo.full_name}，适合作为近期 AI 开源方向的源码观察样本。"
            language = repo.language or "项目文档"
            quick = f"{language} · 从 README 的安装与最小示例开始"
            enhancements.append(
                RepositoryEnhancement(
                    full_name=repo.full_name,
                    summary_zh=summary[:280],
                    quick_start=quick,
                )
            )
        return EnhancementResult(enhancements=enhancements)


@dataclass(frozen=True)
class PipelineResult:
    report: DailyReport
    snapshots_written: int
    report_path: str


def run_pipeline(
    repositories: list[Repository],
    *,
    store: JsonDataStore,
    config: RadarConfig,
    report_date: date,
    readmes: Mapping[str, str] | None = None,
    enhancer: ContentEnhancer | None = None,
    generated_at: datetime | None = None,
    replace_report: bool = False,
) -> PipelineResult:
    generated = generated_at or datetime.now(UTC)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=UTC)
    readme_map = readmes or {}
    store.initialize()

    historical_snapshots = store.load_snapshots()
    previous_reports = [
        report for report in store.load_reports() if report.report_date < report_date
    ]
    feedback_events = store.load_feedback_events(include_outbox=True)
    profile = rebuild_interest_profile(feedback_events, effective_on=report_date)

    passed, _decisions, reason_counts = filter_repositories(
        repositories,
        config,
        now=generated,
    )
    scored = []
    for repository in passed:
        history = [
            snapshot
            for snapshot in historical_snapshots
            if snapshot.repo_full_name == repository.full_name
        ]
        growth = compute_growth_signal(
            repository,
            history,
            observed_at=generated,
            low_base_star_floor=config.scoring.low_base_star_floor,
        )
        scored.append(
            score_repository(
                repository,
                growth,
                profile,
                config,
                today=report_date,
                previous_reports=previous_reports,
            )
        )

    recommendations = select_recommendations(
        scored,
        config,
        day_number=len(previous_reports) + 1,
    )

    model_status = ModelStatus.NOT_REQUESTED
    model_error_category = None
    degradation_message = None
    status = ReportStatus.NORMAL
    if enhancer is not None and recommendations:
        enhancement = enhancer.enhance(recommendations, readme_map)
        if enhancement.error_category:
            model_status = ModelStatus.DEGRADED
            model_error_category = enhancement.error_category
            degradation_message = enhancement.message or "AI 中文摘要暂不可用。"
            status = ReportStatus.DEGRADED
            recommendations = [
                recommendation.model_copy(update={"model_status": ModelStatus.DEGRADED})
                for recommendation in recommendations
            ]
        else:
            by_name = {item.full_name: item for item in enhancement.enhancements}
            recommendations = [
                recommendation.model_copy(
                    update={
                        "summary_zh": by_name[recommendation.repository.full_name].summary_zh,
                        "quick_start": by_name[recommendation.repository.full_name].quick_start,
                        "model_status": ModelStatus.ENHANCED,
                    }
                )
                if recommendation.repository.full_name in by_name
                else recommendation.model_copy(update={"model_status": ModelStatus.DEGRADED})
                for recommendation in recommendations
            ]
            missing = [
                item.repository.full_name
                for item in recommendations
                if item.model_status == ModelStatus.DEGRADED
            ]
            if missing:
                model_status = ModelStatus.DEGRADED
                status = ReportStatus.DEGRADED
                model_error_category = "partial_response"
                degradation_message = "部分项目的 AI 中文摘要暂不可用。"
            else:
                model_status = ModelStatus.ENHANCED

    report = DailyReport(
        report_date=report_date,
        generated_at=generated,
        status=status,
        model_status=model_status,
        model_error_category=model_error_category,
        degradation_message=degradation_message,
        recommendations=recommendations,
        stats=ReportStats(
            candidate_count=len(repositories),
            passed_filter_count=len(passed),
            recommendation_count=len(recommendations),
            filter_reason_counts=reason_counts,
            quota={
                "interest": config.quota.interest,
                "rising": config.quota.rising,
                "exploration": config.quota.exploration,
            },
        ),
    )

    current_snapshots = [
        RepositorySnapshot(
            observed_at=generated,
            repo_full_name=repository.full_name,
            stars=repository.stars,
            pushed_at=repository.pushed_at,
            latest_release_tag=repository.latest_release_tag,
        )
        for repository in repositories
    ]
    store.append_snapshots(current_snapshots)
    store.write_repository_metadata(repositories)
    store.save_interest_profile(profile)
    report_path = store.write_report(report, replace=replace_report)
    return PipelineResult(
        report=report,
        snapshots_written=len(current_snapshots),
        report_path=str(report_path),
    )
