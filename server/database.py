from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Iterable

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  size INTEGER NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS uploads (
  upload_id TEXT PRIMARY KEY,
  manifest_digest TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('uploading','completed','aborted')),
  total_bytes INTEGER NOT NULL,
  version_id TEXT,
  created_at REAL NOT NULL,
  completed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_uploads_digest ON uploads(manifest_digest, state);
CREATE TABLE IF NOT EXISTS upload_chunks (
  upload_id TEXT NOT NULL,
  chunk_id TEXT NOT NULL,
  size INTEGER NOT NULL,
  PRIMARY KEY (upload_id, chunk_id)
);
CREATE TABLE IF NOT EXISTS versions (
  version_id TEXT PRIMARY KEY,
  upload_id TEXT NOT NULL,
  created_at REAL NOT NULL,
  total_bytes INTEGER NOT NULL,
  uploaded_bytes INTEGER NOT NULL,
  reused_bytes INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS version_entries (
  version_id TEXT NOT NULL,
  path TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('file','dir')),
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  PRIMARY KEY (version_id, path)
);
CREATE TABLE IF NOT EXISTS version_file_chunks (
  version_id TEXT NOT NULL,
  path TEXT NOT NULL,
  idx INTEGER NOT NULL,
  chunk_id TEXT NOT NULL,
  size INTEGER NOT NULL,
  PRIMARY KEY (version_id, path, idx)
);
CREATE INDEX IF NOT EXISTS idx_vfc_chunk ON version_file_chunks(chunk_id);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=30000")
        return con

    def _init(self) -> None:
        with self.connect() as con:
            con.executescript(SCHEMA)

    def create_or_resume_upload(self, digest: str, manifest: dict, total_bytes: int) -> tuple[str, bool]:
        with self.connect() as con:
            row = con.execute(
                "SELECT upload_id, state FROM uploads WHERE manifest_digest=? AND state='uploading' ORDER BY created_at DESC LIMIT 1",
                (digest,),
            ).fetchone()
            if row:
                return row["upload_id"], True
            import uuid
            upload_id = uuid.uuid4().hex
            con.execute(
                "INSERT INTO uploads(upload_id,manifest_digest,manifest_json,state,total_bytes,created_at) VALUES(?,?,?,?,?,?)",
                (upload_id, digest, json.dumps(manifest, sort_keys=True, separators=(",", ":")), "uploading", total_bytes, time.time()),
            )
            return upload_id, False

    def get_upload(self, upload_id: str):
        with self.connect() as con:
            return con.execute("SELECT * FROM uploads WHERE upload_id=?", (upload_id,)).fetchone()

    def list_uploads(self) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute("SELECT upload_id,created_at,total_bytes FROM uploads WHERE state='uploading' ORDER BY created_at").fetchall()

    def record_chunk(self, upload_id: str, chunk_id: str, size: int) -> bool:
        with self.connect() as con:
            cur = con.execute(
                "INSERT OR IGNORE INTO upload_chunks(upload_id,chunk_id,size) VALUES(?,?,?)",
                (upload_id, chunk_id, size),
            )
            return cur.rowcount == 1

    def uploaded_bytes(self, upload_id: str) -> int:
        with self.connect() as con:
            row = con.execute("SELECT COALESCE(SUM(size),0) n FROM upload_chunks WHERE upload_id=?", (upload_id,)).fetchone()
            return int(row["n"])

    def existing_chunk_ids(self, ids: Iterable[str]) -> set[str]:
        ids = list(ids)
        if not ids:
            return set()
        with self.connect() as con:
            result: set[str] = set()
            for start in range(0, len(ids), 500):
                batch = ids[start:start + 500]
                q = ",".join("?" for _ in batch)
                rows = con.execute(f"SELECT id FROM chunks WHERE id IN ({q})", batch).fetchall()
                result.update(r["id"] for r in rows)
            return result

    def add_chunk(self, chunk_id: str, size: int) -> None:
        with self.connect() as con:
            con.execute("INSERT OR IGNORE INTO chunks(id,size,created_at) VALUES(?,?,?)", (chunk_id, size, time.time()))

    def get_chunk(self, chunk_id: str):
        with self.connect() as con:
            return con.execute("SELECT * FROM chunks WHERE id=?", (chunk_id,)).fetchone()

    def commit_upload(self, upload_id: str, manifest: dict, verified_ids: set[str], file_sizes: dict[str, int]) -> dict:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            upload = con.execute("SELECT * FROM uploads WHERE upload_id=?", (upload_id,)).fetchone()
            if not upload:
                raise KeyError("UPLOAD_NOT_FOUND")
            if upload["state"] == "completed":
                version = con.execute("SELECT * FROM versions WHERE version_id=?", (upload["version_id"],)).fetchone()
                return dict(version) | {"files": self._count_entries(con, version["version_id"], "file"), "chunks": self._count_file_chunks(con, version["version_id"])}
            if upload["state"] != "uploading":
                raise ValueError("UPLOAD_NOT_ACTIVE")

            required = {c["id"] for e in manifest["entries"] for c in e["chunks"]}
            if required != verified_ids:
                raise ValueError("UPLOAD_INCOMPLETE")

            next_num = con.execute("SELECT COALESCE(MAX(CAST(SUBSTR(version_id,2) AS INTEGER)),0)+1 FROM versions").fetchone()[0]
            version_id = f"v{int(next_num):04d}"
            now = time.time()
            uploaded_bytes = int(con.execute("SELECT COALESCE(SUM(size),0) n FROM upload_chunks WHERE upload_id=?", (upload_id,)).fetchone()["n"])
            total_bytes = int(upload["total_bytes"])
            reused_bytes = total_bytes - uploaded_bytes
            con.execute(
                "INSERT INTO versions(version_id,upload_id,created_at,total_bytes,uploaded_bytes,reused_bytes) VALUES(?,?,?,?,?,?)",
                (version_id, upload_id, now, total_bytes, uploaded_bytes, reused_bytes),
            )
            for entry in manifest["entries"]:
                con.execute(
                    "INSERT INTO version_entries(version_id,path,type,size,mtime_ns) VALUES(?,?,?,?,?)",
                    (version_id, entry["path"], entry["type"], entry["size"], entry["mtime_ns"]),
                )
                for idx, chunk in enumerate(entry["chunks"]):
                    con.execute(
                        "INSERT INTO version_file_chunks(version_id,path,idx,chunk_id,size) VALUES(?,?,?,?,?)",
                        (version_id, entry["path"], idx, chunk["id"], chunk["size"]),
                    )
            con.execute("UPDATE uploads SET state='completed',version_id=?,completed_at=? WHERE upload_id=?", (version_id, now, upload_id))
            con.execute("COMMIT")
            return {
                "version_id": version_id, "total_bytes": total_bytes,
                "uploaded_bytes": uploaded_bytes, "reused_bytes": reused_bytes,
                "files": sum(e["type"] == "file" for e in manifest["entries"]),
                "chunks": len(required),
            }

    @staticmethod
    def _count_entries(con, version_id: str, item_type: str) -> int:
        return int(con.execute("SELECT COUNT(*) n FROM version_entries WHERE version_id=? AND type=?", (version_id, item_type)).fetchone()["n"])

    @staticmethod
    def _count_file_chunks(con, version_id: str) -> int:
        return int(con.execute("SELECT COUNT(*) n FROM version_file_chunks WHERE version_id=?", (version_id,)).fetchone()["n"])

    def stats(self) -> dict[str, int]:
        with self.connect() as con:
            chunks = con.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(size),0) bytes FROM chunks"
            ).fetchone()
            versions = con.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(total_bytes),0) total, "
                "COALESCE(SUM(uploaded_bytes),0) uploaded, COALESCE(SUM(reused_bytes),0) reused "
                "FROM versions"
            ).fetchone()
            uploads = con.execute(
                "SELECT COUNT(*) n FROM uploads WHERE state='uploading'"
            ).fetchone()
            return {
                "unique_chunks": int(chunks["n"]),
                "stored_bytes": int(chunks["bytes"]),
                "completed_versions": int(versions["n"]),
                "version_total_bytes": int(versions["total"]),
                "version_uploaded_bytes": int(versions["uploaded"]),
                "version_reused_bytes": int(versions["reused"]),
                "unfinished_uploads": int(uploads["n"]),
            }

    def list_versions(self) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute("""
                SELECT v.*,
                       (SELECT COUNT(*) FROM version_entries e WHERE e.version_id=v.version_id AND e.type='file') files,
                       (SELECT COUNT(*) FROM version_file_chunks f WHERE f.version_id=v.version_id) chunks
                FROM versions v ORDER BY v.created_at
            """).fetchall()

    def get_manifest(self, version_id: str) -> dict | None:
        with self.connect() as con:
            version = con.execute("SELECT * FROM versions WHERE version_id=?", (version_id,)).fetchone()
            if not version:
                return None
            entries = []
            rows = con.execute("SELECT * FROM version_entries WHERE version_id=? ORDER BY path", (version_id,)).fetchall()
            for row in rows:
                chunks = con.execute("SELECT chunk_id,size FROM version_file_chunks WHERE version_id=? AND path=? ORDER BY idx", (version_id, row["path"])).fetchall()
                entries.append({
                    "path": row["path"], "type": row["type"], "size": row["size"], "mtime_ns": row["mtime_ns"],
                    "chunks": [{"id": c["chunk_id"], "size": c["size"]} for c in chunks],
                })
            return {"chunk_size": None, "entries": entries}

    def affected_files(self, chunk_ids: set[str]) -> dict[str, list[dict[str, str]]]:
        if not chunk_ids:
            return {}
        with self.connect() as con:
            result: dict[str, list[dict[str, str]]] = {cid: [] for cid in chunk_ids}
            ids = list(chunk_ids)
            for start in range(0, len(ids), 500):
                batch = ids[start:start + 500]
                q = ",".join("?" for _ in batch)
                rows = con.execute(
                    f"SELECT DISTINCT chunk_id,version_id,path FROM version_file_chunks WHERE chunk_id IN ({q}) ORDER BY version_id,path",
                    batch,
                ).fetchall()
                for r in rows:
                    result[r["chunk_id"]].append({"version_id": r["version_id"], "path": r["path"]})
            return result

    def completed_chunk_ids(self) -> set[str]:
        with self.connect() as con:
            return {r["chunk_id"] for r in con.execute("SELECT DISTINCT chunk_id FROM version_file_chunks")}
