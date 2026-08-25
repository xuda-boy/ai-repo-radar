from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class RecommendationKind(StrEnum):
    INTEREST = "interest"
    RISING = "rising"
    EXPLORATION = "exploration"


class EvidenceKind(StrEnum):
    MEASURED = "measured"
    ESTIMATED = "estimated"


class ModelStatus(StrEnum):
    ENHANCED = "enhanced"
    DEGRADED = "degraded"
    NOT_REQUESTED = "not_requested"


class ReportStatus(StrEnum):
    NORMAL = "normal"
    DEGRADED = "degraded"


class FeedbackAction(StrEnum):
    MORE_LIKE = "more_like"
    SAVE = "save"
    IRRELEVANT = "irrelevant"
    KNOWN = "known"


class SyncStatus(StrEnum):
    LOCAL = "local"
    SYNCING = "syncing"
    SYNCED = "synced"
    PENDING_RETRY = "pending_retry"


class Repository(StrictModel):
    full_name: str
    owner: str
    name: str
    html_url: str
    description: str | None = None
    stars: int = Field(ge=0)
    forks: int = Field(default=0, ge=0)
    open_issues: int = Field(default=0, ge=0)
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    pushed_at: datetime
    archived: bool = False
    disabled: bool = False
    fork: bool = False
    is_mirror: bool = False
    has_readme: bool = False
    license_spdx: str | None = None
    default_branch: str = "main"
    discovery_sources: list[str] = Field(default_factory=list)
    latest_release_tag: str | None = None
    latest_release_at: datetime | None = None

    @field_validator("full_name")
    @classmethod
    def full_name_must_be_owner_repo(cls, value: str) -> str:
        if value.count("/") != 1 or any(not part.strip() for part in value.split("/")):
            raise ValueError("full_name must be in owner/repository form")
        return value

    @field_validator("topics")
    @classmethod
    def normalize_topics(cls, value: list[str]) -> list[str]:
        return sorted({topic.strip().lower() for topic in value if topic.strip()})


class RepositorySnapshot(StrictModel):
    observed_at: datetime
    repo_full_name: str
    stars: int = Field(ge=0)
    pushed_at: datetime
    latest_release_tag: str | None = None


class StarPoint(StrictModel):
    observed_on: date
    stars: int = Field(ge=0)


class GrowthSignal(StrictModel):
    delta_24h: int | None = None
    delta_7d: int | None = None
    relative_7d: float | None = None
    proxy_score: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: EvidenceKind
    accelerated: bool = False
    history: list[StarPoint] = Field(default_factory=list)


class FilterDecision(StrictModel):
    repo_full_name: str
    passed: bool
    reasons: list[str] = Field(default_factory=list)


class ScoreBreakdown(StrictModel):
    quality: float = Field(ge=0.0, le=1.0)
    interest: float = Field(ge=0.0, le=1.0)
    growth: float = Field(ge=0.0, le=1.0)
    health: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)
    total: float
    matched_topics: list[str] = Field(default_factory=list)
    explanation_codes: list[str] = Field(default_factory=list)


class ScoredRepository(StrictModel):
    repository: Repository
    growth: GrowthSignal
    score: ScoreBreakdown


class Recommendation(StrictModel):
    repository: Repository
    kind: RecommendationKind
    growth: GrowthSignal
    score: ScoreBreakdown
    recommendation_reason: str
    summary_zh: str | None = None
    quick_start: str | None = None
    model_status: ModelStatus = ModelStatus.NOT_REQUESTED


class ReportStats(StrictModel):
    candidate_count: int = Field(ge=0)
    passed_filter_count: int = Field(ge=0)
    recommendation_count: int = Field(ge=0)
    filter_reason_counts: dict[str, int] = Field(default_factory=dict)
    quota: dict[str, int] = Field(default_factory=dict)


class DailyReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    report_date: date
    generated_at: datetime
    status: ReportStatus
    model_status: ModelStatus
    model_error_category: str | None = None
    degradation_message: str | None = None
    recommendations: list[Recommendation] = Field(default_factory=list, max_length=8)
    stats: ReportStats

    @model_validator(mode="after")
    def degraded_report_requires_message(self) -> DailyReport:
        if self.status == ReportStatus.DEGRADED and not self.degradation_message:
            raise ValueError("degraded reports require a degradation_message")
        return self


class FeedbackEvent(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: UUID
    repo_full_name: str
    action: FeedbackAction
    topics: list[str] = Field(default_factory=list)
    created_at: datetime
    effective_date: date
    report_date: date | None = None
    sync_status: SyncStatus = SyncStatus.LOCAL

    @model_validator(mode="after")
    def feedback_takes_effect_later(self) -> FeedbackEvent:
        if self.effective_date <= self.created_at.date():
            raise ValueError("feedback must take effect no earlier than the next day")
        return self


class InterestProfile(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    weights: dict[str, float] = Field(default_factory=dict)
    applied_event_ids: list[UUID] = Field(default_factory=list)
    updated_at: datetime | None = None

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, value: dict[str, float]) -> dict[str, float]:
        return {
            topic.strip().lower(): round(max(-1.0, min(1.0, float(weight))), 6)
            for topic, weight in value.items()
            if topic.strip()
        }


class RepositoryEnhancement(StrictModel):
    full_name: str
    summary_zh: str = Field(min_length=4, max_length=280)
    quick_start: str = Field(min_length=2, max_length=180)


class EnhancementBatch(StrictModel):
    repositories: list[RepositoryEnhancement]
