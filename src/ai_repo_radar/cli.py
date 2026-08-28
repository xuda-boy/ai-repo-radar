from __future__ import annotations

import os
import threading
import webbrowser
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from ai_repo_radar.cache import CacheRepository, rebuild_cache
from ai_repo_radar.config import load_config, resolve_data_dir
from ai_repo_radar.paths import database_path
from ai_repo_radar.pipeline import FixtureEnhancer, run_pipeline
from ai_repo_radar.providers.github import GitHubClient
from ai_repo_radar.providers.minimax import MiniMaxClient
from ai_repo_radar.sample_data import is_fixture_report, load_sample_fixture
from ai_repo_radar.storage import JsonDataStore
from ai_repo_radar.sync import private_repository_root, sync_private_data_safely

app = typer.Typer(
    name="ai-repo-radar",
    help="Explainable, local-first AI GitHub repository radar.",
    no_args_is_help=True,
)
console = Console()


def _beijing_today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def _paths(data_dir: Path | None, database: Path | None) -> tuple[Path, Path]:
    return resolve_data_dir(data_dir), database_path(database)


def _report_table(report_date: date, recommendations: list[object]) -> Table:
    table = Table(title=f"AI Repo Radar · {report_date.isoformat()}")
    table.add_column("#", justify="right")
    table.add_column("Repository")
    table.add_column("Type")
    table.add_column("Score", justify="right")
    for index, recommendation in enumerate(recommendations, start=1):
        table.add_row(
            str(index),
            recommendation.repository.full_name,
            recommendation.kind.value,
            f"{recommendation.score.total:.3f}",
        )
    return table


@app.command()
def sample(
    data_dir: Path | None = typer.Option(None, help="Fixture JSON data root."),
    database: Path | None = typer.Option(None, help="Derived SQLite cache path."),
    fixture: Path | None = typer.Option(None, help="Optional fixed sample_input.json."),
) -> None:
    """Run the full deterministic fixture pipeline and rebuild the local cache."""
    data_root, db_path = _paths(data_dir, database)
    store = JsonDataStore(data_root)
    store.initialize()
    sample_fixture = load_sample_fixture(fixture)
    existing_report = next(
        (
            report
            for report in store.load_reports()
            if report.report_date == sample_fixture.report_date
        ),
        None,
    )
    store.append_snapshots(sample_fixture.historical_snapshots)
    result = run_pipeline(
        sample_fixture.repositories,
        store=store,
        config=load_config(),
        report_date=sample_fixture.report_date,
        readmes=sample_fixture.readmes,
        enhancer=FixtureEnhancer(sample_fixture.enhancements),
        generated_at=sample_fixture.generated_at,
        replace_report=bool(existing_report and is_fixture_report(existing_report)),
    )
    rebuild_cache(store, db_path)
    console.print(_report_table(result.report.report_date, result.report.recommendations))
    console.print(f"[green]Sample report:[/green] {result.report_path}")
    console.print(f"[green]SQLite cache:[/green] {db_path}")


@app.command()
def daily(
    data_dir: Path | None = typer.Option(None, help="Private append-only data root."),
    database: Path | None = typer.Option(None, help="Derived SQLite cache path."),
    config: Path | None = typer.Option(None, help="TOML configuration path."),
    report_date: str | None = typer.Option(None, "--date", help="Report date in YYYY-MM-DD."),
    replace_report: bool = typer.Option(False, help="Explicitly replace an existing normal report."),
    skip_existing: bool = typer.Option(
        False,
        help="Exit successfully before network calls when the target report already exists.",
    ),
    allow_unauthenticated: bool = typer.Option(
        False,
        help="Allow GitHub calls without a token; unsuitable for the default 300-candidate run.",
    ),
) -> None:
    """Collect live GitHub data, rank deterministically, enhance with MiniMax and persist."""
    radar = load_config(config)
    data_root, db_path = _paths(data_dir, database)
    try:
        target_date = date.fromisoformat(report_date) if report_date else _beijing_today()
    except ValueError as error:
        raise typer.BadParameter("--date must use YYYY-MM-DD") from error
    if replace_report and skip_existing:
        raise typer.BadParameter("--replace-report and --skip-existing cannot be combined")
    store = JsonDataStore(data_root)
    store.initialize()
    if skip_existing and store.report_path(target_date).exists():
        rebuild_cache(store, db_path)
        console.print(
            f"[cyan]Report already exists for {target_date}; skipped live collection.[/cyan]"
        )
        return
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token and not allow_unauthenticated:
        raise typer.BadParameter(
            "GITHUB_TOKEN is required for the default live run; use GitHub Actions or set it in the shell"
        )
    minimax_key = os.environ.get("MINIMAX_API_KEY")
    with GitHubClient(github_token, radar.github) as github:
        collection = github.collect(today=target_date, radar=radar)
    with MiniMaxClient(minimax_key, radar.minimax) as minimax:
        result = run_pipeline(
            collection.repositories,
            store=store,
            config=radar,
            report_date=target_date,
            readmes=collection.readmes,
            enhancer=minimax,
            generated_at=datetime.now(UTC),
            replace_report=replace_report,
        )
    rebuild_cache(store, db_path)
    console.print(_report_table(result.report.report_date, result.report.recommendations))
    if result.report.model_error_category:
        console.print(
            f"[yellow]Model degraded:[/yellow] {result.report.model_error_category} — "
            f"{result.report.degradation_message}"
        )
    console.print(f"[green]Report:[/green] {result.report_path}")


@app.command("rebuild-cache")
def rebuild_cache_command(
    data_dir: Path | None = typer.Option(None, help="Private append-only data root."),
    database: Path | None = typer.Option(None, help="Derived SQLite cache path."),
) -> None:
    """Delete and fully rebuild the derived SQLite cache from JSON facts."""
    data_root, db_path = _paths(data_dir, database)
    rebuilt = rebuild_cache(JsonDataStore(data_root), db_path)
    console.print(f"[green]Rebuilt:[/green] {rebuilt}")


@app.command()
def profile(
    database: Path | None = typer.Option(None, help="Derived SQLite cache path."),
) -> None:
    """Show the explainable topic weights currently effective in the cache."""
    repository = CacheRepository(database_path(database))
    interest = repository.interest_profile()
    table = Table(title="Topic interest profile")
    table.add_column("Topic")
    table.add_column("Weight", justify="right")
    for topic, weight in sorted(interest.weights.items(), key=lambda item: (-item[1], item[0])):
        table.add_row(topic, f"{weight:+.2f}")
    console.print(table)


@app.command()
def serve(
    data_dir: Path | None = typer.Option(None, help="Private append-only data root."),
    database: Path | None = typer.Option(None, help="Derived SQLite cache path."),
    config: Path | None = typer.Option(None, help="TOML configuration path."),
    port: int | None = typer.Option(
        None,
        min=1,
        max=65535,
        help="Override the dashboard port from configuration.",
    ),
    no_browser: bool = typer.Option(False, help="Do not open the default browser."),
) -> None:
    """Rebuild the cache, then serve the private dashboard on 127.0.0.1 only."""
    radar = load_config(config)
    data_root, db_path = _paths(data_dir, database)
    store = JsonDataStore(data_root)
    if private_repository_root(data_root):
        synced = sync_private_data_safely(store)
        if synced.success:
            console.print(
                f"[green]Private data synced:[/green] {synced.synced_events} feedback event(s)"
            )
        else:
            console.print(
                f"[yellow]Private sync pending:[/yellow] {synced.error_category} — "
                "local outbox was preserved"
            )
    rebuild_cache(store, db_path)
    from ai_repo_radar.web import create_app

    web_app = create_app(
        data_root=data_root,
        database_path=db_path,
        auto_sync_interval_seconds=radar.dashboard.auto_sync_interval_seconds,
    )
    dashboard_port = port if port is not None else radar.dashboard.port
    url = f"http://{radar.dashboard.host}:{dashboard_port}"
    if radar.dashboard.open_browser and not no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    console.print(f"[green]Dashboard:[/green] {url}")
    uvicorn.run(
        web_app,
        host=radar.dashboard.host,
        port=dashboard_port,
        log_level="info",
    )


@app.command("sync-data")
def sync_data(
    data_dir: Path | None = typer.Option(None, help="Private append-only data root."),
    database: Path | None = typer.Option(None, help="Derived SQLite cache path."),
) -> None:
    """Pull private facts, push pending feedback, then rebuild the SQLite cache."""
    data_root, db_path = _paths(data_dir, database)
    store = JsonDataStore(data_root)
    result = sync_private_data_safely(store)
    rebuild_cache(store, db_path)
    if not result.success:
        console.print(
            f"[yellow]Sync pending:[/yellow] {result.error_category} — local outbox was preserved"
        )
        raise typer.Exit(code=1)
    console.print(
        f"[green]Synced:[/green] {result.synced_events} feedback event(s) on {result.branch}"
    )


@app.command()
def doctor(
    data_dir: Path | None = typer.Option(None, help="Data root to inspect."),
    database: Path | None = typer.Option(None, help="Derived SQLite cache path."),
) -> None:
    """Check local prerequisites without printing any secret value."""
    data_root, db_path = _paths(data_dir, database)
    checks = {
        "data directory exists": data_root.exists(),
        "SQLite cache exists": db_path.exists(),
        "GITHUB_TOKEN configured": bool(os.environ.get("GITHUB_TOKEN")),
        "MINIMAX_API_KEY configured": bool(os.environ.get("MINIMAX_API_KEY")),
    }
    table = Table(title="AI Repo Radar doctor")
    table.add_column("Check")
    table.add_column("Result")
    for name, passed in checks.items():
        table.add_row(name, "OK" if passed else "NOT READY")
    console.print(table)
