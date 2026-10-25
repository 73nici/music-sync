from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .logger import get_logger
from .scanner import PARTIAL_SUFFIX
from .source_ytmusic import RemoteTrack

logger = get_logger("downloader")


class DiskSpaceError(RuntimeError):
    pass


class DownloadError(RuntimeError):
    pass


class TargetExistsError(DownloadError):
    pass


# webm + opus of one track coexist in the temp dir; long mixes reach a few hundred MB.
TEMP_MIN_FREE_MB = 200


@dataclass(frozen=True)
class DownloadResult:
    file_path: Path
    video_id: str
    tagged: bool = False


class Downloader:
    """Downloads, converts and tags in `temp_dir`, then copies the finished file into the
    library in one sequential write and publishes it with an atomic link/rename.

    Neither our scanner nor Jellyfin ever sees yt-dlp's intermediate files.
    """

    def __init__(
        self,
        temp_dir: Path,
        min_free_space_mb: int = 500,
        pot_provider_url: str | None = None,
    ) -> None:
        # Own subfolder, so cleaning up can never touch anything else in temp_dir.
        self._work_root = temp_dir / "downloads"
        self._min_free_bytes = min_free_space_mb * 1024 * 1024
        self._pot_provider_url = pot_provider_url
        # Runs hold the run lock, so leftovers can only stem from a crashed run.
        shutil.rmtree(self._work_root, ignore_errors=True)
        self._work_root.mkdir(parents=True, exist_ok=True)

    def download(
        self,
        track: RemoteTrack,
        target_path: Path,
        tag: Callable[[Path], bool] | None = None,
    ) -> DownloadResult:
        """Download `track` to `target_path` (must end in '.opus').

        `tag` runs on the temp file before it is copied, so tagging never rewrites the
        file on the library disk. Raises TargetExistsError if the target already exists.
        """
        if target_path.suffix.lower() != ".opus":
            raise ValueError(f"target_path must end in .opus, got: {target_path}")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        self._check_disk_space(target_path.parent, self._min_free_bytes)
        self._check_disk_space(self._work_root, TEMP_MIN_FREE_MB * 1024 * 1024)

        # Named after the video id: short, unique and free of NAME_MAX trouble.
        work_dir = self._work_root / track.video_id
        shutil.rmtree(work_dir, ignore_errors=True)
        work_dir.mkdir(parents=True)
        try:
            temp_file = self._fetch(track, work_dir)
            tagged = tag(temp_file) if tag is not None else False
            _publish(temp_file, target_path)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        return DownloadResult(file_path=target_path, video_id=track.video_id, tagged=tagged)

    def _fetch(self, track: RemoteTrack, work_dir: Path) -> Path:
        import yt_dlp  # heavy import (~850 files): only when actually downloading

        output = work_dir / f"{track.video_id}.opus"
        outtmpl = str(work_dir / f"{track.video_id}.%(ext)s")

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

        if not output.exists():
            raise DownloadError(f"Expected output {output} not found after download")
        return output

    @staticmethod
    def _check_disk_space(directory: Path, min_free_bytes: int) -> None:
        usage = shutil.disk_usage(directory)
        if usage.free < min_free_bytes:
            raise DiskSpaceError(
                f"Insufficient disk space in {directory}: {usage.free // (1024 * 1024)} MB "
                f"free, need at least {min_free_bytes // (1024 * 1024)} MB"
            )


def _publish(temp_file: Path, target_path: Path) -> None:
    """Copy into a hidden '.<name>.partial' next to the target, then publish atomically.

    The partial name has no audio extension, so scanners ignore it. It is 9 bytes longer
    than the target name, which fits the headroom reserved in filters.MAX_FILENAME_BYTES.
    os.link fails instead of silently overwriting an existing target; filesystems
    without hard links fall back to an exists-check plus rename.
    """
    partial = target_path.with_name(f".{target_path.name}{PARTIAL_SUFFIX}")
    try:
        shutil.copyfile(temp_file, partial)
        try:
            os.link(partial, target_path)
        except FileExistsError as exc:
            raise TargetExistsError(f"Target appeared meanwhile: {target_path}") from exc
        except OSError:
            if target_path.exists():
                raise TargetExistsError(f"Target appeared meanwhile: {target_path}") from None
            os.rename(partial, target_path)
    except OSError as exc:
        raise DownloadError(f"Failed to move download into {target_path}: {exc}") from exc
    finally:
        partial.unlink(missing_ok=True)
