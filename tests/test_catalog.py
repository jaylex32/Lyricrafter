from app.models.catalog import ModelCatalog, ModelManager


def test_catalog_contains_required_whisper_models() -> None:
    catalog = ModelCatalog()
    ids = set(catalog.ids("whisper"))

    assert {"tiny", "base", "small", "medium", "large-v3", "turbo", "distil-large-v3"} <= ids


def test_catalog_has_one_recommendation_for_each_system_tier() -> None:
    recommendations = {
        model.id: model.recommended_for
        for model in ModelCatalog().list_models("whisper")
        if model.recommended
    }

    assert recommendations == {
        "small": "Small systems",
        "medium": "Medium systems",
        "large-v2": "Large / Default",
    }


def test_model_manager_maps_distil_repo(tmp_path) -> None:
    manager = ModelManager(tmp_path)

    assert manager.REPO_ALIASES["distil-large-v3"] == "Systran/faster-distil-whisper-large-v3"


def test_model_manager_detects_and_deletes_faster_whisper_model(tmp_path) -> None:
    manager = ModelManager(tmp_path)
    model_path = manager.installation_path("tiny", "faster-whisper")
    snapshot = model_path / "snapshots" / "test-revision"
    snapshot.mkdir(parents=True)
    (snapshot / "model.bin").write_bytes(b"test")

    assert manager.is_installed("tiny", "faster-whisper")
    assert manager.installed_faster_whisper_path("tiny") == snapshot
    assert manager.delete_model("tiny", "faster-whisper")
    assert not model_path.exists()
    assert not manager.is_installed("tiny", "faster-whisper")


def test_model_manager_detects_and_deletes_whisper_cpp_model(tmp_path) -> None:
    manager = ModelManager(tmp_path)
    model_path = manager.installation_path("tiny-q5_1", "whisper.cpp")
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"test")

    assert manager.is_installed("tiny-q5_1", "whisper.cpp")
    assert manager.delete_model("tiny-q5_1", "whisper.cpp")
    assert not model_path.exists()


def test_model_manager_resolves_legacy_hugging_face_cache(tmp_path, monkeypatch) -> None:
    manager = ModelManager(tmp_path / "managed")
    legacy_hub = tmp_path / "legacy" / "hub"
    snapshot = legacy_hub / "models--Systran--faster-whisper-large-v2" / "snapshots" / "revision"
    snapshot.mkdir(parents=True)
    (snapshot / "model.bin").write_bytes(b"model")
    monkeypatch.setenv("HF_HUB_CACHE", str(legacy_hub))

    assert manager.installed_faster_whisper_path("large-v2") is None
    assert manager.resolved_faster_whisper_path("large-v2") == snapshot
