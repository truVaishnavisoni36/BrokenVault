from client.api import ClientAPI
from client.uploader import backup


def test_corruption_detection(server, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.bin").write_bytes(b"A" * 100)
    api = ClientAPI(server["base"])
    result = backup(source, api, 64)

    manifest = api.manifest(result["version_id"])
    chunk_id = manifest["entries"][0]["chunks"][0]["id"]
    path = server["data"] / "chunks" / chunk_id[:2] / chunk_id[2:4] / chunk_id
    path.write_bytes(b"CORRUPTED")

    report = api.verify()
    assert not report["ok"]
    damaged = next(d for d in report["damaged"] if d["chunk_id"] == chunk_id)
    assert damaged["reason"] == "corrupt"
    assert {a["version_id"] for a in damaged["affected"]} == {result["version_id"]}
    assert {a["path"] for a in damaged["affected"]} == {"data.bin"}
