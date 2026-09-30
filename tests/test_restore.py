from pathlib import Path
import os

from client.api import ClientAPI
from client.restorer import restore
from client.uploader import backup


def snapshot(root: Path):
    result = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_dir():
            result[rel] = ("dir", p.stat().st_mtime_ns)
        else:
            result[rel] = ("file", p.read_bytes(), p.stat().st_mtime_ns)
    return result


def test_exact_restore(server, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "nested").mkdir()
    (source / "nested" / "data.txt").write_text("hello" * 100, encoding="utf-8")
    (source / "empty.txt").touch()
    (source / "empty_dir").mkdir()
    fixed = 1_700_000_000_123_456_789
    os.utime(source / "nested" / "data.txt", ns=(fixed, fixed))

    api = ClientAPI(server["base"])
    result = backup(source, api, 64)
    target = tmp_path / "restored"
    restored = restore(result["version_id"], target, api)
    assert restored["files"] == 2
    assert snapshot(source) == snapshot(target)
