from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _default_cache_dir() -> Path:
    """Honor XDG_CACHE_HOME so Docker can override the cache location via env."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "music-sync"


DEFAULT_FILTER_KEYWORDS = [
    "(Live)",
    "(Acoustic)",
    "(Remix)",
    "(Cover)",
    "(Demo)",
    "(Instrumental)",
    "(Karaoke)",
]


@dataclass(frozen=True)
class ArtistConfig:
    name: str
    ytmusic_id: str | None = None
    youtube_url: str | None = None

    def __post_init__(self) -> None:
        if not self.ytmusic_id and not self.youtube_url:
            raise ValueError(f"Artist '{self.name}' needs either ytmusic_id or youtube_url")


@dataclass(frozen=True)
class PlaylistConfig:
    name: str
    id: str
    artist: str | None = None
    apply_filter: bool = True


@dataclass(frozen=True)
class Config:
    music_dir: Path
    download_dir: Path
    artists: list[ArtistConfig]
    playlists: list[PlaylistConfig] = field(default_factory=list)
    cookies_file: Path | None = None
    pot_provider_url: str | None = None
    min_free_space_mb: int = 500
    fuzzy_match_threshold: int = 85
    log_level: str = "INFO"
    filter_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_FILTER_KEYWORDS))
    cache_dir: Path = field(default_factory=_default_cache_dir)

    @property
    def state_db_path(self) -> Path:
        return self.cache_dir / "state.db"

    @property
    def api_cache_path(self) -> Path:
        return self.cache_dir / "api_cache.db"

    @property
    def log_file_path(self) -> Path:
        return self.cache_dir / "music-sync.log"


def load_config(path: Path) -> Config:
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\nRun 'music-sync init' to create one."
        )

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    music_dir = _required_path(raw, "music_dir")
    download_dir = _required_path(raw, "download_dir")

    cookies_file = raw.get("cookies_file")
    cookies_path = Path(cookies_file).expanduser() if cookies_file else None

    pot_provider_url = raw.get("pot_provider_url") or None

    artists_raw = raw.get("artists") or []
    playlists_raw = raw.get("playlists") or []
    if not artists_raw and not playlists_raw:
        raise ValueError("Config must define at least one entry in 'artists' or 'playlists'")

    artists = [
        ArtistConfig(
            name=entry["name"],
            ytmusic_id=entry.get("ytmusic_id"),
            youtube_url=entry.get("youtube_url"),
        )
        for entry in artists_raw
    ]

    playlists = [
        PlaylistConfig(
            name=entry["name"],
            id=entry["id"],
            artist=entry.get("artist"),
            apply_filter=bool(entry.get("apply_filter", True)),
        )
        for entry in playlists_raw
    ]

    filter_keywords = raw.get("filter_keywords")
    if filter_keywords is None:
        filter_keywords = list(DEFAULT_FILTER_KEYWORDS)

    return Config(
        music_dir=music_dir,
        download_dir=download_dir,
        artists=artists,
        playlists=playlists,
        cookies_file=cookies_path,
        pot_provider_url=pot_provider_url,
        min_free_space_mb=int(raw.get("min_free_space_mb", 500)),
        fuzzy_match_threshold=int(raw.get("fuzzy_match_threshold", 85)),
        log_level=str(raw.get("log_level", "INFO")).upper(),
        filter_keywords=filter_keywords,
    )


def _required_path(raw: dict, key: str) -> Path:
    value = raw.get(key)
    if not value:
        raise ValueError(f"Config field '{key}' is required")
    return Path(value).expanduser()
