from __future__ import annotations

import json
import urllib.parse
import urllib.request

from app.lyrics.align import confidence_for_candidate
from app.lyrics.parsing import parse_lrc_text
from app.lyrics.types import LyricCandidate, LyricSearchQuery, ProviderLyrics
from app.metadata.service import USER_AGENT

LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"


class LRCLIBProvider:
    name = "LRCLIB"

    def search(self, query: LyricSearchQuery) -> list[LyricCandidate]:
        params = {
            "track_name": query.title,
            "artist_name": query.artist,
            "album_name": query.album,
        }
        url = f"{LRCLIB_SEARCH_URL}?{urllib.parse.urlencode({k: v for k, v in params.items() if v})}"
        if not query.title:
            url = f"{LRCLIB_SEARCH_URL}?{urllib.parse.urlencode({'q': query.source_path.stem})}"
        data = _get_json(url)
        if not isinstance(data, list):
            return []
        candidates: list[LyricCandidate] = []
        for item in data[:12]:
            synced = bool(item.get("syncedLyrics"))
            plain = bool(item.get("plainLyrics"))
            if not synced and not plain:
                continue
            title = str(item.get("trackName") or "")
            artist = str(item.get("artistName") or "")
            album = str(item.get("albumName") or "")
            duration = _duration(item.get("duration"))
            confidence = confidence_for_candidate(
                query.title,
                query.artist,
                query.album,
                query.duration,
                title,
                artist,
                album,
                duration,
                synced,
            )
            candidates.append(
                LyricCandidate(
                    provider=self.name,
                    title=title,
                    artist=artist,
                    album=album,
                    synced=synced,
                    confidence=confidence,
                    language=str(item.get("lang") or ""),
                    source_id=str(item.get("id") or ""),
                    payload=item,
                )
            )
        return sorted(candidates, key=lambda candidate: (candidate.confidence, candidate.synced), reverse=True)

    def fetch(self, candidate: LyricCandidate) -> ProviderLyrics:
        payload = candidate.payload
        synced_text = str(payload.get("syncedLyrics") or "")
        plain_text = str(payload.get("plainLyrics") or "")
        lines = parse_lrc_text(synced_text) if synced_text else []
        return ProviderLyrics(
            provider=self.name,
            title=candidate.title,
            artist=candidate.artist,
            album=candidate.album,
            synced=bool(lines),
            lines=lines,
            plain_text=plain_text,
            confidence=candidate.confidence,
            language=candidate.language,
        )


def _get_json(url: str):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _duration(value) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None
