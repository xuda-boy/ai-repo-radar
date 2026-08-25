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
