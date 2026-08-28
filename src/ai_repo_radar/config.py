from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class QuotaConfig:
    interest: int = 5
    rising: int = 2
    exploration: int = 1


@dataclass(frozen=True)
class ScoringConfig:
    quality_weight: float = 0.28
    interest_weight: float = 0.30
    growth_weight: float = 0.24
    health_weight: float = 0.12
    novelty_weight: float = 0.06
    low_base_star_floor: int = 50


@dataclass(frozen=True)
class GitHubConfig:
    api_url: str = "https://api.github.com"
    api_version: str = "2026-03-10"
    timeout_seconds: float = 20.0
    max_retries: int = 3
    readme_excerpt_chars: int = 6000


@dataclass(frozen=True)
class MiniMaxConfig:
    api_url: str = "https://api.minimaxi.com/v1/chat/completions"
    model: str = "MiniMax-M3"
    timeout_seconds: float = 90.0
    max_retries: int = 2
    max_completion_tokens: int = 4096


@dataclass(frozen=True)
class DashboardConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    open_browser: bool = True
    auto_sync_interval_seconds: int = 300


@dataclass(frozen=True)
class RadarConfig:
    candidate_limit: int = 300
    readme_rank_limit: int = 30
    min_stars: int = 10
    max_inactive_days: int = 180
    max_daily_recommendations: int = 8
    cold_start_days: int = 7
    repeat_interval_days: int = 7
    minimum_quality_score: float = 0.34
    quota: QuotaConfig = field(default_factory=QuotaConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    minimax: MiniMaxConfig = field(default_factory=MiniMaxConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)

    def validate(self) -> RadarConfig:
        if self.candidate_limit < 1 or self.candidate_limit > 1000:
            raise ValueError("candidate_limit must be between 1 and 1000")
        if not 1 <= self.readme_rank_limit <= self.candidate_limit:
            raise ValueError("readme_rank_limit must be within candidate_limit")
        if self.max_daily_recommendations != sum(
            (self.quota.interest, self.quota.rising, self.quota.exploration)
        ):
            raise ValueError("daily recommendation count must equal the quota sum")
        if self.dashboard.host != "127.0.0.1":
            raise ValueError("the dashboard must bind to 127.0.0.1")
        if not 0 <= self.dashboard.auto_sync_interval_seconds <= 86_400:
            raise ValueError("dashboard auto sync interval must be between 0 and 86400 seconds")
        weights = (
            self.scoring.quality_weight,
            self.scoring.interest_weight,
            self.scoring.growth_weight,
            self.scoring.health_weight,
            self.scoring.novelty_weight,
        )
        if abs(sum(weights) - 1.0) > 1e-6:
            raise ValueError("scoring weights must sum to 1.0")
        return self


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"configuration section [{key}] must be a table")
    return value


def load_config(path: Path | None = None) -> RadarConfig:
    resolved = path
    if resolved is None and os.environ.get("AI_REPO_RADAR_CONFIG"):
        resolved = Path(os.environ["AI_REPO_RADAR_CONFIG"])

    raw: dict[str, Any] = {}
    if resolved is not None:
        with resolved.expanduser().open("rb") as handle:
            raw = tomllib.load(handle)

    radar = _section(raw, "radar")
    config = RadarConfig(
        candidate_limit=int(radar.get("candidate_limit", 300)),
        readme_rank_limit=int(radar.get("readme_rank_limit", 30)),
        min_stars=int(radar.get("min_stars", 10)),
        max_inactive_days=int(radar.get("max_inactive_days", 180)),
        max_daily_recommendations=int(radar.get("max_daily_recommendations", 8)),
        cold_start_days=int(radar.get("cold_start_days", 7)),
        repeat_interval_days=int(radar.get("repeat_interval_days", 7)),
        minimum_quality_score=float(radar.get("minimum_quality_score", 0.34)),
        quota=QuotaConfig(**_section(raw, "quota")),
        scoring=ScoringConfig(**_section(raw, "scoring")),
        github=GitHubConfig(**_section(raw, "github")),
        minimax=MiniMaxConfig(**_section(raw, "minimax")),
        dashboard=DashboardConfig(**_section(raw, "dashboard")),
    )
    return config.validate()


def resolve_data_dir(value: Path | None = None) -> Path:
    if value is not None:
        return value.expanduser().resolve()
    if os.environ.get("AI_REPO_RADAR_DATA_DIR"):
        return Path(os.environ["AI_REPO_RADAR_DATA_DIR"]).expanduser().resolve()
    return (Path.cwd() / ".local" / "data").resolve()
