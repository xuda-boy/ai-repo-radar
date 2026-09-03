import tomllib
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


def test_daily_workflow_uses_the_tested_concurrent_publish_command() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "radar-daily.yml").read_text(
        encoding="utf-8"
    )

    assert "ai-repo-radar publish-facts" in workflow
    assert '--repository "${{ github.workspace }}/private-data"' in workflow
    assert '--data-directory "${{ inputs.data_directory }}"' in workflow


def test_public_version_is_consistent_across_runtime_surfaces() -> None:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]

    assert version == "0.2.3"
    assert f'__version__ = "{version}"' in (
        REPOSITORY_ROOT / "src" / "ai_repo_radar" / "__init__.py"
    ).read_text(encoding="utf-8")
    assert f"LOCAL MODE · v{version}" in (
        REPOSITORY_ROOT / "src" / "ai_repo_radar" / "templates" / "base.html"
    ).read_text(encoding="utf-8")
