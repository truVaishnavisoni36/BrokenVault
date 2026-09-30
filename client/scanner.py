from __future__ import annotations

import os
import stat
from pathlib import Path

from common.errors import BrokenVaultError
from common.models import ManifestEntry
from common.paths import normalize_relative_path


def scan_tree(root: Path) -> list[ManifestEntry]:
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise BrokenVaultError(f"Source folder does not exist or is not a directory: {root}", "INVALID_SOURCE")
    entries: list[ManifestEntry] = []
    seen: set[str] = set()

    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        # Symlinks are explicitly outside core scope; reject them rather than following them.
        for name in list(dirs):
            p = current_path / name
            if p.is_symlink():
                raise BrokenVaultError(f"Symlink is not supported: {p}", "UNSUPPORTED_TYPE")
        for name in list(files):
            p = current_path / name
            if p.is_symlink():
                raise BrokenVaultError(f"Symlink is not supported: {p}", "UNSUPPORTED_TYPE")
            if not stat.S_ISREG(p.stat().st_mode):
                raise BrokenVaultError(f"Only regular files are supported: {p}", "UNSUPPORTED_TYPE")

        for name in sorted(dirs):
            p = current_path / name
            rel = p.relative_to(root).as_posix()
            rel = normalize_relative_path(rel)
            if rel in seen:
                raise BrokenVaultError(f"Duplicate logical path: {rel}", "DUPLICATE_PATH")
            seen.add(rel)
            st = p.stat()
            entries.append(ManifestEntry(rel, "dir", 0, st.st_mtime_ns, ()))

        for name in sorted(files):
            p = current_path / name
            st = p.stat()
            rel = normalize_relative_path(p.relative_to(root).as_posix())
            if rel in seen:
                raise BrokenVaultError(f"Duplicate logical path: {rel}", "DUPLICATE_PATH")
            seen.add(rel)
            entries.append(ManifestEntry(rel, "file", st.st_size, st.st_mtime_ns, ()))

    return sorted(entries, key=lambda e: e.path)
