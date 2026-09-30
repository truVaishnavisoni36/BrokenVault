from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from common.errors import BrokenVaultError
from common.manifest import manifest_digest, canonical_json
from common.paths import normalize_relative_path
from .database import Database
from .storage import ChunkStore
from .verifier import verify_all


class UploadRequest(BaseModel):
    manifest: dict


class AppState:
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(data_dir / "metadata.db")
        self.store = ChunkStore(data_dir, self.db)


def validate_manifest(manifest: dict) -> tuple[int, set[str], int]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("entries"), list):
        raise BrokenVaultError("Manifest must contain entries", "INVALID_MANIFEST")
    chunk_size = int(manifest.get("chunk_size") or 256 * 1024)
    if chunk_size <= 0 or chunk_size > 16 * 1024 * 1024:
        raise BrokenVaultError("Invalid chunk size", "INVALID_MANIFEST")
    seen: set[str] = set()
    chunk_ids: set[str] = set()
    total = 0
    for entry in manifest["entries"]:
        path = normalize_relative_path(entry.get("path"))
        if path in seen:
            raise BrokenVaultError(f"Duplicate manifest path: {path}", "DUPLICATE_PATH")
        seen.add(path)
        typ = entry.get("type")
        size = int(entry.get("size", -1))
        mtime = int(entry.get("mtime_ns", -1))
        chunks = entry.get("chunks", [])
        if typ not in {"file", "dir"} or size < 0 or mtime < 0 or not isinstance(chunks, list):
            raise BrokenVaultError(f"Invalid manifest entry: {path}", "INVALID_MANIFEST")
        if typ == "dir" and (size != 0 or chunks):
            raise BrokenVaultError(f"Directory entry is invalid: {path}", "INVALID_MANIFEST")
        if typ == "file":
            total += size
            chunk_total = 0
            for c in chunks:
                cid = c.get("id")
                csize = int(c.get("size", -1))
                if not isinstance(cid, str) or len(cid) != 64 or any(ch not in "0123456789abcdef" for ch in cid):
                    raise BrokenVaultError(f"Invalid chunk ID in {path}", "INVALID_MANIFEST")
                if csize <= 0 or csize > chunk_size:
                    raise BrokenVaultError(f"Invalid chunk size in {path}", "INVALID_MANIFEST")
                chunk_total += csize
                chunk_ids.add(cid)
            if chunk_total != size:
                raise BrokenVaultError(f"Chunk sizes do not equal file size: {path}", "INVALID_MANIFEST")
    canonical = {"chunk_size": chunk_size, "entries": sorted(manifest["entries"], key=lambda e: e["path"])}
    # The server normalizes the manifest before persistence so its digest is stable.
    manifest.clear(); manifest.update(canonical)
    return chunk_size, chunk_ids, total


def create_app(data_dir: Path | str = "storage") -> FastAPI:
    state = AppState(Path(data_dir))
    app = FastAPI(title="BrokenVault Server", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8010", "http://localhost:8010"],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"]
    )
    app.state.bv = state

    @app.exception_handler(BrokenVaultError)
    async def bv_error(_request: Request, exc: BrokenVaultError):
        status = 400
        if exc.code in {"UPLOAD_NOT_FOUND", "VERSION_NOT_FOUND", "CHUNK_MISSING"}:
            status = 404
        if exc.code in {"UPLOAD_INCOMPLETE", "HASH_MISMATCH", "SIZE_MISMATCH"}:
            status = 409
        return JSONResponse(status_code=status, content={"error": str(exc), "code": exc.code, "detail": str(exc)})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/stats")
    def stats():
        return state.db.stats()

    @app.post("/uploads")
    def create_upload(payload: UploadRequest):
        manifest = json.loads(json.dumps(payload.manifest))
        _chunk_size, chunk_ids, total = validate_manifest(manifest)
        digest = manifest_digest(manifest)
        upload_id, resumed = state.db.create_or_resume_upload(digest, manifest, total)
        existing = {cid for cid in chunk_ids if state.store.has(cid)}
        missing = sorted(chunk_ids - existing)
        return {"upload_id": upload_id, "resumed": resumed, "missing": missing, "manifest_digest": digest}

    @app.get("/uploads")
    def uploads():
        return {"uploads": [dict(r) for r in state.db.list_uploads()]}

    @app.get("/uploads/{upload_id}")
    def upload_status(upload_id: str):
        row = state.db.get_upload(upload_id)
        if not row:
            raise BrokenVaultError("Upload not found", "UPLOAD_NOT_FOUND")
        return dict(row)

    @app.get("/uploads/{upload_id}/missing")
    def missing(upload_id: str):
        row = state.db.get_upload(upload_id)
        if not row:
            raise BrokenVaultError("Upload not found", "UPLOAD_NOT_FOUND")
        manifest = json.loads(row["manifest_json"])
        ids = {c["id"] for e in manifest["entries"] for c in e["chunks"]}
        existing = {cid for cid in ids if state.store.has(cid)}
        return {"missing": sorted(ids - existing), "verified": sorted(existing)}

    @app.put("/uploads/{upload_id}/chunks/{chunk_id}")
    async def put_chunk(upload_id: str, chunk_id: str, request: Request):
        row = state.db.get_upload(upload_id)
        if not row or row["state"] != "uploading":
            raise BrokenVaultError("Upload is not active", "UPLOAD_NOT_FOUND")
        manifest = json.loads(row["manifest_json"])
        expected = None
        for e in manifest["entries"]:
            for c in e["chunks"]:
                if c["id"] == chunk_id:
                    expected = c["size"]
                    break
            if expected is not None:
                break
        if expected is None:
            raise BrokenVaultError("Chunk is not part of this upload", "CHUNK_NOT_IN_MANIFEST")
        status, size = await state.store.put_stream(chunk_id, request.stream(), expected)
        state.db.record_chunk(upload_id, chunk_id, size) if status == "stored" else None
        return {"status": status, "chunk_id": chunk_id, "size": size}

    @app.post("/uploads/{upload_id}/commit")
    def commit(upload_id: str):
        row = state.db.get_upload(upload_id)
        if not row:
            raise BrokenVaultError("Upload not found", "UPLOAD_NOT_FOUND")
        manifest = json.loads(row["manifest_json"])
        required = {c["id"] for e in manifest["entries"] for c in e["chunks"]}
        verified: set[str] = set()
        for cid in required:
            ok, reason = state.store.verify(cid)
            if not ok:
                raise BrokenVaultError(f"Required chunk {cid} is {reason}", "UPLOAD_INCOMPLETE")
            verified.add(cid)
        file_sizes = {e["path"]: e["size"] for e in manifest["entries"] if e["type"] == "file"}
        try:
            return state.db.commit_upload(upload_id, manifest, verified, file_sizes)
        except ValueError as exc:
            raise BrokenVaultError(str(exc), str(exc)) from exc

    @app.get("/versions")
    def versions():
        return {"versions": [dict(r) for r in state.db.list_versions()]}

    @app.get("/versions/{version_id}/manifest")
    def version_manifest(version_id: str):
        manifest = state.db.get_manifest(version_id)
        if manifest is None:
            raise BrokenVaultError("Version not found or not completed", "VERSION_NOT_FOUND")
        return manifest

    @app.get("/chunks/{chunk_id}")
    def get_chunk(chunk_id: str):
        path = state.store.read(chunk_id)
        return FileResponse(path, media_type="application/octet-stream")

    @app.post("/verify")
    def verify():
        result = verify_all(state.db, state.store)
        return JSONResponse(status_code=200 if result["ok"] else 409, content=result)

    return app


app = create_app()
