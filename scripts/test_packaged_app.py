from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def packaged_executable(dist_root: Path = ROOT / "dist") -> Path:
    if sys.platform == "win32":
        return dist_root / "Lyricrafter" / "Lyricrafter.exe"
    if sys.platform == "darwin":
        return dist_root / "Lyricrafter.app" / "Contents" / "MacOS" / "Lyricrafter"
    return dist_root / "Lyricrafter" / "Lyricrafter"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--model-download", action="store_true")
    parser.add_argument("--model-download-only", action="store_true")
    parser.add_argument("--skip-ui", action="store_true")
    parser.add_argument("--dist-root", type=Path, default=ROOT / "dist")
    args = parser.parse_args()

    executable = packaged_executable(args.dist_root.resolve())
    if not executable.exists():
        raise FileNotFoundError(f"Packaged executable was not found: {executable}")
    report = ROOT / "artifacts" / "package-smoke.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["LYRICRAFTER_SMOKE_REPORT"] = str(report)
    if args.network:
        environment["LYRICRAFTER_SMOKE_NETWORK"] = "1"
    if args.model_download or args.model_download_only:
        environment["LYRICRAFTER_SMOKE_MODEL_DOWNLOAD"] = "1"
    if args.model_download_only:
        environment["LYRICRAFTER_SMOKE_SKIP_MODEL_INFERENCE"] = "1"

    subprocess.run([str(executable), "--package-smoke-test"], env=environment, check=True, timeout=600)
    payload = json.loads(report.read_text(encoding="utf-8"))
    if not payload.get("ok") or not payload.get("frozen"):
        raise RuntimeError(json.dumps(payload, indent=2))

    if not args.skip_ui:
        ui_environment = environment.copy()
        ui_environment.setdefault("QT_QPA_PLATFORM", "offscreen")
        subprocess.run([str(executable), "--ui-smoke-test"], env=ui_environment, check=True, timeout=45)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
