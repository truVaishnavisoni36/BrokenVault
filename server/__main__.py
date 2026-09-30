import argparse
import uvicorn
from .app import create_app

p = argparse.ArgumentParser(prog="python -m server")
p.add_argument("--host", default="127.0.0.1")
p.add_argument("--port", type=int, default=8000)
p.add_argument("--data-dir", default="storage")
args = p.parse_args()
uvicorn.run(create_app(args.data_dir), host=args.host, port=args.port)
