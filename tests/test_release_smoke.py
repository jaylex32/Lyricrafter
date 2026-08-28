from app.release_smoke import run_package_smoke_test


def test_package_smoke_checks_source_environment(tmp_path, monkeypatch) -> None:
    report = tmp_path / "smoke.json"
    model_dir = tmp_path / "models"
    monkeypatch.setattr("app.release_smoke.default_model_dir", lambda: model_dir)

    result = run_package_smoke_test(report)

    assert result == 0
    assert report.exists()
    assert '"ok": true' in report.read_text(encoding="utf-8")
