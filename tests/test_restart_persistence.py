from client.api import ClientAPI
from client.uploader import backup
from tests.conftest import restart_server


def test_completed_version_survives_server_restart(server, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "persist.txt").write_text("persist me", encoding="utf-8")
    api = ClientAPI(server["base"])
    first = backup(source, api, 64)
    restart_server(server)
    versions = ClientAPI(server["base"]).versions()
    assert [v["version_id"] for v in versions] == [first["version_id"]]
