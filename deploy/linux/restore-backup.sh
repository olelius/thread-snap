#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run with sudo/root" >&2
  exit 2
fi
if [[ $# -ne 2 || "$2" != "--confirm" ]]; then
  echo "Usage: sudo bash deploy/restore-backup.sh BACKUP.tar.gz --confirm" >&2
  exit 2
fi

ARCHIVE="$(readlink -f "$1")"
[[ -f "$ARCHIVE" ]] || { echo "ERROR: backup archive missing" >&2; exit 3; }
[[ -f "$ARCHIVE.sha256" ]] || { echo "ERROR: checksum sidecar missing: $ARCHIVE.sha256" >&2; exit 3; }
(cd "$(dirname "$ARCHIVE")" && sha256sum -c "$(basename "$ARCHIVE.sha256")")

WORK="$(mktemp -d "${TMPDIR:-/tmp}/threadsnap-restore.XXXXXX")"
cleanup() { rm -rf -- "$WORK"; }
trap cleanup EXIT

python3 - "$ARCHIVE" "$WORK" <<'PY'
import sys, tarfile
from pathlib import Path, PurePosixPath

archive, destination = sys.argv[1:]
with tarfile.open(archive, "r:gz") as bundle:
    members = bundle.getmembers()
    roots = set()
    for member in members:
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or member.issym()
            or member.islnk()
            or not (member.isfile() or member.isdir())
        ):
            raise SystemExit(f"ERROR: unsafe backup member: {member.name}")
        if path.parts:
            roots.add(path.parts[0])
    if len(roots) != 1:
        raise SystemExit("ERROR: backup must contain one top-level directory")
    bundle.extractall(destination)
print(next(iter(roots)))
PY
BACKUP_ROOT="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d -print -quit)"
[[ -f "$BACKUP_ROOT/SHA256SUMS" && -d "$BACKUP_ROOT/data" && -f "$BACKUP_ROOT/config/threadsnap.env" ]] || {
  echo "ERROR: backup structure invalid" >&2
  exit 3
}
(cd "$BACKUP_ROOT" && sha256sum -c SHA256SUMS)

RESTORED_ENV="$BACKUP_ROOT/config/threadsnap.env"
DATA_DIR="$(sed -n 's/^THREADSNAP_DATA_DIR=//p' "$RESTORED_ENV" | tail -n 1)"
[[ "$DATA_DIR" == /* && "$DATA_DIR" != / ]] || { echo "ERROR: invalid restored data directory" >&2; exit 3; }

STAMP="$(date +%Y%m%d-%H%M%S)"
ROLLBACK_DATA="${DATA_DIR}.before-restore-$STAMP"
ROLLBACK_ENV="/etc/threadsnap/threadsnap.env.before-restore-$STAMP"
systemctl stop threadsnap.service

if [[ -e "$DATA_DIR" ]]; then
  mv "$DATA_DIR" "$ROLLBACK_DATA"
fi
if [[ -f /etc/threadsnap/threadsnap.env ]]; then
  cp -a /etc/threadsnap/threadsnap.env "$ROLLBACK_ENV"
fi

mkdir -p "$(dirname "$DATA_DIR")"
mv "$BACKUP_ROOT/data" "$DATA_DIR"
cp -a "$RESTORED_ENV" /etc/threadsnap/threadsnap.env
chown -R threadsnap:threadsnap "$DATA_DIR"
chown root:threadsnap /etc/threadsnap/threadsnap.env
chmod 0700 "$DATA_DIR"
chmod 0640 /etc/threadsnap/threadsnap.env

systemctl start threadsnap.service
if ! bash /opt/threadsnap/current/deploy/verify.sh --quick; then
  systemctl stop threadsnap.service
  rm -rf -- "$DATA_DIR"
  [[ -e "$ROLLBACK_DATA" ]] && mv "$ROLLBACK_DATA" "$DATA_DIR"
  [[ -f "$ROLLBACK_ENV" ]] && mv "$ROLLBACK_ENV" /etc/threadsnap/threadsnap.env
  systemctl start threadsnap.service
  echo "ERROR: restored backup failed health verification; original data/config restored" >&2
  exit 4
fi

trap - EXIT
rm -rf -- "$WORK"
echo "restored_backup=$ARCHIVE"
echo "previous_data=$ROLLBACK_DATA"
echo "previous_environment=$ROLLBACK_ENV"
