# Cross-platform onedir build. Models are downloaded into user data at runtime.
# Build with: pyinstaller --clean --noconfirm packaging/pyinstaller.spec

from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)


SPEC_DIR = Path(SPECPATH)
ROOT = SPEC_DIR.parent
ICON_DIR = SPEC_DIR / "icons"


def safe_collect_data(package):
    try:
        return collect_data_files(package)
    except Exception:
        return []


def safe_collect_dynamic(package):
    try:
        return collect_dynamic_libs(package)
    except Exception:
        return []


def safe_collect_submodules(package, **kwargs):
    try:
        return collect_submodules(package, **kwargs)
    except Exception:
        return []


def safe_copy_metadata(package):
    try:
        return copy_metadata(package, recursive=True)
    except Exception:
        return []


packages_with_metadata = [
    "av",
    "ctranslate2",
    "demucs",
    "faster-whisper",
    "huggingface-hub",
    "imageio-ffmpeg",
    "mutagen",
    "Pillow",
    "platformdirs",
    "sentencepiece",
    "syncedlyrics",
    "torch",
    "torchaudio",
    "transformers",
    "yt-dlp",
]

datas = [
    (str(ROOT / "app" / "models" / "manifest.json"), "app/models"),
    (str(ROOT / "app" / "assets" / "lyricrafter.svg"), "app/assets"),
    (str(ROOT / "app" / "assets" / "icons" / "*.svg"), "app/assets/icons"),
]
for package in ("demucs", "imageio_ffmpeg", "sentencepiece", "syncedlyrics", "transformers"):
    datas += safe_collect_data(package)
for package in packages_with_metadata:
    datas += safe_copy_metadata(package)

binaries = []
for package in ("ctranslate2", "sentencepiece"):
    binaries += safe_collect_dynamic(package)

hiddenimports = []
for package in (
    "av",
    "ctranslate2",
    "demucs",
    "dora",
    "faster_whisper",
    "julius",
    "openunmix",
    "sentencepiece",
    "syncedlyrics",
    "tokenizers",
    "yt_dlp",
):
    hiddenimports += safe_collect_submodules(package)
for package in (
    "transformers.generation",
    "transformers.models.auto",
    "transformers.models.m2m_100",
    "transformers.models.nllb",
):
    hiddenimports += safe_collect_submodules(package)

icon = (
    ICON_DIR / "lyricrafter.ico"
    if sys.platform == "win32"
    else ICON_DIR / "lyricrafter.icns"
    if sys.platform == "darwin"
    else ICON_DIR / "lyricrafter-256.png"
)

a = Analysis(
    [str(ROOT / "lyricrafter.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(SPEC_DIR / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "onnx",
        "onnxruntime",
        "pytest",
        "tensorflow",
        "tensorboard",
        "torchvision",
        "triton",
        "xformers",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Lyricrafter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=os.environ.get("PYINSTALLER_TARGET_ARCH") or None,
    codesign_identity=os.environ.get("APPLE_CODESIGN_IDENTITY") or None,
    entitlements_file=None,
    icon=str(icon),
    version=str(SPEC_DIR / "version_info.txt") if sys.platform == "win32" else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Lyricrafter",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Lyricrafter.app",
        icon=str(icon),
        bundle_identifier="com.lyricrafter.studio",
        info_plist={
            "CFBundleDisplayName": "Lyricrafter",
            "CFBundleName": "Lyricrafter",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "NSMicrophoneUsageDescription": "Lyricrafter processes audio files selected by the user.",
        },
    )
