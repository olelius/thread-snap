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
    reputation_init = sub.add_parser(
        "reputation-init", help="从UTF-8 CSV一次性初始化27款口碑车型范围"
    )
    reputation_init.add_argument("--file", type=Path, required=True)
    reputation_acceptance = sub.add_parser(
        "reputation-real-acceptance",
        help="把已完成的真实映射验证冻结为一次基线验收批次",
    )
    reputation_acceptance.add_argument(
        "--validation-run",
        action="append",
        required=True,
        help="可重复提供，后提供的成功项覆盖同车型较早结果",
    )
    sub.add_parser(
        "reputation-compact-evidence",
        help="把历史口碑证据收敛为单张指标区域截图并移除长截图",
    )
    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run("threadsnap.app:app", host=args.host, port=args.port, reload=False)
    elif args.command == "import-session":
        container = Container(get_settings())
        container.session_store.import_file(args.platform, args.file)
        print("平台会话已加密导入。")
    elif args.command == "reputation-init":
        container = Container(get_settings())
        result = container.reputation.initialize_scope_csv(args.file)
        print(
            f"口碑范围已初始化：{len(result['vehicles'])} 款车型，"
            f"修订号 {result['revision']}。"
        )
    elif args.command == "reputation-real-acceptance":
        container = Container(get_settings())
        result = container.reputation.create_real_acceptance(args.validation_run)
        print(
            f"真实口碑验收批次已创建：{result['number']}，"
            f"{result['completed_count']}/{result['planned_count']} 项成功。"
        )
    else:
        container = Container(get_settings())
        result = container.reputation.compact_region_evidence()
        print(
            f"口碑证据已收敛：验证尝试{result['validation_attempts']}项，"
            f"巡检证据{result['run_evidence']}项，移除文件{result['removed_files']}个。"
        )


if __name__ == "__main__":
    main()
