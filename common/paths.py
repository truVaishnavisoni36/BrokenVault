from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from .errors import BrokenVaultError


def normalize_relative_path(path: str) -> str:
    """Validate and normalize a manifest path to a safe POSIX relative path."""
    if not isinstance(path, str) or not path:
        raise BrokenVaultError("Path must be a non-empty string", "UNSAFE_PATH")
    if "\\" in path:
        raise BrokenVaultError("Backslash is not allowed in manifest paths", "UNSAFE_PATH")
    if path.startswith("/") or Path(path).is_absolute():
        raise BrokenVaultError(f"Absolute path is not allowed: {path}", "UNSAFE_PATH")
    pure = PurePosixPath(path)
    if any(part in ("", ".", "..") for part in pure.parts):
        raise BrokenVaultError(f"Unsafe relative path: {path}", "UNSAFE_PATH")
    normalized = pure.as_posix()
    if normalized != path:
        raise BrokenVaultError(f"Non-canonical path: {path}", "UNSAFE_PATH")
    return normalized


def safe_destination(root: Path, relative_path: str) -> Path:
    """Return a destination under root, rejecting traversal and symlink escapes."""
    rel = normalize_relative_path(relative_path)
    root = root.resolve()
    target = (root / Path(*rel.split("/"))).resolve(strict=False)
    if os.path.commonpath([str(root), str(target)]) != str(root):
        raise BrokenVaultError(f"Path escapes restore directory: {relative_path}", "UNSAFE_PATH")
    return target
