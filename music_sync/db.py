from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .logger import get_logger

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

    def update_channel_sync(self, artist: str, source: str, source_id: str) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO channel_state (artist, source, source_id, last_sync)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(artist) DO UPDATE SET
                    source=excluded.source,
                    source_id=excluded.source_id,
                    last_sync=excluded.last_sync
                """,
                (artist, source, source_id, datetime.utcnow().isoformat()),
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
