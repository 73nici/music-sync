from __future__ import annotations

import heapq
import os
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen import MutagenError

from .db import connect
from .logger import get_logger

logger = get_logger("scanner")

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".wma", ".aac"}
# Hidden in-flight copies written by the downloader before the atomic rename.
PARTIAL_SUFFIX = ".partial"

# Bump when the tag-reading logic changes so cached results of the old parser are re-read.
PARSER_VERSION = 1
# Files modified this recently may still change within the timestamp granularity
# ("racy clean", as in git): read them, but don't trust a cache entry for them yet.
RACY_WINDOW_NS = 2_000_000_000
# Abort instead of pruning the cache when far fewer files show up than are cached —
# typically an unmounted disk, which would otherwise trigger a mass re-download.
MIN_FOUND_RATIO = 0.5
COMMIT_EVERY = 500

LIBRARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS library_files (
    relpath BLOB PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    ctime_ns INTEGER NOT NULL,
    artist TEXT,
    title TEXT,
    album TEXT,
    parser_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS library_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class LibraryShrunkError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalTrack:
    artist: str
    title: str
    album: str | None
    path: Path


@dataclass(frozen=True)
class _Tags:
    artist: str | None
    title: str | None
    album: str | None


@dataclass(frozen=True)
class _Candidate:
    inode: int
    path: str


class LibraryCache:
    """Tags of library files keyed by path relative to music_dir.

    Paths are stored as raw bytes (os.fsencode) so non-UTF-8 file names survive, and
    relative so the Docker (/music) and host paths share one cache.
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = connect(db_path)
        self._connection.executescript(LIBRARY_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def load(self) -> dict[bytes, sqlite3.Row]:
        rows = self._connection.execute("SELECT * FROM library_files").fetchall()
        return {bytes(row["relpath"]): row for row in rows}

    def upsert(self, rows: list[tuple]) -> None:
        self._connection.executemany(
            """
            INSERT INTO library_files
                (relpath, size, mtime_ns, ctime_ns, artist, title, album, parser_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(relpath) DO UPDATE SET
                size=excluded.size,
                mtime_ns=excluded.mtime_ns,
                ctime_ns=excluded.ctime_ns,
                artist=excluded.artist,
                title=excluded.title,
                album=excluded.album,
                parser_version=excluded.parser_version
            """,
            rows,
        )

    def delete(self, relpaths: list[bytes]) -> None:
        self._connection.executemany(
            "DELETE FROM library_files WHERE relpath = ?", [(r,) for r in relpaths]
        )

    def set_meta(self, key: str, value: str) -> None:
        self._connection.execute(
            "INSERT INTO library_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def commit(self) -> None:
        self._connection.commit()

    def record_file(
        self, music_dir: Path, path: Path, artist: str, title: str, album: str | None
    ) -> None:
        """Store tags we just wrote ourselves, saving the next run from reading the file.

        No racy-clean check: the content is known, not guessed from a timestamp.
        """
        st = os.stat(path)
        relpath = os.fsencode(os.path.relpath(path, music_dir))
        self.upsert(
            [
                (
                    relpath,
                    st.st_size,
                    st.st_mtime_ns,
                    st.st_ctime_ns,
                    artist,
                    title,
                    album,
                    PARSER_VERSION,
                )
            ]
        )
        self.commit()


def scan_library(
    music_dir: Path, cache: LibraryCache | None = None, rescan: bool = False
) -> dict[str, list[LocalTrack]]:
    """Walk music_dir recursively and return tracks grouped by lowercased artist.

    With `cache`, only new or changed files (size/mtime/ctime) are opened; everything
    else comes from the cache. `rescan` re-reads every file and also accepts a library
    that shrank a lot (see MIN_FOUND_RATIO).
    """
    if not music_dir.exists():
        raise FileNotFoundError(f"Music directory does not exist: {music_dir}")

    candidates, partials = _walk(music_dir)
    cached = cache.load() if cache is not None else {}

    if cache is not None and not rescan and cached:
        if len(candidates) < len(cached) * MIN_FOUND_RATIO:
            raise LibraryShrunkError(
                f"Only {len(candidates)} audio files found in {music_dir}, but "
                f"{len(cached)} are cached. Is the disk mounted? "
                "Run with --rescan to accept the smaller library."
            )

    for partial in partials:
        logger.info("Removing stale partial download: %s", partial)
        try:
            os.unlink(partial)
        except OSError as exc:
            logger.warning("Could not remove %s: %s", partial, exc)

    tracks_by_artist: dict[str, list[LocalTrack]] = defaultdict(list)
    seen: set[bytes] = set()
    pending: list[tuple] = []
    read_count = 0
    scan_started_ns = time.time_ns()

    # Inode order turns the stat/read pass into a mostly monotonic sweep over the inode
    # tables instead of jumping around in ext4's hash order.
    for candidate in sorted(candidates, key=lambda c: c.inode):
        try:
            st = os.stat(candidate.path)
        except OSError as exc:
            logger.warning("Cannot stat %s: %s", candidate.path, exc)
            continue
        relpath = os.fsencode(os.path.relpath(candidate.path, music_dir))
        seen.add(relpath)

        row = None if rescan else cached.get(relpath)
        if row is not None and _is_fresh(row, st):
            tags = _Tags(row["artist"], row["title"], row["album"])
        else:
            read = _read_tags(candidate.path)
            read_count += 1
            if read is None:  # I/O error: don't cache, retry next run
                continue
            tags = read
            if cache is not None and not _is_racy(st, scan_started_ns):
                pending.append(
                    (
                        relpath,
                        st.st_size,
                        st.st_mtime_ns,
                        st.st_ctime_ns,
                        tags.artist,
                        tags.title,
                        tags.album,
                        PARSER_VERSION,
                    )
                )
                if len(pending) >= COMMIT_EVERY:
                    cache.upsert(pending)
                    cache.commit()
                    pending.clear()

        track = _to_track(Path(candidate.path), tags)
        if track is not None:
            tracks_by_artist[track.artist.lower()].append(track)

    if cache is not None:
        cache.upsert(pending)
        cache.delete([relpath for relpath in cached if relpath not in seen])
        cache.set_meta("music_dir", str(music_dir))
        cache.commit()

    logger.info(
        "Scanned %d artists in %s (%d files, %d read from disk)",
        len(tracks_by_artist),
        music_dir,
        len(candidates),
        read_count,
    )
    return dict(tracks_by_artist)


def _walk(music_dir: Path) -> tuple[list[_Candidate], list[str]]:
    """Collect audio files without a stat per entry (d_type from getdents).

    Directories are visited in global inode order via a heap. Directory symlinks are not
    followed; file symlinks to audio files are kept, like the former rglob/is_file scan.
    Returns the audio candidates and stale '.<name>.partial' files of the downloader.
    """
    candidates: list[_Candidate] = []
    partials: list[str] = []
    root = os.fspath(music_dir)
    heap: list[tuple[int, str]] = [(os.stat(root).st_ino, root)]

    while heap:
        _, directory = heapq.heappop(heap)
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            logger.warning("Cannot list %s: %s", directory, exc)
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    heapq.heappush(heap, (entry.inode(), entry.path))
                    continue
                name = entry.name
                if name.startswith(".") and name.endswith(PARTIAL_SUFFIX):
                    partials.append(entry.path)
                    continue
                if os.path.splitext(name)[1].lower() not in SUPPORTED_EXTENSIONS:
                    continue
                if entry.is_file():  # follows file symlinks; drops dangling ones
                    candidates.append(_Candidate(inode=entry.inode(), path=entry.path))
            except OSError as exc:
                logger.warning("Cannot inspect %s: %s", entry.path, exc)

    return candidates, partials


def _is_fresh(row: sqlite3.Row, st: os.stat_result) -> bool:
    return (
        row["parser_version"] == PARSER_VERSION
        and row["size"] == st.st_size
        and row["mtime_ns"] == st.st_mtime_ns
        and row["ctime_ns"] == st.st_ctime_ns
    )


def _is_racy(st: os.stat_result, scan_started_ns: int) -> bool:
    return scan_started_ns - max(st.st_mtime_ns, st.st_ctime_ns) < RACY_WINDOW_NS


def _read_tags(path: str) -> _Tags | None:
    """Read artist/title/album. Returns None on I/O errors (not cacheable); a file that
    mutagen cannot parse yields empty tags (cacheable — it won't parse next time either).
    """
    try:
        audio = MutagenFile(path, easy=True)
    except MutagenError as exc:
        if isinstance(exc.__cause__, OSError):  # mutagen wraps I/O errors
            logger.warning("Failed to read %s: %s", path, exc)
            return None
        logger.warning("Failed to read tags from %s: %s", path, exc)
        audio = None
    except OSError as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None
    except Exception as exc:
        logger.warning("Failed to read tags from %s: %s", path, exc)
        audio = None

    if audio is None:
        return _Tags(None, None, None)
    return _Tags(
        artist=_first(audio.get("artist")),
        title=_first(audio.get("title")),
        album=_first(audio.get("album")),
    )


def _to_track(path: Path, tags: _Tags) -> LocalTrack | None:
    artist, title = tags.artist, tags.title
    if not artist or not title:
        artist_fb, title_fb = _parse_filename(path)
        artist = artist or artist_fb
        title = title or title_fb

    if not artist or not title:
        logger.debug("Skipping file with no usable metadata: %s", path)
        return None

    return LocalTrack(artist=artist.strip(), title=title.strip(), album=tags.album, path=path)


def _first(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return str(value)


def _parse_filename(path: Path) -> tuple[str | None, str | None]:
    """Fallback: parse 'Artist - Title' from filename stem."""
    stem = path.stem
    if " - " not in stem:
        return None, None
    artist, _, title = stem.partition(" - ")
    return artist.strip() or None, title.strip() or None
