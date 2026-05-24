from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ytmusicapi import YTMusic

from .filters import is_studio_version
from .logger import get_logger

logger = get_logger("source_ytmusic")


@dataclass(frozen=True)
class RemoteTrack:
    video_id: str
    title: str
    artist: str
    album: str | None
    track_number: int | None
    duration_seconds: int | None
    cover_url: str | None
    source: str = "ytmusic"
    release_year: int | None = None

    @property
    def watch_url(self) -> str:
        return f"https://music.youtube.com/watch?v={self.video_id}"


class YTMusicSource:
    def __init__(self, filter_keywords: list[str]) -> None:
        self._client = YTMusic()
        self._filter_keywords = filter_keywords

    def fetch_playlist_tracks(
        self,
        playlist_id: str,
        playlist_name: str,
        apply_filter: bool = True,
    ) -> list[RemoteTrack]:
        """Fetch tracks of a YT-Music playlist. Original artists kept as-is."""
        try:
            data = self._client.get_playlist(playlist_id, limit=None)
        except Exception as exc:
            logger.error("Failed to get_playlist(%s): %s", playlist_id, exc)
            return []

        entries = data.get("tracks") or []
        results: list[RemoteTrack] = []

        for idx, entry in enumerate(entries, start=1):
            video_id = entry.get("videoId")
            title = entry.get("title")
            if not video_id or not title:
                continue
            if apply_filter and not is_studio_version(title, self._filter_keywords):
                logger.debug("Playlist '%s' filtered (non-studio): %s", playlist_name, title)
                continue

            artists_list = entry.get("artists") or []
            artist_str = ", ".join(a.get("name", "") for a in artists_list if a.get("name"))
            if not artist_str:
                artist_str = playlist_name

            cover_url = _largest_thumbnail(entry.get("thumbnails") or [])
            duration = _parse_duration(entry.get("duration"))

            results.append(
                RemoteTrack(
                    video_id=video_id,
                    title=title,
                    artist=artist_str,
                    album=playlist_name,
                    track_number=idx,
                    duration_seconds=duration,
                    cover_url=cover_url,
                )
            )

        logger.info("Playlist '%s' yielded %d tracks (apply_filter=%s)", playlist_name, len(results), apply_filter)
        return results

    def fetch_artist_tracks(self, channel_id: str, artist_name: str) -> list[RemoteTrack]:
        """Fetch all studio tracks of an artist from YT Music (albums + singles).

        Returns the raw list including duplicates across album/compilation releases.
        Downstream `_dedup_releases` picks the best version (priority: track_number,
        album, then oldest release_year) — that is how an Original Studio Album beats
        a later Compilation appearance.
        """
        try:
            artist_data = self._client.get_artist(channel_id)
        except Exception as exc:
            logger.error("Failed to get_artist(%s): %s", channel_id, exc)
            return []

        tracks: list[RemoteTrack] = []

        album_browse_ids = self._collect_album_ids(artist_data)
        logger.info("Artist '%s' has %d albums/EPs to inspect", artist_name, len(album_browse_ids))

        for browse_id in album_browse_ids:
            for track in self._fetch_album_tracks(browse_id, artist_name):
                if not is_studio_version(track.title, self._filter_keywords):
                    logger.debug("Filtered (non-studio): %s", track.title)
                    continue
                tracks.append(track)

        for track in self._collect_singles(artist_data, artist_name):
            if not is_studio_version(track.title, self._filter_keywords):
                continue
            tracks.append(track)

        logger.info("Artist '%s' yielded %d studio tracks (pre-dedup)", artist_name, len(tracks))
        return tracks

    def _collect_album_ids(self, artist_data: dict[str, Any]) -> list[str]:
        """Collect album browseIds from both inline lists and the full library endpoint.

        YT Music caps inline `artist.albums.results` at ~10 entries for big catalogs.
        For full coverage we also do an extra browse request to the artist's complete
        album page (`MPAD<channel_id>`) when the section exposes a continuation `params`.
        """
        ids: list[str] = []
        seen: set[str] = set()

        def add(browse_id: str | None) -> None:
            if browse_id and browse_id not in seen:
                seen.add(browse_id)
                ids.append(browse_id)

        for section in ("albums", "singles"):
            section_data = artist_data.get(section) or {}
            for entry in section_data.get("results", []) or []:
                add(entry.get("browseId"))

            full_browse_id = section_data.get("browseId")
            params = section_data.get("params")
            if full_browse_id and params:
                for browse_id in self._fetch_full_album_list(full_browse_id, params):
                    add(browse_id)

        return ids

    def _fetch_full_album_list(self, browse_id: str, params: str) -> list[str]:
        """Browse the artist's full album/singles page and return all album browseIds."""
        try:
            response = self._client._send_request("browse", {"browseId": browse_id, "params": params})
        except Exception as exc:
            logger.warning("Full album list browse failed (%s): %s", browse_id, exc)
            return []

        ids: list[str] = []
        try:
            tabs = response["contents"]["singleColumnBrowseResultsRenderer"]["tabs"]
            sections = tabs[0]["tabRenderer"]["content"]["sectionListRenderer"]["contents"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("Unexpected full album list structure for %s: %s", browse_id, exc)
            return ids

        for section in sections:
            grid = section.get("gridRenderer") or {}
            for item in grid.get("items", []) or []:
                row = item.get("musicTwoRowItemRenderer") or {}
                nav = row.get("navigationEndpoint") or {}
                inner_id = (nav.get("browseEndpoint") or {}).get("browseId")
                if inner_id:
                    ids.append(inner_id)

        logger.info("Fetched %d album ids from full list (%s)", len(ids), browse_id)
        return ids

    def _fetch_album_tracks(self, browse_id: str, artist_name: str) -> list[RemoteTrack]:
        try:
            album = self._client.get_album(browse_id)
        except Exception as exc:
            logger.warning("Failed to get_album(%s): %s", browse_id, exc)
            return []

        album_title = album.get("title")
        cover_url = _largest_thumbnail(album.get("thumbnails") or [])
        release_year = _parse_year(album.get("year"))

        results: list[RemoteTrack] = []
        for idx, raw_track in enumerate(album.get("tracks") or [], start=1):
            video_id = raw_track.get("videoId")
            title = raw_track.get("title")
            if not video_id or not title:
                continue
            duration = _parse_duration(raw_track.get("duration"))
            results.append(
                RemoteTrack(
                    video_id=video_id,
                    title=title,
                    artist=artist_name,
                    album=album_title,
                    track_number=raw_track.get("trackNumber") or idx,
                    duration_seconds=duration,
                    cover_url=cover_url,
                    release_year=release_year,
                )
            )
        return results

    def _collect_singles(
        self, artist_data: dict[str, Any], artist_name: str
    ) -> list[RemoteTrack]:
        """Some singles may live in 'songs' section and not be linked to a release."""
        results: list[RemoteTrack] = []
        songs_section = artist_data.get("songs") or {}
        for entry in songs_section.get("results", []) or []:
            video_id = entry.get("videoId")
            title = entry.get("title")
            if not video_id or not title:
                continue
            album_entry = entry.get("album") or {}
            album_title = album_entry.get("name") if isinstance(album_entry, dict) else None
            cover_url = _largest_thumbnail(entry.get("thumbnails") or [])
            results.append(
                RemoteTrack(
                    video_id=video_id,
                    title=title,
                    artist=artist_name,
                    album=album_title,
                    track_number=None,
                    duration_seconds=None,
                    cover_url=cover_url,
                )
            )
        return results


def _largest_thumbnail(thumbs: list[dict[str, Any]]) -> str | None:
    if not thumbs:
        return None
    best = max(thumbs, key=lambda t: int(t.get("width", 0) or 0))
    return best.get("url")


def _parse_year(value) -> int | None:
    """YT Music sometimes returns int, sometimes str. Some entries return None."""
    if value is None:
        return None
    try:
        return int(str(value).strip()[:4])
    except (ValueError, IndexError):
        return None


def _parse_duration(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None
