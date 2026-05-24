from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .scanner import LocalTrack

PARENS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
NON_ALNUM = re.compile(r"[^a-z0-9\s]")
WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class MatchResult:
    is_match: bool
    score: int
    matched_track: LocalTrack | None


def normalize(text: str) -> str:
    """Lowercase, strip parens/brackets, remove non-alphanumeric, collapse whitespace."""
    lowered = text.lower()
    stripped = PARENS.sub("", lowered)
    cleaned = NON_ALNUM.sub(" ", stripped)
    return WHITESPACE.sub(" ", cleaned).strip()


def is_song_in_library(
    title: str,
    artist: str,
    library: dict[str, list[LocalTrack]],
    threshold: int = 85,
) -> MatchResult:
    """Check if a song (by title) already exists in the local library for the given artist."""
    artist_key = artist.lower()
    tracks = library.get(artist_key, [])
    if not tracks:
        return MatchResult(is_match=False, score=0, matched_track=None)

    norm_title = normalize(title)
    if not norm_title:
        return MatchResult(is_match=False, score=0, matched_track=None)

    best_score = 0
    best_track: LocalTrack | None = None
    for track in tracks:
        norm_existing = normalize(track.title)
        if not norm_existing:
            continue
        score = int(fuzz.token_set_ratio(norm_title, norm_existing))
        if score > best_score:
            best_score = score
            best_track = track

    return MatchResult(
        is_match=best_score >= threshold,
        score=best_score,
        matched_track=best_track if best_score >= threshold else None,
    )
