from datetime import datetime, timedelta

import pytest
from music_sync.schedule import (
    DEFAULT_SCAN_TIERS,
    ArtistScanState,
    ScanTier,
    apply_scan_result,
    format_duration,
    format_interval,
    interval_for,
    is_due,
    last_release_date,
    next_due,
    release_signature,
)

NOW = datetime(2026, 7, 31, 12, 0, 0)
TIERS = list(DEFAULT_SCAN_TIERS)


def state(**kwargs) -> ArtistScanState:
    return ArtistScanState(artist=kwargs.pop("artist", "Rammstein"), **kwargs)


# --- signature ---------------------------------------------------------------


def test_signature_is_order_independent():
    assert release_signature(["b", "a"]) == release_signature(["a", "b"])


def test_signature_changes_when_a_track_appears():
    assert release_signature(["a", "b"]) != release_signature(["a", "b", "c"])


def test_signature_of_empty_set_is_none():
    assert release_signature([]) is None


# --- release age -------------------------------------------------------------


def test_release_year_is_read_as_end_of_year():
    """Only the year is exposed by YT Music — assume the latest possible date so we
    never under-estimate how fresh an artist is."""
    released = last_release_date(state(newest_release_year=2025), NOW)
    assert released == datetime(2025, 12, 31, 23, 59, 59)


def test_current_release_year_is_clamped_to_now():
    released = last_release_date(state(newest_release_year=2026), NOW)
    assert released == NOW


def test_detected_change_beats_older_catalog_year():
    detected = NOW - timedelta(days=3)
    released = last_release_date(state(newest_release_year=2019, last_release_at=detected), NOW)
    assert released == detected


def test_unknown_release_age_has_no_date():
    assert last_release_date(state(), NOW) is None


def test_first_seen_is_the_fallback_when_no_date_signal_exists():
    """YouTube-Fallback-Künstler liefern kein Release-Jahr — dann zählt, seit wann wir
    ohne Neuigkeit zuschauen."""
    watching_since = NOW - timedelta(days=200)
    assert last_release_date(state(first_seen=watching_since), NOW) == watching_since


def test_first_seen_never_overrides_a_real_signal():
    released = last_release_date(
        state(newest_release_year=2019, first_seen=NOW - timedelta(days=1)), NOW
    )
    assert released == datetime(2019, 12, 31, 23, 59, 59)


# --- interval tiers ----------------------------------------------------------


@pytest.mark.parametrize(
    ("last_release_at", "expected_hours"),
    [
        (NOW - timedelta(days=1), 0),  # brandneu -> jeder Lauf
        (NOW - timedelta(days=29), 0),
        (NOW - timedelta(days=90), 12),
        (NOW - timedelta(days=300), 24),
        (NOW - timedelta(days=800), 72),
        (NOW - timedelta(days=4000), 168),  # Karteileiche -> wöchentlich
    ],
)
def test_interval_scales_with_release_age(last_release_at, expected_hours):
    interval = interval_for(state(last_release_at=last_release_at), TIERS, NOW)
    assert interval == timedelta(hours=expected_hours)


def test_unknown_release_age_is_checked_every_run():
    assert interval_for(state(), TIERS, NOW) == timedelta(0)


def test_falls_back_to_longest_tier_without_catch_all():
    tiers = [ScanTier(30, 0), ScanTier(365, 24)]
    interval = interval_for(state(last_release_at=NOW - timedelta(days=5000)), tiers, NOW)
    assert interval == timedelta(hours=24)


def test_empty_tier_list_disables_backoff():
    assert interval_for(state(last_release_at=NOW - timedelta(days=5000)), [], NOW) == timedelta(0)


# --- due dates ---------------------------------------------------------------


def test_never_checked_is_due_immediately():
    assert is_due(state(newest_release_year=1999), TIERS, NOW) is True


def test_dormant_artist_is_skipped_between_intervals():
    cold = state(last_checked=NOW - timedelta(hours=6), newest_release_year=2005)
    assert is_due(cold, TIERS, NOW) is False
    assert next_due(cold, TIERS, NOW) == NOW - timedelta(hours=6) + timedelta(hours=168)


def test_active_artist_is_due_on_every_run():
    hot = state(last_checked=NOW - timedelta(minutes=1), last_release_at=NOW - timedelta(days=2))
    assert is_due(hot, TIERS, NOW) is True


def test_dormant_artist_becomes_due_once_the_interval_elapsed():
    cold = state(last_checked=NOW - timedelta(days=8), newest_release_year=2005)
    assert is_due(cold, TIERS, NOW) is True


# --- folding scan results ----------------------------------------------------


def test_first_observation_is_not_counted_as_new_release():
    """Otherwise every artist would land in the hottest tier on the first run after
    this feature is deployed."""
    new_state, detected = apply_scan_result(state(), "sig-1", 2010, NOW)

    assert detected is False
    assert new_state.last_release_at is None
    assert new_state.release_signature == "sig-1"
    assert new_state.last_checked == NOW
    assert new_state.first_seen == NOW


def test_first_seen_is_never_moved_forward():
    previous = state(release_signature="sig-1", first_seen=NOW - timedelta(days=100))
    new_state, _ = apply_scan_result(previous, "sig-2", None, NOW)

    assert new_state.first_seen == previous.first_seen


def test_changed_signature_marks_a_new_release():
    previous = state(release_signature="sig-1", last_checked=NOW - timedelta(days=7))
    new_state, detected = apply_scan_result(previous, "sig-2", 2026, NOW)

    assert detected is True
    assert new_state.last_release_at == NOW


def test_unchanged_signature_only_bumps_last_checked():
    previous = state(
        release_signature="sig-1",
        last_checked=NOW - timedelta(days=7),
        last_release_at=NOW - timedelta(days=400),
    )
    new_state, detected = apply_scan_result(previous, "sig-1", 2010, NOW)

    assert detected is False
    assert new_state.last_checked == NOW
    assert new_state.last_release_at == previous.last_release_at


def test_failed_fetch_keeps_previous_signature():
    """An API error yields no tracks — storing that would make the next successful
    fetch look like a burst of new releases."""
    previous = state(release_signature="sig-1", newest_release_year=2010)
    new_state, detected = apply_scan_result(previous, None, None, NOW)

    assert detected is False
    assert new_state.release_signature == "sig-1"
    assert new_state.newest_release_year == 2010
    assert new_state.last_checked == NOW  # nicht in Dauerschleife neu versuchen


def test_missing_year_keeps_the_stored_one():
    previous = state(release_signature="sig-1", newest_release_year=2010)
    new_state, _ = apply_scan_result(previous, "sig-2", None, NOW)

    assert new_state.newest_release_year == 2010


# --- formatting --------------------------------------------------------------


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(0), "jeder Lauf"),
        (timedelta(hours=-5), "jeder Lauf"),
        (timedelta(hours=12), "12h"),
        (timedelta(days=7), "7d"),
        (timedelta(minutes=30), "30min"),
    ],
)
def test_format_interval(delta, expected):
    assert format_interval(delta) == expected


def test_format_interval_custom_zero_label():
    assert format_interval(timedelta(0), "fällig") == "fällig"


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(0), "gerade eben"),
        (timedelta(seconds=30), "1min"),
        (timedelta(minutes=59), "59min"),
        (timedelta(hours=47), "47h"),
        (timedelta(days=3), "3d"),
        (timedelta(days=59), "59d"),
        (timedelta(days=90), "3 Monate"),
        (timedelta(days=63), "2 Monate"),
        (timedelta(days=730), "2,0 Jahre"),
        (timedelta(days=6800), "18,6 Jahre"),
    ],
)
def test_format_duration_picks_the_largest_useful_unit(delta, expected):
    assert format_duration(delta) == expected
