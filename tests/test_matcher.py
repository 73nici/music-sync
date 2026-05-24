from pathlib import Path

from music_sync.matcher import is_song_in_library, normalize
from music_sync.scanner import LocalTrack


def make_library(artist: str, titles: list[str]) -> dict[str, list[LocalTrack]]:
    tracks = [LocalTrack(artist=artist, title=t, album=None, path=Path(f"/m/{t}.mp3")) for t in titles]
    return {artist.lower(): tracks}


def test_normalize_strips_parens():
    assert normalize("Numb [HD] (Official Video)") == "numb"


def test_normalize_keeps_alnum():
    assert normalize("Du Hast 2025") == "du hast 2025"


def test_match_exact_title_present():
    lib = make_library("Linkin Park", ["Numb"])
    result = is_song_in_library("Numb", "Linkin Park", lib, threshold=85)
    assert result.is_match is True


def test_match_with_official_video_suffix():
    lib = make_library("Linkin Park", ["Numb"])
    result = is_song_in_library("Numb [Official Music Video]", "Linkin Park", lib, threshold=85)
    assert result.is_match is True


def test_missing_song_returns_no_match():
    lib = make_library("Linkin Park", ["Numb"])
    result = is_song_in_library("In The End", "Linkin Park", lib, threshold=85)
    assert result.is_match is False


def test_unknown_artist_returns_no_match():
    lib = make_library("Linkin Park", ["Numb"])
    result = is_song_in_library("Numb", "Unknown Artist", lib, threshold=85)
    assert result.is_match is False
    assert result.matched_track is None


def test_feat_normalization():
    lib = make_library("Eminem", ["Stan ft. Dido"])
    result = is_song_in_library("Stan (feat. Dido)", "Eminem", lib, threshold=80)
    assert result.is_match is True
