from __future__ import annotations

from pathlib import Path

from app.export.lrc import LyricLine, render_lrc, render_txt


SUPPORTED_EMBED_EXTENSIONS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".mp4"}


def can_embed_lyrics(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EMBED_EXTENSIONS


def embed_lyrics(path: Path, lines: list[LyricLine]) -> bool:
    suffix = path.suffix.lower()
    plain = render_txt(lines).strip()
    synced = render_lrc(lines).strip()
    if not plain and not synced:
        return False

    if suffix == ".mp3":
        return _embed_mp3(path, plain, synced)
    if suffix in {".flac", ".ogg", ".opus"}:
        return _embed_vorbis_comments(path, plain, synced)
    if suffix in {".m4a", ".mp4"}:
        return _embed_mp4(path, plain, synced)
    return False


def _embed_mp3(path: Path, plain: str, synced: str) -> bool:
    from mutagen.id3 import ID3, ID3NoHeaderError, TXXX, USLT

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    tags.delall("USLT")
    tags.delall("TXXX:LYRICRAFTER_LRC")
    tags.add(USLT(encoding=3, lang="eng", desc="Lyricrafter", text=plain))
    if synced:
        tags.add(TXXX(encoding=3, desc="LYRICRAFTER_LRC", text=[synced]))
    tags.save(path)
    return True


def _embed_vorbis_comments(path: Path, plain: str, synced: str) -> bool:
    from mutagen import File

    audio = File(path)
    if audio is None:
        return False
    audio["LYRICS"] = plain
    audio["UNSYNCEDLYRICS"] = plain
    if synced:
        audio["LYRICRAFTER_LRC"] = synced
        audio["SYNCEDLYRICS"] = synced
    audio.save()
    return True


def _embed_mp4(path: Path, plain: str, synced: str) -> bool:
    from mutagen.mp4 import MP4

    audio = MP4(path)
    audio["\xa9lyr"] = [plain]
    if synced:
        audio["----:com.apple.iTunes:LYRICRAFTER_LRC"] = [synced.encode("utf-8")]
    audio.save()
    return True
