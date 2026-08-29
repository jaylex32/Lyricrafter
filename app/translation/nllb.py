from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.core.cuda import add_cuda_dll_directories
from app.core.config import default_model_dir
from app.models.catalog import _expected_snapshot_bytes, _start_size_monitor, _windows_runtime_snapshot

ProgressCallback = Callable[[int, str], None]


class NllbTranslator:
    def __init__(
        self,
        model_id: str = "facebook/nllb-200-distilled-600M",
        model_dir: Path | None = None,
    ) -> None:
        self.model_id = model_id
        self.model_dir = model_dir or default_model_dir()
        self._tokenizer = None
        self._model = None
        self._device = "cpu"

    def translate_lines(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        progress: ProgressCallback | None = None,
        batch_size: int = 8,
    ) -> list[str]:
        clean_texts = [text.strip() for text in texts]
        if not clean_texts:
            return []
        if source_lang == target_lang:
            return clean_texts

        self._load(progress)
        tokenizer = self._tokenizer
        model = self._model
        if tokenizer is None or model is None:
            raise RuntimeError("Translator model failed to load.")

        tokenizer.src_lang = source_lang
        forced_bos_token_id = tokenizer.convert_tokens_to_ids(target_lang)
        translated: list[str] = []
        total = len(clean_texts)

        for start in range(0, total, batch_size):
            batch = clean_texts[start : start + batch_size]
            if progress:
                percent = 20 + int((start / total) * 75)
                progress(percent, f"Translating lines {start + 1}-{start + len(batch)}")
            inputs = tokenizer(batch, return_tensors="pt", padding=True, truncation=True, max_length=256)
            inputs = {key: value.to(self._device) for key, value in inputs.items()}
            outputs = model.generate(
                **inputs,
                forced_bos_token_id=forced_bos_token_id,
                max_new_tokens=96,
                num_beams=4,
            )
            translated.extend(tokenizer.batch_decode(outputs, skip_special_tokens=True))

        if progress:
            progress(100, "Translation complete")
        return translated

    def _load(self, progress: ProgressCallback | None = None) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        if progress:
            progress(0, f"Loading translation model: {self.model_id}")
        add_cuda_dll_directories()
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("Install translation dependencies: transformers sentencepiece") from exc

        model_path = self._download_model(progress)
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._tokenizer = AutoTokenizer.from_pretrained(model_path)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
        self._model.to(self._device)
        self._model.eval()
        if progress:
            progress(20, f"Translation model ready on {self._device}")

    def _download_model(self, progress: ProgressCallback | None = None) -> Path | str:
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            return self.model_id

        cache_dir = self.model_dir / "translation"
        cache_dir.mkdir(parents=True, exist_ok=True)
        expected_bytes = _expected_snapshot_bytes(self.model_id, cache_dir, ["*"])
        stop_monitor = None
        monitor = None
        if progress:
            import threading

            progress(1, f"Downloading translation model: {self.model_id}")
            stop_monitor = threading.Event()
            monitor = _start_size_monitor(
                cache_dir,
                expected_bytes,
                stop_monitor,
                lambda percent: progress(
                    min(19, max(1, int(percent * 0.19))),
                    f"Downloading translation model: {self.model_id} ({percent}%)",
                ),
            )
        try:
            snapshot = Path(
                snapshot_download(
                    repo_id=self.model_id,
                    cache_dir=str(cache_dir),
                    local_files_only=False,
                    allow_patterns=["*.json", "*.model", "*.safetensors", "*.bin", "sentencepiece.*", "tokenizer.*"],
                )
            )
            return _windows_runtime_snapshot(snapshot)
        finally:
            if stop_monitor is not None:
                stop_monitor.set()
            if monitor is not None:
                monitor.join(timeout=1)
