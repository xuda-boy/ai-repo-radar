from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "privacy_audit.py"
    spec = importlib.util.spec_from_file_location("privacy_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_privacy_audit_detects_tokens_and_private_fact_paths(tmp_path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    secret = tmp_path / "unsafe.txt"
    token = "abcdefghijklmnop" + "qrstuvwxyz123456"
    secret.write_text(f"Authorization: Bearer {token}", encoding="utf-8")
    report = tmp_path / "reports" / "2026.json"
    report.parent.mkdir()
    report.write_text("{}", encoding="utf-8")

    findings = module.audit([secret, report])

    assert any("Authorization bearer" in finding for finding in findings)
    assert any("private data path" in finding for finding in findings)


def test_privacy_audit_allows_public_fixture(tmp_path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    fixture = tmp_path / "examples" / "fixtures" / "sample.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text('{"fixture": true}', encoding="utf-8")

    assert module.audit([fixture]) == []


def test_privacy_audit_allows_public_feedback_route_artifacts(tmp_path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    report = tmp_path / "docs" / "ui-v4" / "routes" / "feedback" / "UI_QA_REPORT.md"
    report.parent.mkdir(parents=True)
    report.write_text("public sample UI audit", encoding="utf-8")

    assert module.audit([report]) == []
