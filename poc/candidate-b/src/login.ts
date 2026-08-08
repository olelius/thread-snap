/** 候选 B：使用 Crawlee PlaywrightCrawler 建立持久登录会话。 */

import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { PlaywrightCrawler } from 'crawlee';
import { classifyDocument, extractInputPostId, urlSha256 } from './contract.js';

interface Options {
  probeUrl: string;
  profileDir: string;
  output: string;
  headless: boolean;
}

function parseArgs(argv: string[]): Options {
  const values = new Map<string, string>();
  let headless = false;
  for (let index = 0; index < argv.length;) {
    const key = argv[index]!;
    if (key === '--headless') {
      headless = true;
      index += 1;
      continue;
    }
    const value = argv[index + 1];
    if (!key.startsWith('--') || value === undefined) throw new Error(`参数格式错误: ${key}`);
    values.set(key, value);
    index += 2;
  }
  const probeUrl = values.get('--probe-url');
  const profileDir = values.get('--profile-dir');
  const output = values.get('--output');
  if (!probeUrl || !profileDir || !output) throw new Error('缺少 --probe-url、--profile-dir 或 --output');
  return { probeUrl, profileDir: resolve(profileDir), output: resolve(output), headless };
}

function pathTemplate(value: string): string {
  const parsed = new URL(value);
  const path = parsed.pathname.replace(/\d{6,}/g, 'POST_ID');
  const keys = [...new Set(parsed.searchParams.keys())].sort();
  return keys.length ? `${path}?keys=${keys.join(',')}` : path;
}

async function main(): Promise<void> {
  const options = parseArgs(process.argv.slice(2));
  const account = process.env['THREADSNAP_PLATFORM_ACCOUNT'];
  const password = process.env['THREADSNAP_PLATFORM_PASSWORD'];
  if (!account || !password) throw new Error('缺少登录凭证环境变量');
  delete process.env['THREADSNAP_PLATFORM_ACCOUNT'];
  delete process.env['THREADSNAP_PLATFORM_PASSWORD'];

  mkdirSync(options.profileDir, { recursive: true });
  mkdirSync(resolve(options.output, '..'), { recursive: true });
  const documents: Array<{ status: number; path: string }> = [];
  const subrequestStatuses = new Set<number>();
  let result: Record<string, unknown> | undefined;
  const crawler = new PlaywrightCrawler({
    maxConcurrency: 1,
    maxRequestRetries: 0,
    retryOnBlocked: false,
    useSessionPool: false,
    requestHandlerTimeoutSecs: 90,
    launchContext: {
      userDataDir: options.profileDir,
      launchOptions: { headless: options.headless, channel: 'chrome' },
    },
    preNavigationHooks: [
      async ({ page }) => {
        page.on('response', (response) => {
          const resourceType = response.request().resourceType();
          if (resourceType === 'document') documents.push({ status: response.status(), path: pathTemplate(response.url()) });
          else if (resourceType === 'xhr' || resourceType === 'fetch') subrequestStatuses.add(response.status());
        });
      },
    ],
    requestHandler: async ({ page }) => {
      await page.waitForTimeout(2_000);
      let submitted = false;
      if (page.url().includes('/login-required')) {
        if (await page.locator('input[name="code"]').count()) {
          await page.locator('button').last().click({ timeout: 5_000 });
          await page.waitForTimeout(500);
        }
        await page.locator('input[name="account"]').fill(account);
        await page.locator('input[name="password"]').fill(password);
        await page.getByRole('button', { name: '登录', exact: true }).click({ timeout: 10_000 });
        submitted = true;
        await page.waitForTimeout(10_000);
      }
      const finalUrl = page.url();
      const document = await page.content();
      const classification = classifyDocument(finalUrl, 200, document, extractInputPostId(options.probeUrl));
      const cookies = await page.context().cookies();
      result = {
        schema_version: '1.0',
        candidate: 'candidate-b',
        submitted,
        logged_in: !finalUrl.includes('/login-required') && classification.response_class === 'post',
        final_path: pathTemplate(finalUrl),
        response_class: classification.response_class,
        status: classification.status,
        cookie_count: cookies.length,
        cookie_name_hashes: cookies.map((cookie) => createHash('sha256').update(cookie.name).digest('hex')).sort(),
        verification_required: ['captcha', '验证码', '验证中心'].some((marker) => document.toLowerCase().includes(marker)),
        document_chain: documents,
        subrequest_statuses: [...subrequestStatuses].sort(),
      };
    },
  });
  await crawler.run([{ url: options.probeUrl, uniqueKey: `login:${urlSha256(options.probeUrl)}` }]);
  if (!result) throw new Error('登录运行未生成结果');
  writeFileSync(options.output, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  const printable = { ...result };
  delete printable['cookie_name_hashes'];
  console.log(JSON.stringify(printable));
  if (!result['logged_in']) process.exitCode = 4;
}

await main();
