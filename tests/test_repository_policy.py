from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_agents_policy_keeps_commit_and_test_requirements() -> None:
    policy = (REPOSITORY_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    manifest = (REPOSITORY_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "每次改动后必须创建对应的 Git commit" in policy
    assert "每次改动后必须编写或更新测试" in policy
    assert "uv run pytest --cov=ai_repo_radar" in policy
    assert "uv run python scripts/privacy_audit.py" in policy
    assert "git diff --check" in policy
    assert "include AGENTS.md" in manifest
