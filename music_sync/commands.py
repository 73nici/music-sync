from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from .cache import ApiCache
from .config import ArtistConfig, Config, PlaylistConfig
from .db import DownloadIndex, StateDB
from .downloader import DiskSpaceError, Downloader, DownloadError, TargetExistsError
from .filters import build_playlist_target_path, build_target_path
from .logger import get_logger
from .matcher import is_song_in_library, normalize
from .scanner import LibraryCache, LocalTrack, scan_library
from .schedule import (
    ArtistScanState,
    apply_scan_result,
    format_duration,
    format_interval,
    interval_for,
    is_due,
    last_release_date,
    next_due,
    release_signature,
    utcnow,
)
from .source_youtube import YouTubeChannelSource
from .source_ytmusic import RemoteTrack, YTMusicSource
from .tagger import tag_file

logger = get_logger("commands")
console = Console()


@dataclass(frozen=True)
class MissingTrack:
    """A missing track to be downloaded.

    Either `artist_config` (from artist sync) or `playlist_config` (from playlist sync) is set,
    never both. The downloader uses this to decide where the file should land.
    """

    remote: RemoteTrack
    artist_config: ArtistConfig | None = None
    playlist_config: PlaylistConfig | None = None

    def __post_init__(self) -> None:
        if (self.artist_config is None) == (self.playlist_config is None):
            raise ValueError("MissingTrack needs exactly one of artist_config or playlist_config")


Library = dict[str, list[LocalTrack]]


def _scan(config: Config, library_cache: LibraryCache, rescan: bool) -> Library:
    return scan_library(config.music_dir, cache=library_cache, rescan=rescan)


def cmd_scan(config: Config, rescan: bool = False) -> None:
    with closing(LibraryCache(config.state_db_path)) as library_cache:
        library = _scan(config, library_cache, rescan)
    table = Table(title=f"Lokale Musikbibliothek: {config.music_dir}")
    table.add_column("Künstler")
    table.add_column("Songs", justify="right")
    for artist_key in sorted(library.keys()):
        tracks = library[artist_key]
        display = tracks[0].artist if tracks else artist_key
        table.add_row(display, str(len(tracks)))
    console.print(table)
    console.print(f"\nGesamt: {sum(len(v) for v in library.values())} Tracks")


def cmd_sync(
    config: Config,
    artist_name: str | None,
    dry_run: bool,
    refresh: bool = False,
    all_artists: bool = False,
    rescan: bool = False,
) -> None:
    _require_music_dir(config)
    with (
        StateDB(config.state_db_path) as db,
        closing(LibraryCache(config.state_db_path)) as library_cache,
    ):
        # Only walk the library once an artist is actually due.
        library = cache(lambda: _scan(config, library_cache, rescan))
        missing = _collect_missing_tracks(
            config, library, db, artist_name, refresh=refresh, ignore_schedule=all_artists
        )
        missing += _collect_playlist_tracks(config, db, artist_name)

        if not missing:
            console.print("[green]Keine fehlenden Songs gefunden.[/green]")
            return

        console.print(f"[bold]{len(missing)} fehlende Songs identifiziert.[/bold]")

        if dry_run:
            _print_missing_table(missing)
            console.print("\n[yellow]Dry-Run: nichts heruntergeladen.[/yellow]")
            return

        _download_missing(config, db, library_cache, missing)


def cmd_list_missing(
    config: Config,
    artist_name: str | None,
    refresh: bool = False,
    all_artists: bool = False,
    rescan: bool = False,
) -> None:
    _require_music_dir(config)
    with (
        StateDB(config.state_db_path) as db,
        closing(LibraryCache(config.state_db_path)) as library_cache,
    ):
        library = cache(lambda: _scan(config, library_cache, rescan))
        missing = _collect_missing_tracks(
            config, library, db, artist_name, refresh=refresh, ignore_schedule=all_artists
        )
        missing += _collect_playlist_tracks(config, db, artist_name)
    if not missing:
        console.print("[green]Keine fehlenden Songs.[/green]")
        return
    _print_missing_table(missing)
    console.print(f"\nGesamt: {len(missing)} fehlende Songs")


def _require_music_dir(config: Config) -> None:
    """Fail fast on a missing mount, even if the lazy library scan never runs."""
    if not config.music_dir.exists():
        raise FileNotFoundError(f"Music directory does not exist: {config.music_dir}")


def cmd_schedule(config: Config) -> None:
    """Show when each artist was last scanned and when the next scan is due."""
    with StateDB(config.state_db_path) as db:
        states = db.load_scan_states()
    now = utcnow()
    tiers = config.scan_schedule.tiers

    table = Table(title="Scan-Zeitplan")
    table.add_column("Künstler")
    table.add_column("Letzter Scan")
    table.add_column("Letztes Release")
    table.add_column("Intervall", justify="right")
    table.add_column("Nächster Scan")

    rows = []
    for artist_cfg in config.artists:
        state = states.get(artist_cfg.name.lower()) or ArtistScanState(artist=artist_cfg.name)
        due = next_due(state, tiers, now)
        released = last_release_date(state, now)
        rows.append(
            (
                due,
                artist_cfg.name,
                _fmt_ago(state.last_checked, now),
                _fmt_ago(released, now),
                format_interval(interval_for(state, tiers, now)),
                "[green]fällig[/green]" if due <= now else f"in {format_duration(due - now)}",
            )
        )

    for _, *cells in sorted(rows, key=lambda row: row[0]):
        table.add_row(*cells)

    console.print(table)
    if not config.scan_schedule.enabled:
        console.print(
            "\n[yellow]scan_schedule.enabled: false — jeder Lauf prüft alle Künstler.[/yellow]"
        )


def _fmt_ago(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "—"
    delta = now - moment
    return "gerade eben" if delta.total_seconds() <= 0 else f"vor {format_duration(delta)}"


def cmd_retry_failed(config: Config) -> None:
    with (
        StateDB(config.state_db_path) as db,
        closing(LibraryCache(config.state_db_path)) as library_cache,
    ):
        _retry_failed(config, db, library_cache)


def _retry_failed(config: Config, db: StateDB, library_cache: LibraryCache) -> None:
    failed = db.list_failed()
    if not failed:
        console.print("[green]Keine fehlgeschlagenen Downloads zum Retry.[/green]")
        return

    artist_lookup = {a.name.lower(): a for a in config.artists}
    downloader = _make_downloader(config)

    for record in failed:
        artist_cfg = artist_lookup.get(record.artist.lower())
        if artist_cfg is None:
            console.print(
                f"[yellow]Skip {record.artist} - {record.title}: nicht mehr in config[/yellow]"
            )
            continue
        remote = RemoteTrack(
            video_id=record.video_id,
            title=record.title,
            artist=record.artist,
            album=record.album,
            track_number=None,
            duration_seconds=None,
            cover_url=None,
        )
        _download_single(
            config,
            db,
            library_cache,
            downloader,
            MissingTrack(remote=remote, artist_config=artist_cfg),
        )


def _collect_missing_tracks(
    config: Config,
    library: Library | Callable[[], Library],
    db: StateDB,
    artist_filter: str | None,
    refresh: bool = False,
    ignore_schedule: bool = False,
) -> list[MissingTrack]:
    """`library` may be a callable so the (HDD-heavy) scan only runs if an artist is due."""
    api_cache = ApiCache(config.api_cache_path)
    try:
        return _collect_artist_tracks(
            config, library, db, artist_filter, api_cache, refresh, ignore_schedule
        )
    finally:
        if api_cache is not None:
            api_cache.close()


def _collect_artist_tracks(
    config: Config,
    library: Library | Callable[[], Library],
    db: StateDB,
    artist_filter: str | None,
    api_cache: ApiCache,
    refresh: bool,
    ignore_schedule: bool,
) -> list[MissingTrack]:
    missing: list[MissingTrack] = []

    ytmusic = YTMusicSource(filter_keywords=config.filter_keywords, cache=api_cache)
    yt_fallback = YouTubeChannelSource(filter_keywords=config.filter_keywords)
    index = db.load_download_index()

    now = utcnow()
    tiers = config.scan_schedule.tiers
    states = db.load_scan_states()
    # Ein explizit angeforderter Künstler und --refresh/--all umgehen den Zeitplan.
    use_schedule = (
        config.scan_schedule.enabled and not ignore_schedule and not refresh and not artist_filter
    )
    skipped: list[tuple[str, datetime]] = []

    for artist_cfg in config.artists:
        if artist_filter and artist_cfg.name.lower() != artist_filter.lower():
            continue

        state = states.get(artist_cfg.name.lower()) or ArtistScanState(artist=artist_cfg.name)
        if use_schedule and not is_due(state, tiers, now):
            due = next_due(state, tiers, now)
            skipped.append((artist_cfg.name, due))
            logger.info(
                "Skipping %s per schedule (next check %s)", artist_cfg.name, due.isoformat()
            )
            continue

        console.print(f"[cyan]→ Lade Diskografie für {artist_cfg.name}...[/cyan]")

        if artist_cfg.ytmusic_id:
            source, source_id = "ytmusic", artist_cfg.ytmusic_id
            remote_tracks = ytmusic.fetch_artist_tracks(
                artist_cfg.ytmusic_id, artist_cfg.name, refresh=refresh
            )
        else:
            assert artist_cfg.youtube_url
            source, source_id = "youtube", artist_cfg.youtube_url
            remote_tracks = yt_fallback.fetch_artist_tracks(artist_cfg.youtube_url, artist_cfg.name)

        local = library() if callable(library) else library
        # One commit per artist instead of one per row (each commit used to cost fsyncs).
        with db.batch():
            _record_scan(db, state, remote_tracks, source, source_id, now)
            missing += _missing_for_artist(config, db, index, local, artist_cfg, remote_tracks)

    _report_skipped(skipped, now)
    return missing


def _missing_for_artist(
    config: Config,
    db: StateDB,
    index: DownloadIndex,
    library: Library,
    artist_cfg: ArtistConfig,
    remote_tracks: list[RemoteTrack],
) -> list[MissingTrack]:
    missing: list[MissingTrack] = []
    for remote in _dedup_releases(remote_tracks):
        if remote.video_id in index.known:
            continue
        result = is_song_in_library(
            title=remote.title,
            artist=artist_cfg.name,
            library=library,
            threshold=config.fuzzy_match_threshold,
        )
        if result.is_match:
            if remote.video_id not in index.recorded:
                db.record_skip(remote.video_id, artist_cfg.name, remote.title, remote.album)
                index.recorded.add(remote.video_id)
            logger.debug(
                "Skip (lokal vorhanden, score=%d): %s — %s",
                result.score,
                artist_cfg.name,
                remote.title,
            )
            continue
        missing.append(MissingTrack(remote=remote, artist_config=artist_cfg))
    return missing


def _record_scan(
    db: StateDB,
    state: ArtistScanState,
    remote_tracks: list[RemoteTrack],
    source: str,
    source_id: str,
    now: datetime,
) -> None:
    """Persist the scan outcome so the next run can decide whether to skip this artist."""
    signature = release_signature(track.video_id for track in remote_tracks)
    newest_year = max(
        (track.release_year for track in remote_tracks if track.release_year), default=None
    )
    new_state, detected = apply_scan_result(state, signature, newest_year, now)
    db.save_scan_state(new_state, source, source_id)

    if detected:
        console.print(f"  [green]✔ Neue Releases erkannt — {state.artist}[/green]")
        logger.info("New releases detected for %s", state.artist)
    elif signature is None:
        logger.warning("No tracks returned for %s — keeping previous signature", state.artist)


def _report_skipped(skipped: list[tuple[str, datetime]], now: datetime) -> None:
    if not skipped:
        return
    soonest_artist, soonest_due = min(skipped, key=lambda item: item[1])
    console.print(
        f"[dim]{len(skipped)} Künstler ohne frische Releases übersprungen "
        f"(nächster: {soonest_artist} in {format_duration(soonest_due - now)})[/dim]"
    )


def _collect_playlist_tracks(
    config: Config,
    db: StateDB,
    artist_filter: str | None,
) -> list[MissingTrack]:
    missing: list[MissingTrack] = []
    if not config.playlists:
        return missing

    ytmusic = YTMusicSource(filter_keywords=config.filter_keywords)
    index = db.load_download_index()

    for playlist_cfg in config.playlists:
        if artist_filter and (playlist_cfg.artist or "").lower() != artist_filter.lower():
            continue

        console.print(f"[cyan]→ Lade Playlist '{playlist_cfg.name}'...[/cyan]")
        tracks = ytmusic.fetch_playlist_tracks(
            playlist_id=playlist_cfg.id,
            playlist_name=playlist_cfg.name,
            apply_filter=playlist_cfg.apply_filter,
        )

        for remote in _dedup_releases(tracks):
            if remote.video_id in index.known:
                continue
            missing.append(MissingTrack(remote=remote, playlist_config=playlist_cfg))

    return missing


def _dedup_releases(tracks: list[RemoteTrack]) -> list[RemoteTrack]:
    """Drop multiple releases of the same song from one sync run.

    YT Music can list one song multiple times: once as an album track, again as a separate
    single/feature release. They have distinct video_ids, so the per-video_id state DB
    cannot detect this — dedup keyed on normalized title is needed.

    Solo vs. featuring collaborations are kept as DISTINCT releases — '(feat. X)' /
    '(ft. X)' / '(with X)' content is preserved in the dedup key.

    Preference order when two tracks share the key:
      1. Track with a track_number (album version)
      2. Track with album set
      3. First seen
    """
    best_by_key: dict[str, RemoteTrack] = {}
    skipped = 0
    for track in tracks:
        key = _dedup_key(track.title)
        if not key:
            best_by_key[track.video_id] = track
            continue
        existing = best_by_key.get(key)
        if existing is None:
            best_by_key[key] = track
            continue
        if _release_priority(track) > _release_priority(existing):
            best_by_key[key] = track
        skipped += 1
    if skipped:
        logger.info("Deduped %d cross-release duplicates", skipped)
    return list(best_by_key.values())


_FEAT_PAREN = re.compile(
    r"[\(\[]\s*(?:feat\.?|ft\.?|with)\b([^\)\]]*)[\)\]]",
    re.IGNORECASE,
)
_LANG_VERSION_PAREN = re.compile(
    r"[\(\[]\s*("
    r"swedish|german|french|spanish|italian|japanese|portuguese|english|"
    r"deutsch|deutsche"
    r")\s+version\s*[\)\]]",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")


def _dedup_key(title: str) -> str:
    """Like matcher.normalize() but preserves feat./ft./with collaborators AND
    language-version markers ('(Swedish Version)', '(German Version)', …) as distinct keys.
    """
    collabs = [m.group(1) for m in _FEAT_PAREN.finditer(title)]
    languages = [m.group(1) for m in _LANG_VERSION_PAREN.finditer(title)]
    base = normalize(title)  # strips all parens + non-alnum

    parts = [base]
    if collabs:
        collab_token = _WS.sub(" ", _NON_ALNUM.sub(" ", " ".join(collabs).lower())).strip()
        if collab_token:
            parts.append(f"feat:{collab_token}")
    if languages:
        lang_token = " ".join(sorted({lang.lower() for lang in languages}))
        parts.append(f"lang:{lang_token}")
    return "|".join(parts)


def _release_priority(track: RemoteTrack) -> tuple[int, int, int]:
    """Higher tuple = preferred. Lexicographic comparison.

    Ranking:
      1. Has track_number (album track > loose single)
      2. Has album set
      3. Older release year wins (Original Studio-Album beats Compilation)
         — Tracks without a known year are treated as 'very old' so they win
           against known-late Compilations, but lose to tracks with a known year.
    """
    has_track = 1 if track.track_number else 0
    has_album = 1 if track.album else 0
    # Negative year for descending sort. Missing year = 0 (treated as very old).
    year_score = -track.release_year if track.release_year else 0
    return (has_track, has_album, year_score)


def _make_downloader(config: Config) -> Downloader:
    return Downloader(
        temp_dir=config.temp_dir,
        min_free_space_mb=config.min_free_space_mb,
        pot_provider_url=config.pot_provider_url,
    )


def _download_missing(
    config: Config, db: StateDB, library_cache: LibraryCache, missing: list[MissingTrack]
) -> None:
    downloader = _make_downloader(config)
    success = 0
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Downloading", total=len(missing))
        for item in missing:
            progress.update(task, description=f"{item.remote.artist} — {item.remote.title}")
            ok = _download_single(config, db, library_cache, downloader, item)
            if ok:
                success += 1
            else:
                failed += 1
            progress.advance(task)

    console.print(f"\n[green]Erfolg: {success}[/green]  [red]Fehler: {failed}[/red]")


def _download_single(
    config: Config,
    db: StateDB,
    library_cache: LibraryCache,
    downloader: Downloader,
    item: MissingTrack,
) -> bool:
    remote = item.remote
    target = _target_path_for(config, item)
    db_artist = item.artist_config.name if item.artist_config else item.remote.artist

    if target.exists():
        logger.info("Target file already exists, skipping: %s", target)
        db.record_skip(remote.video_id, db_artist, remote.title, remote.album)
        return True

    def tag(path: Path) -> bool:
        try:
            return tag_file(path, remote)
        except Exception as exc:
            logger.warning("Tagging failed for %s: %s", path, exc)
            return False

    try:
        result = downloader.download(remote, target, tag=tag)
    except TargetExistsError as exc:
        logger.info("%s", exc)
        db.record_skip(remote.video_id, db_artist, remote.title, remote.album)
        return True
    except DiskSpaceError as exc:
        logger.error("Disk space error: %s", exc)
        console.print(f"[red]Disk-Space erschöpft: {exc}[/red]")
        db.record_failure(remote.video_id, db_artist, remote.title, remote.album, str(exc))
        return False
    except DownloadError as exc:
        logger.error("Download failed for %s: %s", remote.watch_url, exc)
        db.record_failure(remote.video_id, db_artist, remote.title, remote.album, str(exc))
        return False

    db.record_success(remote.video_id, db_artist, remote.title, remote.album, result.file_path)
    if result.tagged and result.file_path.is_relative_to(config.music_dir):
        # Exactly the values tag_file wrote — the next scan needn't open the file.
        library_cache.record_file(
            config.music_dir, result.file_path, remote.artist, remote.title, remote.album
        )
    logger.info("Downloaded: %s — %s → %s", db_artist, remote.title, result.file_path)
    return True


def _target_path_for(config: Config, item: MissingTrack) -> Path:
    remote = item.remote
    if item.playlist_config is not None:
        return build_playlist_target_path(
            base_dir=config.download_dir,
            playlist_name=item.playlist_config.name,
            title=remote.title,
            track_number=remote.track_number,
            artist=item.playlist_config.artist,
        )
    assert item.artist_config is not None
    return build_target_path(
        base_dir=config.download_dir,
        artist=item.artist_config.name,
        album=remote.album,
        title=remote.title,
        track_number=remote.track_number,
    )


def _print_missing_table(missing: list[MissingTrack]) -> None:
    """Render the missing-tracks table grouped by album / playlist."""
    table = Table(title="Fehlende Songs")
    table.add_column("Quelle")
    table.add_column("Künstler")
    table.add_column("Album / Playlist")
    table.add_column("Track", justify="right")
    table.add_column("Titel")

    def group_key(item: MissingTrack) -> tuple[str, str, str]:
        source = f"Playlist: {item.playlist_config.name}" if item.playlist_config else "Channel"
        artist = (
            item.remote.artist
            if item.playlist_config
            else (item.artist_config.name if item.artist_config else item.remote.artist)
        )
        album = item.remote.album or ""
        return (source, artist, album)

    def sort_key(item: MissingTrack):
        group = group_key(item)
        return (*group, item.remote.track_number or 9999, item.remote.title.lower())

    sorted_missing = sorted(missing, key=sort_key)

    previous_group: tuple[str, str, str] | None = None
    for item in sorted_missing:
        current = group_key(item)
        if previous_group is not None and current != previous_group:
            table.add_section()
        source = f"Playlist: {item.playlist_config.name}" if item.playlist_config else "Channel"
        table.add_row(
            source,
            item.remote.artist,
            item.remote.album or "—",
            str(item.remote.track_number) if item.remote.track_number else "—",
            item.remote.title,
        )
        previous_group = current
    console.print(table)
