from __future__ import annotations

from .database import Database
from .storage import ChunkStore


def verify_all(db: Database, store: ChunkStore) -> dict:
    ids = db.completed_chunk_ids()
    damaged = []
    for chunk_id in sorted(ids):
        ok, reason = store.verify(chunk_id)
        if not ok:
            damaged.append({"chunk_id": chunk_id, "reason": reason, "affected": []})
    affected = db.affected_files({d["chunk_id"] for d in damaged})
    for item in damaged:
        item["affected"] = affected.get(item["chunk_id"], [])
    return {"ok": not damaged, "damaged": damaged, "checked_chunks": len(ids)}
