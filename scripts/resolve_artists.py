#!/usr/bin/env python3
"""One-off helper: find folders not yet in config.yaml and resolve their YT Music
artist browseId via search. Prints a JSON report; does NOT modify config."""
from __future__ import annotations

import json
import sys
import time
import unicodedata
from pathlib import Path

import yaml
from rapidfuzz import fuzz
from ytmusicapi import YTMusic

ARTISTS_DIR = Path("/mnt/undertaker/media/music/artists")
CONFIG_PATH = Path("/mnt/code/music-sync/config.yaml")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold().strip()


def main() -> None:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    existing = {norm(a["name"]) for a in (raw.get("artists") or [])}

    folders = sorted(
        {p.name for p in ARTISTS_DIR.iterdir() if p.is_dir()},
        key=str.casefold,
    )
    missing = [f for f in folders if norm(f) not in existing]

    yt = YTMusic()
    report = []
    for name in missing:
        entry = {"folder": name, "candidates": []}
        try:
            results = yt.search(name, filter="artists", limit=3) or []
        except Exception as exc:  # noqa: BLE001
            entry["error"] = str(exc)
            report.append(entry)
            continue
        for r in results[:3]:
            cand_name = r.get("artist") or ""
            entry["candidates"].append(
                {
                    "name": cand_name,
                    "browseId": r.get("browseId"),
                    "score": round(fuzz.ratio(norm(name), norm(cand_name)), 1),
                }
            )
        report.append(entry)
        time.sleep(0.15)

    print(json.dumps({"missing_count": len(missing), "report": report},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
