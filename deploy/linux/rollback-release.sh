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

timer_was_active=false
systemctl is-active --quiet threadsnap-backup-retention.timer && timer_was_active=true
restore_current() {
  trap - ERR
  systemctl stop threadsnap-nginx.service || true
  systemctl stop threadsnap.service || true
  ln -sfn "$current_target" "$APP_ROOT/.current.restore"
  mv -Tf "$APP_ROOT/.current.restore" "$CURRENT"
  ln -sfn "$previous_target" "$PREVIOUS"
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
from threadsnap.app import Container
from threadsnap.config import Settings
from threadsnap.models import ScreenshotArtifactVersion
from threadsnap.storage_activity import StorageProcessLock

settings = Settings(_env_file="/etc/threadsnap/threadsnap.env")
with StorageProcessLock(settings.data_dir / "retention" / "application.lock"):
    container = Container(settings)
    try:
        with container.sessions() as db:
            versions = list(db.scalars(select(ScreenshotArtifactVersion).where(
                ScreenshotArtifactVersion.status == "ready"
            )))
        count = 0
        for version in versions:
            if not Path(version.package_path).is_file():
                container.screenshots.artifact_file(version.group_id, version=version.version)
                count += 1
        print(f"materialized_packages={count}")
    finally:
        container.engine.dispose()
PY
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
echo "NOTE: release rollback does not downgrade the SQLite schema; use a matched backup for incompatible migrations"
