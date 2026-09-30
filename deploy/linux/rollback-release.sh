#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run with sudo/root" >&2
  exit 2
fi

APP_ROOT=/opt/threadsnap
CURRENT="$APP_ROOT/current"
PREVIOUS="$APP_ROOT/previous"
[[ -L "$CURRENT" && -L "$PREVIOUS" ]] || {
  echo "ERROR: current/previous release links are not both available" >&2
  exit 3
}

current_target="$(readlink -f "$CURRENT")"
previous_target="$(readlink -f "$PREVIOUS")"
[[ -d "$previous_target" ]] || { echo "ERROR: previous release directory missing" >&2; exit 3; }

# 读取目标wheel自己的迁移head；不启动应用，不让Container预检时自动升级数据库。
previous_head="$("$previous_target/venv/bin/python" - <<'HEAD_PY'
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
import threadsnap.db

config = Config()
config.set_main_option("script_location", str(Path(threadsnap.db.__file__).parent / "migrations"))
heads = ScriptDirectory.from_config(config).get_heads()
if len(heads) != 1:
    raise SystemExit("ERROR: target release must have exactly one migration head")
print(heads[0])
HEAD_PY
)"

schema_action() {
  runuser -u threadsnap -- "$current_target/venv/bin/python" - "$1" "$2" <<'SCHEMA_PY'
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event

INDEX_REVISION = "d9e4b7a2c601"
BASE_REVISION = "f3b6c9d2a804"


def current_revision(database_url):
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            heads = MigrationContext.configure(connection).get_current_heads()
        if len(heads) != 1:
            raise RuntimeError("Database must have exactly one migration revision")
        return heads[0]
    finally:
        engine.dispose()


def run_schema_action(database_url, migrations, mode, target_head):
    """仅允许同版本或本次索引revision回退；永不替换业务数据库。"""
    config = Config()
    config.set_main_option("script_location", str(migrations))
    config.attributes["database_url"] = database_url
    scripts = ScriptDirectory.from_config(config)
    actual = current_revision(database_url)
    if scripts.get_revision(actual) is None:
        raise RuntimeError("Unknown database revision; rollback refused")
    if mode == "preflight":
        if actual == target_head:
            return f"{actual}:same"
        if (actual, target_head) != (INDEX_REVISION, BASE_REVISION):
            raise RuntimeError("Incompatible database revision; rollback refused")
        if scripts.get_revision(INDEX_REVISION).down_revision != BASE_REVISION:
            raise RuntimeError("Index-only migration parent mismatch")
        return f"{actual}:downgrade"
    if mode == "downgrade":
        if (actual, target_head) != (INDEX_REVISION, BASE_REVISION):
            raise RuntimeError("Database changed after preflight; downgrade refused")
    elif mode == "recover":
        if target_head != INDEX_REVISION:
            if actual != target_head:
                raise RuntimeError("Original release schema changed; service restart refused")
            return f"{actual}:same"
        if actual not in {BASE_REVISION, INDEX_REVISION}:
            raise RuntimeError("Unknown recovery revision; service restart refused")
    else:
        raise RuntimeError("Unknown schema rollback action")
    revision = scripts.get_revision(INDEX_REVISION)
    if revision.down_revision != BASE_REVISION:
        raise RuntimeError("Index-only migration parent mismatch")

    # pysqlite默认可能自动提交DDL。仅在本辅助进程中显式BEGIN，让六项索引与revision
    # 一起提交/回滚；不修改应用迁移env，也不依赖它支持外部connection。
    def sqlite_begin(connection):
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")

    event.listen(Engine, "begin", sqlite_begin)
    try:
        if mode == "downgrade":
            command.downgrade(config, BASE_REVISION)
            expected = BASE_REVISION
        elif actual == BASE_REVISION:
            command.upgrade(config, INDEX_REVISION)
            expected = INDEX_REVISION
        else:
            # Alembic在head时upgrade(head)不重跑迁移。仅重放这一个已知幂等索引迁移，
            # 兼容之前的非事务DDL中断；不stamp revision或执行其它历史迁移。
            engine = create_engine(database_url)
            try:
                with engine.begin() as connection:
                    with EnvironmentContext(config, scripts) as environment:
                        environment.configure(connection=connection)
                        with Operations.context(environment.get_context()):
                            revision.module.upgrade()
            finally:
                engine.dispose()
            expected = INDEX_REVISION
    finally:
        event.remove(Engine, "begin", sqlite_begin)
    if current_revision(database_url) != expected:
        raise RuntimeError("Schema transition did not reach the required revision")
    return f"{expected}:{mode}"


if __name__ == "__main__":
    import threadsnap.db
    from threadsnap.config import Settings

    settings = Settings(_env_file="/etc/threadsnap/threadsnap.env")
    migrations = Path(threadsnap.db.__file__).parent / "migrations"
    print(run_schema_action(settings.database_url, migrations, sys.argv[1], sys.argv[2]))
SCHEMA_PY
}

# 先只读检查；未知schema在停服、补ZIP或任何迁移之前立即拒绝。
schema_plan="$(schema_action preflight "$previous_head")"
schema_before="${schema_plan%%:*}"
schema_transition="${schema_plan#*:}"
schema_downgrade_attempted=false
timer_was_active=false
systemctl is-active --quiet threadsnap-backup-retention.timer && timer_was_active=true
restore_current() {
  trap - ERR
  systemctl stop threadsnap-nginx.service || true
  systemctl stop threadsnap.service || true
  ln -sfn "$current_target" "$APP_ROOT/.current.restore"
  mv -Tf "$APP_ROOT/.current.restore" "$CURRENT"
  ln -sfn "$previous_target" "$PREVIOUS"
  # 失败只恢复索引与程序指针，不恢复会丢失新业务写入的旧数据库备份。
  if [[ "$schema_downgrade_attempted" == true ]]; then
    if ! schema_action recover "$schema_before"; then
      echo "ERROR: restored release links, but schema recovery failed; services remain stopped" >&2
      exit 4
    fi
  fi
  systemctl start threadsnap.service || true
  systemctl start threadsnap-nginx.service || true
  if [[ "$timer_was_active" == true ]]; then
    systemctl start threadsnap-backup-retention.timer || true
  fi
  echo "ERROR: rollback failed; restored $current_target" >&2
  exit 4
}
trap restore_current ERR

systemctl stop threadsnap-backup-retention.timer 2>/dev/null || true
systemctl stop threadsnap-nginx.service
systemctl stop threadsnap.service
# 旧程序要求ZIP已存在；只补齐已冻结PNG的封装，不重绘、重采或改写历史包。
if "$current_target/venv/bin/python" -c 'import importlib.util,sys;sys.exit(importlib.util.find_spec("threadsnap.retention") is None)'; then
  runuser -u threadsnap -- "$current_target/venv/bin/python" - <<'PY'
from pathlib import Path
from sqlalchemy import select
from threadsnap.config import Settings
from threadsnap.db import build_engine, build_session_factory
from threadsnap.models import ScreenshotArtifactVersion
from threadsnap.screenshots import ScreenshotService
from threadsnap.storage_activity import StorageProcessLock

settings = Settings(_env_file="/etc/threadsnap/threadsnap.env")
with StorageProcessLock(settings.data_dir / "retention" / "application.lock"):
    engine = build_engine(settings.database_url)
    sessions = build_session_factory(engine)
    screenshots = ScreenshotService(sessions, settings)
    try:
        with sessions() as db:
            versions = list(db.scalars(select(ScreenshotArtifactVersion).where(
                ScreenshotArtifactVersion.status == "ready"
            )))
        count = 0
        for version in versions:
            if not Path(version.package_path).is_file():
                screenshots.artifact_file(version.group_id, version=version.version)
                count += 1
        print(f"materialized_packages={count}")
    finally:
        engine.dispose()
PY
fi

if [[ "$schema_transition" == downgrade ]]; then
  schema_downgrade_attempted=true
  schema_action downgrade "$previous_head"
fi

ln -sfn "$previous_target" "$APP_ROOT/.current.rollback"
mv -Tf "$APP_ROOT/.current.rollback" "$CURRENT"
ln -sfn "$current_target" "$PREVIOUS"
systemctl start threadsnap.service
for _ in $(seq 1 50); do
  curl --fail --silent http://127.0.0.1:8000/health >/dev/null && break
  sleep 0.2
done
systemctl start threadsnap-nginx.service

if ! bash "$CURRENT/deploy/verify.sh" --quick; then
  restore_current
fi
if "$previous_target/venv/bin/python" -c 'import importlib.util,sys;sys.exit(importlib.util.find_spec("threadsnap.backup_retention") is None)'; then
  systemctl start threadsnap-backup-retention.timer
fi
trap - ERR

echo "current_release=$previous_target"
echo "previous_release=$current_target"
echo "NOTE: only the verified index-only migration may be downgraded; business data was not replaced"
