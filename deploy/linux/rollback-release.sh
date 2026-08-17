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

ln -sfn "$previous_target" "$APP_ROOT/.current.rollback"
mv -Tf "$APP_ROOT/.current.rollback" "$CURRENT"
ln -sfn "$current_target" "$PREVIOUS"
systemctl restart threadsnap.service

if ! bash "$CURRENT/deploy/verify.sh" --quick; then
  ln -sfn "$current_target" "$APP_ROOT/.current.restore"
  mv -Tf "$APP_ROOT/.current.restore" "$CURRENT"
  ln -sfn "$previous_target" "$PREVIOUS"
  systemctl restart threadsnap.service
  echo "ERROR: previous release failed health verification; restored $current_target" >&2
  exit 4
fi

echo "current_release=$previous_target"
echo "previous_release=$current_target"
echo "NOTE: release rollback does not downgrade the SQLite schema; use a matched backup for incompatible migrations"
