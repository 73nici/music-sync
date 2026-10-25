from pathlib import Path

from music_sync.matcher import is_song_in_library, normalize
from music_sync.scanner import LocalTrack


def make_library(artist: str, titles: list[str]) -> dict[str, list[LocalTrack]]:
    tracks = [
        LocalTrack(artist=artist, title=t, album=None, path=Path(f"/m/{t}.mp3")) for t in titles
    ]
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


def _reference_match(title: str, artist: str, library, threshold: int):
    """The former pure-Python loop, as reference for the extractOne version."""
    from rapidfuzz import fuzz

    norm_title = normalize(title)
    best_score, best_track = 0, None
    for track in library.get(artist.lower(), []):
        norm_existing = normalize(track.title)
        if not norm_existing:
            continue
        score = int(fuzz.token_set_ratio(norm_title, norm_existing))
        if score > best_score:
            best_score, best_track = score, track
    return best_score, best_track if best_score >= threshold else None


def test_matches_former_implementation():
    local = ["Numb", "Numb (Live)", "In the End", "(Intro)", "Faint", "Papercut", "Crawling"]
    lib = make_library("Linkin Park", local)
    remote = ["Numb", "In The End (Remastered)", "Crawling [HD]", "One Step Closer", "Faint"]
    for title in remote:
        result = is_song_in_library(title, "Linkin Park", lib, threshold=85)
        score, track = _reference_match(title, "Linkin Park", lib, threshold=85)
        assert (result.score, result.matched_track) == (score, track)


def test_only_empty_local_titles_yield_no_match():
    lib = make_library("Artist", ["(Intro)", "[Bonus]"])
    result = is_song_in_library("Intro", "Artist", lib, threshold=50)
    assert result.is_match is False
    assert result.score == 0
