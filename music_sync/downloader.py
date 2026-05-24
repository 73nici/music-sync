from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from .logger import get_logger
from .source_ytmusic import RemoteTrack

logger = get_logger("downloader")


class DiskSpaceError(RuntimeError):
    pass


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadResult:
    file_path: Path
    video_id: str


class Downloader:
    def __init__(
        self,
        cookies_file: Path | None = None,
        min_free_space_mb: int = 500,
        pot_provider_url: str | None = None,
    ) -> None:
        self._cookies_file = cookies_file
        self._min_free_bytes = min_free_space_mb * 1024 * 1024
        self._pot_provider_url = pot_provider_url

    def download(self, track: RemoteTrack, target_path: Path) -> DownloadResult:
        """Download `track` to `target_path` (must end in '.opus'). Returns final file path."""
        if target_path.suffix.lower() != ".opus":
            raise ValueError(f"target_path must end in .opus, got: {target_path}")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        self._check_disk_space(target_path.parent)

        # IMPORTANT: do NOT use Path.with_suffix here — it treats the last '.' as the
        # extension, which mangles names like 'Song (feat. Artist).opus'.
        outtmpl = f"{str(target_path)[:-len('.opus')]}.%(ext)s"

        opts: dict = {
            "format": "bestaudio[ext=webm]/bestaudio/best",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "opus",
                    "preferredquality": "0",
                }
            ],
            "retries": 3,
            "fragment_retries": 3,
        }

        if self._cookies_file and self._cookies_file.exists():
            opts["cookiefile"] = str(self._cookies_file)

        if self._pot_provider_url:
            opts["extractor_args"] = {
                "youtubepot-bgutilhttp": {"base_url": [self._pot_provider_url]},
            }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([track.watch_url])
        except yt_dlp.utils.DownloadError as exc:
            raise DownloadError(str(exc)) from exc
        except Exception as exc:
            raise DownloadError(f"unexpected error: {exc}") from exc

        if not target_path.exists():
            raise DownloadError(f"Expected output {target_path} not found after download")

        return DownloadResult(file_path=target_path, video_id=track.video_id)

    def _check_disk_space(self, directory: Path) -> None:
        usage = shutil.disk_usage(directory)
        if usage.free < self._min_free_bytes:
            raise DiskSpaceError(
                f"Insufficient disk space: {usage.free // (1024*1024)} MB free, "
                f"need at least {self._min_free_bytes // (1024*1024)} MB"
            )
