from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile

from app.core.nvidia_runtime import NvidiaPackage, NvidiaRuntimeManager


def _wheel_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return output.getvalue()


def test_runtime_status_requires_all_dlls(tmp_path: Path) -> None:
    manager = NvidiaRuntimeManager(root=tmp_path, packages=())
    manager.bin_dir.mkdir(parents=True)

    assert not manager.installed

    for name in ("cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll"):
        (manager.bin_dir / name).write_bytes(b"dll")

    assert manager.installed


def test_runtime_install_downloads_verifies_and_extracts(tmp_path: Path, monkeypatch) -> None:
    wheel = _wheel_bytes(
        {
            "nvidia/runtime/bin/cudart64_12.dll": b"runtime",
            "nvidia/runtime/bin/cublas64_12.dll": b"cublas",
            "nvidia/runtime/bin/cublasLt64_12.dll": b"cublas-lt",
            "nvidia/runtime/bin/cudnn64_9.dll": b"cudnn",
            "nvidia/runtime/include/ignored.h": b"header",
        }
    )
    package = NvidiaPackage(
        name="test-runtime",
        version="1.0",
        filename="test_runtime-1.0-py3-none-win_amd64.whl",
        sha256=hashlib.sha256(wheel).hexdigest(),
        size=len(wheel),
    )
    metadata = json.dumps(
        {
            "urls": [
                {
                    "filename": package.filename,
                    "url": "https://example.invalid/runtime.whl",
                    "digests": {"sha256": package.sha256},
                }
            ]
        }
    ).encode()

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def fake_urlopen(request, timeout=0):
        url = request.full_url
        return Response(metadata if "pypi.org" in url else wheel)

    monkeypatch.setattr("app.core.nvidia_runtime.sys.platform", "win32")
    monkeypatch.setattr("app.core.nvidia_runtime.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("app.core.nvidia_runtime.add_cuda_dll_directories", lambda: [])
    manager = NvidiaRuntimeManager(root=tmp_path / "runtime", packages=(package,))
    updates: list[int] = []

    installed = manager.install(lambda percent, _message: updates.append(percent))

    assert installed == manager.root
    assert manager.installed
    assert not (manager.bin_dir / "ignored.h").exists()
    assert updates[-1] == 100
    assert manager.uninstall()
    assert not manager.root.exists()
