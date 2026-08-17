#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run with sudo/root" >&2
  exit 2
fi

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
cleanup() {
  rm -rf -- "$WORK"
  if [[ "$was_active" == true ]]; then
    systemctl start threadsnap.service || true
  fi
}
trap cleanup EXIT

if systemctl is-active --quiet threadsnap.service; then
  was_active=true
  systemctl stop threadsnap.service
fi

mkdir -p "$WORK/$NAME/data" "$WORK/$NAME/config"
cp -a "$DATA_DIR/." "$WORK/$NAME/data/"
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

find "$WORK/$NAME" -type f ! -name SHA256SUMS -print0 | sort -z | while IFS= read -r -d '' file; do
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

if [[ "$was_active" == true ]]; then
  systemctl start threadsnap.service
  was_active=false
fi
trap - EXIT
rm -rf -- "$WORK"

echo "backup=$ARCHIVE"
echo "checksum=$ARCHIVE.sha256"
echo "IMPORTANT: copy both files to a different filesystem or backup host"
