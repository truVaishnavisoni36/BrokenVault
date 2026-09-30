from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator

from common.models import ChunkRef, ManifestEntry

DEFAULT_CHUNK_SIZE = 256 * 1024


def iter_file_chunks(path: Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[tuple[str, int, int, bytes]]:
    """Yield (sha256, size, offset, bytes) without loading the whole file."""
    offset = 0
    with path.open("rb") as handle:
        while True:
            data = handle.read(chunk_size)
            if not data:
                return
            yield hashlib.sha256(data).hexdigest(), len(data), offset, data
            offset += len(data)


def chunk_entry(root: Path, entry: ManifestEntry, chunk_size: int = DEFAULT_CHUNK_SIZE) -> ManifestEntry:
    if entry.type == "dir" or entry.size == 0:
        return entry
    refs: list[ChunkRef] = []
    total = 0
    for chunk_id, size, _offset, _data in iter_file_chunks(root / Path(*entry.path.split("/")), chunk_size):
        refs.append(ChunkRef(chunk_id, size))
        total += size
    if total != entry.size:
        raise OSError(f"File changed while being hashed: {entry.path}")
    return ManifestEntry(entry.path, entry.type, entry.size, entry.mtime_ns, tuple(refs))
