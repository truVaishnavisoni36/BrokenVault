# BrokenVault

BrokenVault is a small client-server backup system built for the BrokenVault One-Day Systems Challenge. It focuses on the scored core: deterministic content-addressed chunks, deduplication, resumable uploads, atomic version publication, exact restore, and integrity verification.

The implementation follows the supplied architecture and workflow documents: Python 3.12, FastAPI/Uvicorn, HTTP, SQLite, and a filesystem chunk store. The architecture explicitly uses a client/server split, 256 KiB fixed chunks, lowercase SHA-256 IDs, a persistent upload journal, atomic completion, exact restore, and server-side verification.

## 1. Requirements covered

- Recursive folders, nested folders, empty files and empty folders
- Safe relative paths; traversal and symlinks are rejected
- Deterministic 256 KiB fixed-size chunks
- Lowercase SHA-256 chunk IDs
- Content-addressed deduplication
- Server-side hash verification before accepting chunks
- Missing-chunk planning before upload
- Persistent upload sessions and resume after client/server restart
- Incomplete uploads hidden from the completed version list
- Atomic completion only after all required chunks verify
- Exact restore of bytes, paths, empty items and modification times
- Restore-time chunk verification
- `verify` reports missing/corrupt chunks and every affected version/file
- CLI: `backup`, `list`, `restore`, `verify`, plus `status`
- Streaming file reads and HTTP chunk bodies; no whole-file RAM loading
- No cloud, paid service, existing backup engine, or hard-coded dataset

The end-to-end supplied workflow calls out the same sequence: scan/hash, build a safe manifest, upload only missing chunks, show uploaded/reused bytes, interrupt/resume, exact restore, then damage and verify without auto-repair.

## 2. Architecture

```text
              HTTP
+---------+ <-----> +-------------------+
| Client  |         | FastAPI Server    |
|         |         |                   |
| scan    |         | upload sessions   |
| chunk   |         | atomic commit     |
| manifest|         | verification      |
| resume  |         +---------+---------+
| restore |                   |
| CLI     |             +-----+-----+
+---------+             | SQLite    |
                        | metadata  |
                        +-----+-----+
                              |
                        +-----+-----+
                        | chunks/   |
                        | filesystem|
                        +-----------+
```

The client and server are separate processes and communicate through HTTP; neither reads the other's private files.

### Server storage

```text
storage/
├── metadata.db
└── chunks/
    ├── ab/cd/<sha256>
    └── tmp/
```

A chunk's SHA-256 is its storage identity. A single physical chunk can be referenced by many files and versions.

### Completion model

```text
uploading
   |
   | all required chunks present + hash verified
   v
COMPLETED
```

Unfinished uploads live only in the `uploads` table. Completed-version tables are populated only inside the commit transaction, so an unfinished upload cannot appear in `list` or be restored. This follows the supplied architecture's structural hiding rule.

## 3. Repository structure

```text
brokenvault/
├── client/
│   ├── api.py
│   ├── chunker.py
│   ├── cli.py
│   ├── journal.py
│   ├── restorer.py
│   ├── scanner.py
│   └── uploader.py
├── common/
│   ├── errors.py
│   ├── hashing.py
│   ├── manifest.py
│   ├── models.py
│   └── paths.py
├── server/
│   ├── app.py
│   ├── database.py
│   ├── storage.py
│   └── verifier.py
├── tests/
├── docs/architecture.md
├── storage/.gitkeep
├── pyproject.toml
├── requirements.txt
├── .gitignore
└── README.md
```

## 4. Prerequisites

- Python 3.12.x
- Local filesystem with enough free space for the backup dataset
- No internet or paid service is required at runtime

## 5. Installation

From the repository root:

```bash
python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## 6. Start the server

```bash
python -m server --host 127.0.0.1 --port 8000 --data-dir storage
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok"}
```

## 7. CLI commands

In a second terminal, from the repository root:

```bash
python -m client --server http://127.0.0.1:8000 backup ./dataset
python -m client --server http://127.0.0.1:8000 list
python -m client --server http://127.0.0.1:8000 restore v0001 ./restored
python -m client --server http://127.0.0.1:8000 verify
python -m client --server http://127.0.0.1:8000 status
```

If the package is installed with `pip install -e .`, the shorter `bv` command is also available:

```bash
bv --server http://127.0.0.1:8000 backup ./dataset
```

## 8. Deduplication demo

Create or use any dataset; do not use a hard-coded judge dataset.

```bash
python -m client --server http://127.0.0.1:8000 backup ./dataset
```

Change a small region of a file, then run:

```bash
python -m client --server http://127.0.0.1:8000 backup ./dataset
```

The second result reports `uploaded_bytes` for newly accepted chunks and `reused_bytes` for existing content. The supplied end-to-end flow specifically calls for making this difference prominent because it is a key judging observation.

## 9. Interrupt/resume demo

Start a backup with a deliberate interruption after two missing chunks:

```bash
python -m client --server http://127.0.0.1:8000 backup ./dataset --stop-after 2
```

The command exits with `INTERRUPTED`. The unfinished upload remains on the server, but `list` still shows only completed versions:

```bash
python -m client --server http://127.0.0.1:8000 list
python -m client --server http://127.0.0.1:8000 status
```

Restart the server if desired, then run the same backup again:

```bash
python -m client --server http://127.0.0.1:8000 backup ./dataset
```

The client recreates the manifest, the server matches the unfinished upload by manifest digest, the client asks for missing chunks, and only the remaining chunks are sent. The supplied architecture explicitly uses both a client journal and server-side manifest matching for this behavior.

## 10. Restore demo

Always restore into a new or empty directory:

```bash
rm -rf restored
python -m client --server http://127.0.0.1:8000 restore v0001 ./restored
```

The restore path validates every manifest path, streams chunks into a temporary file, verifies each chunk hash, atomically moves the file into place, and restores mtimes. Empty files and folders are created from the manifest.

## 11. Damage + verify demo

After a backup, choose a chunk from the version manifest. The simplest judge-friendly approach is to modify or delete one file under `storage/chunks/ab/cd/` where the filename is the chunk hash.

Then run:

```bash
python -m client --server http://127.0.0.1:8000 verify
```

Expected shape:

```text
CORRUPTION DETECTED
Chunk: <sha256>
Reason: corrupt
  Version: v0001  File: path/to/file.bin
```

Verification never repairs the chunk. It reports the damaged chunk and all completed versions/files that reference it, matching the supplied workflow.

## 12. Tests

One command runs the complete suite:

```bash
python -m pytest
```

The suite covers:

- basic recursive backup and manifest contents
- empty files/folders
- deduplication and byte accounting
- interruption and resume
- incomplete-version hiding
- completed-version persistence across server restart
- exact restore and mtimes
- corruption detection and dependency tracing
- path traversal rejection
- repeated chunk-upload idempotency

## 13. API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Server status |
| POST | `/uploads` | Create/resume upload from manifest |
| GET | `/uploads` | List unfinished uploads |
| GET | `/uploads/{id}` | Upload state |
| GET | `/uploads/{id}/missing` | Server-authoritative missing chunks |
| PUT | `/uploads/{id}/chunks/{hash}` | Stream and verify one chunk |
| POST | `/uploads/{id}/commit` | Verify and atomically publish version |
| GET | `/versions` | Completed versions only |
| GET | `/versions/{id}/manifest` | Completed manifest |
| GET | `/chunks/{hash}` | Download one chunk |
| POST | `/verify` | Full integrity scan |

## 14. Security considerations

- Manifest paths must be relative, canonical POSIX paths.
- Absolute paths and `..` traversal are rejected.
- Restore resolves every destination and checks it remains under the requested target.
- Symlinks are rejected during scanning because they are outside the challenge's core scope.
- Chunk IDs must be 64 lowercase hexadecimal characters.
- The server hashes every received chunk and rejects mismatches.
- Chunk writes use a temporary file, `fsync`, and atomic rename.
- Restore writes to a temporary file and only replaces the final file after successful chunk verification.

## 15. Known limitations

- No authentication, encryption, cloud storage, multi-user support, permissions, symlinks, sparse files, garbage collection, or partial restore; these are outside the core scope.
- The implementation uses fixed-size chunks rather than content-defined chunking.
- The CLI is the required interface; no optional web UI is included.
- The server verifies all required chunks at commit time. This favors correctness and safe completion over avoiding a second hash pass.

## 16. External libraries

- FastAPI — HTTP API
- Uvicorn — ASGI server
- httpx — HTTP client
- Pydantic — request validation
- pytest — automated tests

The storage engine itself is implemented with Python, SQLite, and the local filesystem; no existing backup engine is used.

## 17. AI-assisted development disclosure

This repository was developed with AI assistance under human direction. The implementation was reviewed against the supplied challenge/architecture/workflow documents and exercised with the automated test suite. The team remains responsible for the submitted code and demo.

## 18. Team

| Role | Name |
|---|---|
| Lead developer | __________________ |
| Client / restore | __________________ |
| Server / database | __________________ |
| Testing / demo | __________________ |

## 19. 4–6 minute demo script

1. Start server.
2. Back up a normal dataset; show total and uploaded bytes.
3. Change a small part; back up again; show reused bytes.
4. Start another backup with `--stop-after 2`; show no new completed version.
5. Restart server; run the same backup; show resume and completion.
6. Restore the completed version to an empty directory.
7. Modify/delete one stored chunk.
8. Run `verify`; show the chunk, version and affected file.

This is the exact high-level demo flow described in the supplied end-to-end process: backup → change → interrupt → restart/resume → restore → damage/verify.

## Web UI

The repository includes a local browser UI in `client/web/` and `client/webapp.py`. It is an integration layer over the existing client/server implementation, not a separate backup engine or mock dashboard.

The data flow is:

```text
Browser
   | same-origin HTTP
   v
client.webapp (localhost:8010)
   | ClientAPI over HTTP
   v
FastAPI server (localhost:8000)
   |
   +-- SQLite metadata
   +-- filesystem chunk store
```

Start the FastAPI server first:

```powershell
python -m server --host 127.0.0.1 --port 8000 --data-dir storage
```

In a second terminal, start the existing WebUI module:

```powershell
python -m client.webapp
```

Open `http://127.0.0.1:8010`.

The WebUI reads real server data for health, completed versions, unique stored chunks, stored chunk bytes, and unfinished uploads. Backup, restore, and verify actions call the existing client services, which communicate with the FastAPI API and therefore use the existing SQLite/chunk-store path.

The backup form accepts a real local source-folder path. It does not assume `demo-data`. The last source path is remembered only in the browser's local storage for convenience; backup data itself remains in the existing BrokenVault server storage.

The backup panel also reports real job progress from the existing uploader, including uploaded bytes/chunks and remaining missing chunks. Interrupted uploads remain persisted by the server and can be resumed by running the same source folder again.

### WebUI configuration

The default FastAPI URL is `http://127.0.0.1:8000`. Override it without changing code: 

```powershell
$env:BROKENVAULT_SERVER_URL = "http://127.0.0.1:8000"
python -m client.webapp
```

The WebUI port defaults to `8010`; override it with `BROKENVAULT_WEB_PORT`.

The FastAPI server permits the local WebUI origins `http://127.0.0.1:8010` and `http://localhost:8010` through CORS for direct local API access. The current WebUI normally uses the same-origin `client.webapp` proxy, so browser CORS is not required for normal operation.
