from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ai_repo_radar.models import (
    DailyReport,
    FeedbackAction,
    FeedbackEvent,
    InterestProfile,
    Recommendation,
    SyncStatus,
)
from ai_repo_radar.sample_data import canonical_fixture_repository_name
from ai_repo_radar.storage import JsonDataStore

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_info (
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    report_date TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    model_status TEXT NOT NULL,
    recommendation_count INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recommendations (
    report_date TEXT NOT NULL,
    position INTEGER NOT NULL,
    repo_full_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (report_date, repo_full_name),
    FOREIGN KEY (report_date) REFERENCES reports(report_date) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS snapshots (
    observed_at TEXT NOT NULL,
    repo_full_name TEXT NOT NULL,
    stars INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (observed_at, repo_full_name)
);
CREATE TABLE IF NOT EXISTS feedback_events (
    event_id TEXT PRIMARY KEY,
    repo_full_name TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    report_date TEXT,
    sync_status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS saved (
    repo_full_name TEXT PRIMARY KEY,
    saved_at TEXT NOT NULL,
    report_date TEXT,
    recommendation_json TEXT
);
CREATE TABLE IF NOT EXISTS interest_profile (
    topic TEXT PRIMARY KEY,
    weight REAL NOT NULL,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_recommendations_report ON recommendations(report_date, position);
CREATE INDEX IF NOT EXISTS idx_feedback_repo ON feedback_events(repo_full_name, created_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_repo ON snapshots(repo_full_name, observed_at);
"""


def _payload(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _recommendation_lookup(reports: list[DailyReport]) -> dict[tuple[date, str], Recommendation]:
    result: dict[tuple[date, str], Recommendation] = {}
    for report in reports:
        for recommendation in report.recommendations:
            result[(report.report_date, recommendation.repository.full_name)] = recommendation
    return result


def rebuild_cache(store: JsonDataStore, database_path: Path) -> Path:
    database_path = database_path.expanduser().resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = database_path.with_suffix(database_path.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()

    reports = store.load_reports()
    events = store.load_feedback_events(include_outbox=True)
    snapshots = store.load_snapshots()
    profile = store.load_interest_profile()
    lookup = _recommendation_lookup(reports)

    with closing(_connect(temporary)) as connection:
        connection.executescript(SCHEMA)
        connection.execute("DELETE FROM schema_info")
        connection.execute("INSERT INTO schema_info(version) VALUES (1)")
        for report in reports:
            connection.execute(
                "INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?)",
                (
                    report.report_date.isoformat(),
                    report.generated_at.isoformat(),
                    report.status.value,
                    report.model_status.value,
                    len(report.recommendations),
                    _payload(report),
                ),
            )
            for position, recommendation in enumerate(report.recommendations, start=1):
                connection.execute(
                    "INSERT INTO recommendations VALUES (?, ?, ?, ?, ?)",
                    (
                        report.report_date.isoformat(),
                        position,
                        recommendation.repository.full_name,
                        recommendation.kind.value,
                        _payload(recommendation),
                    ),
                )
        for snapshot in snapshots:
            connection.execute(
                "INSERT OR IGNORE INTO snapshots VALUES (?, ?, ?, ?)",
                (
                    snapshot.observed_at.isoformat(),
                    snapshot.repo_full_name,
                    snapshot.stars,
                    _payload(snapshot),
                ),
            )
        for event in events:
            cache_repo_full_name = canonical_fixture_repository_name(event.repo_full_name)
            connection.execute(
                "INSERT OR REPLACE INTO feedback_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(event.event_id),
                    event.repo_full_name,
                    event.action.value,
                    event.created_at.isoformat(),
                    event.effective_date.isoformat(),
                    event.report_date.isoformat() if event.report_date else None,
                    event.sync_status.value,
                    _payload(event),
                ),
            )
            if event.action == FeedbackAction.SAVE:
                recommendation = (
                    lookup.get((event.report_date, cache_repo_full_name))
                    if event.report_date
                    else None
                )
                connection.execute(
                    "INSERT OR REPLACE INTO saved VALUES (?, ?, ?, ?)",
                    (
                        cache_repo_full_name,
                        event.created_at.isoformat(),
                        event.report_date.isoformat() if event.report_date else None,
                        _payload(recommendation) if recommendation else None,
                    ),
                )
        for topic, weight in profile.weights.items():
            connection.execute(
                "INSERT INTO interest_profile VALUES (?, ?, ?)",
                (topic, weight, profile.updated_at.isoformat() if profile.updated_at else None),
            )
        connection.commit()

    os.replace(temporary, database_path)
    return database_path


@dataclass(frozen=True)
class ReportSummary:
    report_date: date
    status: str
    model_status: str
    recommendation_count: int
    saved_count: int


@dataclass(frozen=True)
class SavedItem:
    repo_full_name: str
    saved_at: str
    report_date: str | None
    recommendation: Recommendation | None


class CacheRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path.expanduser().resolve()

    def _connection(self) -> sqlite3.Connection:
        if not self.database_path.exists():
            raise FileNotFoundError(f"cache does not exist: {self.database_path}")
        return _connect(self.database_path)

    def latest_report(self) -> DailyReport | None:
        with closing(self._connection()) as connection:
            row = connection.execute(
                "SELECT payload_json FROM reports ORDER BY report_date DESC LIMIT 1"
            ).fetchone()
        return DailyReport.model_validate_json(row["payload_json"]) if row else None

    def get_report(self, report_date: date) -> DailyReport | None:
        with closing(self._connection()) as connection:
            row = connection.execute(
                "SELECT payload_json FROM reports WHERE report_date = ?",
                (report_date.isoformat(),),
            ).fetchone()
        return DailyReport.model_validate_json(row["payload_json"]) if row else None

    def list_reports(self) -> list[ReportSummary]:
        with closing(self._connection()) as connection:
            rows = connection.execute(
                """
                SELECT r.report_date, r.status, r.model_status, r.recommendation_count,
                       COALESCE(SUM(CASE WHEN f.action = 'save' THEN 1 ELSE 0 END), 0) AS saved_count
                FROM reports r
                LEFT JOIN feedback_events f ON f.report_date = r.report_date
                GROUP BY r.report_date
                ORDER BY r.report_date DESC
                """
            ).fetchall()
        return [
            ReportSummary(
                report_date=date.fromisoformat(row["report_date"]),
                status=row["status"],
                model_status=row["model_status"],
                recommendation_count=row["recommendation_count"],
                saved_count=row["saved_count"],
            )
            for row in rows
        ]

    def list_saved(self) -> list[SavedItem]:
        with closing(self._connection()) as connection:
            rows = connection.execute("SELECT * FROM saved ORDER BY saved_at DESC").fetchall()
        return [
            SavedItem(
                repo_full_name=row["repo_full_name"],
                saved_at=row["saved_at"],
                report_date=row["report_date"],
                recommendation=Recommendation.model_validate_json(row["recommendation_json"])
                if row["recommendation_json"]
                else None,
            )
            for row in rows
        ]

    def feedback_for_report(self, report_date: date) -> dict[str, FeedbackEvent]:
        with closing(self._connection()) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM feedback_events ORDER BY created_at"
            ).fetchall()
        result: dict[str, FeedbackEvent] = {}
        for row in rows:
            event = FeedbackEvent.model_validate_json(row["payload_json"])
            if event.report_date == report_date:
                result[canonical_fixture_repository_name(event.repo_full_name)] = event
        return result

    def insert_feedback(self, event: FeedbackEvent, recommendation: Recommendation | None) -> None:
        with closing(self._connection()) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO feedback_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(event.event_id),
                    event.repo_full_name,
                    event.action.value,
                    event.created_at.isoformat(),
                    event.effective_date.isoformat(),
                    event.report_date.isoformat() if event.report_date else None,
                    event.sync_status.value,
                    _payload(event),
                ),
            )
            if event.action == FeedbackAction.SAVE:
                connection.execute(
                    "INSERT OR REPLACE INTO saved VALUES (?, ?, ?, ?)",
                    (
                        event.repo_full_name,
                        event.created_at.isoformat(),
                        event.report_date.isoformat() if event.report_date else None,
                        _payload(recommendation) if recommendation else None,
                    ),
                )
            connection.commit()

    def sync_counts(self) -> dict[str, int]:
        with closing(self._connection()) as connection:
            rows = connection.execute(
                "SELECT sync_status, COUNT(*) AS count FROM feedback_events GROUP BY sync_status"
            ).fetchall()
        counts = {status.value: 0 for status in SyncStatus}
        counts.update({row["sync_status"]: row["count"] for row in rows})
        return counts

    def interest_profile(self) -> InterestProfile:
        with closing(self._connection()) as connection:
            rows = connection.execute("SELECT topic, weight, updated_at FROM interest_profile").fetchall()
        updated = next((row["updated_at"] for row in rows if row["updated_at"]), None)
        return InterestProfile(weights={row["topic"]: row["weight"] for row in rows}, updated_at=updated)
