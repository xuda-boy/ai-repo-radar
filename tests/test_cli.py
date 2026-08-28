from typer.testing import CliRunner

from ai_repo_radar.cli import app


def test_serve_accepts_port_override(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(_app, **kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("ai_repo_radar.cli.uvicorn.run", fake_run)

    result = CliRunner().invoke(
        app,
        [
            "serve",
            "--data-dir",
            str(tmp_path / "data"),
            "--database",
            str(tmp_path / "radar.sqlite3"),
            "--port",
            "8766",
            "--no-browser",
        ],
    )

    assert result.exit_code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8766


def test_sample_can_refresh_an_existing_fixture_report(tmp_path) -> None:
    args = [
        "sample",
        "--data-dir",
        str(tmp_path / "data"),
        "--database",
        str(tmp_path / "radar.sqlite3"),
    ]
    runner = CliRunner()

    first = runner.invoke(app, args)
    second = runner.invoke(app, args)

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "ReportAlreadyExistsError" not in second.output


def test_daily_can_skip_an_existing_report_without_credentials(tmp_path) -> None:
    data_dir = tmp_path / "data"
    database = tmp_path / "radar.sqlite3"
    runner = CliRunner()
    sample = runner.invoke(
        app,
        ["sample", "--data-dir", str(data_dir), "--database", str(database)],
    )

    result = runner.invoke(
        app,
        [
            "daily",
            "--data-dir",
            str(data_dir),
            "--database",
            str(database),
            "--date",
            "2026-08-25",
            "--skip-existing",
        ],
    )

    assert sample.exit_code == 0
    assert result.exit_code == 0
    assert "skipped live collection" in result.output
    assert "GITHUB_TOKEN" not in result.output
