from __future__ import annotations

from app.core.cuda import add_cuda_dll_directories


def main() -> int:
    added = add_cuda_dll_directories()
    print("DLL search paths:")
    for path in added:
        print(f"  {path}")

    try:
        import torch
    except Exception as exc:
        print(f"torch import failed: {exc}")
        return 1

    print(f"torch: {torch.__version__}")
    print(f"torch cuda version: {torch.version.cuda}")
    print(f"torch cuda available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"gpu: {torch.cuda.get_device_name(0)}")

    try:
        import ctranslate2

        print(f"ctranslate2: {ctranslate2.__version__}")
        print(f"ctranslate2 CUDA devices: {ctranslate2.get_cuda_device_count()}")
    except Exception as exc:
        print(f"ctranslate2 CUDA check failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
