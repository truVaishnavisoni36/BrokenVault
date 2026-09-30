from pathlib import Path

from client.api import ClientAPI
from client.uploader import backup, prepare_manifest


def make_tree(root: Path) -> None:
    (root / "folder").mkdir(parents=True)
    (root / "folder" / "a.txt").write_text("hello nested", encoding="utf-8")
    (root / "file.txt").write_text("hello world", encoding="utf-8")
    (root / "empty.txt").touch()
    (root / "empty_folder").mkdir()


def test_basic_backup_manifest(server, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_tree(source)
    manifest = prepare_manifest(source, 64)
    paths = [e["path"] for e in manifest["entries"]]
    assert paths == ["empty.txt", "empty_folder", "file.txt", "folder", "folder/a.txt"]
    assert next(e for e in manifest["entries"] if e["path"] == "empty.txt")["chunks"] == []
    assert next(e for e in manifest["entries"] if e["path"] == "empty_folder")["type"] == "dir"

    result = backup(source, ClientAPI(server["base"]), 64)
    assert result["version_id"] == "v0001"
    assert result["uploaded_bytes"] == result["total_bytes"]
    versions = ClientAPI(server["base"]).versions()
    assert len(versions) == 1
    assert versions[0]["version_id"] == "v0001"
