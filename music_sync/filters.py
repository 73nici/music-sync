from __future__ import annotations

import re
from pathlib import Path

FS_KILLERS = re.compile(r'[/\\:?*"<>|]')
WHITESPACE = re.compile(r"\s+")
PAREN_GROUPS = re.compile(r"[\(\[][^\)\]]*[\)\]]")


def sanitize_filename(name: str) -> str:
    """Replace characters illegal on Linux/Windows filesystems with underscore."""
    cleaned = FS_KILLERS.sub("_", name).strip()
    cleaned = WHITESPACE.sub(" ", cleaned)
    return cleaned.rstrip(". ")


def sanitize_path_component(name: str) -> str:
    cleaned = sanitize_filename(name)
    if not cleaned or set(cleaned) <= {"_", " "}:
        return "Unknown"
    return cleaned


def is_studio_version(title: str, keywords: list[str]) -> bool:
    """Return True if no forbidden keyword appears either as substring or inside a (...) / [...] group.

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
        if track_number:
            file_name = f"{track_number:02d} - {title_clean}.{extension}"
        else:
            file_name = f"{title_clean}.{extension}"
        return base_dir / artist_dir / album_dir / file_name

    return base_dir / artist_dir / "Singles" / f"{title_clean}.{extension}"


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

    if track_number:
        file_name = f"{track_number:03d} - {title_clean}.{extension}"
    else:
        file_name = f"{title_clean}.{extension}"

    if artist:
        return base_dir / sanitize_path_component(artist) / "Playlists" / playlist_dir / file_name
    return base_dir / "Playlists" / playlist_dir / file_name
