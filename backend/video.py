"""Video probing and frame extraction (OpenCV-based, CPU-only).

Runs identically in mock and real mode — mock mode only fakes the *model*
(see mock_engine.py), not the video source, so cv2 is a light/always-on
dependency here rather than lazily imported like torch/transformers in
worker.py.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import cv2

_MAX_LONG_EDGE = 1280
_JPEG_QUALITY = 85


class VideoDecodeError(ValueError):
    pass


def probe(video_path: Path) -> dict:
    """Cheap metadata read (container header only, no frame decoding)."""
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise VideoDecodeError(f"Could not open video: {video_path.name}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
            raise VideoDecodeError(f"Unreadable or empty video: {video_path.name}")
        return {
            "duration_s": frame_count / fps,
            "fps": fps,
            "frame_count": frame_count,
            "width": width,
            "height": height,
        }
    finally:
        cap.release()


def effective_sample_fps(duration_s: float, requested_fps: float, max_frames: int) -> float:
    """Thin the sample rate so `duration_s * fps` never exceeds `max_frames`."""
    if duration_s <= 0 or requested_fps <= 0:
        return requested_fps
    if duration_s * requested_fps <= max_frames:
        return requested_fps
    return max_frames / duration_s


def _resize_dims(width: int, height: int) -> tuple[int, int]:
    long_edge = max(width, height)
    if long_edge <= _MAX_LONG_EDGE:
        return width, height
    scale = _MAX_LONG_EDGE / long_edge
    return max(1, round(width * scale)), max(1, round(height * scale))


def extract_frames(
    video_path: Path, out_dir: Path, sample_fps: float, max_frames: int
) -> tuple[list[dict], dict]:
    """Sample frames from `video_path` at ~`sample_fps` and save them as JPEGs
    under `out_dir`.

    Returns `(frames, meta)`:
    - `frames`: [{id, frame_index, timestamp_ms, path, width, height}, ...],
      ordered by timestamp.
    - `meta`: the probed video info plus the *effective* sample_fps actually
      used (thinned down via `effective_sample_fps` if the requested rate
      would exceed `max_frames` over the clip's duration).
    """
    meta = probe(video_path)
    fps = effective_sample_fps(meta["duration_s"], sample_fps, max_frames)
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise VideoDecodeError(f"Could not open video: {video_path.name}")

    src_fps = meta["fps"]
    step = max(1, round(src_fps / fps)) if fps > 0 else 1
    out_w, out_h = _resize_dims(meta["width"], meta["height"])
    needs_resize = (out_w, out_h) != (meta["width"], meta["height"])

    frames: list[dict] = []
    try:
        src_index = 0
        while len(frames) < max_frames:
            # grab() is a cheap demux-only step; retrieve() (the actual decode)
            # only runs for frames we're keeping, so skipped frames stay fast.
            if not cap.grab():
                break
            if src_index % step == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                if needs_resize:
                    frame = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)
                out_index = len(frames)
                frame_path = out_dir / f"{out_index:05d}.jpg"
                cv2.imwrite(str(frame_path), frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
                frames.append(
                    {
                        "id": uuid.uuid4().hex,
                        "frame_index": out_index,
                        "timestamp_ms": round(src_index / src_fps * 1000),
                        "path": frame_path,
                        "width": out_w,
                        "height": out_h,
                    }
                )
            src_index += 1
    finally:
        cap.release()

    if not frames:
        raise VideoDecodeError(f"No frames could be extracted from: {video_path.name}")
    return frames, {**meta, "sample_fps": fps}
