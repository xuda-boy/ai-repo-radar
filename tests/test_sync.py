from __future__ import annotations

import subprocess
from pathlib import Path

from ai_repo_radar.feedback import create_feedback_event
from ai_repo_radar.models import FeedbackAction, SyncStatus
from ai_repo_radar.storage import JsonDataStore
from ai_repo_radar.sync import (
    PRIVATE_REPOSITORY_SENTINEL,
    publish_private_facts,
    pull_private_data_safely,
    sync_private_data_safely,
)


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def _private_repository(tmp_path: Path) -> tuple[Path, Path, JsonDataStore]:
    repository = tmp_path / "private"
    remote = tmp_path / "remote.git"
    repository.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "Test User")
    _git(repository, "config", "user.email", "test@example.com")
    (repository / PRIVATE_REPOSITORY_SENTINEL).write_text("version=1\n", encoding="utf-8")
    (repository / ".gitignore").write_text("data/outbox/\n.cache/\n", encoding="utf-8")
    _git(repository, "add", PRIVATE_REPOSITORY_SENTINEL, ".gitignore")
    _git(repository, "commit", "-m", "initialize private data repository")
    _git(repository, "remote", "add", "origin", str(remote))
    _git(repository, "push", "-u", "origin", "main")
    store = JsonDataStore(repository / "data")
    store.initialize()
    return repository, remote, store


def test_private_git_sync_pushes_uuid_event_and_clears_outbox(
    tmp_path,
    sample_fixture,
) -> None:
    repository, remote, store = _private_repository(tmp_path)
    event = create_feedback_event(
        repo_full_name="nova-labs/agent-forge",
        action=FeedbackAction.MORE_LIKE,
        topics=["agents", "llm"],
        created_at=sample_fixture.generated_at,
        report_date=sample_fixture.report_date,
    )
    store.write_feedback_event(event)

    result = sync_private_data_safely(store)

    assert result.success is True
    assert result.synced_events == 1
    assert store.pending_feedback_events() == []
    synced = store.load_feedback_events(include_outbox=False)[0]
    assert synced.sync_status == SyncStatus.SYNCED
    assert not subprocess.run(
        ["git", "--git-dir", str(remote), "show", f"main:data/feedback/events/{event.event_id}.json"],
        check=False,
        capture_output=True,
    ).returncode
    assert not _status(repository)


def _status(repository: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_unmarked_repository_never_attempts_a_push(tmp_path, sample_fixture) -> None:
    repository = tmp_path / "public-like"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    store = JsonDataStore(repository / ".local" / "data")
    store.initialize()
    event = create_feedback_event(
        repo_full_name="nova-labs/agent-forge",
        action=FeedbackAction.KNOWN,
        topics=["llm"],
        created_at=sample_fixture.generated_at,
    )
    store.write_feedback_event(event)

    result = sync_private_data_safely(store)

    assert result.success is False
    assert result.error_category == "not_configured"
    assert store.pending_feedback_events()[0].sync_status == SyncStatus.PENDING_RETRY


def test_pull_private_data_updates_facts_without_publishing_outbox(
    tmp_path,
    sample_fixture,
) -> None:
    repository, remote, store = _private_repository(tmp_path)
    event = create_feedback_event(
        repo_full_name="nova-labs/agent-forge",
        action=FeedbackAction.KNOWN,
        topics=["llm"],
        created_at=sample_fixture.generated_at,
    )
    store.write_feedback_event(event)

    publisher = tmp_path / "publisher"
    subprocess.run(
        ["git", "clone", "--branch", "main", str(remote), str(publisher)],
        check=True,
        capture_output=True,
    )
    _git(publisher, "config", "user.name", "Test Publisher")
    _git(publisher, "config", "user.email", "publisher@example.com")
    marker = publisher / "data" / "remote-marker.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("new private fact\n", encoding="utf-8")
    _git(publisher, "add", "data/remote-marker.txt")
    _git(publisher, "commit", "-m", "data: publish remote fact")
    _git(publisher, "push", "origin", "main")

    result = pull_private_data_safely(store)

    assert result.success is True
    assert result.changed is True
    assert (repository / "data" / "remote-marker.txt").read_text(encoding="utf-8") == (
        "new private fact\n"
    )
    assert store.pending_feedback_events() == [event]
    assert not _status(repository)


def test_publish_private_facts_rebases_after_a_concurrent_remote_push(tmp_path) -> None:
    repository, remote, _store = _private_repository(tmp_path)
    publisher = tmp_path / "publisher"
    subprocess.run(
        ["git", "clone", "--branch", "main", str(remote), str(publisher)],
        check=True,
        capture_output=True,
    )
    _git(publisher, "config", "user.name", "Concurrent Publisher")
    _git(publisher, "config", "user.email", "publisher@example.com")

    report = repository / "data" / "reports" / "2026" / "09" / "03.json"
    report.parent.mkdir(parents=True)
    report.write_text('{"report_date":"2026-09-03"}\n', encoding="utf-8")

    marker = publisher / "README.md"
    marker.write_text("concurrent workflow change\n", encoding="utf-8")
    _git(publisher, "add", "README.md")
    _git(publisher, "commit", "-m", "docs: concurrent workflow change")
    _git(publisher, "push", "origin", "main")

    changed = publish_private_facts(
        repository,
        data_directory="data",
        message="data: daily radar 2026-09-03",
    )

    assert changed is True
    assert not _status(repository)
    assert not subprocess.run(
        ["git", "--git-dir", str(remote), "show", "main:data/reports/2026/09/03.json"],
        check=False,
        capture_output=True,
    ).returncode
    assert not subprocess.run(
        ["git", "--git-dir", str(remote), "show", "main:README.md"],
        check=False,
        capture_output=True,
    ).returncode
