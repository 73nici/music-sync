from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from .logger import get_logger

logger = get_logger("cache")

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_cache (
    key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class ApiCache:
    """Persistent cache for immutable YT-Music API responses.

    Album track lists are immutable once a release is published, so cached
    entries never expire. The artist-level album LIST is intentionally NOT
    cached here (callers fetch it fresh each run) so new releases are still
    discovered while the per-album fetches are served from cache.

    Only successful fetches are stored — if `fetch_fn` raises, the exception
    propagates uncached. Pass ``force=True`` to bypass the read and refresh the
    stored payload (used by ``--refresh``).
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_album(
        self, browse_id: str, fetch_fn: Callable[[], Any], *, force: bool = False
    ) -> Any:
        """Return the cached album payload for `browse_id`, fetching+storing on miss."""
        return self.get_or_fetch(browse_id, "album", fetch_fn, force=force)

    def get_or_fetch(
        self, key: str, kind: str, fetch_fn: Callable[[], Any], *, force: bool = False
    ) -> Any:
        if not force:
            cached = self._read(key)
            if cached is not None:
                logger.debug("cache hit (%s): %s", kind, key)
                return cached
        value = fetch_fn()  # stored only on success; exceptions propagate
        self._write(key, kind, value)
        logger.debug("cache store (%s): %s", kind, key)
        return value

    def _read(self, key: str) -> Any | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT payload FROM api_cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            return None

    def _write(self, key: str, kind: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO api_cache (key, kind, payload, fetched_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    payload=excluded.payload,
                    fetched_at=excluded.fetched_at
                """,
                (key, kind, payload),
            )

    def clear(self, kind: str | None = None) -> int:
        """Delete cached entries (all, or only a given `kind`). Returns row count."""
        with self._conn() as c:
            if kind is None:
                cur = c.execute("DELETE FROM api_cache")
            else:
                cur = c.execute("DELETE FROM api_cache WHERE kind = ?", (kind,))
            return cur.rowcount

    def stats(self) -> dict[str, int]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT kind, COUNT(*) FROM api_cache GROUP BY kind"
            ).fetchall()
        return {kind: count for kind, count in rows}
