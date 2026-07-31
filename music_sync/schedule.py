from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from .logger import get_logger

logger = get_logger("schedule")


def utcnow() -> datetime:
    """Naive UTC timestamp — matches what StateDB persists."""
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class ScanTier:
    """Re-check artists whose newest release is at most `max_age_days` old every
    `interval_hours`. `max_age_days=None` marks the catch-all tier for everyone else.
    `interval_hours=0` means 'check on every run'.
    """

    max_age_days: int | None
    interval_hours: float


# Aktive Künstler bleiben schnell, Karteileichen fallen auf wöchentlich zurück.
DEFAULT_SCAN_TIERS: tuple[ScanTier, ...] = (
    ScanTier(30, 0),  # Release im letzten Monat -> jeder Lauf
    ScanTier(180, 12),  # letztes halbes Jahr     -> 2x täglich
    ScanTier(365, 24),  # letztes Jahr            -> täglich
    ScanTier(1095, 72),  # letzte 3 Jahre          -> alle 3 Tage
    ScanTier(None, 168),  # älter                   -> wöchentlich
)


@dataclass(frozen=True)
class ArtistScanState:
    """What we know about an artist's release activity, persisted in `channel_state`."""

    artist: str
    last_checked: datetime | None = None
    last_release_at: datetime | None = None
    newest_release_year: int | None = None
    release_signature: str | None = None
    first_seen: datetime | None = None


def release_signature(video_ids: Iterable[str]) -> str | None:
    """Stable fingerprint of a discography. Returns None for an empty track set.

    An empty result means the API call failed or returned nothing usable — the caller
    must not store that as a signature, otherwise the next successful fetch would look
    like a burst of new releases.
    """
    unique = sorted(set(video_ids))
    if not unique:
        return None
    return hashlib.sha256("\n".join(unique).encode()).hexdigest()[:32]


def last_release_date(state: ArtistScanState, now: datetime) -> datetime | None:
    """Best estimate of when the artist last put out something new.

    Two independent signals, the more recent one wins:
      * `last_release_at` — we observed the discography change between two scans.
      * `newest_release_year` — the newest release year YT Music reports. Only the year
        is exposed, so we assume the END of that year (clamped to now). Over-estimating
        freshness is the safe direction: it costs an extra scan, while under-estimating
        would delay picking up a real release.

    Without either signal (typically the YouTube-channel fallback, which exposes no
    release dates) we fall back to `first_seen`: nothing new has shown up since we
    started watching, so the last release is at least that old. That under-estimates
    the real age, so such artists back off slowly instead of never.
    """
    candidates: list[datetime] = []
    if state.last_release_at is not None:
        candidates.append(state.last_release_at)
    if state.newest_release_year:
        year_end = datetime(state.newest_release_year, 12, 31, 23, 59, 59)
        candidates.append(min(year_end, now))
    if candidates:
        return max(candidates)
    return state.first_seen


def interval_for(state: ArtistScanState, tiers: Iterable[ScanTier], now: datetime) -> timedelta:
    """Re-scan interval for this artist. Unknown release age -> every run."""
    tier_list = list(tiers)
    if not tier_list:
        return timedelta(0)

    released = last_release_date(state, now)
    if released is None:
        return timedelta(0)

    age_days = max((now - released).days, 0)
    for tier in tier_list:
        if tier.max_age_days is None or age_days <= tier.max_age_days:
            return timedelta(hours=tier.interval_hours)
    # Kein catch-all konfiguriert: letzte (längste) Stufe gewinnt.
    return timedelta(hours=tier_list[-1].interval_hours)


def next_due(state: ArtistScanState, tiers: Iterable[ScanTier], now: datetime) -> datetime:
    """When this artist should be scanned next. Never scanned before -> now."""
    if state.last_checked is None:
        return now
    return state.last_checked + interval_for(state, tiers, now)


def is_due(state: ArtistScanState, tiers: Iterable[ScanTier], now: datetime) -> bool:
    return next_due(state, tiers, now) <= now


def apply_scan_result(
    state: ArtistScanState,
    signature: str | None,
    newest_release_year: int | None,
    now: datetime,
) -> tuple[ArtistScanState, bool]:
    """Fold a completed scan into the state. Returns (new_state, new_release_detected).

    A missing signature (failed/empty fetch) only bumps `last_checked` so the artist
    is not hammered every run; the last known-good fingerprint stays untouched.

    The FIRST observation of an artist never counts as a new release — otherwise every
    artist would land in the hottest tier right after this feature is rolled out.
    """
    if signature is None:
        return replace(state, last_checked=now), False

    detected = state.release_signature is not None and state.release_signature != signature
    return (
        replace(
            state,
            last_checked=now,
            release_signature=signature,
            newest_release_year=newest_release_year or state.newest_release_year,
            last_release_at=now if detected else state.last_release_at,
            first_seen=state.first_seen or now,
        ),
        detected,
    )


def format_interval(delta: timedelta, zero_label: str = "jeder Lauf") -> str:
    """Exact rendering of a CONFIGURED interval ('jeder Lauf', '12h', '7d')."""
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return zero_label
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    return f"{seconds // 60}min"


def format_duration(delta: timedelta, zero_label: str = "gerade eben") -> str:
    """Approximate rendering of an ARBITRARY span, for 'vor …' / 'in …' columns.

    Picks the largest unit that still carries information — a release from 2007 reads
    as '18,6 Jahre', not as a seven-digit minute count.
    """
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return zero_label
    minutes = seconds // 60
    if minutes < 60:
        return f"{max(minutes, 1)}min"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    days = hours // 24
    if days < 60:
        return f"{days}d"
    if days < 730:
        months = round(days / 30)
        return f"{months} Monat" if months == 1 else f"{months} Monate"
    return f"{days / 365.25:.1f} Jahre".replace(".", ",")
