from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path, monkeypatch):
    port = free_port()
    data = tmp_path / "server-data"
    journal = tmp_path / "journal"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["BV_JOURNAL_DIR"] = str(journal)
    proc = subprocess.Popen(
        [sys.executable, "-m", "server", "--host", "127.0.0.1", "--port", str(port), "--data-dir", str(data)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 10
    import httpx
    while time.time() < deadline:
        try:
            if httpx.get(base + "/health", timeout=0.5).status_code == 200:
                break
        except Exception:
            time.sleep(0.05)
    else:
        proc.kill()
        raise RuntimeError(proc.stderr.read())

    yield {"base": base, "data": data, "journal": journal, "port": port, "process": proc}

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def restart_server(info):
    proc = info["process"]
    proc.terminate()
    proc.wait(timeout=5)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["BV_JOURNAL_DIR"] = str(info["journal"])
    info["process"] = subprocess.Popen(
        [sys.executable, "-m", "server", "--host", "127.0.0.1", "--port", str(info["port"]), "--data-dir", str(info["data"])],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    import httpx
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if httpx.get(info["base"] + "/health", timeout=0.5).status_code == 200:
                return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("Server failed to restart")
