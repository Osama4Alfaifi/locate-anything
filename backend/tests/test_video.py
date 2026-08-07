from pathlib import Path

import cv2
import numpy as np
import pytest

import video


def _write_video(path: Path, *, n_frames: int = 30, fps: float = 10.0, size: tuple[int, int] = (64, 48)) -> None:
    w, h = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for i in range(n_frames):
        frame = np.full((h, w, 3), i % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()


@pytest.fixture
def clip_path(tmp_path):
    path = tmp_path / "clip.mp4"
    _write_video(path)
    return path


def test_probe_reads_metadata(clip_path):
    meta = video.probe(clip_path)
    assert meta["fps"] == pytest.approx(10.0)
    assert meta["frame_count"] == 30
    assert meta["width"] == 64
    assert meta["height"] == 48
    assert meta["duration_s"] == pytest.approx(3.0)


def test_probe_rejects_missing_file(tmp_path):
    with pytest.raises(video.VideoDecodeError):
        video.probe(tmp_path / "does-not-exist.mp4")


def test_effective_sample_fps_thins_when_over_budget():
    # 3s @ requested 10fps = 30 frames, budget is 6 -> thinned to 2fps
    assert video.effective_sample_fps(3.0, 10.0, 6) == pytest.approx(2.0)
    # under budget -> unchanged
    assert video.effective_sample_fps(3.0, 1.0, 6) == pytest.approx(1.0)


def test_extract_frames_samples_at_requested_rate(clip_path, tmp_path):
    out_dir = tmp_path / "frames"
    frames, meta = video.extract_frames(clip_path, out_dir, sample_fps=2.0, max_frames=150)

    # 3s clip @ 2fps -> ~6 frames
    assert 5 <= len(frames) <= 7
    assert meta["sample_fps"] == pytest.approx(2.0)

    timestamps = [f["timestamp_ms"] for f in frames]
    assert timestamps == sorted(timestamps)
    assert [f["frame_index"] for f in frames] == list(range(len(frames)))

    for f in frames:
        assert Path(f["path"]).exists()
        assert f["width"] == 64
        assert f["height"] == 48


def test_extract_frames_respects_max_frames_cap(clip_path, tmp_path):
    out_dir = tmp_path / "frames"
    frames, meta = video.extract_frames(clip_path, out_dir, sample_fps=10.0, max_frames=5)
    assert len(frames) <= 5
    # requested 10fps over 3s would be 30 frames > cap of 5, so the rate is thinned
    assert meta["sample_fps"] < 10.0


def test_extract_frames_downscales_large_frames(tmp_path):
    path = tmp_path / "big.mp4"
    _write_video(path, n_frames=5, fps=5.0, size=(2000, 1000))
    out_dir = tmp_path / "frames"
    frames, _meta = video.extract_frames(path, out_dir, sample_fps=5.0, max_frames=50)
    for f in frames:
        assert max(f["width"], f["height"]) <= 1280


def test_extract_frames_raises_on_undecodable_file(tmp_path):
    bogus = tmp_path / "bogus.mp4"
    bogus.write_bytes(b"not a real video file")
    with pytest.raises(video.VideoDecodeError):
        video.extract_frames(bogus, tmp_path / "frames", sample_fps=1.0, max_frames=10)
