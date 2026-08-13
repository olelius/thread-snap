"""ThreadSnap 命令行入口。"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .app import Container
from .config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="threadsnap")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="启动 HTTP API、调度器和 Worker")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    import_session = sub.add_parser(
        "import-session", help="从本机 storage-state.json 导入加密平台会话"
    )
    import_session.add_argument("--platform", default="dongchedi")
    import_session.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run("threadsnap.app:app", host=args.host, port=args.port, reload=False)
    else:
        container = Container(get_settings())
        container.session_store.import_file(args.platform, args.file)
        print("平台会话已加密导入。")


if __name__ == "__main__":
    main()
