from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_FILE_NAME = "music-sync.lock"


class LockBusyError(RuntimeError):
    pass


@contextmanager
def run_lock(cache_dir: Path) -> Iterator[None]:
    """Exclusive, non-blocking lock so overlapping cron runs never work on the same state.

    flock works across the container/host boundary as long as both see the same file on
    the /cache volume, and the kernel releases it when the process dies.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(cache_dir / LOCK_FILE_NAME, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockBusyError(
                f"Another music-sync run holds {cache_dir / LOCK_FILE_NAME}"
            ) from exc
        yield
    finally:
        os.close(fd)
