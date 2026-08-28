from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def open_in_file_manager(path: Path) -> None:
    target = path.resolve()
    if sys.platform == "win32":
        os.startfile(target)
        return
    command = ["open", str(target)] if sys.platform == "darwin" else ["xdg-open", str(target)]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
