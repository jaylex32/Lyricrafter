from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from app.core.config import runtime_dir


_DLL_HANDLES: list[object] = []
_DLL_PATHS: set[str] = set()


def nvidia_runtime_bin_dir() -> Path:
    return runtime_dir() / "nvidia-cu12" / "bin"


def _cuda_dll_candidates() -> list[Path]:
    candidates: list[Path] = [nvidia_runtime_bin_dir()]
    try:
        torch_spec = importlib.util.find_spec("torch")
        if torch_spec and torch_spec.origin:
            candidates.append(Path(torch_spec.origin).resolve().parent / "lib")
    except (ImportError, OSError, ValueError):
        pass

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    candidates.extend(sorted((program_files / "NVIDIA GPU Computing Toolkit" / "CUDA").glob("v*\\bin")))
    return candidates


def add_cuda_dll_directories() -> list[Path]:
    """Add common CUDA DLL locations for Windows before GPU libraries load."""
    if sys.platform != "win32":
        return []

    added: list[Path] = []
    path_parts = os.environ.get("PATH", "").split(os.pathsep)
    for candidate in _cuda_dll_candidates():
        if not candidate.exists():
            continue
        key = str(candidate.resolve()).casefold()
        if key in _DLL_PATHS:
            added.append(candidate)
            continue
        try:
            handle = os.add_dll_directory(str(candidate))
        except (FileNotFoundError, OSError):
            continue
        _DLL_HANDLES.append(handle)
        _DLL_PATHS.add(key)
        if str(candidate) not in path_parts:
            os.environ["PATH"] = str(candidate) + os.pathsep + os.environ.get("PATH", "")
        added.append(candidate)
    return added


def ctranslate2_cuda_available() -> bool:
    if sys.platform != "win32":
        try:
            import ctranslate2

            return ctranslate2.get_cuda_device_count() > 0
        except Exception:
            return False

    if not any(
        (candidate / "cublas64_12.dll").is_file()
        and (candidate / "cudnn64_9.dll").is_file()
        for candidate in _cuda_dll_candidates()
    ):
        return False
    add_cuda_dll_directories()
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False
