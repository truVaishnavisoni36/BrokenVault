# BrokenVault Architecture

## Goal

BrokenVault sends less data on repeated backups, continues after interruption, and restores every completed version exactly.

## System overview

```text
+----------------------+          HTTP          +----------------------+
|       CLIENT         | <--------------------> |       SERVER         |
|                      |                        |                      |
| scanner              |                        | FastAPI API          |
| chunker + SHA-256    |                        | upload sessions      |
| manifest builder     |                        | atomic commit        |
| upload planner       |                        | integrity verifier   |
| resume journal       |                        |                      |
| restore engine       |                        | SQLite metadata      |
| CLI                  |                        | filesystem chunks    |
+----------------------+                        +----------------------+
```

The supplied architecture specifies separate client/server processes that communicate only over HTTP. The client reads the user's source folder; the server owns long-term backup storage. The implementation keeps that separation. 

## Responsibilities

### Client

- Recursively scans the source folder.
- Rejects unsupported symlinks and unsafe logical paths.
- Streams files into deterministic fixed-size chunks.
- Calculates lowercase SHA-256 IDs.
- Builds a canonical, sorted manifest.
- Creates/resumes uploads over HTTP.
- Stores a small resume journal locally.
- Restores completed versions and checks each chunk before writing it.
- Provides the CLI.

### Server

- Accepts manifests over HTTP.
- Tracks unfinished upload sessions in SQLite.
- Checks which content-addressed chunks are available.
- Re-hashes every received chunk before accepting it.
- Stores one physical copy per SHA-256 ID.
- Publishes completed versions atomically.
- Serves manifests/chunks for restore.
- Re-hashes chunks used by completed versions for `verify`.

## Manifest

A manifest contains one entry per file or directory:

```json
{
  "chunk_size": 262144,
  "entries": [
    {
      "path": "folder/file.bin",
      "type": "file",
      "size": 524288,
      "mtime_ns": 1700000000000000000,
      "chunks": [
        {"id": "...64 lowercase hex chars...", "size": 262144},
        {"id": "...64 lowercase hex chars...", "size": 262144}
      ]
    }
  ]
}
```

Paths are relative, canonical POSIX paths and are sorted. Empty files have zero chunks; empty directories are represented as `dir` entries. The supplied architecture uses 256 KiB fixed chunks and the lowercase SHA-256 of the original bytes as the chunk ID.

## Chunking

Files are read incrementally in 256 KiB blocks. For each block:

```text
file bytes -> 256 KiB block -> SHA-256 -> chunk ID
```

The last chunk may be shorter. The whole file is never loaded into memory.

## Deduplication flow

```text
Client builds manifest
        |
        v
POST /uploads
        |
        v
Server checks content-addressed chunk store
        |
        +---- existing ----> skip upload
        |
        +---- missing -----> PUT chunk
                              |
                              v
                         re-hash server-side
                              |
                              v
                         atomic chunk write
```

`uploaded_bytes` counts only chunks newly accepted for the current upload. `reused_bytes` is `total_bytes - uploaded_bytes`. HTTP headers and manifest JSON are not included.

## Resume flow

```text
Backup starts
    |
    v
Server creates upload_id + stores manifest
    |
    v
Client writes local journal
    |
    v
Upload some chunks
    |
    X interruption / restart
    |
    v
Client rebuilds same manifest
    |
    v
Server finds same manifest digest / journal identifies upload
    |
    v
GET /uploads/{id}/missing
    |
    v
Upload only remaining chunks
    |
    v
Commit
```

The server is authoritative for which chunks are available. Repeated requests are safe: a chunk already stored is not physically copied again.

## Completion state machine

```text
             +----------------+
             |   uploading    |
             +-------+--------+
                     |
          all required chunks
          present + verified
                     |
                     v
             +----------------+
             |   COMPLETED    |
             +----------------+
```

Unfinished uploads are not represented in the completed-version tables. The commit transaction:

1. Re-checks every required chunk exists and its bytes hash to its ID.
2. Allocates the next version ID.
3. Inserts version/file/file-chunk metadata.
4. Marks the upload completed.

If the transaction fails, SQLite rolls it back and the version is not published.

## Database design

```text
chunks
  id PK
  size
  created_at

uploads
  upload_id PK
  manifest_digest
  manifest_json
  state
  total_bytes
  version_id
  created_at
  completed_at

upload_chunks
  upload_id
  chunk_id
  size
  PK(upload_id, chunk_id)

versions
  version_id PK
  upload_id
  created_at
  total_bytes
  uploaded_bytes
  reused_bytes

version_entries
  version_id
  path
  type
  size
  mtime_ns
  PK(version_id, path)

version_file_chunks
  version_id
  path
  idx
  chunk_id
  size
  PK(version_id, path, idx)
```

The schema separates upload progress from published versions. That makes hiding incomplete backups structural rather than dependent on a UI flag.

## Chunk storage

```text
storage/
├── metadata.db
└── chunks/
    ├── ab/
    │   └── cd/
    │       └── abcdef...64hex...
    └── tmp/
```

Chunk writes go to a random temporary file, are flushed and `fsync`ed, then atomically renamed into the hash-derived destination. Temporary files are removed when the server starts.

## Restore flow

```text
completed version
      |
      v
fetch manifest
      |
      v
validate every relative path
      |
      v
create directories
      |
      v
for each file:
  fetch chunk -> hash -> write temp file
      |
      v
atomic rename + restore file mtime
      |
      v
restore directory mtimes deepest-first
```

Restore requires an empty destination. A manifest path is resolved under that destination and rejected if it escapes. Each downloaded chunk is hashed before the final file is published.

## Verification flow

```text
completed-version references
          |
          v
iterate unique chunk IDs
          |
          v
exists? ---- no ----> missing
   |
  yes
   |
   v
SHA-256 matches ID?
   |             |
  yes            no
   |             |
   v             v
  OK           corrupt
                 |
                 v
       query version_file_chunks
                 |
                 v
       report version + path
```

`verify` never repairs data. A non-clean result is reported with the chunk ID, reason, and every affected completed version/file.

## Failure handling

| Fault | Behavior |
|---|---|
| Client killed during upload | Server keeps upload as unfinished; journal remains; next backup resumes |
| Server killed during upload | SQLite upload state and already committed chunks survive; temp files are cleaned |
| Both restart | Manifest digest and journal allow the same unfinished upload to continue |
| Crash during commit | SQLite transaction rolls back; no completed version is published |
| Missing/corrupt chunk | `verify` reports it; restore also fails safely when it reads it |
| Bad manifest path | Rejected by server; restore validates again |
| Non-empty restore target | Restore refuses with `TARGET_NOT_EMPTY` |
| Duplicate chunk request | Existing content is reused; no second physical copy |

## Security/path validation

- Absolute paths are rejected.
- `..` traversal is rejected.
- Manifest paths must be canonical POSIX relative paths.
- Duplicate logical paths are rejected.
- Restore checks the resolved path remains under the requested destination.
- Symlinks are rejected during source scanning because they are outside the documented core scope.
- Chunk IDs must be lowercase hexadecimal SHA-256 values.
- The server re-hashes uploaded bytes rather than trusting the client-provided ID.

## Web UI integration

The repository includes the optional UI described by the supplied architecture as a plain local web client. `client/webapp.py` serves `client/web/index.html`, `app.js`, and `styles.css`. Its `/api/*` routes call the existing `ClientAPI`, which communicates with the FastAPI server over HTTP. The UI therefore uses the same uploader, restore, verification, SQLite metadata, and filesystem chunk store as the CLI.

Dashboard statistics are read from persisted server metadata through `GET /stats`: unique stored chunks, stored chunk bytes, completed versions, aggregate version bytes, and unfinished upload count. They are not hard-coded or inferred from mock/demo data.

The browser normally talks to the same-origin local web client, so the web client acts as the browser-facing adapter. The FastAPI server also allows the two local UI origins (`http://127.0.0.1:8010` and `http://localhost:8010`) through CORS for direct local API use.

## Design trade-offs

### Fixed chunks instead of content-defined chunks

Fixed 256 KiB chunks are deterministic, simple, fast to implement, and directly supported by the supplied architecture. Content-defined chunking is optional/stretch and was intentionally not added before the core system.

### Sequential upload instead of complex concurrency

A sequential uploader keeps resume and byte accounting easy to reason about for a one-day hackathon. It is fast enough for the target laptop-scale demo and avoids adding synchronization complexity before correctness is proven.

### Hash at commit time

The server verifies every required chunk before publication, including chunks reused from previous versions. This adds a verification pass but guarantees that a completed version is never published against a missing or modified chunk.

### CLI instead of UI

The supplied workflow discusses a possible UI, but the challenge/master requirements state that a CLI is sufficient and list graphical UI as unnecessary core scope. The implementation therefore keeps one clear CLI path and spends effort on resume, restore, deduplication and verification.
