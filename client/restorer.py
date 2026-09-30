from __future__ import annotations

import os
import tempfile
from pathlib import Path

from common.errors import BrokenVaultError
from common.hashing import sha256_bytes
from common.paths import safe_destination
from .api import ClientAPI


def _ensure_empty_target(target: Path) -> None:
    if target.exists():
        if not target.is_dir():
            raise BrokenVaultError(f"Restore target is not a directory: {target}", "INVALID_DESTINATION")
        if any(target.iterdir()):
            raise BrokenVaultError("Restore target must be empty", "TARGET_NOT_EMPTY")
    else:
        target.mkdir(parents=True)


def restore(version_id: str, target: Path, api: ClientAPI) -> dict:
    target = target.resolve()
    _ensure_empty_target(target)
    manifest = api.manifest(version_id)
    entries = manifest["entries"]

    for entry in entries:
        safe_destination(target, entry["path"])

    dirs = [e for e in entries if e["type"] == "dir"]
    files = [e for e in entries if e["type"] == "file"]

    # Create directories before files.
    for entry in sorted(dirs, key=lambda e: e["path"]):
        safe_destination(target, entry["path"]).mkdir(parents=True, exist_ok=True)

    for entry in files:
        destination = safe_destination(target, entry["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".brokenvault-", dir=str(destination.parent))
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            with tmp.open("wb") as out:
                for chunk in entry["chunks"]:
                    digest = __import__("hashlib").sha256()
                    received = 0
                    for block in api.stream_chunk(chunk["id"]):
                        digest.update(block)
                        out.write(block)
                        received += len(block)
                    actual = digest.hexdigest()
                    if actual != chunk["id"] or received != chunk["size"]:
                        raise BrokenVaultError(
                            f"Restore integrity failure for {entry['path']} chunk {chunk['id']}",
                            "CHUNK_CORRUPT",
                        )
            tmp.replace(destination)
            os.utime(destination, ns=(entry["mtime_ns"], entry["mtime_ns"]))
        finally:
            tmp.unlink(missing_ok=True)

    # Set directory mtimes last and deepest first.
    for entry in sorted(dirs, key=lambda e: e["path"].count("/"), reverse=True):
        path = safe_destination(target, entry["path"])
        os.utime(path, ns=(entry["mtime_ns"], entry["mtime_ns"]))

    return {"version_id": version_id, "files": len(files), "folders": len(dirs)}
