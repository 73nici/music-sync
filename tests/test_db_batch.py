import sqlite3

import pytest
from music_sync.db import MAX_RETRIES, StateDB
from music_sync.lock import LockBusyError, run_lock


@pytest.fixture
def db(tmp_path):
    state = StateDB(tmp_path / "state.db")
    yield state
    state.close()


def count_rows(path) -> int:
    with sqlite3.connect(path) as other:
        return other.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]


def test_uses_wal_journal(db, tmp_path):
    with sqlite3.connect(tmp_path / "state.db") as other:
        assert other.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_batch_commits_once_at_the_end(db, tmp_path):
    with db.batch():
        db.record_skip("v1", "A", "One", None)
        db.record_skip("v2", "A", "Two", None)
        assert count_rows(tmp_path / "state.db") == 0  # not visible before the commit
    assert count_rows(tmp_path / "state.db") == 2


def test_batch_rolls_back_on_error(db, tmp_path):
    with pytest.raises(RuntimeError), db.batch():
        db.record_skip("v1", "A", "One", None)
        raise RuntimeError("network down")
    assert count_rows(tmp_path / "state.db") == 0


def test_writes_outside_a_batch_commit_immediately(db, tmp_path):
    db.record_success("v1", "A", "One", None, tmp_path / "one.opus")
    assert count_rows(tmp_path / "state.db") == 1


def test_download_index_splits_known_and_recorded(db, tmp_path):
    db.record_success("ok", "A", "One", None, tmp_path / "one.opus")
    db.record_skip("skipped", "A", "Two", None)
    db.record_failure("failed-once", "A", "Three", None, "boom")
    for _ in range(MAX_RETRIES):
        db.record_failure("failed-often", "A", "Four", None, "boom")

    index = db.load_download_index()
    assert index.known == {"ok", "failed-often"}  # 'skipped' must stay re-checkable
    assert index.recorded == {"ok", "skipped", "failed-once", "failed-often"}
    assert all(db.is_known(v) == (v in index.known) for v in index.recorded)


def test_run_lock_is_exclusive(tmp_path):
    with run_lock(tmp_path):
        with pytest.raises(LockBusyError), run_lock(tmp_path):
            pass
    with run_lock(tmp_path):  # released again
        pass
