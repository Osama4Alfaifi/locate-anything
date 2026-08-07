"""SQLite-backed search history + image storage (stdlib only)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    id              TEXT PRIMARY KEY,
    task            TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    generation_mode TEXT NOT NULL,
    image_path      TEXT NOT NULL,
    image_width     INTEGER NOT NULL,
    image_height    INTEGER NOT NULL,
    result_json     TEXT NOT NULL,
    stats_json      TEXT,
    timing_ms       REAL NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clips (
    id           TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    video_path   TEXT NOT NULL,
    duration_s   REAL,
    fps          REAL,
    width        INTEGER,
    height       INTEGER,
    size_bytes   INTEGER,
    sample_fps   REAL NOT NULL,
    status       TEXT NOT NULL,
    error        TEXT,
    frame_count  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clip_frames (
    id           TEXT PRIMARY KEY,
    clip_id      TEXT NOT NULL,
    frame_index  INTEGER NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    image_path   TEXT NOT NULL,
    width        INTEGER NOT NULL,
    height       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clip_frames_clip ON clip_frames(clip_id);

CREATE TABLE IF NOT EXISTS clip_searches (
    id              TEXT PRIMARY KEY,
    clip_id         TEXT NOT NULL,
    task            TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    generation_mode TEXT NOT NULL,
    status          TEXT NOT NULL,
    error           TEXT,
    frames_total    INTEGER NOT NULL,
    frames_done     INTEGER NOT NULL DEFAULT 0,
    matches_json    TEXT,
    created_at      TEXT NOT NULL,
    finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_clip_searches_clip ON clip_searches(clip_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.images_dir = self.data_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.clips_dir = self.data_dir / "clips"
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "history.db"
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    def image_path_for(self, search_id: str, suffix: str) -> Path:
        suffix = suffix if suffix.startswith(".") else f".{suffix}"
        return self.images_dir / f"{search_id}{suffix}"

    def save(
        self,
        *,
        search_id: str,
        task: str,
        prompt: str,
        generation_mode: str,
        image_path: Path,
        image_width: int,
        image_height: int,
        result: dict,
        stats: dict | None,
        timing_ms: float,
    ) -> dict:
        created_at = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT INTO searches (id, task, prompt, generation_mode, image_path,
                   image_width, image_height, result_json, stats_json, timing_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                search_id,
                task,
                prompt,
                generation_mode,
                str(image_path),
                image_width,
                image_height,
                json.dumps(result),
                json.dumps(stats) if stats is not None else None,
                timing_ms,
                created_at,
            ),
        )
        self._conn.commit()
        return self.get(search_id)

    def get(self, search_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list(self, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        total = self._conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
        rows = self._conn.execute(
            "SELECT * FROM searches ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows], total

    def delete(self, search_id: str) -> bool:
        row = self.get(search_id)
        if row is None:
            return False
        try:
            Path(row["image_path"]).unlink(missing_ok=True)
        except OSError:
            pass
        self._conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))
        self._conn.commit()
        return True

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["result"] = json.loads(d.pop("result_json"))
        stats = d.pop("stats_json")
        d["stats"] = json.loads(stats) if stats else None
        return d

    def _update(self, table: str, row_id: str, **fields) -> None:
        """Build `UPDATE {table} SET ... WHERE id = ?` from keyword fields.

        `table`/field names are internal constants (never user input), so this
        is safe despite the f-string.
        """
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._conn.execute(f"UPDATE {table} SET {cols} WHERE id = ?", (*fields.values(), row_id))
        self._conn.commit()

    # -- Clips -----------------------------------------------------------

    def clip_video_path_for(self, clip_id: str, suffix: str) -> Path:
        suffix = suffix if suffix.startswith(".") else f".{suffix}"
        clip_dir = self.clips_dir / clip_id
        clip_dir.mkdir(parents=True, exist_ok=True)
        return clip_dir / f"video{suffix}"

    def clip_frames_dir_for(self, clip_id: str) -> Path:
        frames_dir = self.clips_dir / clip_id / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        return frames_dir

    def save_clip(
        self, *, clip_id: str, filename: str, video_path: Path, size_bytes: int, sample_fps: float
    ) -> dict:
        self._conn.execute(
            """INSERT INTO clips (id, filename, video_path, duration_s, fps, width, height,
                   size_bytes, sample_fps, status, error, frame_count, created_at)
               VALUES (?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, 'extracting', NULL, 0, ?)""",
            (clip_id, filename, str(video_path), size_bytes, sample_fps, _now()),
        )
        self._conn.commit()
        return self.get_clip(clip_id)

    def get_clip(self, clip_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        return dict(row) if row else None

    def list_clips(self, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        total = self._conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        rows = self._conn.execute(
            "SELECT * FROM clips ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
        return [dict(r) for r in rows], total

    def update_clip_status(self, clip_id: str, status: str, *, error: str | None = None, **metadata) -> None:
        self._update("clips", clip_id, status=status, error=error, **metadata)

    def delete_clip(self, clip_id: str) -> bool:
        if self.get_clip(clip_id) is None:
            return False
        self._conn.execute("DELETE FROM clip_searches WHERE clip_id = ?", (clip_id,))
        self._conn.execute("DELETE FROM clip_frames WHERE clip_id = ?", (clip_id,))
        self._conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        self._conn.commit()
        shutil.rmtree(self.clips_dir / clip_id, ignore_errors=True)
        return True

    # -- Frames ------------------------------------------------------------

    def save_frames(self, clip_id: str, frames: list[dict]) -> None:
        """`frames`: [{id, frame_index, timestamp_ms, path, width, height}, ...]
        (matches video.extract_frames' return shape)."""
        self._conn.executemany(
            """INSERT INTO clip_frames (id, clip_id, frame_index, timestamp_ms, image_path,
                   width, height) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    f["id"],
                    clip_id,
                    f["frame_index"],
                    f["timestamp_ms"],
                    str(f["path"]),
                    f["width"],
                    f["height"],
                )
                for f in frames
            ],
        )
        self._conn.commit()

    def list_frames(self, clip_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM clip_frames WHERE clip_id = ? ORDER BY frame_index", (clip_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_frame(self, frame_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM clip_frames WHERE id = ?", (frame_id,)).fetchone()
        return dict(row) if row else None

    # -- Searches ------------------------------------------------------------

    def create_search(
        self,
        *,
        search_id: str,
        clip_id: str,
        task: str,
        prompt: str,
        generation_mode: str,
        frames_total: int,
    ) -> dict:
        self._conn.execute(
            """INSERT INTO clip_searches (id, clip_id, task, prompt, generation_mode, status,
                   error, frames_total, frames_done, matches_json, created_at, finished_at)
               VALUES (?, ?, ?, ?, ?, 'queued', NULL, ?, 0, NULL, ?, NULL)""",
            (search_id, clip_id, task, prompt, generation_mode, frames_total, _now()),
        )
        self._conn.commit()
        return self.get_search(search_id)

    def update_search_progress(self, search_id: str, frames_done: int, status: str = "running") -> None:
        self._update("clip_searches", search_id, status=status, frames_done=frames_done)

    def finish_search(
        self, search_id: str, status: str, *, matches: list[dict] | None = None, error: str | None = None
    ) -> None:
        self._update(
            "clip_searches",
            search_id,
            status=status,
            error=error,
            matches_json=json.dumps(matches) if matches is not None else None,
            finished_at=_now(),
        )

    def get_search(self, search_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM clip_searches WHERE id = ?", (search_id,)).fetchone()
        return self._row_to_search_dict(row) if row else None

    def list_searches(self, clip_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM clip_searches WHERE clip_id = ? ORDER BY created_at DESC", (clip_id,)
        ).fetchall()
        return [self._row_to_search_dict(r) for r in rows]

    @staticmethod
    def _row_to_search_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        matches = d.pop("matches_json")
        d["matches"] = json.loads(matches) if matches else None
        return d

    def reconcile_interrupted_jobs(self) -> None:
        """Called at startup: a crash/restart mid-job would otherwise leave the
        UI polling a clip/search that will never finish."""
        note = "Interrupted by server restart."
        self._conn.execute(
            "UPDATE clips SET status = 'error', error = ? WHERE status = 'extracting'", (note,)
        )
        self._conn.execute(
            "UPDATE clip_searches SET status = 'error', error = ?, finished_at = ? "
            "WHERE status IN ('queued', 'running')",
            (note, _now()),
        )
        self._conn.commit()
