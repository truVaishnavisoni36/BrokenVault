from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChunkRef:
    id: str
    size: int

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "size": self.size}


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    type: str
    size: int
    mtime_ns: int
    chunks: tuple[ChunkRef, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "type": self.type,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "chunks": [c.as_dict() for c in self.chunks],
        }
