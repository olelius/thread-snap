"""ThreadSnap 命令行入口。"""

from __future__ import annotations

import argparse
import json
from contextlib import nullcontext
from pathlib import Path

import uvicorn

from .app import Container
from .config import get_settings
from .storage_activity import StorageProcessLock


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
    retention = sub.add_parser("retention", help="只读预览固定14天过期链；--apply仅供停服维护")
    retention.add_argument("--apply", action="store_true")
    backup_retention = sub.add_parser("retention-backups", help="运维固定14天备份保留，默认仅预览")
    backup_retention.add_argument("--apply", action="store_true")
    sub.add_parser("compact-screenshot-storage", help="停服维护：不改字节地合并同哈希PNG物理存储")
    sub.add_parser("materialize-screenshot-packages", help="停服回退前补齐保留版本的懒ZIP")
    args = parser.parse_args()
    if args.command == "retention-backups":
        from .backup_retention import prune_backups

        lock = (StorageProcessLock(Path("/run/lock/threadsnap-backup-maintenance.lock"))
                if args.apply else nullcontext())
        with lock:
            result = prune_backups(get_settings().data_dir, apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["errors"]:
            raise SystemExit(1)
    elif args.command in {"retention", "compact-screenshot-storage", "materialize-screenshot-packages"}:
        settings = get_settings()
        lock = (StorageProcessLock(settings.data_dir / "retention" / "application.lock")
                if args.command != "retention" or args.apply else nullcontext())
        with lock:
            container = Container(settings)
            try:
                if args.command == "retention":
                    result = (container.retention.process_once(force=True) if args.apply
                              else container.retention.preview())
                elif args.command == "materialize-screenshot-packages":
                    from sqlalchemy import select

                    from .models import ScreenshotArtifactVersion

                    with container.sessions() as db:
                        versions = list(db.scalars(select(ScreenshotArtifactVersion).where(
                            ScreenshotArtifactVersion.status == "ready"
                        )))
                    completed = 0
                    for version in versions:
                        if not Path(version.package_path).is_file():
                            container.screenshots.artifact_file(
                                version.group_id, version=version.version
                            )
                            completed += 1
                    result = {"materialized_packages": completed}
                else:
                    with container.storage_activity.maintenance() as acquired:
                        if not acquired:
                            raise RuntimeError("仍有业务在使用存储")
                        result = container.screenshots.compact_identical_pngs()
                print(json.dumps(result, ensure_ascii=False, indent=2))
            finally:
                container.engine.dispose()
    elif args.command == "serve":
        # Linux 多线程采集后，uvloop 的 fork 回调可能在清理继承的 curl 线程池时崩溃。
        # 固定标准循环，让驱动使用无 Python fork 后清理的 subprocess 启动路径。
        uvicorn.run(
            "threadsnap.app:app", host=args.host, port=args.port, reload=False, loop="asyncio"
        )
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
