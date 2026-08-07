"""FastAPI application for the LocateAnything-3B web UI."""

from __future__ import annotations

import io
import threading
import time
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image

import clips
from config import VALID_MODES, get_settings
from schemas import (
    DeviceRequest,
    DevicesResponse,
    HealthResponse,
    HistoryItem,
    HistoryList,
    LocateResponse,
    TaskInfo,
)
from storage import Store
from tasks import DEFAULT_TASK, TASKS, build_prompt, parse_output

_EXT_BY_TYPE = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class EngineService:
    """Holds the inference engine and loads it without blocking server startup.

    Real-model loading takes seconds and pulls a multi-GB model on first run, so
    we open the web server immediately and load in a background thread. /health
    reports `loading` until the engine is ready, so the UI can show progress
    instead of looking like the backend is down.
    """

    def __init__(self, settings):  # noqa: ANN001
        self.settings = settings
        self.status = "loading"  # loading | ready | error
        self.error: str | None = None
        self.engine = None

    def start(self) -> None:
        if self.settings.mock:
            from mock_engine import MockEngine

            self.engine = MockEngine()
            self.status = "ready"
            return
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            from worker import RealEngine

            self.engine = RealEngine(self.settings.model_path, device_index=self.settings.device)
            self.status = "ready"
        except Exception as exc:  # noqa: BLE001
            # Keep the detail server-side only (logs); clients get a generic
            # message to avoid leaking internal paths/tokens.
            self.error = str(exc)
            self.status = "error"
            traceback.print_exc()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.store = Store(settings.data_dir)
    app.state.store.reconcile_interrupted_jobs()
    app.state.job_lock = threading.Lock()
    app.state.cancelled_searches: set[str] = set()
    svc = EngineService(settings)
    svc.start()
    app.state.svc = svc
    yield


app = FastAPI(title="LocateAnything UI", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(clips.router, prefix="/api")


def _image_url(search_id: str) -> str:
    return f"/api/images/{search_id}"


def _to_history_item(row: dict) -> HistoryItem:
    result = row["result"]
    return HistoryItem(
        id=row["id"],
        task=row["task"],
        prompt=row["prompt"],
        generation_mode=row["generation_mode"],
        image_url=_image_url(row["id"]),
        box_count=len(result.get("boxes", [])),
        point_count=len(result.get("points", [])),
        created_at=row["created_at"],
    )


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = app.state.settings
    svc = app.state.svc

    if svc.status == "ready":
        info = svc.engine.info()
        return HealthResponse(
            status="ready",
            mock=settings.mock,
            model_loaded=info.get("model_loaded", False),
            model_path=settings.model_path,
            device=info.get("device"),
            device_index=info.get("device_index"),
            gpu_name=info.get("gpu_name"),
            vram_gb=info.get("vram_gb"),
            compatible=info.get("compatible"),
            note=info.get("note"),
        )

    # Still loading (or failed) — report GPU info anyway so the UI can show the
    # target card while the model loads.
    from worker import gpu_report

    gpu = gpu_report()
    return HealthResponse(
        status=svc.status,
        mock=settings.mock,
        model_loaded=False,
        model_path=settings.model_path,
        device=gpu.get("device"),
        gpu_name=gpu.get("gpu_name"),
        vram_gb=gpu.get("vram_gb"),
        compatible=gpu.get("compatible"),
        note=(
            "Model failed to load — see server logs." if svc.status == "error" else "Loading model…"
        ),
    )


@app.get("/api/tasks", response_model=list[TaskInfo])
def list_tasks() -> list[TaskInfo]:
    return [
        TaskInfo(
            name=s.name,
            label=s.label,
            output_type=s.output_type,
            input_kind=s.input_kind,
            placeholder=s.placeholder,
            description=s.description,
        )
        for s in TASKS.values()
    ]


@app.get("/api/devices", response_model=DevicesResponse)
def list_devices() -> DevicesResponse:
    svc = app.state.svc
    if svc.status == "ready":
        return DevicesResponse(**svc.engine.list_devices())
    if app.state.settings.mock:
        return DevicesResponse(current=None, devices=[])
    # Real mode, still loading — enumerate cards so the UI can show them.
    from worker import enumerate_devices

    return DevicesResponse(current=None, devices=enumerate_devices())


@app.post("/api/device", response_model=DevicesResponse)
def set_device(req: DeviceRequest) -> DevicesResponse:
    if app.state.settings.mock:
        raise HTTPException(status_code=400, detail="GPU switching is not available in mock mode.")
    svc = app.state.svc
    if svc.status != "ready":
        raise HTTPException(status_code=503, detail="Model is still loading.")
    try:
        return DevicesResponse(**svc.engine.switch_device(req.index))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except MemoryError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to switch GPU.") from None


@app.post("/api/locate", response_model=LocateResponse)
async def locate(
    image: UploadFile = File(...),
    task: str = Form(DEFAULT_TASK),
    prompt: str = Form(""),
    generation_mode: str = Form(""),
) -> LocateResponse:
    svc = app.state.svc
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

    mode = (generation_mode or app.state.settings.default_mode).strip().lower()
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid generation_mode: {mode!r}")

    if spec.input_kind != "none" and not prompt.strip():
        raise HTTPException(status_code=400, detail="A prompt is required for this task.")

    data = await image.read()
    try:
        pil = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read image file.") from None
    width, height = pil.size

    full_prompt = build_prompt(task, prompt)

    started = time.perf_counter()
    out = svc.engine.predict(pil, full_prompt, mode, output_type=spec.output_type)
    timing_ms = (time.perf_counter() - started) * 1000

    raw = out.get("raw", "")
    parsed = parse_output(task, raw, width, height)
    parsed["raw"] = raw

    store: Store = app.state.store
    search_id = store.new_id()
    suffix = _EXT_BY_TYPE.get(image.content_type or "", ".jpg")
    img_path = store.image_path_for(search_id, suffix)
    img_path.write_bytes(data)

    store.save(
        search_id=search_id,
        task=task,
        prompt=prompt,
        generation_mode=mode,
        image_path=img_path,
        image_width=width,
        image_height=height,
        result=parsed,
        stats=out.get("stats"),
        timing_ms=timing_ms,
    )

    return LocateResponse(
        id=search_id,
        task=task,
        prompt=prompt,
        generation_mode=mode,
        image_width=width,
        image_height=height,
        image_url=_image_url(search_id),
        boxes=parsed["boxes"],
        points=parsed["points"],
        raw=raw,
        stats=out.get("stats"),
        timing_ms=round(timing_ms, 1),
        created_at=store.get(search_id)["created_at"],
    )


@app.get("/api/history", response_model=HistoryList)
def history(limit: int = 50, offset: int = 0) -> HistoryList:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    rows, total = app.state.store.list(limit=limit, offset=offset)
    return HistoryList(
        items=[_to_history_item(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/api/history/{search_id}", response_model=LocateResponse)
def history_item(search_id: str) -> LocateResponse:
    row = app.state.store.get(search_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    result = row["result"]
    return LocateResponse(
        id=row["id"],
        task=row["task"],
        prompt=row["prompt"],
        generation_mode=row["generation_mode"],
        image_width=row["image_width"],
        image_height=row["image_height"],
        image_url=_image_url(row["id"]),
        boxes=result.get("boxes", []),
        points=result.get("points", []),
        raw=result.get("raw", ""),
        stats=row["stats"],
        timing_ms=round(row["timing_ms"], 1),
        created_at=row["created_at"],
    )


@app.delete("/api/history/{search_id}")
def delete_history(search_id: str) -> dict:
    if not app.state.store.delete(search_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": search_id}


@app.get("/api/images/{search_id}")
def get_image(search_id: str):
    row = app.state.store.get(search_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(row["image_path"])
