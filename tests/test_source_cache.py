from pathlib import Path

import pytest
from music_sync import source_ytmusic
from music_sync.cache import ApiCache


class FakeClient:
    """Stand-in for ytmusicapi.YTMusic that counts get_album calls."""

    def __init__(self) -> None:
        self.album_calls = 0

    def get_album(self, browse_id: str) -> dict:
        self.album_calls += 1
        return {
            "title": "Greatest Hits",
            "thumbnails": [],
            "year": "1980",
            "tracks": [{"videoId": "v1", "title": "Song", "trackNumber": 1, "duration": "3:00"}],
        }


@pytest.fixture
def source(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(source_ytmusic, "YTMusic", lambda *a, **k: FakeClient())
    cache = ApiCache(tmp_path / "api_cache.db")
    return source_ytmusic.YTMusicSource(filter_keywords=[], cache=cache)


def test_album_fetch_is_cached(source):
    first = source._fetch_album_tracks("MPREb_1", "ABBA")
    second = source._fetch_album_tracks("MPREb_1", "ABBA")

    assert source._client.album_calls == 1  # second served from cache
    assert first[0].video_id == second[0].video_id == "v1"
    assert second[0].artist == "ABBA"  # artist re-applied on cached read


def test_refresh_forces_refetch(source):
    source._fetch_album_tracks("MPREb_1", "ABBA")
    source._fetch_album_tracks("MPREb_1", "ABBA", refresh=True)

    assert source._client.album_calls == 2


def test_without_cache_always_calls_api(tmp_path, monkeypatch):
    monkeypatch.setattr(source_ytmusic, "YTMusic", lambda *a, **k: FakeClient())
    src = source_ytmusic.YTMusicSource(filter_keywords=[], cache=None)

    src._fetch_album_tracks("MPREb_1", "ABBA")
    src._fetch_album_tracks("MPREb_1", "ABBA")

    assert src._client.album_calls == 2  # no cache -> every call hits the API
