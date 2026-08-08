#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
[[ -f .runtime/ready ]] || { echo "ERROR: 请先运行 ./poc/linux/start.sh" >&2; exit 2; }
NODE_HOME="$ROOT/.runtime/node-v22.17.0-linux-x64"
export PATH="$NODE_HOME/bin:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.runtime/browsers"

.runtime/candidate-a/bin/python - <<'PY'
import asyncio
from scrapling.fetchers import AsyncDynamicSession
async def main():
    async with AsyncDynamicSession(headless=True, max_pages=1):
        pass
asyncio.run(main())
print("candidate-a browser ok")
PY

node --input-type=module - <<'JS'
import { chromium } from './poc/candidate-b/node_modules/playwright/index.mjs';
const browser = await chromium.launch({ headless: true });
await browser.close();
console.log('candidate-b browser ok');
JS
echo "healthcheck ok"
