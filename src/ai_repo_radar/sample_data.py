from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from ai_repo_radar.models import Repository, RepositorySnapshot


@dataclass(frozen=True)
class SampleFixture:
    report_date: date
    generated_at: datetime
    repositories: list[Repository]
    readmes: dict[str, str]
    historical_snapshots: list[RepositorySnapshot]


def default_fixture_path() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "sample_input.json"


def load_sample_fixture(path: Path | None = None) -> SampleFixture:
    fixture_path = path or default_fixture_path()
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    if raw.get("fixture") is not True:
        raise ValueError("sample input must declare fixture=true")

    repositories: list[Repository] = []
    readmes: dict[str, str] = {}
    snapshots: list[RepositorySnapshot] = []
    for item in raw["repositories"]:
        repository_payload: dict[str, Any] = {
            key: value for key, value in item.items() if key not in {"readme", "star_history"}
        }
        repository = Repository.model_validate(repository_payload)
        repositories.append(repository)
        if item.get("readme"):
            readmes[repository.full_name] = item["readme"]
        for observed_on, stars in item.get("star_history", []):
            snapshots.append(
                RepositorySnapshot(
                    observed_at=datetime.combine(
                        date.fromisoformat(observed_on),
                        time(hour=0, minute=34),
                        tzinfo=UTC,
                    ),
                    repo_full_name=repository.full_name,
                    stars=stars,
                    pushed_at=repository.pushed_at,
                    latest_release_tag=repository.latest_release_tag,
                )
            )
    return SampleFixture(
        report_date=date.fromisoformat(raw["fixture_date"]),
        generated_at=datetime.fromisoformat(raw["generated_at"].replace("Z", "+00:00")),
        repositories=repositories,
        readmes=readmes,
        historical_snapshots=snapshots,
    )
