from __future__ import annotations

import argparse
from pathlib import Path
import os
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-root", type=Path, default=ROOT / "dist-release")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "release" / "windows-installer")
    args = parser.parse_args()

    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    compiler = next((path for path in candidates if path.is_file()), None)
    if compiler is None:
        raise FileNotFoundError("Inno Setup 6 was not found. Install JRSoftware.InnoSetup with winget.")
    app_dir = args.dist_root.resolve() / "Lyricrafter"
    executable = app_dir / "Lyricrafter.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"Packaged application was not found: {executable}")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = ROOT / "packaging" / "windows-installer.iss"
    subprocess.run(
        [
            str(compiler),
            f"/DDistDir={app_dir}",
            f"/DInstallerOutputDir={output_dir}",
            str(source),
        ],
        cwd=ROOT,
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
