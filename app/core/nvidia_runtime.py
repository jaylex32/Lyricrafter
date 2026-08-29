from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Callable
import urllib.request
import zipfile

from app.core.cuda import add_cuda_dll_directories, nvidia_runtime_bin_dir


ProgressCallback = Callable[[int, str], None]


@dataclass(frozen=True)
class NvidiaPackage:
    name: str
    version: str
    filename: str
    sha256: str
    size: int


NVIDIA_PACKAGES = (
    NvidiaPackage(
        name="nvidia-cuda-runtime-cu12",
        version="12.8.90",
        filename="nvidia_cuda_runtime_cu12-12.8.90-py3-none-win_amd64.whl",
        sha256="c0c6027f01505bfed6c3b21ec546f69c687689aad5f1a377554bc6ca4aa993a8",
        size=944_318,
    ),
    NvidiaPackage(
        name="nvidia-cublas-cu12",
        version="12.8.4.1",
        filename="nvidia_cublas_cu12-12.8.4.1-py3-none-win_amd64.whl",
        sha256="47e9b82132fa8d2b4944e708049229601448aaad7e6f296f630f2d1a32de35af",
        size=567_544_208,
    ),
    NvidiaPackage(
        name="nvidia-cudnn-cu12",
        version="9.10.2.21",
        filename="nvidia_cudnn_cu12-9.10.2.21-py3-none-win_amd64.whl",
        sha256="c6288de7d63e6cf62988f0923f96dc339cea362decb1bf5b3141883392a7d65e",
        size=692_992_268,
    ),
)

REQUIRED_DLLS = ("cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")


class NvidiaRuntimeManager:
    def __init__(
        self,
        root: Path | None = None,
        packages: tuple[NvidiaPackage, ...] = NVIDIA_PACKAGES,
    ) -> None:
        self.root = (root or nvidia_runtime_bin_dir().parent).resolve()
        self.bin_dir = self.root / "bin"
        self.packages = packages

    @property
    def supported(self) -> bool:
        return sys.platform == "win32"

    @property
    def installed(self) -> bool:
        return all((self.bin_dir / name).is_file() for name in REQUIRED_DLLS)

    def status_text(self) -> str:
        if not self.supported:
            return "Optional NVIDIA runtime is available on Windows x64."
        if self.installed:
            return "NVIDIA Whisper acceleration is installed."
        return "CPU ready. Install NVIDIA support only on compatible systems."

    def install(self, progress: ProgressCallback | None = None) -> Path:
        if not self.supported:
            raise RuntimeError("The optional NVIDIA runtime is currently available on Windows x64 only.")
        total_bytes = sum(package.size for package in self.packages)
        downloaded_bytes = 0
        self.root.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="lyricrafter-nvidia-", dir=self.root.parent) as temp_name:
            temp_dir = Path(temp_name)
            staging = temp_dir / "runtime"
            staging_bin = staging / "bin"
            staging_bin.mkdir(parents=True)
            package_records: list[dict[str, object]] = []

            for index, package in enumerate(self.packages, start=1):
                if progress:
                    progress(
                        int(downloaded_bytes * 90 / max(total_bytes, 1)),
                        f"Downloading NVIDIA component {index}/{len(self.packages)}",
                    )
                url = self._package_url(package)
                wheel_path = temp_dir / package.filename
                self._download(
                    url,
                    wheel_path,
                    package,
                    downloaded_bytes,
                    total_bytes,
                    progress,
                )
                self._verify(wheel_path, package.sha256)
                self._extract_dlls(wheel_path, staging_bin)
                downloaded_bytes += package.size
                package_records.append(
                    {"name": package.name, "version": package.version, "sha256": package.sha256}
                )

            missing = [name for name in REQUIRED_DLLS if not (staging_bin / name).is_file()]
            if missing:
                raise RuntimeError(f"NVIDIA package is incomplete; missing: {', '.join(missing)}")
            (staging / "runtime.json").write_text(
                json.dumps({"schema": 1, "packages": package_records}, indent=2),
                encoding="utf-8",
            )
            if progress:
                progress(96, "Installing NVIDIA runtime")
            if self.root.exists():
                shutil.rmtree(self.root)
            shutil.move(str(staging), str(self.root))

        add_cuda_dll_directories()
        if progress:
            progress(100, "NVIDIA Whisper acceleration installed")
        return self.root

    def uninstall(self) -> bool:
        if not self.root.exists():
            return False
        shutil.rmtree(self.root)
        return True

    @staticmethod
    def _package_url(package: NvidiaPackage) -> str:
        endpoint = f"https://pypi.org/pypi/{package.name}/{package.version}/json"
        request = urllib.request.Request(endpoint, headers={"User-Agent": "Lyricrafter/0.1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        for item in payload.get("urls", []):
            if item.get("filename") != package.filename:
                continue
            remote_hash = str(item.get("digests", {}).get("sha256", ""))
            if remote_hash.lower() != package.sha256.lower():
                raise RuntimeError(f"PyPI checksum changed for {package.name}; download stopped.")
            return str(item["url"])
        raise RuntimeError(f"The Windows package for {package.name} was not found on PyPI.")

    @staticmethod
    def _download(
        url: str,
        destination: Path,
        package: NvidiaPackage,
        completed_bytes: int,
        total_bytes: int,
        progress: ProgressCallback | None,
    ) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": "Lyricrafter/0.1"})
        current = 0
        with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                current += len(chunk)
                if progress:
                    percent = int((completed_bytes + current) * 90 / max(total_bytes, 1))
                    progress(
                        min(90, percent),
                        f"Downloading {package.name} ({current / 1024**2:.0f} MB)",
                    )

    @staticmethod
    def _verify(path: Path, expected_sha256: str) -> None:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != expected_sha256.lower():
            raise RuntimeError(f"Checksum validation failed for {path.name}.")

    @staticmethod
    def _extract_dlls(wheel_path: Path, destination: Path) -> None:
        extracted = 0
        with zipfile.ZipFile(wheel_path) as archive:
            for member in archive.infolist():
                if member.is_dir() or not member.filename.lower().endswith(".dll"):
                    continue
                target = destination / Path(member.filename).name
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                extracted += 1
        if not extracted:
            raise RuntimeError(f"No runtime libraries were found in {wheel_path.name}.")
