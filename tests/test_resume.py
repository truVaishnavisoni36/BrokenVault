from pathlib import Path

import pytest

from client.api import ClientAPI
from client.uploader import backup
from tests.conftest import restart_server


def test_interrupt_resume_and_hidden_version(server, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "large.bin").write_bytes(b"A" * 64 + b"B" * 64 + b"C" * 64 + b"D" * 64)
    api = ClientAPI(server["base"])
    with pytest.raises(KeyboardInterrupt):
        backup(source, api, 64, stop_after=2)

    assert api.versions() == []
    assert len(api.unfinished()) == 1

    restart_server(server)
    result = backup(source, ClientAPI(server["base"]), 64)
    assert result["version_id"] == "v0001"
    assert result["uploaded_bytes"] == 256
    assert len(ClientAPI(server["base"]).versions()) == 1
