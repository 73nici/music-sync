from pathlib import Path

import pytest

from music_sync.filters import (
    build_playlist_target_path,
    build_target_path,
    is_studio_version,
    sanitize_filename,
    sanitize_path_component,
)

KEYWORDS = ["(Live)", "(Acoustic)", "(Remix)", "(Cover)", "(Demo)"]


def test_sanitize_removes_forbidden_chars():
    assert sanitize_filename('AC/DC: Hells "Bells"?') == "AC_DC_ Hells _Bells__"


def test_sanitize_keeps_umlauts():
    assert sanitize_filename("Schönster Tag") == "Schönster Tag"


def test_sanitize_path_component_fallback():
    assert sanitize_path_component("///") == "Unknown"


def test_studio_filter_allows_studio_tracks():
    assert is_studio_version("Du Hast", KEYWORDS) is True


def test_studio_filter_blocks_live_tracks():
    assert is_studio_version("Du Hast (Live)", KEYWORDS) is False


def test_studio_filter_case_insensitive():
    assert is_studio_version("Numb (live)", KEYWORDS) is False


def test_studio_filter_blocks_live_with_suffix():
    assert is_studio_version("Alle Jahre wieder (Live aus der Wuhlheide)", KEYWORDS) is False


def test_studio_filter_blocks_bracket_remix():
    assert is_studio_version("Ride It [Jonas Blue Remix]", KEYWORDS + ["(Remix)"]) is False


def test_studio_filter_allows_song_with_live_in_name():
    # Substring 'live' im Songtitel ohne Klammern soll NICHT filtern.
    assert is_studio_version("Living On A Prayer", KEYWORDS) is True


def test_build_target_path_with_album():
    path = build_target_path(Path("/m"), "Rammstein", "Zeit", "Armee", 1)
    assert path == Path("/m/Rammstein/Zeit/01 - Armee.opus")


def test_build_target_path_without_album():
    path = build_target_path(Path("/m"), "Rammstein", None, "Pussy", None)
    assert path == Path("/m/Rammstein/Singles/Pussy.opus")


def test_build_target_path_sanitizes_components():
    path = build_target_path(Path("/m"), "AC/DC", "T:N:T", "Hells/Bells", 3)
    assert path == Path("/m/AC_DC/T_N_T/03 - Hells_Bells.opus")


def test_build_target_path_with_dot_in_title():
    """Regression: 'Song (feat. Artist)' breaks Path.suffix-based extension handling."""
    path = build_target_path(Path("/m"), "Kummer", "Album", "DER LETZTE SONG (feat. Nina Chuba)", 1)
    assert path.name == "01 - DER LETZTE SONG (feat. Nina Chuba).opus"


def test_playlist_path_with_artist():
    path = build_playlist_target_path(
        base_dir=Path("/m"),
        playlist_name="This is Bounce",
        title="Whitney Houston - I Will Always Love You (HBz Remix)",
        track_number=1,
        artist="HBz",
    )
    assert path == Path(
        "/m/HBz/Playlists/This is Bounce/001 - Whitney Houston - I Will Always Love You (HBz Remix).opus"
    )


def test_playlist_path_without_artist():
    path = build_playlist_target_path(
        base_dir=Path("/m"),
        playlist_name="Bounce Hits",
        title="Track",
        track_number=42,
    )
    assert path == Path("/m/Playlists/Bounce Hits/042 - Track.opus")


def test_playlist_path_without_track_number():
    path = build_playlist_target_path(
        base_dir=Path("/m"),
        playlist_name="Mix",
        title="Solo Song",
        track_number=None,
        artist="HBz",
    )
    assert path == Path("/m/HBz/Playlists/Mix/Solo Song.opus")


def test_playlist_path_sanitizes_problematic_chars():
    path = build_playlist_target_path(
        base_dir=Path("/m"),
        playlist_name="Hits / Top 50",
        title="Song: Part One",
        track_number=1,
        artist="A/B",
    )
    assert path == Path("/m/A_B/Playlists/Hits _ Top 50/001 - Song_ Part One.opus")
