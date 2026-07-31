import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from music_sync.db import StateDB
from music_sync.schedule import ArtistScanState

NOW = datetime(2026, 7, 31, 12, 0, 0)

OLD_SCHEMA = """
CREATE TABLE channel_state (
    artist TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    last_sync TIMESTAMP
);
"""


def test_scan_state_roundtrip(tmp_path: Path):
    db = StateDB(tmp_path / "state.db")
    state = ArtistScanState(
        artist="Rammstein",
        last_checked=NOW,
        last_release_at=NOW - timedelta(days=30),
        newest_release_year=2022,
        release_signature="sig-1",
        first_seen=NOW - timedelta(days=90),
    )

    db.save_scan_state(state, "ytmusic", "UC123")

    assert StateDB(tmp_path / "state.db").load_scan_states() == {"rammstein": state}


def test_scan_state_lookup_is_case_insensitive(tmp_path: Path):
    db = StateDB(tmp_path / "state.db")
    db.save_scan_state(ArtistScanState(artist="Linkin Park", last_checked=NOW), "ytmusic", "UC1")

    assert "linkin park" in db.load_scan_states()


def test_save_overwrites_previous_state(tmp_path: Path):
    db = StateDB(tmp_path / "state.db")
    db.save_scan_state(
        ArtistScanState(artist="ABBA", last_checked=NOW, release_signature="old"), "ytmusic", "UC1"
    )
    db.save_scan_state(
        ArtistScanState(artist="ABBA", last_checked=NOW, release_signature="new"), "ytmusic", "UC1"
    )

    states = db.load_scan_states()
    assert len(states) == 1
    assert states["abba"].release_signature == "new"


def test_missing_state_columns_are_migrated(tmp_path: Path):
    """Existing production DBs predate the scheduling columns."""
    db_path = tmp_path / "state.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO channel_state (artist, source, source_id, last_sync) VALUES (?, ?, ?, ?)",
        ("Rammstein", "ytmusic", "UC123", NOW.isoformat()),
    )
    conn.commit()
    conn.close()

    states = StateDB(db_path).load_scan_states()

    assert states["rammstein"] == ArtistScanState(
        artist="Rammstein",
        last_checked=NOW,  # last_sync wird als "zuletzt geprüft" weiterverwendet
        last_release_at=None,
        newest_release_year=None,
        release_signature=None,
        first_seen=None,
    )


def test_migration_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "state.db"
    StateDB(db_path)
    StateDB(db_path)  # zweiter Start darf nicht an ALTER TABLE scheitern

    assert StateDB(db_path).load_scan_states() == {}


def test_unparseable_timestamp_is_tolerated(tmp_path: Path):
    db_path = tmp_path / "state.db"
    StateDB(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO channel_state (artist, source, source_id, last_sync) VALUES (?, ?, ?, ?)",
        ("Broken", "ytmusic", "UC1", "not-a-date"),
    )
    conn.commit()
    conn.close()

    assert StateDB(db_path).load_scan_states()["broken"].last_checked is None
