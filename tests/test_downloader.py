from pathlib import Path

import pytest
from music_sync import downloader as downloader_module
from music_sync.downloader import Downloader, TargetExistsError, _publish
from music_sync.source_ytmusic import RemoteTrack

TRACK = RemoteTrack(
    video_id="vid123",
    title="Song",
    artist="Artist",
    album="Album",
    track_number=1,
    duration_seconds=180,
    cover_url=None,
)


@pytest.fixture
def fake_fetch(monkeypatch):
    def fetch(self, track, work_dir: Path) -> Path:
        output = work_dir / f"{track.video_id}.opus"
        (work_dir / f"{track.video_id}.webm").write_bytes(b"intermediate")
        output.write_bytes(b"opus data")
        return output

    monkeypatch.setattr(Downloader, "_fetch", fetch)


def test_publish_is_atomic_and_leaves_no_partial(tmp_path):
    source = tmp_path / "tmp.opus"
    source.write_bytes(b"opus data")
    target = tmp_path / "lib" / "Song.opus"
    target.parent.mkdir()

    _publish(source, target)
    assert target.read_bytes() == b"opus data"
    assert [p.name for p in target.parent.iterdir()] == ["Song.opus"]


def test_publish_never_overwrites(tmp_path):
    source = tmp_path / "tmp.opus"
    source.write_bytes(b"new")
    target = tmp_path / "Song.opus"
    target.write_bytes(b"existing")

    with pytest.raises(TargetExistsError):
        _publish(source, target)
    assert target.read_bytes() == b"existing"
    assert not (tmp_path / ".Song.opus.partial").exists()


def test_publish_falls_back_to_rename_without_hard_links(tmp_path, monkeypatch):
    def no_links(*args):
        raise PermissionError("hard links not supported")

    monkeypatch.setattr(downloader_module.os, "link", no_links)
    source = tmp_path / "tmp.opus"
    source.write_bytes(b"opus data")
    target = tmp_path / "Song.opus"

    _publish(source, target)
    assert target.read_bytes() == b"opus data"
    assert not (tmp_path / ".Song.opus.partial").exists()


def test_download_tags_in_temp_dir_and_cleans_up(tmp_path, fake_fetch):
    temp_dir = tmp_path / "tmpfs"
    library = tmp_path / "music"
    downloader = Downloader(temp_dir=temp_dir, min_free_space_mb=0)
    tagged_paths: list[Path] = []

    def tag(path: Path) -> bool:
        tagged_paths.append(path)
        return True

    result = downloader.download(TRACK, library / "Artist" / "Song.opus", tag=tag)

    assert result.tagged is True
    assert tagged_paths[0].is_relative_to(temp_dir)  # tagging never touches the library
    assert result.file_path.read_bytes() == b"opus data"
    assert [p.name for p in (library / "Artist").iterdir()] == ["Song.opus"]
    assert list((temp_dir / "downloads").iterdir()) == []


def test_download_cleans_up_after_failure(tmp_path, monkeypatch):
    def failing_fetch(self, track, work_dir):
        (work_dir / "half.webm.part").write_bytes(b"x")
        raise downloader_module.DownloadError("network")

    monkeypatch.setattr(Downloader, "_fetch", failing_fetch)
    temp_dir = tmp_path / "tmpfs"
    downloader = Downloader(temp_dir=temp_dir, min_free_space_mb=0)

    with pytest.raises(downloader_module.DownloadError):
        downloader.download(TRACK, tmp_path / "music" / "Song.opus")
    assert list((temp_dir / "downloads").iterdir()) == []


def test_downloader_only_clears_its_own_subfolder(tmp_path):
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    (temp_dir / "unrelated.txt").write_text("keep me")
    (temp_dir / "downloads" / "old").mkdir(parents=True)

    Downloader(temp_dir=temp_dir)
    assert (temp_dir / "unrelated.txt").exists()
    assert list((temp_dir / "downloads").iterdir()) == []
