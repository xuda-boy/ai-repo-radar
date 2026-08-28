from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ai_repo_radar.models import SyncStatus
from ai_repo_radar.storage import JsonDataStore

PRIVATE_REPOSITORY_SENTINEL = ".ai-repo-radar-private"


class GitSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class SyncResult:
    success: bool
    synced_events: int
    branch: str | None
    changed: bool = False
    error_category: str | None = None
    message: str | None = None


def _git(
    repository: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        operation = " ".join(arguments[:2])
        raise GitSyncError(f"git {operation} failed with exit code {result.returncode}")
    return result


def private_repository_root(data_root: Path) -> Path | None:
    resolved = data_root.expanduser().resolve()
    probe = _git(resolved, "rev-parse", "--show-toplevel", check=False)
    if probe.returncode != 0:
        return None
    root = Path(probe.stdout.strip()).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    if not (root / PRIVATE_REPOSITORY_SENTINEL).is_file():
        return None
    return root


def _ensure_clean(repository: Path) -> None:
    status = _git(repository, "status", "--porcelain", "--untracked-files=all").stdout
    if status.strip():
        raise GitSyncError(
            "private data repository has unrelated local changes; commit or stash them first"
        )


def _remote_branch_exists(repository: Path, branch: str) -> bool:
    result = _git(
        repository,
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/remotes/origin/{branch}",
        check=False,
    )
    return result.returncode == 0


def sync_private_data(store: JsonDataStore) -> SyncResult:
    repository = private_repository_root(store.root)
    if repository is None:
        raise GitSyncError(
            f"data root is not inside a repository marked with {PRIVATE_REPOSITORY_SENTINEL}"
        )
    _ensure_clean(repository)
    branch = _git(repository, "branch", "--show-current").stdout.strip()
    if not branch:
        raise GitSyncError("private data repository is in detached HEAD state")
    if _git(repository, "remote", "get-url", "origin", check=False).returncode != 0:
        raise GitSyncError("private data repository has no origin remote")

    _git(repository, "fetch", "--prune", "origin")
    if _remote_branch_exists(repository, branch):
        _git(repository, "rebase", f"origin/{branch}")

    pending = store.pending_feedback_events()
    staged_paths: list[str] = []
    for event in pending:
        path = store.stage_synced_feedback(event)
        relative = path.resolve().relative_to(repository).as_posix()
        _git(repository, "add", "--", relative)
        staged_paths.append(relative)

    has_staged = _git(repository, "diff", "--cached", "--quiet", check=False).returncode != 0
    if has_staged:
        _git(
            repository,
            "commit",
            "-m",
            f"data: sync {len(staged_paths)} feedback event(s)",
        )
    _git(repository, "push", "origin", f"HEAD:{branch}")

    for event in pending:
        store.remove_from_outbox(event.event_id)
    return SyncResult(success=True, synced_events=len(pending), branch=branch)


def pull_private_data(store: JsonDataStore) -> SyncResult:
    """Fast-forward local private facts without publishing local feedback."""
    repository = private_repository_root(store.root)
    if repository is None:
        raise GitSyncError(
            f"data root is not inside a repository marked with {PRIVATE_REPOSITORY_SENTINEL}"
        )
    _ensure_clean(repository)
    branch = _git(repository, "branch", "--show-current").stdout.strip()
    if not branch:
        raise GitSyncError("private data repository is in detached HEAD state")
    if _git(repository, "remote", "get-url", "origin", check=False).returncode != 0:
        raise GitSyncError("private data repository has no origin remote")

    before = _git(repository, "rev-parse", "HEAD").stdout.strip()
    _git(repository, "fetch", "--prune", "origin")
    if _remote_branch_exists(repository, branch):
        _git(repository, "rebase", f"origin/{branch}")
    after = _git(repository, "rev-parse", "HEAD").stdout.strip()
    return SyncResult(
        success=True,
        synced_events=0,
        branch=branch,
        changed=before != after,
    )


def pull_private_data_safely(store: JsonDataStore) -> SyncResult:
    try:
        return pull_private_data(store)
    except (GitSyncError, OSError) as error:
        category = "not_configured" if private_repository_root(store.root) is None else "git_error"
        return SyncResult(
            success=False,
            synced_events=0,
            branch=None,
            error_category=category,
            message=str(error),
        )


def sync_private_data_safely(store: JsonDataStore) -> SyncResult:
    try:
        return sync_private_data(store)
    except (GitSyncError, OSError) as error:
        for event in store.pending_feedback_events():
            store.update_outbox_status(event.event_id, SyncStatus.PENDING_RETRY)
        category = "not_configured" if private_repository_root(store.root) is None else "git_error"
        return SyncResult(
            success=False,
            synced_events=0,
            branch=None,
            error_category=category,
            message=str(error),
        )
