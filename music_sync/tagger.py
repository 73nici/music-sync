from __future__ import annotations

import base64
from pathlib import Path

import requests
from mutagen.flac import Picture
from mutagen.oggopus import OggOpus

from .logger import get_logger
from .source_ytmusic import RemoteTrack

logger = get_logger("tagger")

REQUEST_TIMEOUT = 15
MIME_BY_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def tag_file(file_path: Path, track: RemoteTrack) -> None:
    """Write metadata + embed cover art into the downloaded .opus file."""
    try:
        audio = OggOpus(file_path)
    except Exception as exc:
        logger.error("Failed to open %s for tagging: %s", file_path, exc)
        return

    audio["title"] = track.title
    audio["artist"] = track.artist
    if track.album:
        audio["album"] = track.album
    if track.track_number:
        audio["tracknumber"] = str(track.track_number)
    audio["source"] = track.watch_url

    if track.cover_url:
        try:
            _embed_cover(audio, track.cover_url)
        except Exception as exc:
            logger.warning("Failed to embed cover art for %s: %s", file_path, exc)

    try:
        audio.save()
    except Exception as exc:
        logger.error("Failed to save tags for %s: %s", file_path, exc)


def _embed_cover(audio: OggOpus, cover_url: str) -> None:
    response = requests.get(cover_url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.content

    mime = _guess_mime(cover_url, data)

    picture = Picture()
    picture.data = data
    picture.type = 3
    picture.mime = mime
    picture.desc = "Cover"

    encoded = base64.b64encode(picture.write()).decode("ascii")
    audio["metadata_block_picture"] = [encoded]


def _guess_mime(url: str, data: bytes) -> str:
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    if suffix in MIME_BY_EXT:
        return MIME_BY_EXT[suffix]
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"
