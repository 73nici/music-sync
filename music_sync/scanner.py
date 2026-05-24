from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from mutagen import File as MutagenFile

from .logger import get_logger

logger = get_logger("scanner")

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".wma", ".aac"}


@dataclass(frozen=True)
class LocalTrack:
    artist: str
    title: str
    album: str | None
    path: Path


def scan_library(music_dir: Path) -> dict[str, list[LocalTrack]]:
    """Walk music_dir recursively and return tracks grouped by lowercased artist."""
    if not music_dir.exists():
        raise FileNotFoundError(f"Music directory does not exist: {music_dir}")

    tracks_by_artist: dict[str, list[LocalTrack]] = defaultdict(list)

    for path in music_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        track = _read_track(path)
        if track is None:
            continue

        tracks_by_artist[track.artist.lower()].append(track)

    logger.info("Scanned %d artists in %s", len(tracks_by_artist), music_dir)
    return dict(tracks_by_artist)


def _read_track(path: Path) -> LocalTrack | None:
    try:
        audio = MutagenFile(path, easy=True)
    except Exception as exc:
        logger.warning("Failed to read tags from %s: %s", path, exc)
        audio = None

    artist: str | None = None
    title: str | None = None
    album: str | None = None

    if audio is not None:
        artist = _first(audio.get("artist"))
        title = _first(audio.get("title"))
        album = _first(audio.get("album"))

    if not artist or not title:
        artist_fb, title_fb = _parse_filename(path)
        artist = artist or artist_fb
        title = title or title_fb

    if not artist or not title:
        logger.debug("Skipping file with no usable metadata: %s", path)
        return None

    return LocalTrack(artist=artist.strip(), title=title.strip(), album=album, path=path)


def _first(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return str(value)


def _parse_filename(path: Path) -> tuple[str | None, str | None]:
    """Fallback: parse 'Artist - Title' from filename stem."""
    stem = path.stem
    if " - " not in stem:
        return None, None
    artist, _, title = stem.partition(" - ")
    return artist.strip() or None, title.strip() or None
