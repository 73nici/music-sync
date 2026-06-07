from music_sync.commands import _dedup_releases, _release_priority
from music_sync.source_ytmusic import RemoteTrack


def make(
    video_id: str,
    title: str,
    album: str | None = None,
    track_number: int | None = None,
    release_year: int | None = None,
) -> RemoteTrack:
    return RemoteTrack(
        video_id=video_id,
        title=title,
        artist="Kummer",
        album=album,
        track_number=track_number,
        duration_seconds=None,
        cover_url=None,
        release_year=release_year,
    )


def test_dedup_prefers_album_track_over_single():
    album_track = make("v1", "Bei Dir", album="KIOX", track_number=3)
    single = make("v2", "Bei Dir", album="KIOX", track_number=None)
    result = _dedup_releases([single, album_track])
    assert len(result) == 1
    assert result[0].video_id == "v1"


def test_dedup_keeps_unique_titles():
    a = make("v1", "Song A", track_number=1)
    b = make("v2", "Song B", track_number=2)
    result = _dedup_releases([a, b])
    assert {t.video_id for t in result} == {"v1", "v2"}


def test_dedup_keeps_feat_collab_separate_from_solo():
    """Solo version and (feat. X) version are distinct releases — keep both."""
    feat_version = make("v1", "DER LETZTE SONG (feat. Nina Chuba)", track_number=1)
    solo_album = make("v2", "DER LETZTE SONG", album="ALLES WIRD GUT", track_number=1)
    result = _dedup_releases([feat_version, solo_album])
    assert {t.video_id for t in result} == {"v1", "v2"}


def test_dedup_different_collaborators_kept_separate():
    """'Song (feat. A)' and 'Song (feat. B)' are different collaborations."""
    a = make("v1", "Song (feat. Artist A)")
    b = make("v2", "Song (feat. Artist B)")
    result = _dedup_releases([a, b])
    assert {t.video_id for t in result} == {"v1", "v2"}


def test_dedup_strips_non_feat_parens():
    """'Song [Official Audio]' and 'Song' should collapse — bracket content is not a collab."""
    a = make("v1", "Song [Official Audio]")
    b = make("v2", "Song", track_number=1)
    result = _dedup_releases([a, b])
    assert len(result) == 1
    assert result[0].video_id == "v2"


def test_dedup_ft_and_feat_treated_same():
    """'(ft. X)' and '(feat. X)' should produce the same key — abbreviation only."""
    ft = make("v1", "Song (ft. X)")
    feat = make("v2", "Song (feat. X)", track_number=1)
    result = _dedup_releases([ft, feat])
    assert len(result) == 1
    assert result[0].video_id == "v2"


def test_dedup_first_wins_when_priority_equal():
    a = make("v1", "Same Title")
    b = make("v2", "Same Title")
    result = _dedup_releases([a, b])
    assert result[0].video_id == "v1"


def test_release_priority_ranking():
    album_track = make("v1", "X", album="A", track_number=1)
    single_with_album = make("v2", "X", album="A")
    bare_single = make("v3", "X")
    assert _release_priority(album_track) > _release_priority(single_with_album)
    assert _release_priority(single_with_album) > _release_priority(bare_single)


def test_dedup_prefers_original_album_over_compilation():
    """ABBA's 'Hasta Manana' should land on Waterloo (1974), not on a Compilation (2024)."""
    original = make("v1", "Hasta Manana", album="Waterloo", track_number=4, release_year=1974)
    compilation = make("v2", "Hasta Manana", album="The Singles", track_number=7, release_year=2024)
    result = _dedup_releases([compilation, original])
    assert len(result) == 1
    assert result[0].video_id == "v1"
    assert result[0].album == "Waterloo"


def test_dedup_prefers_original_over_anniversary_edition():
    original = make("v1", "Waterloo", album="Waterloo", track_number=1, release_year=1974)
    anniversary = make(
        "v2", "Waterloo", album="Waterloo (50th Anniversary)", track_number=1, release_year=2024
    )
    result = _dedup_releases([anniversary, original])
    assert result[0].video_id == "v1"


def test_dedup_missing_year_treated_as_very_old():
    """If original has no year but a compilation does, original should still win."""
    original = make("v1", "Song", album="OriginalAlbum", track_number=1, release_year=None)
    compilation = make("v2", "Song", album="Hits", track_number=5, release_year=2024)
    result = _dedup_releases([compilation, original])
    assert result[0].video_id == "v1"


def test_dedup_keeps_language_versions_separate():
    """'Waterloo' (English) and 'Waterloo (Swedish Version)' must stay distinct."""
    english = make("v1", "Waterloo", album="Waterloo", track_number=1, release_year=1974)
    swedish = make(
        "v2", "Waterloo (Swedish Version)", album="Waterloo", track_number=13, release_year=1974
    )
    result = _dedup_releases([english, swedish])
    assert {t.video_id for t in result} == {"v1", "v2"}


def test_dedup_keeps_multiple_language_versions():
    swedish = make(
        "v1", "Waterloo (Swedish Version)", album="Anniv", track_number=2, release_year=2024
    )
    german = make(
        "v2", "Waterloo (German Version)", album="Anniv", track_number=3, release_year=2024
    )
    french = make(
        "v3", "Waterloo (French Version)", album="Anniv", track_number=4, release_year=2024
    )
    result = _dedup_releases([swedish, german, french])
    assert {t.video_id for t in result} == {"v1", "v2", "v3"}


def test_dedup_collapses_same_language_across_albums():
    """Same language version on multiple releases dedups to the older one."""
    in_original_album = make(
        "v1", "Waterloo (Swedish Version)", album="Waterloo", track_number=13, release_year=1974
    )
    in_anniversary = make(
        "v2", "Waterloo (Swedish Version)", album="Anniversary", track_number=2, release_year=2024
    )
    result = _dedup_releases([in_anniversary, in_original_album])
    assert len(result) == 1
    assert result[0].video_id == "v1"
