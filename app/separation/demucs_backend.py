from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from app.core.config import stems_cache_dir
from app.core.jobs import ProcessingOptions

ProgressCallback = Callable[[int, str], None]


class DemucsSeparator:
    def isolate_vocals(
        self,
        source_path: Path,
        options: ProcessingOptions,
        progress: ProgressCallback | None = None,
    ) -> Path:
        cache_key = hashlib.sha256(str(source_path.resolve()).encode("utf-8")).hexdigest()[:16]
        output_root = stems_cache_dir() / cache_key
        expected = output_root / options.separation_model / source_path.stem / "vocals.wav"
        if expected.exists():
            if progress:
                progress(12, "Using cached vocal stem")
            return expected

        try:
            import demucs.separate
        except ImportError as exc:
            raise RuntimeError(
                "Demucs is not installed. Run: python -m pip install -e .[separation]"
            ) from exc

        args = [
            "-n",
            options.separation_model,
            "--two-stems",
            "vocals",
            "-o",
            str(output_root),
            str(source_path),
        ]
        if options.device in {"cpu", "cuda"}:
            args[0:0] = ["-d", options.device]

        if progress:
            progress(5, "Separating vocals with Demucs")
        demucs.separate.main(args)
        if not expected.exists():
            raise RuntimeError(f"Demucs did not create expected vocal stem: {expected}")
        return expected
