from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5


def setup_logging(log_file: Path, level: str = "INFO", to_stdout: bool = True) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("music_sync")
    root.setLevel(level)
    root.handlers.clear()

    file_handler = RotatingFileHandler(
        log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(file_handler)

    if to_stdout:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root.addHandler(stream)

    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"music_sync.{name}")
