from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = {
    "GitHub classic token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "GitHub fine-grained token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "Authorization bearer": re.compile(r"Bearer\s+[A-Za-z0-9._-]{24,}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "assigned MiniMax key": re.compile(
        r"MINIMAX_API_KEY[ \t]*=[ \t]*[^\s#'\"]{12,}"
    ),
}
PRIVATE_PATH_PARTS = {"reports", "snapshots", "feedback", "outbox", "profile"}
ALLOWED_PRIVATE_FIXTURES = (Path("examples/fixtures"), Path("src/ai_repo_radar/fixtures"))


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [ROOT / raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw]


def audit(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        relative = path.relative_to(ROOT)
        allowed_fixture = any(
            relative.is_relative_to(directory) for directory in ALLOWED_PRIVATE_FIXTURES
        )
        if any(part in PRIVATE_PATH_PARTS for part in relative.parts) and not allowed_fixture:
            findings.append(f"private data path is tracked: {relative.as_posix()}")
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".sqlite3", ".db"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{label} pattern in {relative.as_posix()}")
    return findings


def main() -> int:
    findings = audit(tracked_files())
    if findings:
        print("Privacy audit failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Privacy audit passed: no tracked secret patterns or private fact paths found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
