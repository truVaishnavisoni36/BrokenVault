from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from common.errors import BrokenVaultError, RemoteError
from .api import ClientAPI
from .restorer import restore
from .uploader import backup

WEB_DIR = Path(__file__).parent / "web"
DEFAULT_SERVER_URL = "http://127.0.0.1:8000"


class BackupRequest(BaseModel):
    source: str = Field(min_length=1)
    stop_after: int | None = Field(default=None, ge=1)


class RestoreRequest(BaseModel):
    version: str = Field(min_length=1)
    destination: str = Field(min_length=1)


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self.active_id: str | None = None

    def create(self, source: str, stop_after: int | None) -> str:
        with self._lock:
            if self.active_id and self._jobs[self.active_id]["status"] == "running":
                raise RuntimeError("A backup is already running")
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "running",
                "source": source,
                "stop_after": stop_after,
                "phase": "preparing",
                "message": "Preparing backup",
                "uploaded_bytes": 0,
                "uploaded_chunks": 0,
                "missing_chunks": 0,
                "total_bytes": 0,
            }
            self.active_id = job_id
            return job_id

    def update(self, job_id: str, **values: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(values)
            if values.get("status") in {"completed", "interrupted", "failed"} and self.active_id == job_id:
                self.active_id = None

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._jobs.get(job_id)) if job_id in self._jobs else None

    def active(self) -> dict[str, Any] | None:
        with self._lock:
            if self.active_id is None:
                return None
            return dict(self._jobs[self.active_id])


jobs = JobStore()
app = FastAPI(title="BrokenVault Web Client", version="1.1.0")


def server_url() -> str:
    return os.environ.get("BROKENVAULT_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")


def api_client() -> ClientAPI:
    return ClientAPI(server_url())


def run_backup(job_id: str, source: str, stop_after: int | None) -> None:
    def progress(update: dict[str, Any]) -> None:
        phase = update.get("phase", "uploading")
        uploaded = int(update.get("uploaded_bytes", 0))
        missing = int(update.get("missing_chunks", 0))
        processed = int(update.get("uploaded_chunks", 0))
        total = int(update.get("total_bytes", 0))
        if phase == "committing":
            message = "Verifying chunks and committing version"
        elif missing:
            message = f"Uploading chunks · {processed} uploaded · {missing} remaining"
        else:
            message = "All required chunks uploaded"
        jobs.update(
            job_id,
            phase=phase,
            message=message,
            uploaded_bytes=uploaded,
            uploaded_chunks=processed,
            missing_chunks=missing,
            total_bytes=total,
        )

    try:
        jobs.update(job_id, phase="scanning", message="Scanning source and building manifest")
        result = backup(Path(source), api_client(), stop_after=stop_after, progress_callback=progress)
        jobs.update(job_id, status="completed", phase="completed", message="Backup completed", result=result)
    except KeyboardInterrupt as exc:
        jobs.update(job_id, status="interrupted", phase="interrupted", message=str(exc), error=str(exc))
    except Exception as exc:  # noqa: BLE001 - surfaced to the local UI
        jobs.update(job_id, status="failed", phase="failed", message=str(exc), error=str(exc))


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/static/styles.css")
def styles() -> FileResponse:
    return FileResponse(WEB_DIR / "styles.css", media_type="text/css")


@app.get("/static/app.js")
def script() -> FileResponse:
    return FileResponse(WEB_DIR / "app.js", media_type="text/javascript")


@app.get("/api/config")
def config():
    return {"server_url": server_url()}


@app.get("/api/state")
def state():
    client = api_client()
    try:
        health = client.health()
        versions = client.versions()
        uploads = client.unfinished()
        stats = client.stats()
        return {
            "server_ok": health.get("status") == "ok",
            "server_url": server_url(),
            "versions": versions,
            "uploads": uploads,
            "stats": stats,
            "job": jobs.active(),
        }
    except Exception as exc:  # noqa: BLE001 - surfaced to the local UI
        return JSONResponse(
            status_code=200,
            content={
                "server_ok": False,
                "server_url": server_url(),
                "versions": [],
                "uploads": [],
                "stats": {},
                "job": jobs.active(),
                "error": str(exc),
            },
        )


@app.post("/api/backup")
def start_backup(payload: BackupRequest):
    source = Path(payload.source).expanduser()
    if not source.exists() or not source.is_dir():
        return JSONResponse(status_code=400, content={"detail": f"Source folder does not exist or is not a directory: {source}"})
    try:
        job_id = jobs.create(str(source), payload.stop_after)
    except RuntimeError as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    thread = threading.Thread(target=run_backup, args=(job_id, str(source), payload.stop_after), daemon=True)
    thread.start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    result = jobs.get(job_id)
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Job not found"})
    return result


@app.post("/api/restore")
def restore_version(payload: RestoreRequest):
    try:
        return restore(payload.version, Path(payload.destination).expanduser(), api_client())
    except (BrokenVaultError, RemoteError) as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.post("/api/verify")
def verify():
    result = api_client().verify()
    return JSONResponse(status_code=200, content=result)


if __name__ == "__main__":
    uvicorn.run("client.webapp:app", host="127.0.0.1", port=int(os.environ.get("BROKENVAULT_WEB_PORT", "8010")), reload=False)
