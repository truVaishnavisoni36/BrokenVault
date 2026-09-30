from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO, Iterable


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_stream(stream: BinaryIO, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    while True:
        block = stream.read(block_size)
        if not block:
            break
        digest.update(block)
    return digest.hexdigest()


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    with path.open("rb") as handle:
        return sha256_stream(handle, block_size)
