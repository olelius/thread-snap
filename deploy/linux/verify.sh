#!/usr/bin/env bash
set -euo pipefail

LISTEN_PORT="80"
SERVER_NAME="_"
QUICK=false
while (($#)); do
  case "$1" in
    --listen-port) LISTEN_PORT="${2:?missing port}"; shift 2 ;;
    --server-name) SERVER_NAME="${2:?missing server name}"; shift 2 ;;
    --quick) QUICK=true; shift ;;
    *) echo "ERROR: unknown option: $1" >&2; exit 2 ;;
  esac
done

failures=0
check() {
  local label="$1"
  shift
  if "$@"; then
    echo "PASS: $label"
  else
    echo "FAIL: $label" >&2
    failures=$((failures + 1))
  fi
}

check "threadsnap service active" systemctl is-active --quiet threadsnap.service
check "Wayland service active" systemctl is-active --quiet threadsnap-wayland.service
check "nginx service active" systemctl is-active --quiet nginx.service
check "nginx configuration" nginx -t

health_ready=false
for _ in $(seq 1 30); do
  if curl --fail --silent --show-error http://127.0.0.1:8000/health | grep -q '"status":"ok"'; then
    health_ready=true
    break
  fi
  sleep 1
done
check "direct backend health" test "$health_ready" = true
check "Nginx health" bash -c "curl --header 'Host: ${SERVER_NAME}' --fail --silent http://127.0.0.1:${LISTEN_PORT}/health | grep -q '\"status\":\"ok\"'"
check "SPA index" bash -c "curl --header 'Host: ${SERVER_NAME}' --fail --silent http://127.0.0.1:${LISTEN_PORT}/ | grep -qi '<!doctype html'"
check "Nginx blocks internal API" bash -c \
  "test \"\$(curl --header 'Host: ${SERVER_NAME}' --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:${LISTEN_PORT}/internal/v1/platforms)\" = 404"
check "loopback internal API remains available" bash -c \
  "test \"\$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:8000/internal/v1/platforms)\" = 200"

if ss -ltnH '( sport = :8000 )' | awk '{print $4}' | grep -Ev '^(127\.0\.0\.1|\[::1\]):8000$' | grep -q .; then
  echo "FAIL: backend port 8000 is exposed beyond loopback" >&2
  failures=$((failures + 1))
else
  echo "PASS: backend port 8000 is loopback-only"
fi

if ss -ltnH | awk '{print $4}' | grep -Eq ':(9222|9223)$'; then
  echo "FAIL: raw CDP port is listening" >&2
  failures=$((failures + 1))
else
  echo "PASS: raw CDP ports are closed"
fi

ENV_FILE=/etc/threadsnap/threadsnap.env
check "environment file exists" test -f "$ENV_FILE"
check "headed browser mode configured" grep -q '^THREADSNAP_AUTH_BROWSER_HEADLESS=false$' "$ENV_FILE"
check "Fernet key configured" grep -q '^THREADSNAP_SESSION_FERNET_KEY=.' "$ENV_FILE"

if [[ "$QUICK" == false ]]; then
  check "headed Chromium launches under Wayland" runuser -u threadsnap -- env \
    HOME="$(sed -n 's/^THREADSNAP_DATA_DIR=//p' "$ENV_FILE" | tail -n 1)" \
    XDG_RUNTIME_DIR=/run/threadsnap-wayland \
    WAYLAND_DISPLAY=wayland-99 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/threadsnap/browsers \
    /opt/threadsnap/current/venv/bin/python - <<'PY'
import asyncio
from patchright.async_api import async_playwright

async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=False,
            args=["--ozone-platform=wayland"],
        )
        page = await browser.new_page()
        await page.set_content("<title>ThreadSnap browser smoke</title><h1>ok</h1>")
        assert await page.title() == "ThreadSnap browser smoke"
        await browser.close()

asyncio.run(main())
PY
fi

if ((failures)); then
  echo "verification_failures=$failures" >&2
  exit 1
fi
echo "verification=passed"
