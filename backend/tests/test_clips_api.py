import io
import time

import cv2
import numpy as np
import pytest


def _make_clip_bytes(*, n_frames: int = 20, fps: float = 10.0, size: tuple[int, int] = (64, 48)) -> bytes:
    import tempfile
    from pathlib import Path

    w, h = size
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "clip.mp4"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        for i in range(n_frames):
            frame = np.full((h, w, 3), i % 255, dtype=np.uint8)
            writer.write(frame)
        writer.release()
        return path.read_bytes()


@pytest.fixture
def clip_bytes():
    return _make_clip_bytes()


def _upload(client, data, filename="dashcam.mp4", content_type="video/mp4"):
    return client.post("/api/clips", files={"video": (filename, data, content_type)})


def _wait_for_clip_ready(client, clip_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/clips/{clip_id}").json()
        if body["status"] != "extracting":
            return body
        time.sleep(0.05)
    raise TimeoutError(f"clip {clip_id} never left 'extracting'")


def _wait_for_search_done(client, clip_id, search_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/clips/{clip_id}/searches/{search_id}").json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"search {search_id} never finished")


def test_upload_and_ingest_produces_ready_clip(client, clip_bytes):
    r = _upload(client, clip_bytes)
    assert r.status_code == 200
    clip = r.json()
    assert clip["status"] == "extracting"

    clip = _wait_for_clip_ready(client, clip["id"])
    assert clip["status"] == "ready"
    assert clip["frame_count"] > 0
    assert clip["duration_s"] == pytest.approx(2.0, abs=0.2)


def test_upload_rejects_undecodable_file(client):
    r = _upload(client, b"not a real video", filename="bad.mp4")
    assert r.status_code == 400


def test_get_clip_video_and_frame_images(client, clip_bytes):
    clip = _wait_for_clip_ready(client, _upload(client, clip_bytes).json()["id"])
    assert client.get(clip["video_url"]).status_code == 200

    frames_resp = client.get(f"/api/clips/{clip['id']}/searches")
    assert frames_resp.status_code == 200  # no searches yet, but clip exists


def test_search_runs_and_returns_matches(client, clip_bytes):
    clip = _wait_for_clip_ready(client, _upload(client, clip_bytes).json()["id"])

    r = client.post(
        f"/api/clips/{clip['id']}/search",
        data={"task": "ground_multi", "prompt": "a car", "generation_mode": "fast"},
    )
    assert r.status_code == 200
    search = r.json()
    assert search["status"] in ("queued", "running")

    search = _wait_for_search_done(client, clip["id"], search["id"])
    assert search["status"] == "done"
    assert search["frames_done"] == search["frames_total"]
    assert search["matches"]
    for m in search["matches"]:
        assert client.get(m["image_url"]).status_code == 200
        assert m["boxes"] or m["points"]


def test_search_against_non_ready_clip_rejected(client, clip_bytes):
    clip_id = _upload(client, clip_bytes).json()["id"]
    r = client.post(
        f"/api/clips/{clip_id}/search",
        data={"task": "ground_multi", "prompt": "a car", "generation_mode": "fast"},
    )
    assert r.status_code in (400, 409)


def test_search_requires_prompt_for_phrase_task(client, clip_bytes):
    clip = _wait_for_clip_ready(client, _upload(client, clip_bytes).json()["id"])
    r = client.post(
        f"/api/clips/{clip['id']}/search",
        data={"task": "ground_multi", "prompt": "   ", "generation_mode": "fast"},
    )
    assert r.status_code == 400


def test_concurrent_search_rejected_with_409(client, clip_bytes):
    clip = _wait_for_clip_ready(client, _upload(client, clip_bytes).json()["id"])
    first = client.post(
        f"/api/clips/{clip['id']}/search",
        data={"task": "ground_multi", "prompt": "a car", "generation_mode": "fast"},
    )
    assert first.status_code == 200
    second = client.post(
        f"/api/clips/{clip['id']}/search",
        data={"task": "ground_multi", "prompt": "a bike", "generation_mode": "fast"},
    )
    assert second.status_code == 409
    _wait_for_search_done(client, clip["id"], first.json()["id"])


def test_delete_clip_cascades(client, clip_bytes):
    clip = _wait_for_clip_ready(client, _upload(client, clip_bytes).json()["id"])
    assert client.delete(f"/api/clips/{clip['id']}").status_code == 200
    assert client.get(f"/api/clips/{clip['id']}").status_code == 404
    assert client.delete(f"/api/clips/{clip['id']}").status_code == 404


def test_clip_not_found_returns_404(client):
    assert client.get("/api/clips/does-not-exist").status_code == 404
    assert client.get("/api/clips/does-not-exist/video").status_code == 404
    assert client.get("/api/clips/does-not-exist/frames/nope").status_code == 404


def test_list_clips_includes_uploaded(client, clip_bytes):
    clip_id = _upload(client, clip_bytes).json()["id"]
    body = client.get("/api/clips").json()
    assert any(c["id"] == clip_id for c in body["items"])


def test_max_clip_seconds_override_rejects_long_clip(client, clip_bytes):
    # Settings is a frozen dataclass singleton (lru_cache) shared with app.state,
    # so mutate + restore it directly rather than via monkeypatch.setattr.
    import app as app_module

    settings = app_module.get_settings()
    original = settings.max_clip_seconds
    object.__setattr__(settings, "max_clip_seconds", 0.5)
    try:
        r = _upload(client, clip_bytes)
        assert r.status_code == 400
    finally:
        object.__setattr__(settings, "max_clip_seconds", original)
