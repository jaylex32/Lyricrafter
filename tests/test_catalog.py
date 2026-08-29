from pathlib import Path

import os

import pytest

from app.models.catalog import (
    ModelCatalog,
    ModelManager,
    _latest_model_snapshot,
    _windows_runtime_snapshot,
)


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


def test_model_inventory_ignores_inaccessible_snapshot_file(tmp_path, monkeypatch) -> None:
    manager = ModelManager(tmp_path)
    snapshot = manager.installation_path("tiny", "faster-whisper") / "snapshots" / "revision"
    snapshot.mkdir(parents=True)
    blocked = snapshot / "config.json"
    model = snapshot / "model.bin"
    blocked.write_text("{}", encoding="utf-8")
    model.write_bytes(b"model")
    original_is_file = Path.is_file

    def guarded_is_file(path: Path) -> bool:
        if path == blocked:
            raise OSError(448, "untrusted mount point")
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", guarded_is_file)

    assert manager.is_installed("tiny", "faster-whisper")


def test_snapshot_resolution_ignores_untrusted_mount_error(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    snapshot = repo / "snapshots" / "revision"
    snapshot.mkdir(parents=True)
    model = snapshot / "model.bin"
    model.write_bytes(b"model")
    original_is_file = Path.is_file

    def blocked_model(path: Path) -> bool:
        if path == model:
            raise OSError(448, "untrusted mount point")
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", blocked_model)

    assert _latest_model_snapshot(repo) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows runtime materialization")
def test_windows_runtime_snapshot_replaces_model_symlinks_with_regular_files(tmp_path) -> None:
    repo = tmp_path / "repo"
    blobs = repo / "blobs"
    snapshot = repo / "snapshots" / "revision"
    blobs.mkdir(parents=True)
    snapshot.mkdir(parents=True)
    for name, content in (("config.json", b"{}"), ("model.bin", b"model")):
        blob = blobs / f"{name}.blob"
        blob.write_bytes(content)
        (snapshot / name).symlink_to(Path("..") / ".." / "blobs" / blob.name)

    runtime = _windows_runtime_snapshot(snapshot)

    assert runtime != snapshot
    assert (runtime / "config.json").read_bytes() == b"{}"
    assert (runtime / "model.bin").read_bytes() == b"model"
    assert not (runtime / "config.json").is_symlink()
    assert not (runtime / "model.bin").is_symlink()


@pytest.mark.skipif(os.name != "nt", reason="Windows runtime materialization")
def test_windows_runtime_snapshot_supports_translation_model_files(tmp_path) -> None:
    repo = tmp_path / "repo"
    blobs = repo / "blobs"
    snapshot = repo / "snapshots" / "revision"
    blobs.mkdir(parents=True)
    snapshot.mkdir(parents=True)
    model_files = {
        "config.json": b"{}",
        "sentencepiece.bpe.model": b"sentencepiece",
        "tokenizer.json": b"{}",
        "pytorch_model.bin": b"weights",
    }
    for name, content in model_files.items():
        blob = blobs / f"{name}.blob"
        blob.write_bytes(content)
        (snapshot / name).symlink_to(Path("..") / ".." / "blobs" / blob.name)

    runtime = _windows_runtime_snapshot(snapshot)

    for name, content in model_files.items():
        assert (runtime / name).read_bytes() == content
        assert not (runtime / name).is_symlink()


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


def test_model_download_retries_transient_failure(tmp_path, monkeypatch) -> None:
    manager = ModelManager(tmp_path)
    attempts = 0
    messages: list[str] = []

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("temporary DNS failure")
        return tmp_path / "downloaded"

    monkeypatch.setattr("app.models.catalog.time.sleep", lambda _seconds: None)
    result = manager._download_with_retries(
        "tiny",
        lambda _percent, message: messages.append(message),
        operation,
    )

    assert result == tmp_path / "downloaded"
    assert attempts == 3
    assert messages == [
        "tiny: network retry 2/3 in 2s",
        "tiny: network retry 3/3 in 4s",
    ]
