"""End-to-end wiring of the adaptive scan schedule inside `_collect_missing_tracks`."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from music_sync import commands
from music_sync.config import ArtistConfig, Config, ScanScheduleConfig
from music_sync.db import StateDB
from music_sync.source_ytmusic import RemoteTrack


def track(video_id: str, year: int | None = 2010) -> RemoteTrack:
    return RemoteTrack(
        video_id=video_id,
        title=f"Song {video_id}",
        artist="Dormant Band",
        album="Old Album",
        track_number=1,
        duration_seconds=180,
        cover_url=None,
        release_year=year,
    )


class FakeSource:
    """Records which artists were actually fetched."""

    def __init__(self, *args, **kwargs) -> None:
        self.fetched: list[str] = []
        self.tracks: list[RemoteTrack] = [track("v1")]

    def fetch_artist_tracks(self, _id: str, artist_name: str, refresh: bool = False):
        self.fetched.append(artist_name)
        return list(self.tracks)


@pytest.fixture
def source(monkeypatch) -> FakeSource:
    fake = FakeSource()
    monkeypatch.setattr(commands, "YTMusicSource", lambda *a, **k: fake)
    monkeypatch.setattr(commands, "YouTubeChannelSource", lambda *a, **k: fake)
    monkeypatch.setattr(commands, "ApiCache", lambda *a, **k: None)
    return fake


def make_config(tmp_path: Path, **schedule_kwargs) -> Config:
    return Config(
        music_dir=tmp_path,
        download_dir=tmp_path,
        artists=[ArtistConfig(name="Dormant Band", ytmusic_id="UC1")],
        cache_dir=tmp_path / "cache",
        scan_schedule=ScanScheduleConfig(**schedule_kwargs),
    )


def collect(config: Config, db: StateDB, **kwargs):
    return commands._collect_missing_tracks(config, {}, db, None, **kwargs)


def test_dormant_artist_is_skipped_on_the_second_run(tmp_path, source):
    """The whole point: a band whose last release is from 2010 must not be re-scanned
    on every 3h cron run."""
    config = make_config(tmp_path)
    db = StateDB(config.state_db_path)

    collect(config, db)
    collect(config, db)

    assert source.fetched == ["Dormant Band"]  # zweiter Lauf übersprungen


def test_active_artist_is_scanned_on_every_run(tmp_path, source):
    config = make_config(tmp_path)
    db = StateDB(config.state_db_path)
    source.tracks = [track("v1", year=None)]  # kein bekanntes Jahr -> immer prüfen

    collect(config, db)
    collect(config, db)

    assert source.fetched == ["Dormant Band", "Dormant Band"]


def test_artist_without_release_year_backs_off_over_time(tmp_path, source):
    """YouTube-Fallback liefert kein Release-Jahr: nach langem ereignislosem
    Zuschauen darf trotzdem gedrosselt werden."""
    config = make_config(tmp_path)
    db = StateDB(config.state_db_path)
    source.tracks = [track("v1", year=None)]

    collect(config, db)
    state = db.load_scan_states()["dormant band"]
    db.save_scan_state(
        replace(state, first_seen=state.first_seen - timedelta(days=400)), "ytmusic", "UC1"
    )
    collect(config, db)

    assert source.fetched == ["Dormant Band"]  # zweiter Lauf gedrosselt


def test_all_flag_bypasses_the_schedule(tmp_path, source):
    config = make_config(tmp_path)
    db = StateDB(config.state_db_path)

    collect(config, db)
    collect(config, db, ignore_schedule=True)

    assert len(source.fetched) == 2


def test_refresh_bypasses_the_schedule(tmp_path, source):
    config = make_config(tmp_path)
    db = StateDB(config.state_db_path)

    collect(config, db)
    collect(config, db, refresh=True)

    assert len(source.fetched) == 2


def test_explicit_artist_filter_bypasses_the_schedule(tmp_path, source):
    config = make_config(tmp_path)
    db = StateDB(config.state_db_path)

    collect(config, db)
    commands._collect_missing_tracks(config, {}, db, "Dormant Band")

    assert len(source.fetched) == 2


def test_disabled_schedule_scans_everything(tmp_path, source):
    config = make_config(tmp_path, enabled=False)
    db = StateDB(config.state_db_path)

    collect(config, db)
    collect(config, db)

    assert len(source.fetched) == 2


def test_new_release_resets_the_artist_to_the_fast_tier(tmp_path, source):
    config = make_config(tmp_path)
    db = StateDB(config.state_db_path)

    collect(config, db)
    source.tracks = [track("v1"), track("v2")]  # neues Release erscheint
    collect(config, db, ignore_schedule=True)

    state = db.load_scan_states()["dormant band"]
    assert state.last_release_at is not None
    collect(config, db)  # jetzt wieder heiß -> ohne Bypass erneut gescannt
    assert len(source.fetched) == 3


def test_failed_fetch_does_not_look_like_a_new_release(tmp_path, source):
    config = make_config(tmp_path)
    db = StateDB(config.state_db_path)

    collect(config, db)
    source.tracks = []  # API-Fehler: fetch_artist_tracks liefert []
    collect(config, db, ignore_schedule=True)
    source.tracks = [track("v1")]  # API wieder da, unveränderte Diskografie
    collect(config, db, ignore_schedule=True)

    assert db.load_scan_states()["dormant band"].last_release_at is None
