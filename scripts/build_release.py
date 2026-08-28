from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run(*command: str) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    run(sys.executable, "scripts/generate_icons.py")
    run(sys.executable, "-m", "pytest", "-q")
    run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "packaging/pyinstaller.spec",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
