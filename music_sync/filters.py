from __future__ import annotations

import re
from pathlib import Path

FS_KILLERS = re.compile(r'[/\\:?*"<>|]')
WHITESPACE = re.compile(r"\s+")
PAREN_GROUPS = re.compile(r"[\(\[][^\)\]]*[\)\]]")

# Per-component limit on common Linux/macOS filesystems (NAME_MAX). Note this caps the
# *byte* length, not the character count, so multi-byte titles (umlauts, …) count more.
NAME_MAX_BYTES = 255
# Headroom for the intermediate/temp files yt-dlp writes next to the final '.opus'
# (e.g. '<stem>.f251.webm.part', fragment '.part-FragN' suffixes). Keep those within
# NAME_MAX too, otherwise the download itself fails with OSError(36) before conversion.
_TEMP_SUFFIX_HEADROOM = 25
MAX_FILENAME_BYTES = NAME_MAX_BYTES - _TEMP_SUFFIX_HEADROOM


def _truncate_to_bytes(text: str, max_bytes: int) -> str:
    """Shorten `text` so its UTF-8 encoding fits in `max_bytes`, never splitting a
    multi-byte character."""
    if max_bytes <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip(". ")


def sanitize_filename(name: str) -> str:
    """Replace characters illegal on Linux/Windows filesystems with underscore."""
    cleaned = FS_KILLERS.sub("_", name).strip()
    cleaned = WHITESPACE.sub(" ", cleaned)
    return cleaned.rstrip(". ")


def sanitize_path_component(name: str) -> str:
    cleaned = sanitize_filename(name)
    if not cleaned or set(cleaned) <= {"_", " "}:
        return "Unknown"
    return _truncate_to_bytes(cleaned, NAME_MAX_BYTES)


def _build_file_name(title: str, extension: str, prefix: str = "") -> str:
    """Assemble '<prefix><title>.<extension>', shortening only the title so the whole
    filename stays within the filesystem's per-component byte limit."""
    suffix = f".{extension}"
    reserved = len(prefix.encode("utf-8")) + len(suffix.encode("utf-8"))
    title_clean = _truncate_to_bytes(title, MAX_FILENAME_BYTES - reserved)
    return f"{prefix}{title_clean}{suffix}"


def is_studio_version(title: str, keywords: list[str]) -> bool:
    """Return True if no forbidden keyword appears as substring or inside a (...)/[...] group.

    Each configured keyword is normalized by stripping surrounding brackets so a config
    entry like '(Live)' matches any parenthesised group containing 'live' — e.g.
    'Numb (Live)', 'Song (Live aus Berlin)', '[Live Version]' all get filtered.
    """
    lowered = title.lower()
    bracket_groups = [g.lower() for g in PAREN_GROUPS.findall(title)]

    for kw in keywords:
        kw_clean = re.sub(r"[\(\)\[\]]", "", kw).strip().lower()
        if not kw_clean:
            continue
        if any(kw_clean in group for group in bracket_groups):
            return False
        if kw.lower() in lowered:
            return False
    return True


def build_target_path(
    base_dir: Path,
    artist: str,
    album: str | None,
    title: str,
    track_number: int | None,
    extension: str = "opus",
) -> Path:
    artist_dir = sanitize_path_component(artist)
    title_clean = sanitize_filename(title)

    if album:
        album_dir = sanitize_path_component(album)
        prefix = f"{track_number:02d} - " if track_number else ""
        file_name = _build_file_name(title_clean, extension, prefix)
        return base_dir / artist_dir / album_dir / file_name

    return base_dir / artist_dir / "Singles" / _build_file_name(title_clean, extension)


def build_playlist_target_path(
    base_dir: Path,
    playlist_name: str,
    title: str,
    track_number: int | None,
    artist: str | None = None,
    extension: str = "opus",
) -> Path:
    """Playlist tracks: [artist/]Playlists/<playlist_name>/[NNN - ]<title>.opus

    If artist is set, places under <artist>/Playlists/<playlist_name>/.
    Otherwise directly under Playlists/<playlist_name>/.
    """
    title_clean = sanitize_filename(title)
    playlist_dir = sanitize_path_component(playlist_name)

    prefix = f"{track_number:03d} - " if track_number else ""
    file_name = _build_file_name(title_clean, extension, prefix)

    if artist:
        return base_dir / sanitize_path_component(artist) / "Playlists" / playlist_dir / file_name
    return base_dir / "Playlists" / playlist_dir / file_name
