from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common.errors import BrokenVaultError, RemoteError
from .api import ClientAPI
from .chunker import DEFAULT_CHUNK_SIZE
from .restorer import restore
from .uploader import backup


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bv", description="BrokenVault client")
    p.add_argument("--server", default="http://127.0.0.1:8000", help="BrokenVault server URL")
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup", help="Back up a folder")
    b.add_argument("source")
    b.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    b.add_argument("--stop-after", type=int, default=None, help="Demo interruption after N uploaded chunks")
    sub.add_parser("list", help="List completed versions")
    r = sub.add_parser("restore", help="Restore a completed version")
    r.add_argument("version")
    r.add_argument("destination")
    sub.add_parser("verify", help="Verify stored chunks")
    sub.add_parser("status", help="Show server and unfinished upload status")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    api = ClientAPI(args.server)
    try:
        if args.command == "backup":
            result = backup(Path(args.source), api, args.chunk_size, args.stop_after)
            print(f"COMPLETED {result['version_id']}")
            print(f"Total bytes:    {result['total_bytes']}")
            print(f"Uploaded bytes: {result['uploaded_bytes']}")
            print(f"Reused bytes:   {result['reused_bytes']}")
            print(f"Files:          {result['files']}")
            print(f"Chunks:         {result['chunks']}")
            return 0
        if args.command == "list":
            versions = api.versions()
            if not versions:
                print("No completed versions.")
            for v in versions:
                print(
                    f"{v['version_id']}  COMPLETED  total={v['total_bytes']} "
                    f"uploaded={v['uploaded_bytes']} reused={v['reused_bytes']} "
                    f"files={v['files']} chunks={v['chunks']}"
                )
            return 0
        if args.command == "restore":
            result = restore(args.version, Path(args.destination), api)
            print(f"RESTORED {result['version_id']}: {result['files']} files, {result['folders']} folders")
            return 0
        if args.command == "verify":
            result = api.verify()
            if result["ok"]:
                print("VERIFICATION PASSED")
                print("All chunks used by completed versions are valid.")
                return 0
            print("CORRUPTION DETECTED")
            for damage in result["damaged"]:
                print(f"Chunk: {damage['chunk_id']}")
                print(f"Reason: {damage['reason']}")
                for affected in damage["affected"]:
                    print(f"  Version: {affected['version_id']}  File: {affected['path']}")
            return 2
        if args.command == "status":
            print(f"Server: {api.health()['status']}")
            uploads = api.unfinished()
            if uploads:
                print("Unfinished uploads:")
                for u in uploads:
                    print(f"  {u['upload_id']}  {u['created_at']}  total={u['total_bytes']}")
            else:
                print("No unfinished uploads.")
            return 0
    except KeyboardInterrupt as exc:
        print(f"INTERRUPTED: {exc}")
        return 130
    except (BrokenVaultError, RemoteError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
