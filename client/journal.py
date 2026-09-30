from __future__ import annotations

import hashlib
import json
from pathlib import Path


def journal_path(source: Path, base: Path | None = None) -> Path:
    base = base or Path(__import__("os").environ.get("BV_JOURNAL_DIR", str(Path.home() / ".brokenvault" / "journal")))
    base.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()
    return base / f"{key}.json"


def save(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def remove(path: Path) -> None:
    path.unlink(missing_ok=True)
