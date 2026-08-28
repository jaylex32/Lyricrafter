from __future__ import annotations

from pathlib import Path


def app_asset_path(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / name


def app_icon_path() -> Path:
    return app_asset_path("lyricrafter.svg")
