from __future__ import annotations

from pathlib import Path
import argparse
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / "release"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-root", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    dist_root = args.dist_root.resolve()
    RELEASES.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        base = RELEASES / "Lyricrafter-Windows-x64"
        shutil.make_archive(str(base), "zip", dist_root, "Lyricrafter")
    elif sys.platform.startswith("linux"):
        base = RELEASES / "Lyricrafter-Linux-x64"
        shutil.make_archive(str(base), "gztar", dist_root, "Lyricrafter")
    else:
        architecture = "arm64" if __import__("platform").machine() == "arm64" else "x64"
        base = RELEASES / f"Lyricrafter-macOS-{architecture}"
        shutil.make_archive(str(base), "zip", dist_root, "Lyricrafter.app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
