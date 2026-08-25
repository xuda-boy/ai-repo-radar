from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from ai_repo_radar.models import (
    DailyReport,
    FeedbackEvent,
    InterestProfile,
    ReportStatus,
    Repository,
    RepositorySnapshot,
    SyncStatus,
)


class StorageError(RuntimeError):
    pass


class ReportAlreadyExistsError(StorageError):
    pass


class DataIntegrityError(StorageError):
    pass


def _jsonable(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _dump(value: BaseModel | dict[str, Any]) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


class JsonDataStore:
    """Append-oriented private data layout; SQLite is deliberately not authoritative."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.reports_dir = self.root / "reports"
        self.snapshots_dir = self.root / "snapshots"
        self.feedback_dir = self.root / "feedback" / "events"
        self.outbox_dir = self.root / "outbox"
        self.profile_path = self.root / "profile" / "interest.json"
        self.metadata_path = self.root / "metadata" / "repositories.json"

    def initialize(self) -> None:
        for directory in (
            self.reports_dir,
            self.snapshots_dir,
            self.feedback_dir,
            self.outbox_dir,
            self.profile_path.parent,
            self.metadata_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _dated_path(directory: Path, value: date, suffix: str) -> Path:
        return directory / f"{value:%Y}" / f"{value:%m}" / f"{value:%d}{suffix}"

    def report_path(self, report_date: date) -> Path:
        return self._dated_path(self.reports_dir, report_date, ".json")

    def snapshot_path(self, observed_on: date) -> Path:
        return self._dated_path(self.snapshots_dir, observed_on, ".jsonl")

    def write_report(self, report: DailyReport, *, replace: bool = False) -> Path:
        path = self.report_path(report.report_date)
        if path.exists():
            existing = DailyReport.model_validate_json(path.read_text(encoding="utf-8"))
            if existing == report:
                return path
            if existing.status == ReportStatus.NORMAL and report.status == ReportStatus.DEGRADED:
                raise DataIntegrityError("a degraded report cannot replace an existing normal report")
            if existing.status == ReportStatus.NORMAL and not replace:
                raise ReportAlreadyExistsError(
                    f"normal report already exists for {report.report_date}; use explicit replace"
                )
        _atomic_write(path, _dump(report))
        return path

    def load_reports(self) -> list[DailyReport]:
        if not self.reports_dir.exists():
            return []
        reports = [
            DailyReport.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self.reports_dir.rglob("*.json")
        ]
        return sorted(reports, key=lambda report: report.report_date)

    def append_snapshots(self, snapshots: Iterable[RepositorySnapshot]) -> list[Path]:
        grouped: dict[date, list[RepositorySnapshot]] = {}
        for snapshot in snapshots:
            grouped.setdefault(snapshot.observed_at.date(), []).append(snapshot)

        written: list[Path] = []
        for observed_on, items in grouped.items():
            path = self.snapshot_path(observed_on)
            path.parent.mkdir(parents=True, exist_ok=True)
            existing_keys: set[tuple[str, str]] = set()
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    raw = json.loads(line)
                    existing_keys.add((raw["repo_full_name"], raw["observed_at"]))
            new_lines = []
            for snapshot in sorted(items, key=lambda item: item.repo_full_name):
                payload = snapshot.model_dump(mode="json")
                key = (snapshot.repo_full_name, payload["observed_at"])
                if key in existing_keys:
                    continue
                new_lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            if new_lines:
                with path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write("\n".join(new_lines) + "\n")
            written.append(path)
        return written

    def load_snapshots(self) -> list[RepositorySnapshot]:
        if not self.snapshots_dir.exists():
            return []
        snapshots: list[RepositorySnapshot] = []
        for path in sorted(self.snapshots_dir.rglob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    snapshots.append(RepositorySnapshot.model_validate_json(line))
        return sorted(snapshots, key=lambda item: (item.observed_at, item.repo_full_name))

    def write_repository_metadata(self, repositories: Iterable[Repository]) -> Path:
        payload = {
            repository.full_name: repository.model_dump(mode="json")
            for repository in sorted(repositories, key=lambda item: item.full_name)
        }
        _atomic_write(self.metadata_path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return self.metadata_path

    def load_repository_metadata(self) -> dict[str, Repository]:
        if not self.metadata_path.exists():
            return {}
        raw = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        return {name: Repository.model_validate(value) for name, value in raw.items()}

    @staticmethod
    def _event_filename(event_id: UUID) -> str:
        return f"{event_id}.json"

    def write_feedback_event(self, event: FeedbackEvent, *, to_outbox: bool = True) -> Path:
        directory = self.outbox_dir if to_outbox else self.feedback_dir
        path = directory / self._event_filename(event.event_id)
        if path.exists():
            existing = FeedbackEvent.model_validate_json(path.read_text(encoding="utf-8"))
            if existing != event:
                raise DataIntegrityError(f"feedback event {event.event_id} has conflicting content")
            return path
        _atomic_write(path, _dump(event))
        return path

    def pending_feedback_events(self) -> list[FeedbackEvent]:
        if not self.outbox_dir.exists():
            return []
        return sorted(
            [
                FeedbackEvent.model_validate_json(path.read_text(encoding="utf-8"))
                for path in self.outbox_dir.glob("*.json")
            ],
            key=lambda event: (event.created_at, str(event.event_id)),
        )

    def update_outbox_status(self, event_id: UUID, status: SyncStatus) -> FeedbackEvent:
        path = self.outbox_dir / self._event_filename(event_id)
        if not path.exists():
            raise FileNotFoundError(f"outbox event does not exist: {event_id}")
        event = FeedbackEvent.model_validate_json(path.read_text(encoding="utf-8"))
        updated = event.model_copy(update={"sync_status": status})
        _atomic_write(path, _dump(updated))
        return updated

    def load_feedback_events(self, *, include_outbox: bool = True) -> list[FeedbackEvent]:
        by_id: dict[UUID, FeedbackEvent] = {}
        if self.feedback_dir.exists():
            for path in self.feedback_dir.glob("*.json"):
                event = FeedbackEvent.model_validate_json(path.read_text(encoding="utf-8"))
                by_id[event.event_id] = event
        if include_outbox and self.outbox_dir.exists():
            for path in self.outbox_dir.glob("*.json"):
                event = FeedbackEvent.model_validate_json(path.read_text(encoding="utf-8"))
                by_id[event.event_id] = event
        return sorted(by_id.values(), key=lambda event: (event.created_at, str(event.event_id)))

    def stage_synced_feedback(self, event: FeedbackEvent) -> Path:
        synced = event.model_copy(update={"sync_status": SyncStatus.SYNCED})
        return self.write_feedback_event(synced, to_outbox=False)

    def remove_from_outbox(self, event_id: UUID) -> None:
        path = self.outbox_dir / self._event_filename(event_id)
        if path.exists():
            path.unlink()

    def save_interest_profile(self, profile: InterestProfile) -> Path:
        _atomic_write(self.profile_path, _dump(profile))
        return self.profile_path

    def load_interest_profile(self) -> InterestProfile:
        if not self.profile_path.exists():
            return InterestProfile()
        return InterestProfile.model_validate_json(self.profile_path.read_text(encoding="utf-8"))

    def all_json_files(self) -> list[Path]:
        paths = list(self.root.rglob("*.json")) + list(self.root.rglob("*.jsonl"))
        return sorted(set(paths))

    def latest_observation(self) -> datetime | None:
        snapshots = self.load_snapshots()
        return max((snapshot.observed_at for snapshot in snapshots), default=None)
