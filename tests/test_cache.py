from pathlib import Path

from music_sync.cache import ApiCache


def _counter():
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return {"tracks": [{"videoId": f"v{calls['n']}"}]}

    return calls, fetch


def test_miss_then_hit_fetches_only_once(tmp_path: Path):
    cache = ApiCache(tmp_path / "api_cache.db")
    calls, fetch = _counter()

    first = cache.get_album("MPREb_album1", fetch)
    second = cache.get_album("MPREb_album1", fetch)

    assert calls["n"] == 1  # second call served from cache
    assert first == second


def test_distinct_keys_fetch_separately(tmp_path: Path):
    cache = ApiCache(tmp_path / "api_cache.db")
    calls, fetch = _counter()

    cache.get_album("a", fetch)
    cache.get_album("b", fetch)

    assert calls["n"] == 2
    assert cache.stats() == {"album": 2}


def test_force_refetches_and_overwrites(tmp_path: Path):
    cache = ApiCache(tmp_path / "api_cache.db")
    calls, fetch = _counter()

    cache.get_album("a", fetch)
    refreshed = cache.get_album("a", fetch, force=True)

    assert calls["n"] == 2  # force bypassed the cache read
    assert refreshed == {"tracks": [{"videoId": "v2"}]}


def test_failed_fetch_is_not_cached(tmp_path: Path):
    cache = ApiCache(tmp_path / "api_cache.db")

    def boom():
        raise RuntimeError("api down")

    try:
        cache.get_album("a", boom)
    except RuntimeError:
        pass

    assert cache.stats() == {}  # nothing stored on failure


def test_persists_across_instances(tmp_path: Path):
    db = tmp_path / "api_cache.db"
    calls, fetch = _counter()

    ApiCache(db).get_album("a", fetch)
    again = ApiCache(db).get_album("a", fetch)  # fresh instance, same file

    assert calls["n"] == 1
    assert again == {"tracks": [{"videoId": "v1"}]}


def test_clear(tmp_path: Path):
    cache = ApiCache(tmp_path / "api_cache.db")
    _, fetch = _counter()
    cache.get_album("a", fetch)
    cache.get_album("b", fetch)

    removed = cache.clear()

    assert removed == 2
    assert cache.stats() == {}
