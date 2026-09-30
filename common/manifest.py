from __future__ import annotations

import hashlib
import json
from typing import Any

from .errors import BrokenVaultError
from .models import ChunkRef, ManifestEntry
from .paths import normalize_relative_path


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def manifest_digest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()


def build_manifest(entries: list[ManifestEntry], chunk_size: int) -> dict[str, Any]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    normalized = sorted((e.as_dict() for e in entries), key=lambda x: x["path"])
    seen: set[str] = set()
    for entry in normalized:
        path = normalize_relative_path(entry["path"])
        if path in seen:
            raise BrokenVaultError(f"Duplicate manifest path: {path}", "DUPLICATE_PATH")
        seen.add(path)
        if entry["type"] not in {"file", "dir"}:
            raise BrokenVaultError("Invalid manifest item type", "INVALID_MANIFEST")
        if entry["size"] < 0 or entry["mtime_ns"] < 0:
            raise BrokenVaultError("Invalid manifest metadata", "INVALID_MANIFEST")
        if entry["type"] == "dir" and entry["chunks"]:
            raise BrokenVaultError("Directory cannot contain chunks", "INVALID_MANIFEST")
        for chunk in entry["chunks"]:
            if len(chunk["id"]) != 64 or any(c not in "0123456789abcdef" for c in chunk["id"]):
                raise BrokenVaultError("Invalid chunk ID", "INVALID_MANIFEST")
            if chunk["size"] <= 0 or chunk["size"] > chunk_size:
                raise BrokenVaultError("Invalid chunk size", "INVALID_MANIFEST")
    return {"chunk_size": chunk_size, "entries": normalized}
