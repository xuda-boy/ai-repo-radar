from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from ai_repo_radar.models import (
    DailyReport,
    Repository,
    RepositoryEnhancement,
    RepositorySnapshot,
)

LEGACY_FIXTURE_REPOSITORY_ALIASES = {
    "agentmap/runtime-viewer": "Arize-ai/phoenix",
    "latentops/prompt-check": "promptfoo/promptfoo",
    "modeldock/serve-lite": "ollama/ollama",
    "nova-labs/agent-forge": "langchain-ai/langgraph",
    "openmesh/rag-workbench": "run-llama/llama_index",
    "shieldstack/llm-firewall": "protectai/llm-guard",
    "signalcraft/eval-canvas": "confident-ai/deepeval",
    "tinyagents/tool-loop": "huggingface/smolagents",
    "traceyard/llm-observer": "langfuse/langfuse",
    "vectorwave/rapid-infer": "vllm-project/vllm",
}


@dataclass(frozen=True)
class SampleFixture:
    report_date: date
    generated_at: datetime
    repositories: list[Repository]
    readmes: dict[str, str]
    enhancements: dict[str, RepositoryEnhancement]
    historical_snapshots: list[RepositorySnapshot]


def default_fixture_path() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "sample_input.json"


def is_fixture_repository(repository: Repository) -> bool:
    return any(source.startswith("fixture-") for source in repository.discovery_sources)


def is_fixture_report(report: DailyReport) -> bool:
    return bool(report.recommendations) and all(
        is_fixture_repository(item.repository) for item in report.recommendations
    )


def canonical_fixture_repository_name(full_name: str) -> str:
    return LEGACY_FIXTURE_REPOSITORY_ALIASES.get(full_name, full_name)


def load_sample_fixture(path: Path | None = None) -> SampleFixture:
    fixture_path = path or default_fixture_path()
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    if raw.get("fixture") is not True:
        raise ValueError("sample input must declare fixture=true")

    repositories: list[Repository] = []
    readmes: dict[str, str] = {}
    enhancements: dict[str, RepositoryEnhancement] = {}
    snapshots: list[RepositorySnapshot] = []
    for item in raw["repositories"]:
        repository_payload: dict[str, Any] = {
            key: value
            for key, value in item.items()
            if key not in {"quick_start", "readme", "star_history", "summary_zh"}
        }
        repository = Repository.model_validate(repository_payload)
        expected_url = f"https://github.com/{repository.full_name}"
        if repository.html_url.rstrip("/") != expected_url:
            raise ValueError(
                f"sample repository URL must match full_name: {repository.full_name}"
            )
        repositories.append(repository)
        if item.get("readme"):
            readmes[repository.full_name] = item["readme"]
        if item.get("summary_zh") or item.get("quick_start"):
            enhancements[repository.full_name] = RepositoryEnhancement(
                full_name=repository.full_name,
                summary_zh=item["summary_zh"],
                quick_start=item["quick_start"],
            )
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
        enhancements=enhancements,
        historical_snapshots=snapshots,
    )
