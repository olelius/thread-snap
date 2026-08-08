/** 候选 B：使用 Crawlee 原生 SessionPool 诊断重定向、会话连续性和网络链。 */

import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { isIP } from 'node:net';
import { CheerioCrawler, PlaywrightCrawler, type Request, type Session } from 'crawlee';
import { classifyDocument, extractInputPostId, urlSha256 } from './contract.js';

interface DiagnosticRow {
  candidate: 'candidate-b';
  variant: string;
  url_sha256: string;
  document_chain: Array<{ status: number; path: string; location?: string | null }>;
  subrequest_statuses?: Array<{ status: number; path: string; count: number }>;
  final_path?: string;
  cookie_count?: number;
  cookie_name_hashes?: string[];
  ua_headless?: boolean;
  body_bytes?: number;
  jsvm_marker?: boolean;
  response_class?: string;
  status?: string;
  session_label?: string;
  error_category?: string;
}

interface CliOptions {
  input: string;
  outputDir: string;
  limit: number;
  browserEngine: 'bundled' | 'real-chrome';
  directIp?: string;
}

function parseArgs(argv: string[]): CliOptions {
  const values = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith('--') || value === undefined) throw new Error(`参数格式错误: ${key ?? '<empty>'}`);
    values.set(key, value);
  }
  const input = values.get('--input');
  const outputDir = values.get('--output-dir');
  const limit = Number.parseInt(values.get('--limit') ?? '3', 10);
  const browserEngine = values.get('--browser-engine') ?? 'bundled';
  const directIp = values.get('--direct-ip');
  if (!input || !outputDir || !Number.isInteger(limit) || limit < 1) {
    throw new Error('必须提供 --input、--output-dir，且 --limit 必须为正整数');
  }
  if (browserEngine !== 'bundled' && browserEngine !== 'real-chrome') throw new Error('--browser-engine 仅支持 bundled 或 real-chrome');
  if (directIp && isIP(directIp) === 0) throw new Error('--direct-ip 必须是有效 IP 地址');
  return { input: resolve(input), outputDir: resolve(outputDir), limit, browserEngine, directIp };
}

function pathTemplate(value: string | URL): string {
  const parsed = value instanceof URL ? value : new URL(value);
  const path = parsed.pathname.replace(/\d{6,}/g, 'POST_ID');
  const keys = [...new Set(parsed.searchParams.keys())].sort();
  return keys.length ? `${path}?keys=${keys.join(',')}` : path;
}

function inputUrl(request: Request): string {
  const value = request.userData['inputUrl'];
  if (typeof value !== 'string') throw new Error('请求缺少 inputUrl');
  return value;
}

function sessionLabel(session: Session | undefined, labels: Map<string, string>): string {
  if (!session) return 'none';
  const existing = labels.get(session.id);
  if (existing) return existing;
  const label = `session-${labels.size + 1}`;
  labels.set(session.id, label);
  return label;
}

function summarizeSubrequests(events: Array<{ status: number; path: string }>): Array<{ status: number; path: string; count: number }> {
  const counts = new Map<string, { status: number; path: string; count: number }>();
  for (const event of events) {
    const key = `${event.status}\0${event.path}`;
    const current = counts.get(key);
    if (current) current.count += 1;
    else counts.set(key, { ...event, count: 1 });
  }
  return [...counts.values()].sort((left, right) => left.status - right.status || left.path.localeCompare(right.path));
}

async function httpDiagnostics(urls: string[]): Promise<DiagnosticRow[]> {
  const rows = new Map<string, DiagnosticRow>();
  const crawler = new CheerioCrawler({
    maxConcurrency: 1,
    maxRequestRetries: 0,
    retryOnBlocked: false,
    useSessionPool: true,
    persistCookiesPerSession: true,
    sessionPoolOptions: { maxPoolSize: 1, sessionOptions: { maxUsageCount: 100 } },
    requestHandlerTimeoutSecs: 45,
    requestHandler: async ({ request, response, body, session }) => {
      const url = inputUrl(request);
      const document = Buffer.isBuffer(body) ? body.toString('utf8') : String(body);
      const redirectUrls = (response.redirectUrls ?? []) as URL[];
      const chain = [
        ...redirectUrls.map((redirectUrl) => ({ status: 0, path: pathTemplate(redirectUrl) })),
        { status: response.statusCode ?? 0, path: pathTemplate(request.loadedUrl ?? url) },
      ];
      const classification = classifyDocument(
        request.loadedUrl ?? url,
        response.statusCode ?? null,
        document,
        extractInputPostId(url),
      );
      rows.set(url, {
        candidate: 'candidate-b',
        variant: 'http-session-pool',
        url_sha256: urlSha256(url),
        document_chain: chain,
        body_bytes: Buffer.byteLength(document),
        jsvm_marker: document.includes('_$jsvmprt'),
        response_class: classification.response_class,
        status: classification.status,
        session_label: session ? 'session-1' : 'none',
      });
    },
    failedRequestHandler: async ({ request, session }) => {
      const url = inputUrl(request);
      const messages = request.errorMessages.join(' ').toLowerCase();
      rows.set(url, {
        candidate: 'candidate-b',
        variant: 'http-session-pool',
        url_sha256: urlSha256(url),
        document_chain: [],
        response_class: 'error',
        status: 'failed',
        session_label: session ? 'session-1' : 'none',
        error_category: messages.includes('timedout') || messages.includes('timeout') ? 'network_timeout' : 'network_error',
      });
    },
  });
  await crawler.run(
    urls.map((url) => ({
      url,
      uniqueKey: `diag-http:${urlSha256(url)}`,
      userData: { inputUrl: url },
    })),
  );
  return urls.map((url) => rows.get(url) ?? (() => { throw new Error(`HTTP 诊断缺少结果: ${urlSha256(url)}`); })());
}

async function browserDiagnostics(
  urls: string[], outputDir: string, browserEngine: CliOptions['browserEngine'], directIp?: string,
): Promise<DiagnosticRow[]> {
  const rows: DiagnosticRow[] = [];
  const sessionLabels = new Map<string, string>();
  const network = new Map<string, { documents: DiagnosticRow['document_chain']; subrequests: Array<{ status: number; path: string }> }>();
  const origin = new URL(urls[0]!).origin;
  const variantSuffix = `${browserEngine === 'real-chrome' ? '-real-chrome' : ''}${directIp ? '-direct' : ''}`;
  const launchArgs = directIp
    ? ['--no-proxy-server', `--host-resolver-rules=MAP ${new URL(urls[0]!).hostname} ${directIp}`]
    : [];
  const requests = [
    { url: `${origin}/`, uniqueKey: `diag-browser:home:${browserEngine}:${createHash('sha256').update(origin).digest('hex')}`, userData: { inputUrl: `${origin}/`, variant: `browser-home-warmup${variantSuffix}` } },
    ...urls.map((url) => ({ url, uniqueKey: `diag-browser:first:${browserEngine}:${urlSha256(url)}`, userData: { inputUrl: url, variant: `browser-persistent-first${variantSuffix}` } })),
    { url: urls[0]!, uniqueKey: `diag-browser:revisit:${browserEngine}:${urlSha256(urls[0]!)}`, userData: { inputUrl: urls[0]!, variant: `browser-persistent-revisit${variantSuffix}` } },
  ];
  const profile = join(outputDir, 'browser-profile');
  mkdirSync(profile, { recursive: true });

  const crawler = new PlaywrightCrawler({
    maxConcurrency: 1,
    maxRequestRetries: 0,
    retryOnBlocked: false,
    useSessionPool: true,
    persistCookiesPerSession: true,
    sessionPoolOptions: { maxPoolSize: 1, sessionOptions: { maxUsageCount: 100 } },
    requestHandlerTimeoutSecs: 75,
    launchContext: { userDataDir: profile, launchOptions: { headless: true, args: launchArgs, ...(browserEngine === 'real-chrome' ? { channel: 'chrome' as const } : {}) } },
    preNavigationHooks: [
      async ({ request, page }) => {
        const key = request.uniqueKey;
        const state = { documents: [] as DiagnosticRow['document_chain'], subrequests: [] as Array<{ status: number; path: string }> };
        network.set(key, state);
        page.on('response', async (response) => {
          const resourceType = response.request().resourceType();
          if (resourceType === 'document') {
            state.documents.push({
              status: response.status(),
              path: pathTemplate(response.url()),
              location: await response.headerValue('location').then((value) => value ? pathTemplate(new URL(value, response.url())) : null),
            });
          } else if (resourceType === 'xhr' || resourceType === 'fetch') {
            state.subrequests.push({ status: response.status(), path: pathTemplate(response.url()) });
          }
        });
      },
    ],
    requestHandler: async ({ request, page, response, session }) => {
      await page.waitForTimeout(5_000);
      const url = inputUrl(request);
      const variant = String(request.userData['variant']);
      const document = await page.content();
      const state = network.get(request.uniqueKey) ?? { documents: [], subrequests: [] };
      const row: DiagnosticRow = {
        candidate: 'candidate-b',
        variant,
        url_sha256: urlSha256(url),
        document_chain: state.documents,
        subrequest_statuses: summarizeSubrequests(state.subrequests),
        final_path: pathTemplate(page.url()),
        cookie_count: (await page.context().cookies()).length,
        cookie_name_hashes: (await page.context().cookies())
          .map((cookie) => createHash('sha256').update(cookie.name).digest('hex'))
          .sort(),
        ua_headless: await page.evaluate(() => navigator.userAgent.includes('HeadlessChrome')),
        body_bytes: Buffer.byteLength(document),
        session_label: sessionLabel(session, sessionLabels),
      };
      try {
        const classification = classifyDocument(page.url(), response?.status() ?? null, document, extractInputPostId(url));
        row.response_class = classification.response_class;
        row.status = classification.status;
      } catch {
        row.response_class = 'navigation';
        row.status = 'diagnostic';
      }
      rows.push(row);
    },
    failedRequestHandler: async ({ request, session }) => {
      const url = inputUrl(request);
      const messages = request.errorMessages.join(' ').toLowerCase();
      rows.push({
        candidate: 'candidate-b',
        variant: String(request.userData['variant']),
        url_sha256: urlSha256(url),
        document_chain: network.get(request.uniqueKey)?.documents ?? [],
        response_class: 'error',
        status: 'failed',
        session_label: sessionLabel(session, sessionLabels),
        error_category: messages.includes('timedout') || messages.includes('timeout') ? 'network_timeout' : 'network_error',
      });
    },
  });
  await crawler.run(requests);
  return rows;
}

function writeJsonl(path: string, rows: DiagnosticRow[]): void {
  writeFileSync(path, `${rows.map((row) => JSON.stringify(row)).join('\n')}\n`, 'utf8');
}

async function main(): Promise<void> {
  const options = parseArgs(process.argv.slice(2));
  const urls = readFileSync(options.input, 'utf8')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, options.limit);
  if (urls.length !== options.limit) throw new Error('limit 超出输入清单范围');
  mkdirSync(options.outputDir, { recursive: true });
  const rows = [
    ...await httpDiagnostics(urls),
    ...await browserDiagnostics(urls, options.outputDir, options.browserEngine, options.directIp),
  ];
  writeJsonl(join(options.outputDir, 'diagnostics.jsonl'), rows);
  console.log(JSON.stringify({ candidate: 'candidate-b', rows: rows.length }));
}

await main();
