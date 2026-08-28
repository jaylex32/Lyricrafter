from __future__ import annotations

import os
import sys
from pathlib import Path


def add_cuda_dll_directories() -> list[Path]:
    """Add common CUDA DLL locations for Windows before GPU libraries load."""
    if sys.platform != "win32":
        return []

    candidates: list[Path] = []
    try:
        import torch

        candidates.append(Path(torch.__file__).resolve().parent / "lib")
    except Exception:
        pass

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    candidates.extend(sorted((program_files / "NVIDIA GPU Computing Toolkit" / "CUDA").glob("v*\\bin")))

    added: list[Path] = []
    path_parts = os.environ.get("PATH", "").split(os.pathsep)
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            os.add_dll_directory(str(candidate))
        except (FileNotFoundError, OSError):
            continue
        if str(candidate) not in path_parts:
            os.environ["PATH"] = str(candidate) + os.pathsep + os.environ.get("PATH", "")
        added.append(candidate)
    return added
