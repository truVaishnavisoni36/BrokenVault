from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path

from common.errors import BrokenVaultError
from .database import Database

HEX64 = set("0123456789abcdef")


class ChunkStore:
    def __init__(self, root: Path, db: Database) -> None:
        self.root = root
        self.chunks = root / "chunks"
        self.tmp = self.chunks / "tmp"
        self.chunks.mkdir(parents=True, exist_ok=True)
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.db = db
        self.cleanup_tmp()

    def cleanup_tmp(self) -> None:
        for p in self.tmp.iterdir():
            if p.is_file():
                p.unlink(missing_ok=True)

    def validate_id(self, chunk_id: str) -> None:
        if len(chunk_id) != 64 or any(c not in HEX64 for c in chunk_id):
            raise BrokenVaultError("Invalid chunk ID", "INVALID_CHUNK_ID")

    def path_for(self, chunk_id: str) -> Path:
        self.validate_id(chunk_id)
        return self.chunks / chunk_id[:2] / chunk_id[2:4] / chunk_id

    def has(self, chunk_id: str) -> bool:
        self.validate_id(chunk_id)
        row = self.db.get_chunk(chunk_id)
        if not row:
            return False
        p = self.path_for(chunk_id)
        return p.is_file() and p.stat().st_size == row["size"]

    def size(self, chunk_id: str) -> int | None:
        row = self.db.get_chunk(chunk_id)
        if not row:
            return None
        p = self.path_for(chunk_id)
        if not p.is_file():
            return None
        if p.stat().st_size != row["size"]:
            return None
        return row["size"]

    def verify(self, chunk_id: str) -> tuple[bool, str]:
        p = self.path_for(chunk_id)
        row = self.db.get_chunk(chunk_id)
        if not row or not p.is_file():
            return False, "missing"
        digest = hashlib.sha256()
        size = 0
        with p.open("rb") as f:
            while True:
                block = f.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                size += len(block)
        if size != row["size"] or digest.hexdigest() != chunk_id:
            return False, "corrupt"
        return True, "ok"

    async def put_stream(self, chunk_id: str, body_stream, expected_size: int | None = None) -> tuple[str, int]:
        self.validate_id(chunk_id)
        if self.has(chunk_id):
            return "already_present", int(self.db.get_chunk(chunk_id)["size"])

        tmp = self.tmp / f"{secrets.token_hex(16)}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            with tmp.open("wb") as f:
                async for block in body_stream:
                    if not block:
                        continue
                    size += len(block)
                    digest.update(block)
                    f.write(block)
                f.flush()
                os.fsync(f.fileno())
            if expected_size is not None and size != expected_size:
                raise BrokenVaultError("Chunk size mismatch", "SIZE_MISMATCH")
            if digest.hexdigest() != chunk_id:
                raise BrokenVaultError("Chunk SHA-256 does not match its ID", "HASH_MISMATCH")
            destination = self.path_for(chunk_id)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                tmp.unlink(missing_ok=True)
                return "already_present", size
            tmp.replace(destination)
            self.db.add_chunk(chunk_id, size)
            return "stored", size
        finally:
            tmp.unlink(missing_ok=True)

    def read(self, chunk_id: str):
        if not self.has(chunk_id):
            raise BrokenVaultError("Chunk is missing", "CHUNK_MISSING")
        return self.path_for(chunk_id)
