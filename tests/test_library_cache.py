import os
from pathlib import Path

import pytest
from music_sync import scanner
from music_sync.scanner import (
    SUPPORTED_EXTENSIONS,
    LibraryCache,
    LibraryShrunkError,
    _Tags,
    scan_library,
)


@pytest.fixture
def reads(monkeypatch) -> list[str]:
    """Replace the mutagen read with 'Artist - Title' from the file name, counting calls.

    Files created by a test are always "racy" (ctime = now), so the racy window is
    disabled unless a test checks it explicitly.
    """
    calls: list[str] = []

    def fake_read(path: str) -> _Tags:
        calls.append(path)
        stem = Path(path).stem
        artist, _, title = stem.partition(" - ")
        return _Tags(artist or None, title or None, "Album")

    monkeypatch.setattr(scanner, "_read_tags", fake_read)
    monkeypatch.setattr(scanner, "RACY_WINDOW_NS", 0)
    return calls


@pytest.fixture
def cache(tmp_path):
    lib_cache = LibraryCache(tmp_path / "cache" / "state.db")
    yield lib_cache
    lib_cache.close()


def make_library(music: Path, names: list[str]) -> None:
    for name in names:
        path = music / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")


def titles(library) -> set[tuple[str, str]]:
    return {(t.artist, t.title) for tracks in library.values() for t in tracks}


def test_second_scan_reads_no_unchanged_file(tmp_path, reads, cache):
    music = tmp_path / "music"
    make_library(music, ["A/X/A - One.mp3", "A/X/A - Two.flac", "B/B - Three.opus"])

    first = scan_library(music, cache=cache)
    assert len(reads) == 3

    reads.clear()
    second = scan_library(music, cache=cache)
    assert reads == []
    assert titles(second) == titles(first) == {("A", "One"), ("A", "Two"), ("B", "Three")}


def test_changed_file_is_read_again(tmp_path, reads, cache):
    music = tmp_path / "music"
    make_library(music, ["A - One.mp3", "A - Two.mp3"])
    scan_library(music, cache=cache)

    (music / "A - One.mp3").write_bytes(b"retagged audio")  # size + mtime + ctime change
    reads.clear()
    scan_library(music, cache=cache)
    assert [Path(p).name for p in reads] == ["A - One.mp3"]


def test_deleted_files_are_pruned_from_cache(tmp_path, reads, cache):
    music = tmp_path / "music"
    make_library(music, ["A - One.mp3", "A - Two.mp3", "A - Three.mp3"])
    scan_library(music, cache=cache)

    (music / "A - Two.mp3").unlink()
    library = scan_library(music, cache=cache)
    assert titles(library) == {("A", "One"), ("A", "Three")}
    assert len(cache.load()) == 2


def test_shrunk_library_aborts_without_pruning(tmp_path, reads, cache):
    music = tmp_path / "music"
    make_library(music, [f"A - Song {i}.mp3" for i in range(10)])
    scan_library(music, cache=cache)

    for i in range(8):  # e.g. a half-mounted disk
        (music / f"A - Song {i}.mp3").unlink()
    with pytest.raises(LibraryShrunkError):
        scan_library(music, cache=cache)
    assert len(cache.load()) == 10  # nothing deleted

    library = scan_library(music, cache=cache, rescan=True)
    assert len(titles(library)) == 2
    assert len(cache.load()) == 2


def test_rescan_reads_every_file(tmp_path, reads, cache):
    music = tmp_path / "music"
    make_library(music, ["A - One.mp3", "A - Two.mp3"])
    scan_library(music, cache=cache)

    reads.clear()
    scan_library(music, cache=cache, rescan=True)
    assert len(reads) == 2


def test_racy_files_are_not_cached(tmp_path, reads, cache, monkeypatch):
    monkeypatch.setattr(scanner, "RACY_WINDOW_NS", 10**12)
    music = tmp_path / "music"
    make_library(music, ["A - One.mp3"])

    scan_library(music, cache=cache)
    reads.clear()
    library = scan_library(music, cache=cache)
    assert len(reads) == 1  # still read: just-modified files aren't trusted yet
    assert titles(library) == {("A", "One")}


def test_io_errors_are_not_cached(tmp_path, cache, monkeypatch):
    monkeypatch.setattr(scanner, "RACY_WINDOW_NS", 0)
    monkeypatch.setattr(scanner, "_read_tags", lambda path: None)
    music = tmp_path / "music"
    make_library(music, ["A - One.mp3"])

    assert scan_library(music, cache=cache) == {}
    assert cache.load() == {}


def test_untagged_files_are_cached_and_fall_back_to_file_name(tmp_path, cache, monkeypatch):
    monkeypatch.setattr(scanner, "RACY_WINDOW_NS", 0)
    music = tmp_path / "music"
    make_library(music, ["Artist - Title.mp3"])  # not a real mp3 -> no tags

    first = scan_library(music, cache=cache)
    row = next(iter(cache.load().values()))
    assert row["artist"] is None  # the cache keeps the raw read result ...
    assert titles(first) == {("Artist", "Title")}  # ... the fallback is applied on load

    monkeypatch.setattr(scanner, "_read_tags", pytest.fail)
    assert titles(scan_library(music, cache=cache)) == {("Artist", "Title")}


def test_non_utf8_file_names(tmp_path, cache, monkeypatch):
    """Real tags are always valid text; the name only matters via the (uncached)
    file-name fallback, so an untagged file is the interesting case."""
    reads: list[str] = []
    monkeypatch.setattr(
        scanner, "_read_tags", lambda path: reads.append(path) or _Tags(None, None, None)
    )
    monkeypatch.setattr(scanner, "RACY_WINDOW_NS", 0)
    music = tmp_path / "music"
    music.mkdir()
    raw_name = b"Bj\xf6rk - J\xf3ga.mp3"  # latin-1, invalid UTF-8
    try:
        with open(os.path.join(os.fsencode(music), raw_name), "wb") as fh:
            fh.write(b"audio")
    except (OSError, UnicodeEncodeError):
        pytest.skip("filesystem rejects non-UTF-8 names")

    scan_library(music, cache=cache)
    reads.clear()
    library = scan_library(music, cache=cache)
    assert reads == []
    assert len(titles(library)) == 1


def test_cache_uses_relative_paths(tmp_path, reads, cache):
    """Docker (/music) and host paths must share one cache."""
    music = tmp_path / "music"
    make_library(music, ["A - One.mp3"])
    scan_library(music, cache=cache)

    moved = tmp_path / "elsewhere"
    music.rename(moved)
    reads.clear()
    library = scan_library(moved, cache=cache)
    assert reads == []
    assert next(iter(library.values()))[0].path == moved / "A - One.mp3"


def test_stale_partials_are_removed_and_ignored(tmp_path, reads, cache):
    music = tmp_path / "music"
    make_library(music, ["A/A - One.mp3", "A/.A - Two.opus.partial"])

    library = scan_library(music, cache=cache)
    assert titles(library) == {("A", "One")}
    assert not (music / "A" / ".A - Two.opus.partial").exists()


def test_record_file_spares_the_next_read(tmp_path, reads, cache):
    music = tmp_path / "music"
    make_library(music, ["A/Album/01 - Song.opus"])
    cache.record_file(music, music / "A/Album/01 - Song.opus", "A", "Song", "Album")

    library = scan_library(music, cache=cache)
    assert reads == []
    assert titles(library) == {("A", "Song")}


def _baseline_scan(music: Path) -> set[str]:
    """The former rglob + is_file walk, as reference for the new scandir walk."""
    return {
        str(path)
        for path in music.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    }


def test_walk_matches_former_rglob_scan_including_symlinks(tmp_path):
    music = tmp_path / "music"
    outside = tmp_path / "outside"
    make_library(music, ["A/A - One.mp3", "A/cover.jpg", "B/Sub/B - Two.FLAC", "B/notes.nfo"])
    make_library(outside, ["C - Linked.mp3", "Dir/C - Hidden.mp3"])
    (music / "A" / "C - Linked.mp3").symlink_to(outside / "C - Linked.mp3")  # file link
    (music / "linked-dir").symlink_to(outside / "Dir")  # directory link: not followed
    (music / "A" / "Dangling.mp3").symlink_to(outside / "missing.mp3")

    candidates, partials = scanner._walk(music)
    assert {c.path for c in candidates} == _baseline_scan(music)
    assert partials == []
