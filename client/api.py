from __future__ import annotations

from pathlib import Path
from typing import Iterator

import httpx

from common.errors import RemoteError


class ClientAPI:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _raise(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            payload = response.json()
            detail = payload.get("detail") or payload.get("error") or str(payload)
            code = payload.get("code", "HTTP_ERROR")
        except ValueError:
            detail, code = response.text or response.reason_phrase, "HTTP_ERROR"
        raise RemoteError(f"{code}: {detail}", code)

    def health(self) -> dict:
        with httpx.Client(timeout=self.timeout) as c:
            r = c.get(f"{self.base_url}/health")
            self._raise(r)
            return r.json()

    def create_upload(self, manifest: dict) -> dict:
        with httpx.Client(timeout=self.timeout) as c:
            r = c.post(f"{self.base_url}/uploads", json={"manifest": manifest})
            self._raise(r)
            return r.json()

    def missing(self, upload_id: str) -> list[str]:
        with httpx.Client(timeout=self.timeout) as c:
            r = c.get(f"{self.base_url}/uploads/{upload_id}/missing")
            self._raise(r)
            return r.json()["missing"]

    def upload_chunk(self, upload_id: str, chunk_id: str, data: bytes) -> dict:
        with httpx.Client(timeout=self.timeout) as c:
            r = c.put(
                f"{self.base_url}/uploads/{upload_id}/chunks/{chunk_id}",
                content=data,
                headers={"Content-Type": "application/octet-stream"},
            )
            self._raise(r)
            return r.json()

    def commit(self, upload_id: str) -> dict:
        with httpx.Client(timeout=self.timeout) as c:
            r = c.post(f"{self.base_url}/uploads/{upload_id}/commit")
            self._raise(r)
            return r.json()

    def stats(self) -> dict:
        with httpx.Client(timeout=self.timeout) as c:
            r = c.get(f"{self.base_url}/stats")
            self._raise(r)
            return r.json()

    def versions(self) -> list[dict]:
        with httpx.Client(timeout=self.timeout) as c:
            r = c.get(f"{self.base_url}/versions")
            self._raise(r)
            return r.json()["versions"]

    def manifest(self, version_id: str) -> dict:
        with httpx.Client(timeout=self.timeout) as c:
            r = c.get(f"{self.base_url}/versions/{version_id}/manifest")
            self._raise(r)
            return r.json()

    def stream_chunk(self, chunk_id: str) -> Iterator[bytes]:
        with httpx.Client(timeout=self.timeout) as c:
            with c.stream("GET", f"{self.base_url}/chunks/{chunk_id}") as r:
                self._raise(r)
                for block in r.iter_bytes(1024 * 1024):
                    yield block

    def verify(self) -> dict:
        with httpx.Client(timeout=self.timeout) as c:
            r = c.post(f"{self.base_url}/verify")
            if r.status_code not in (200, 409):
                self._raise(r)
            return r.json()

    def unfinished(self) -> list[dict]:
        with httpx.Client(timeout=self.timeout) as c:
            r = c.get(f"{self.base_url}/uploads")
            self._raise(r)
            return r.json()["uploads"]
