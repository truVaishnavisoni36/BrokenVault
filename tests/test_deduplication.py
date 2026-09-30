from pathlib import Path

from client.api import ClientAPI
from client.uploader import backup


def test_deduplication(server, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    data = bytearray(b"A" * 64 + b"B" * 64 + b"C" * 64)
    (source / "big.bin").write_bytes(data)
    api = ClientAPI(server["base"])
    first = backup(source, api, 64)
    assert first["uploaded_bytes"] == 192

    data[64:128] = b"D" * 64
    (source / "big.bin").write_bytes(data)
    second = backup(source, api, 64)
    assert second["uploaded_bytes"] == 64
    assert second["reused_bytes"] == 128

    chunk_files = list((server["data"] / "chunks").rglob("*"))
    physical = [p for p in chunk_files if p.is_file() and p.parent.name != "tmp"]
    assert len(physical) == 4
