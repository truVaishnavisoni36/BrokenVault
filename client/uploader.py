from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from common.manifest import build_manifest, manifest_digest
from common.models import ManifestEntry
from .api import ClientAPI
from .chunker import DEFAULT_CHUNK_SIZE, chunk_entry, iter_file_chunks
from .journal import journal_path, load, remove, save
from .scanner import scan_tree


def prepare_manifest(source: Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict:
    scanned = scan_tree(source)
    chunked = [chunk_entry(source, e, chunk_size) for e in scanned]
    return build_manifest(chunked, chunk_size)


def _chunk_map(manifest: dict) -> dict[str, int]:
    result: dict[str, int] = {}
    for entry in manifest["entries"]:
        for c in entry["chunks"]:
            result.setdefault(c["id"], c["size"])
    return result


def backup(
    source: Path,
    api: ClientAPI,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    stop_after: int | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict:
    source = source.resolve()
    manifest = prepare_manifest(source, chunk_size)
    digest = manifest_digest(manifest)
    journal = journal_path(source)
    j = load(journal)

    # The server matches the same manifest digest, so the client journal is a convenience,
    # not the source of truth.
    result = api.create_upload(manifest)
    upload_id = result["upload_id"]
    save(journal, {
        "upload_id": upload_id,
        "manifest_digest": digest,
        "source_path": str(source),
        "started_at": j.get("started_at") if j else None,
    })

    missing = set(result.get("missing", []))
    if result.get("resumed"):
        missing = set(api.missing(upload_id))

    chunks = _chunk_map(manifest)
    uploaded = 0
    processed = 0
    missing_total = len(missing)
    if progress_callback:
        progress_callback({
            "phase": "uploading",
            "total_bytes": sum(e["size"] for e in manifest["entries"] if e["type"] == "file"),
            "uploaded_bytes": 0,
            "uploaded_chunks": 0,
            "missing_chunks": missing_total,
            "resumed": bool(result.get("resumed")),
        })
    for entry in manifest["entries"]:
        if entry["type"] != "file" or not entry["chunks"]:
            continue
        path = source / Path(*entry["path"].split("/"))
        for chunk_id, size, _offset, data in iter_file_chunks(path, chunk_size):
            if chunk_id not in missing:
                continue
            api.upload_chunk(upload_id, chunk_id, data)
            uploaded += size
            processed += 1
            if progress_callback:
                progress_callback({
                    "phase": "uploading",
                    "total_bytes": sum(e["size"] for e in manifest["entries"] if e["type"] == "file"),
                    "uploaded_bytes": uploaded,
                    "uploaded_chunks": processed,
                    "missing_chunks": max(0, missing_total - processed),
                    "resumed": bool(result.get("resumed")),
                })
            if stop_after is not None and processed >= stop_after:
                raise KeyboardInterrupt(f"Demo interruption after {processed} uploaded chunks")

    # Server is authoritative and rechecks the complete set before publishing.
    if progress_callback:
        progress_callback({"phase": "committing", "uploaded_bytes": uploaded, "uploaded_chunks": processed, "missing_chunks": 0})
    result = api.commit(upload_id)
    remove(journal)
    return result
