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
