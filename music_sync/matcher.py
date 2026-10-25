from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import fuzz, process

from .scanner import LocalTrack

PARENS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
NON_ALNUM = re.compile(r"[^a-z0-9\s]")
WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class MatchResult:
    is_match: bool
    score: int
    matched_track: LocalTrack | None


@lru_cache(maxsize=65536)
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

    # normalize() is cached, so local titles are only normalized once per run; the
    # scoring loop itself runs in rapidfuzz's C code. Ties keep the first best match.
    candidates = [(normalize(track.title), track) for track in tracks]
    candidates = [(norm, track) for norm, track in candidates if norm]
    best = process.extractOne(
        norm_title,
        [norm for norm, _ in candidates],
        scorer=fuzz.token_set_ratio,
        processor=None,
    )
    best_score = int(best[1]) if best else 0
    best_track = candidates[best[2]][1] if best else None

    return MatchResult(
        is_match=best_score >= threshold,
        score=best_score,
        matched_track=best_track if best_score >= threshold else None,
    )
