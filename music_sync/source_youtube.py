from __future__ import annotations

from pathlib import Path

import yt_dlp

from .filters import is_studio_version
from .logger import get_logger
from .source_ytmusic import RemoteTrack

logger = get_logger("source_youtube")


class YouTubeChannelSource:
    """Fallback source for artists not available on YT Music: scrape their YT channel."""

    def __init__(self, filter_keywords: list[str], cookies_file: Path | None = None) -> None:
        self._filter_keywords = filter_keywords
        self._cookies_file = cookies_file

    def fetch_artist_tracks(self, channel_url: str, artist_name: str) -> list[RemoteTrack]:
        opts: dict = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "playlistend": 500,
        }
        if self._cookies_file and self._cookies_file.exists():
            opts["cookiefile"] = str(self._cookies_file)

        target_url = channel_url.rstrip("/")
        if not target_url.endswith("/videos"):
            target_url = f"{target_url}/videos"

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                data = ydl.extract_info(target_url, download=False)
        except Exception as exc:
            logger.error("Failed to extract channel %s: %s", channel_url, exc)
            return []

        entries = (data or {}).get("entries") or []
        results: list[RemoteTrack] = []

        for entry in entries:
            video_id = entry.get("id")
            title = entry.get("title")
            if not video_id or not title:
                continue
            if not is_studio_version(title, self._filter_keywords):
                continue
            thumbs = entry.get("thumbnails") or []
            cover_url = thumbs[-1]["url"] if thumbs else None
            duration = entry.get("duration")
            results.append(
                RemoteTrack(
                    video_id=video_id,
                    title=title,
                    artist=artist_name,
                    album=None,
                    track_number=None,
                    duration_seconds=int(duration) if duration else None,
                    cover_url=cover_url,
                    source="youtube",
                )
            )

        logger.info("YT-Channel %s yielded %d candidates", channel_url, len(results))
        return results
