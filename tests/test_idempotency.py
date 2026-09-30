from client.api import ClientAPI
from client.uploader import prepare_manifest


def test_repeated_chunk_request_is_idempotent(server, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "x.txt").write_bytes(b"hello world")
    api = ClientAPI(server["base"])
    manifest = prepare_manifest(source, 64)
    upload = api.create_upload(manifest)
    chunk = manifest["entries"][0]["chunks"][0]
    data = (source / "x.txt").read_bytes()
    first = api.upload_chunk(upload["upload_id"], chunk["id"], data)
    second = api.upload_chunk(upload["upload_id"], chunk["id"], data)
    assert first["status"] == "stored"
    assert second["status"] == "already_present"
