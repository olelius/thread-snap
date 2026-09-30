#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run with sudo/root" >&2
  exit 2
fi

# 与固定保留任务互斥，正在备份或恢复时不能移除恢复点。
exec 9>/run/lock/threadsnap-backup-maintenance.lock
flock -x 9

ENV_FILE="/etc/threadsnap/threadsnap.env"
[[ -f "$ENV_FILE" ]] || { echo "ERROR: missing $ENV_FILE" >&2; exit 3; }
DATA_DIR="$(sed -n 's/^THREADSNAP_DATA_DIR=//p' "$ENV_FILE" | tail -n 1)"
[[ "$DATA_DIR" == /* && "$DATA_DIR" != / ]] || { echo "ERROR: invalid data directory" >&2; exit 3; }

OUTPUT_DIR="${1:-/var/backups/threadsnap}"
install -d -m 0700 "$OUTPUT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
NAME="threadsnap-backup-$STAMP"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/threadsnap-backup.XXXXXX")"
was_active=false
nginx_was_active=false
start_services() {
  if [[ "$was_active" == true ]]; then
    systemctl start threadsnap.service
  fi
  if [[ "$nginx_was_active" == true ]]; then
    for _ in $(seq 1 50); do
      curl --fail --silent http://127.0.0.1:8000/health >/dev/null && break
      sleep 0.2
    done
    curl --fail --silent http://127.0.0.1:8000/health >/dev/null
    systemctl start threadsnap-nginx.service
  fi
}
cleanup() {
  local status=$?
  trap - EXIT
  rm -rf -- "$WORK"
  start_services || echo "ERROR: backup finished but services require recovery" >&2
  exit "$status"
}
trap cleanup EXIT

if systemctl is-active --quiet threadsnap-nginx.service; then
  nginx_was_active=true
  systemctl stop threadsnap-nginx.service
fi
if systemctl is-active --quiet threadsnap.service; then
  was_active=true
  systemctl stop threadsnap.service
fi

mkdir -p "$WORK/$NAME/data" "$WORK/$NAME/config"
# backups 是本机恢复点入口（可能指向另一分区），不是业务数据；不能嵌套归档。
# 一次 cp -a 复制全部其他顶层项，保留截图跨 evidence/artifacts 路径的硬链接。
shopt -s dotglob nullglob
data_entries=()
for entry in "$DATA_DIR"/*; do
  [[ "${entry##*/}" == backups ]] || data_entries+=("$entry")
done
if [[ ${#data_entries[@]} -gt 0 ]]; then
  cp -a -- "${data_entries[@]}" "$WORK/$NAME/data/"
fi
shopt -u dotglob nullglob
cp -a "$ENV_FILE" "$WORK/$NAME/config/threadsnap.env"
python3 - "$WORK/$NAME/backup-manifest.json" "$DATA_DIR" <<'PY'
import json, os, sys
from datetime import datetime

manifest = {
    "schema_version": "1.0",
    "created_at": datetime.now().astimezone().isoformat(),
    "source_data_dir": sys.argv[2],
    "current_release": os.path.realpath("/opt/threadsnap/current"),
}
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
PY

find "$WORK/$NAME" -type f ! -path "$WORK/$NAME/SHA256SUMS" -print0 | sort -z | while IFS= read -r -d '' file; do
  relative="${file#"$WORK/$NAME/"}"
  printf '%s  %s\n' "$(sha256sum "$file" | awk '{print $1}')" "$relative"
done > "$WORK/$NAME/SHA256SUMS"

ARCHIVE="$OUTPUT_DIR/$NAME.tar.gz"
tar -czf "$ARCHIVE" -C "$WORK" "$NAME"
(
  cd "$OUTPUT_DIR"
  sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256"
)
chmod 0600 "$ARCHIVE" "$ARCHIVE.sha256"

start_services
was_active=false
nginx_was_active=false
trap - EXIT
rm -rf -- "$WORK"

echo "backup=$ARCHIVE"
echo "checksum=$ARCHIVE.sha256"
echo "IMPORTANT: copy both files to a different filesystem or backup host"
