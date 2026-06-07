from music_sync.scanner import _parse_filename


def test_parse_filename_artist_dash_title(tmp_path):
    path = tmp_path / "Rammstein - Du Hast.mp3"
    path.touch()
    artist, title = _parse_filename(path)
    assert artist == "Rammstein"
    assert title == "Du Hast"


def test_parse_filename_no_dash_returns_none(tmp_path):
    path = tmp_path / "song.mp3"
    path.touch()
    artist, title = _parse_filename(path)
    assert artist is None
    assert title is None


def test_parse_filename_strips_whitespace(tmp_path):
    path = tmp_path / "  Artist   -   Song  .mp3"
    path.touch()
    artist, title = _parse_filename(path)
    assert artist == "Artist"
    assert title == "Song"
