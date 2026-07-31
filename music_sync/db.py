from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .logger import get_logger
from .schedule import ArtistScanState

logger = get_logger("db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL UNIQUE,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    album TEXT,
    file_path TEXT,
    status TEXT NOT NULL CHECK (status IN ('success', 'failed', 'skipped')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    downloaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channel_state (
    artist TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    last_sync TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_artist ON downloads(artist);
CREATE INDEX IF NOT EXISTS idx_status ON downloads(status);
"""

# Nachträglich ergänzte Spalten — per ALTER TABLE gegen bestehende Produktiv-DBs.
CHANNEL_STATE_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("release_signature", "TEXT"),
    ("last_release_at", "TIMESTAMP"),
    ("newest_release_year", "INTEGER"),
    ("first_seen", "TIMESTAMP"),
)

MAX_RETRIES = 3


@dataclass(frozen=True)
class FailedRecord:
    video_id: str
    artist: str
    title: str
    album: str | None
    retry_count: int


class StateDB:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)
            existing = {row["name"] for row in c.execute("PRAGMA table_info(channel_state)")}
            for column, coltype in CHANNEL_STATE_MIGRATIONS:
                if column not in existing:
                    c.execute(f"ALTER TABLE channel_state ADD COLUMN {column} {coltype}")
                    logger.info("Migrated channel_state: added column %s", column)

    def is_known(self, video_id: str) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT status, retry_count FROM downloads WHERE video_id = ?",
                (video_id,),
            ).fetchone()
        if row is None:
            return False
        if row["status"] == "success":
            return True
        if row["status"] == "failed" and row["retry_count"] >= MAX_RETRIES:
            return True
        return False

    def record_success(
        self,
        video_id: str,
        artist: str,
        title: str,
        album: str | None,
        file_path: Path,
    ) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO downloads
                    (video_id, artist, title, album, file_path, status, retry_count)
                VALUES (?, ?, ?, ?, ?, 'success', 0)
                ON CONFLICT(video_id) DO UPDATE SET
                    status='success',
                    file_path=excluded.file_path,
                    error_message=NULL,
                    downloaded_at=CURRENT_TIMESTAMP
                """,
                (video_id, artist, title, album, str(file_path)),
            )

    def record_failure(
        self,
        video_id: str,
        artist: str,
        title: str,
        album: str | None,
        error: str,
    ) -> None:
        with self._conn() as c:
            row = c.execute(
                "SELECT retry_count FROM downloads WHERE video_id = ?",
                (video_id,),
            ).fetchone()
            new_count = (row["retry_count"] + 1) if row else 1
            c.execute(
                """
                INSERT INTO downloads
                    (video_id, artist, title, album, status, retry_count, error_message)
                VALUES (?, ?, ?, ?, 'failed', ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    status='failed',
                    retry_count=excluded.retry_count,
                    error_message=excluded.error_message,
                    downloaded_at=CURRENT_TIMESTAMP
                """,
                (video_id, artist, title, album, new_count, error),
            )

    def record_skip(self, video_id: str, artist: str, title: str, album: str | None) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO downloads (video_id, artist, title, album, status, retry_count)
                VALUES (?, ?, ?, ?, 'skipped', 0)
                ON CONFLICT(video_id) DO NOTHING
                """,
                (video_id, artist, title, album),
            )

    def load_scan_states(self) -> dict[str, ArtistScanState]:
        """All persisted artist scan states, keyed by lowercased artist name."""
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT artist, last_sync, last_release_at, newest_release_year,
                       release_signature, first_seen
                FROM channel_state
                """
            ).fetchall()
        return {
            row["artist"].lower(): ArtistScanState(
                artist=row["artist"],
                last_checked=_parse_ts(row["last_sync"]),
                last_release_at=_parse_ts(row["last_release_at"]),
                newest_release_year=row["newest_release_year"],
                release_signature=row["release_signature"],
                first_seen=_parse_ts(row["first_seen"]),
            )
            for row in rows
        }

    def save_scan_state(self, state: ArtistScanState, source: str, source_id: str) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO channel_state
                    (artist, source, source_id, last_sync, release_signature,
                     last_release_at, newest_release_year, first_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artist) DO UPDATE SET
                    source=excluded.source,
                    source_id=excluded.source_id,
                    last_sync=excluded.last_sync,
                    release_signature=excluded.release_signature,
                    last_release_at=excluded.last_release_at,
                    newest_release_year=excluded.newest_release_year,
                    first_seen=excluded.first_seen
                """,
                (
                    state.artist,
                    source,
                    source_id,
                    _format_ts(state.last_checked),
                    state.release_signature,
                    _format_ts(state.last_release_at),
                    state.newest_release_year,
                    _format_ts(state.first_seen),
                ),
            )

    def list_failed(self) -> list[FailedRecord]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT video_id, artist, title, album, retry_count
                FROM downloads
                WHERE status = 'failed' AND retry_count < ?
                ORDER BY artist, title
                """,
                (MAX_RETRIES,),
            ).fetchall()
        return [
            FailedRecord(
                video_id=row["video_id"],
                artist=row["artist"],
                title=row["title"],
                album=row["album"],
                retry_count=row["retry_count"],
            )
            for row in rows
        ]

    def stats(self) -> dict[str, int]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT status, COUNT(*) as n FROM downloads GROUP BY status"
            ).fetchall()
        return {row["status"]: row["n"] for row in rows}


def _parse_ts(value: str | None) -> datetime | None:
    """Parse a stored ISO timestamp back to naive UTC. Tolerates legacy tz-aware values."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        logger.warning("Unparseable timestamp in state DB: %r", value)
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _format_ts(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
