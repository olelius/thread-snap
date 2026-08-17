#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DATA_DIR="/var/lib/threadsnap"
DATA_DIR_EXPLICIT=false
SERVER_NAME="_"
LISTEN_PORT="80"
SKIP_SYSTEM_DEPS=false
START_SERVICES=true

usage() {
  cat <<'EOF'
Usage: sudo bash deploy/install.sh [options]

Options:
  --data-dir PATH       Persistent data directory (default: /var/lib/threadsnap)
  --server-name NAME    Nginx server_name (default: _)
  --listen-port PORT    Nginx HTTP port (default: 80)
  --skip-system-deps    Skip deploy/install-system-deps.sh
  --no-start            Install files without starting services
  -h, --help            Show this help
EOF
}

while (($#)); do
  case "$1" in
    --data-dir)
      DATA_DIR="${2:?missing value for --data-dir}"
      DATA_DIR_EXPLICIT=true
      shift 2
      ;;
    --server-name)
      SERVER_NAME="${2:?missing value for --server-name}"
      shift 2
      ;;
    --listen-port)
      LISTEN_PORT="${2:?missing value for --listen-port}"
      shift 2
      ;;
    --skip-system-deps)
      SKIP_SYSTEM_DEPS=true
      shift
      ;;
    --no-start)
      START_SERVICES=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run with sudo/root" >&2
  exit 2
fi
[[ "$DATA_DIR" == /* ]] || { echo "ERROR: --data-dir must be an absolute path" >&2; exit 2; }
[[ "$DATA_DIR" =~ ^/[A-Za-z0-9._/-]+$ && "$DATA_DIR" != *"/../"* && "$DATA_DIR" != */.. ]] || {
  echo "ERROR: --data-dir contains unsupported or unsafe path components" >&2
  exit 2
}
[[ "$LISTEN_PORT" =~ ^[0-9]+$ ]] && ((LISTEN_PORT >= 1 && LISTEN_PORT <= 65535)) || {
  echo "ERROR: invalid listen port: $LISTEN_PORT" >&2
  exit 2
}
[[ "$SERVER_NAME" =~ ^[A-Za-z0-9._*-]+$ ]] || {
  echo "ERROR: server name contains unsupported characters" >&2
  exit 2
}

for required in PACKAGE-MANIFEST.json SHA256SUMS SYSTEM-PACKAGES.txt backend frontend deploy wheelhouse browsers rpms; do
  [[ -e "$PACKAGE_ROOT/$required" ]] || {
    echo "ERROR: deployment package is incomplete: $required" >&2
    exit 3
  }
done
find "$PACKAGE_ROOT/browsers" -type f -name chrome -print -quit | grep -q . || {
  echo "ERROR: package-local Chromium executable is missing" >&2
  exit 3
}

(
  cd "$PACKAGE_ROOT"
  sha256sum -c SHA256SUMS
)

if [[ "$SKIP_SYSTEM_DEPS" == false ]]; then
  bash "$SCRIPT_DIR/install-system-deps.sh"
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"ERROR: Python 3.11+ required, found {sys.version.split()[0]}")
PY

readarray -t manifest_values < <(
  python3 - "$PACKAGE_ROOT/PACKAGE-MANIFEST.json" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8-sig"))
print(manifest["version"])
print(manifest["source_commit"])
print(str(manifest.get("installable", False)).lower())
print(manifest.get("assembled_on", {}).get("python", ""))
PY
)
APP_VERSION="${manifest_values[0]}"
SOURCE_COMMIT="${manifest_values[1]}"
[[ "${manifest_values[2]}" == "true" ]] || {
  echo "ERROR: this is a builder input package, not the assembled offline deployment package" >&2
  exit 3
}
ASSEMBLED_PYTHON="${manifest_values[3]}"
source /etc/os-release
[[ "${ID:-}" == "centos" && "${VERSION_ID:-}" == 10* && "$(uname -m)" == "x86_64" ]] || {
  echo "ERROR: package target is CentOS Stream 10 x86_64; found ${ID:-unknown} ${VERSION_ID:-unknown} $(uname -m)" >&2
  exit 3
}
CURRENT_PYTHON="$(python3 -c 'import platform; print(platform.python_version())')"
[[ "${CURRENT_PYTHON%.*}" == "${ASSEMBLED_PYTHON%.*}" ]] || {
  echo "ERROR: package Python baseline is $ASSEMBLED_PYTHON, installed interpreter is $CURRENT_PYTHON" >&2
  exit 3
}
RELEASE_ID="${APP_VERSION}-${SOURCE_COMMIT:0:12}"
APP_ROOT="/opt/threadsnap"
RELEASES_DIR="$APP_ROOT/releases"
RELEASE_DIR="$RELEASES_DIR/$RELEASE_ID"
CURRENT_LINK="$APP_ROOT/current"
PREVIOUS_LINK="$APP_ROOT/previous"
BROWSER_DIR="$APP_ROOT/browsers"
CONFIG_DIR="/etc/threadsnap"
ENV_FILE="$CONFIG_DIR/threadsnap.env"
BACKUP_DIR="/var/backups/threadsnap"

if [[ -f "$ENV_FILE" && "$DATA_DIR_EXPLICIT" == false ]]; then
  existing_data_dir="$(sed -n 's/^THREADSNAP_DATA_DIR=//p' "$ENV_FILE" | tail -n 1)"
  [[ "$existing_data_dir" == /* ]] && DATA_DIR="$existing_data_dir"
fi

if ! getent group threadsnap >/dev/null 2>&1; then
  groupadd --system threadsnap
fi
if ! id threadsnap >/dev/null 2>&1; then
  useradd --system --gid threadsnap --home-dir "$DATA_DIR" --shell /sbin/nologin threadsnap
fi

install -d -m 0755 "$APP_ROOT" "$RELEASES_DIR"
install -d -o threadsnap -g threadsnap -m 0700 "$DATA_DIR" "$BROWSER_DIR" "$BACKUP_DIR"
install -d -m 0750 -o root -g threadsnap "$CONFIG_DIR"

if [[ -e "$RELEASE_DIR" ]]; then
  echo "ERROR: release already exists: $RELEASE_DIR" >&2
  exit 4
fi

STAGING_DIR="$RELEASES_DIR/.${RELEASE_ID}.tmp.$$"
cleanup_staging() {
  [[ -d "$STAGING_DIR" ]] && rm -rf -- "$STAGING_DIR"
}
trap cleanup_staging EXIT
install -d -m 0755 "$STAGING_DIR/backend" "$STAGING_DIR/frontend" "$STAGING_DIR/deploy"
cp -a "$PACKAGE_ROOT/backend/." "$STAGING_DIR/backend/"
cp -a "$PACKAGE_ROOT/frontend/." "$STAGING_DIR/frontend/"
cp -a "$PACKAGE_ROOT/deploy/." "$STAGING_DIR/deploy/"
cp "$PACKAGE_ROOT/PACKAGE-MANIFEST.json" "$STAGING_DIR/"

python3 -m venv "$STAGING_DIR/venv"
APP_WHEEL="$(find "$STAGING_DIR/backend" -maxdepth 1 -type f -name 'threadsnap-*.whl' -print -quit)"
[[ -n "$APP_WHEEL" ]] || { echo "ERROR: ThreadSnap wheel missing" >&2; exit 5; }

"$STAGING_DIR/venv/bin/python" -m pip install \
  --no-index --find-links "$PACKAGE_ROOT/wheelhouse" "$APP_WHEEL"
cp -a "$PACKAGE_ROOT/browsers/." "$BROWSER_DIR/"
"$STAGING_DIR/venv/bin/python" -m pip check
chown -R threadsnap:threadsnap "$BROWSER_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  FERNET_KEY="$("$STAGING_DIR/venv/bin/python" - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode("ascii"))
PY
)"
  DATABASE_URL="sqlite:////${DATA_DIR#/}/threadsnap.db"
  sed \
    -e "s|sqlite:////var/lib/threadsnap/threadsnap.db|$DATABASE_URL|" \
    -e "s|THREADSNAP_DATA_DIR=/var/lib/threadsnap|THREADSNAP_DATA_DIR=$DATA_DIR|" \
    -e "s|<FERNET_KEY>|$FERNET_KEY|" \
    "$SCRIPT_DIR/templates/threadsnap.env.example" | sed 's/\r$//' > "$ENV_FILE"
  chown root:threadsnap "$ENV_FILE"
  chmod 0640 "$ENV_FILE"
else
  grep -q '^THREADSNAP_SESSION_FERNET_KEY=.' "$ENV_FILE" || {
    echo "ERROR: existing environment file has no Fernet key: $ENV_FILE" >&2
    exit 6
  }
fi

grep -q '^THREADSNAP_AUTH_BROWSER_HEADLESS=false$' "$ENV_FILE" || {
  echo "ERROR: set THREADSNAP_AUTH_BROWSER_HEADLESS=false in $ENV_FILE for the current Linux/Wayland path" >&2
  exit 6
}

mv "$STAGING_DIR" "$RELEASE_DIR"
trap - EXIT
chmod -R a-w "$RELEASE_DIR"
find "$RELEASE_DIR" -type d -exec chmod a+rx {} +
find "$RELEASE_DIR" -type f -exec chmod a+r {} +

old_release=""
if [[ -L "$CURRENT_LINK" ]]; then
  old_release="$(readlink -f "$CURRENT_LINK")"
  ln -sfn "$old_release" "$PREVIOUS_LINK"
fi
ln -sfn "$RELEASE_DIR" "$APP_ROOT/.current.new"
mv -Tf "$APP_ROOT/.current.new" "$CURRENT_LINK"

sed "s|@DATA_DIR@|$DATA_DIR|g" \
  "$SCRIPT_DIR/systemd/threadsnap.service" > /etc/systemd/system/threadsnap.service
cp "$SCRIPT_DIR/systemd/threadsnap-wayland.service" /etc/systemd/system/threadsnap-wayland.service
sed \
  -e "s|@SERVER_NAME@|$SERVER_NAME|g" \
  -e "s|@LISTEN_PORT@|$LISTEN_PORT|g" \
  "$SCRIPT_DIR/nginx/threadsnap.conf" > "$CONFIG_DIR/nginx-site.conf"
cp "$SCRIPT_DIR/nginx/nginx.conf" "$CONFIG_DIR/nginx.conf"
cp "$SCRIPT_DIR/systemd/threadsnap-nginx.service" /etc/systemd/system/threadsnap-nginx.service

if command -v getenforce >/dev/null 2>&1 && [[ "$(getenforce)" != "Disabled" ]]; then
  semanage fcontext -a -t usr_t '/opt/threadsnap/releases(/.*)?' 2>/dev/null || \
    semanage fcontext -m -t usr_t '/opt/threadsnap/releases(/.*)?'
  semanage fcontext -a -t httpd_sys_content_t '/opt/threadsnap/releases/[^/]+/frontend(/.*)?' 2>/dev/null || \
    semanage fcontext -m -t httpd_sys_content_t '/opt/threadsnap/releases/[^/]+/frontend(/.*)?'
  restorecon -RF "$RELEASES_DIR"
  setsebool -P httpd_can_network_connect 1
  semanage port -a -t http_port_t -p tcp "$LISTEN_PORT" 2>/dev/null || \
    semanage port -m -t http_port_t -p tcp "$LISTEN_PORT"
fi

systemctl daemon-reload
nginx -t -c "$CONFIG_DIR/nginx.conf"

if [[ "$START_SERVICES" == true ]]; then
  systemctl enable threadsnap-wayland.service threadsnap.service threadsnap-nginx.service
  systemctl restart threadsnap-wayland.service
  systemctl restart threadsnap.service
  systemctl restart threadsnap-nginx.service
  if ! bash "$SCRIPT_DIR/verify.sh" --listen-port "$LISTEN_PORT" --server-name "$SERVER_NAME" --quick; then
    echo "ERROR: new release health verification failed" >&2
    if [[ -n "$old_release" && -d "$old_release" ]]; then
      ln -sfn "$old_release" "$APP_ROOT/.current.rollback"
      mv -Tf "$APP_ROOT/.current.rollback" "$CURRENT_LINK"
      systemctl restart threadsnap.service
      echo "restored_previous_release=$old_release" >&2
    fi
    exit 7
  fi
fi

cat <<EOF
installed_release=$RELEASE_DIR
current=$CURRENT_LINK
data_dir=$DATA_DIR
environment=$ENV_FILE
nginx_port=$LISTEN_PORT
next_verify=sudo bash $CURRENT_LINK/deploy/verify.sh
firewall_note=allow TCP $LISTEN_PORT only from the controlled intranet/VPN
EOF
