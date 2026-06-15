from pathlib import Path

from music_sync.filters import (
    MAX_FILENAME_BYTES,
    NAME_MAX_BYTES,
    build_playlist_target_path,
    build_target_path,
    is_studio_version,
    sanitize_filename,
    sanitize_path_component,
)

KEYWORDS = ["(Live)", "(Acoustic)", "(Remix)", "(Cover)", "(Demo)"]

# Real-world title that triggered OSError(36) File name too long (Rednex).
LONG_TITLE = (
    "The Sad But True Story of Ray Mingus, the Lumberjack of Bulk Rock City, "
    "and His Never Slacking Strive to Exploit the So Far Undiscovered Areas of "
    "the Intention to Bodily Intercourse from the Opposite Species of His Kind, "
    "During Intake of All the Mead He Could Find"
)


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


def test_build_target_path_truncates_overlong_filename():
    """Regression: OSError(36) for titles whose filename exceeds the FS per-component limit."""
    path = build_target_path(Path("/m"), "Rednex", "Sex & Violins", LONG_TITLE, 8)
    assert len(path.name.encode("utf-8")) <= MAX_FILENAME_BYTES
    assert path.name.startswith("08 - ")
    assert path.name.endswith(".opus")


def test_build_target_path_keeps_short_filename_unchanged():
    path = build_target_path(Path("/m"), "Rednex", "Sex & Violins", "Cotton Eye Joe", 5)
    assert path.name == "05 - Cotton Eye Joe.opus"


def test_truncation_never_splits_multibyte_chars():
    title = "ä" * 300  # 600 UTF-8 bytes, well over the limit
    path = build_target_path(Path("/m"), "A", "B", title, None)
    assert len(path.name.encode("utf-8")) <= MAX_FILENAME_BYTES
    # Round-trips cleanly only if no multi-byte character was cut in half.
    path.name.encode("utf-8").decode("utf-8")


def test_playlist_path_truncates_overlong_filename():
    path = build_playlist_target_path(
        base_dir=Path("/m"),
        playlist_name="Mix",
        title=LONG_TITLE,
        track_number=3,
        artist="Rednex",
    )
    assert len(path.name.encode("utf-8")) <= MAX_FILENAME_BYTES
    assert path.name.startswith("003 - ")
    assert path.name.endswith(".opus")


def test_sanitize_path_component_truncates_overlong_dir():
    component = sanitize_path_component("A" * 400)
    assert len(component.encode("utf-8")) <= NAME_MAX_BYTES
