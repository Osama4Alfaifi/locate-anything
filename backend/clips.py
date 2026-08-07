"""Dashcam clip endpoints: upload -> frame extraction -> natural-language
search across frames, all as pollable background jobs (see app.py's
EngineService for the same "background thread, poll status" shape).
"""

from __future__ import annotations

import threading
import traceback
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image

from config import VALID_MODES
from schemas import ClipInfo, ClipList, ClipMatch, ClipSearchList, ClipSearchStatus
from storage import Store
from tasks import DEFAULT_TASK, TASKS, build_prompt, parse_output
from video import VideoDecodeError, extract_frames, probe

router = APIRouter()

_VIDEO_EXT_BY_TYPE = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/webm": ".webm",
}
_ALLOWED_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
_CHUNK_SIZE = 1024 * 1024


def _clip_video_url(clip_id: str) -> str:
    return f"/api/clips/{clip_id}/video"


def _frame_image_url(clip_id: str, frame_id: str) -> str:
    return f"/api/clips/{clip_id}/frames/{frame_id}"


def _to_clip_info(row: dict) -> ClipInfo:
    return ClipInfo(
        id=row["id"],
        filename=row["filename"],
        status=row["status"],
        error=row["error"],
        duration_s=row["duration_s"],
        fps=row["fps"],
        width=row["width"],
        height=row["height"],
        sample_fps=row["sample_fps"],
        frame_count=row["frame_count"],
        video_url=_clip_video_url(row["id"]),
        created_at=row["created_at"],
    )


def _to_search_status(row: dict, clip_id: str) -> ClipSearchStatus:
    matches = None
    if row["matches"] is not None:
        matches = [
            ClipMatch(
                frame_id=m["frame_id"],
                frame_index=m["frame_index"],
                timestamp_ms=m["timestamp_ms"],
                image_url=_frame_image_url(clip_id, m["frame_id"]),
                width=m["width"],
                height=m["height"],
                boxes=m["boxes"],
                points=m["points"],
                raw=m["raw"],
            )
            for m in row["matches"]
        ]
    return ClipSearchStatus(
        id=row["id"],
        clip_id=row["clip_id"],
        task=row["task"],
        prompt=row["prompt"],
        generation_mode=row["generation_mode"],
        status=row["status"],
        error=row["error"],
        frames_total=row["frames_total"],
        frames_done=row["frames_done"],
        matches=matches,
        created_at=row["created_at"],
        finished_at=row["finished_at"],
    )


def _run_ingest(state, clip_id: str, lock: threading.Lock) -> None:
    """Background job: decode + sample frames for a freshly uploaded clip.

    Releases the specific `lock` instance the caller acquired (rather than
    reading `state.job_lock` at release time), so this can't mis-release a
    lock that was reassigned on `state` after this thread started.
    """
    store: Store = state.store
    settings = state.settings
    try:
        clip = store.get_clip(clip_id)
        if clip is None:
            return
        video_path = Path(clip["video_path"])
        frames_dir = store.clip_frames_dir_for(clip_id)
        frames, meta = extract_frames(
            video_path, frames_dir, settings.sample_fps, settings.max_search_frames
        )
        store.save_frames(clip_id, frames)
        store.update_clip_status(
            clip_id,
            "ready",
            duration_s=meta["duration_s"],
            fps=meta["fps"],
            width=meta["width"],
            height=meta["height"],
            sample_fps=meta["sample_fps"],
            frame_count=len(frames),
        )
    except Exception as exc:  # noqa: BLE001
        store.update_clip_status(clip_id, "error", error=str(exc))
        traceback.print_exc()
    finally:
        lock.release()


def _run_search(
    state,
    clip_id: str,
    search_id: str,
    task: str,
    prompt: str,
    mode: str,
    frames: list[dict],
    lock: threading.Lock,
) -> None:
    """Background job: run the existing single-frame grounding pipeline over
    every sampled frame, recording any frame with a non-empty result.

    Releases the specific `lock` instance the caller acquired (see `_run_ingest`).
    """
    store: Store = state.store
    svc = state.svc
    spec = TASKS[task]
    full_prompt = build_prompt(task, prompt)
    matches: list[dict] = []
    try:
        for i, frame in enumerate(frames):
            if search_id in state.cancelled_searches:
                store.finish_search(search_id, "cancelled", matches=matches)
                return
            pil = Image.open(frame["image_path"]).convert("RGB")
            out = svc.engine.predict(pil, full_prompt, mode, output_type=spec.output_type)
            parsed = parse_output(task, out.get("raw", ""), frame["width"], frame["height"])
            if parsed["boxes"] or parsed["points"]:
                matches.append(
                    {
                        "frame_id": frame["id"],
                        "frame_index": frame["frame_index"],
                        "timestamp_ms": frame["timestamp_ms"],
                        "width": frame["width"],
                        "height": frame["height"],
                        "boxes": parsed["boxes"],
                        "points": parsed["points"],
                        "raw": out.get("raw", ""),
                    }
                )
            store.update_search_progress(search_id, frames_done=i + 1)
        store.finish_search(search_id, "done", matches=matches)
    except Exception as exc:  # noqa: BLE001
        store.finish_search(search_id, "error", matches=matches, error=str(exc))
        traceback.print_exc()
    finally:
        state.cancelled_searches.discard(search_id)
        lock.release()


@router.post("/clips", response_model=ClipInfo)
async def upload_clip(request: Request, video: UploadFile = File(...)) -> ClipInfo:
    state = request.app.state
    store: Store = state.store
    settings = state.settings
    max_bytes = int(settings.max_upload_mb * 1024 * 1024)

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            # small margin for multipart boundary/header overhead
            too_big = int(content_length) > max_bytes + 1024 * 1024
        except ValueError:
            too_big = False
        if too_big:
            raise HTTPException(
                status_code=413, detail=f"Upload exceeds {settings.max_upload_mb:.0f}MB limit."
            )

    lock = state.job_lock
    if not lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail="Another clip job is already running — try again shortly."
        )

    suffix = _VIDEO_EXT_BY_TYPE.get(video.content_type or "")
    if suffix is None:
        orig_suffix = Path(video.filename or "").suffix.lower()
        suffix = orig_suffix if orig_suffix in _ALLOWED_SUFFIXES else ".mp4"
    clip_id = store.new_id()
    video_path = store.clip_video_path_for(clip_id, suffix)

    try:
        written = 0
        with video_path.open("wb") as f:
            while True:
                chunk = await video.read(_CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds {settings.max_upload_mb:.0f}MB limit.",
                    )
                f.write(chunk)

        meta = probe(video_path)
        if meta["duration_s"] > settings.max_clip_seconds:
            raise HTTPException(
                status_code=400,
                detail=f"Clip is {meta['duration_s']:.0f}s, longer than the "
                f"{settings.max_clip_seconds:.0f}s limit.",
            )
    except VideoDecodeError as exc:
        video_path.unlink(missing_ok=True)
        lock.release()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except HTTPException:
        video_path.unlink(missing_ok=True)
        lock.release()
        raise
    finally:
        await video.close()

    row = store.save_clip(
        clip_id=clip_id,
        filename=video.filename or "clip",
        video_path=video_path,
        size_bytes=written,
        sample_fps=settings.sample_fps,
    )
    store.update_clip_status(
        clip_id,
        "extracting",
        duration_s=meta["duration_s"],
        fps=meta["fps"],
        width=meta["width"],
        height=meta["height"],
    )
    threading.Thread(target=_run_ingest, args=(state, clip_id, lock), daemon=True).start()
    return _to_clip_info(row)


@router.get("/clips", response_model=ClipList)
def list_clips(request: Request, limit: int = 50, offset: int = 0) -> ClipList:
    store: Store = request.app.state.store
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    rows, total = store.list_clips(limit=limit, offset=offset)
    return ClipList(items=[_to_clip_info(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/clips/{clip_id}", response_model=ClipInfo)
def get_clip(request: Request, clip_id: str) -> ClipInfo:
    store: Store = request.app.state.store
    row = store.get_clip(clip_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return _to_clip_info(row)


@router.delete("/clips/{clip_id}")
def delete_clip(request: Request, clip_id: str) -> dict:
    store: Store = request.app.state.store
    if not store.delete_clip(clip_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": clip_id}


@router.get("/clips/{clip_id}/video")
def get_clip_video(request: Request, clip_id: str):
    store: Store = request.app.state.store
    row = store.get_clip(clip_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(row["video_path"])


@router.get("/clips/{clip_id}/frames/{frame_id}")
def get_clip_frame(request: Request, clip_id: str, frame_id: str):
    store: Store = request.app.state.store
    frame = store.get_frame(frame_id)
    if frame is None or frame["clip_id"] != clip_id:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(frame["image_path"])


@router.post("/clips/{clip_id}/search", response_model=ClipSearchStatus)
def start_search(
    request: Request,
    clip_id: str,
    task: str = Form(DEFAULT_TASK),
    prompt: str = Form(""),
    generation_mode: str = Form(""),
) -> ClipSearchStatus:
    state = request.app.state
    store: Store = state.store
    settings = state.settings
    svc = state.svc

    clip = store.get_clip(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Not found")
    if clip["status"] != "ready":
        raise HTTPException(
            status_code=400, detail=f"Clip is not ready (status: {clip['status']})."
        )

    if svc.status != "ready":
        detail = (
            "Model failed to load — see server logs."
            if svc.status == "error"
            else "Model is still loading — try again in a moment."
        )
        raise HTTPException(status_code=503, detail=detail)

    spec = TASKS.get(task)
    if spec is None:
        raise HTTPException(status_code=400, detail=f"Unknown task: {task!r}")

    mode = (generation_mode or settings.default_mode).strip().lower()
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid generation_mode: {mode!r}")

    if spec.input_kind != "none" and not prompt.strip():
        raise HTTPException(status_code=400, detail="A prompt is required for this task.")

    lock = state.job_lock
    if not lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail="Another clip job is already running — try again shortly."
        )

    frames = store.list_frames(clip_id)
    search_id = store.new_id()
    store.create_search(
        search_id=search_id,
        clip_id=clip_id,
        task=task,
        prompt=prompt,
        generation_mode=mode,
        frames_total=len(frames),
    )
    threading.Thread(
        target=_run_search,
        args=(state, clip_id, search_id, task, prompt, mode, frames, lock),
        daemon=True,
    ).start()
    return _to_search_status(store.get_search(search_id), clip_id)


@router.get("/clips/{clip_id}/searches", response_model=ClipSearchList)
def list_searches(request: Request, clip_id: str) -> ClipSearchList:
    store: Store = request.app.state.store
    if store.get_clip(clip_id) is None:
        raise HTTPException(status_code=404, detail="Not found")
    rows = store.list_searches(clip_id)
    return ClipSearchList(items=[_to_search_status(r, clip_id) for r in rows])


@router.get("/clips/{clip_id}/searches/{search_id}", response_model=ClipSearchStatus)
def get_search_status(request: Request, clip_id: str, search_id: str) -> ClipSearchStatus:
    store: Store = request.app.state.store
    row = store.get_search(search_id)
    if row is None or row["clip_id"] != clip_id:
        raise HTTPException(status_code=404, detail="Not found")
    return _to_search_status(row, clip_id)


@router.post("/clips/{clip_id}/searches/{search_id}/cancel")
def cancel_search(request: Request, clip_id: str, search_id: str) -> dict:
    store: Store = request.app.state.store
    row = store.get_search(search_id)
    if row is None or row["clip_id"] != clip_id:
        raise HTTPException(status_code=404, detail="Not found")
    if row["status"] not in ("queued", "running"):
        raise HTTPException(
            status_code=400, detail=f"Search is not running (status: {row['status']})."
        )
    request.app.state.cancelled_searches.add(search_id)
    return {"cancelling": search_id}
