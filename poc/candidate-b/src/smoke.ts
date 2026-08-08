/** 候选 B：Crawlee HTTP 优先、Playwright 回退的阶段 1 冒烟。 */

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
import { performance } from 'node:perf_hooks';
import { CheerioCrawler, PlaywrightCrawler, type Request } from 'crawlee';
import {
  CONTROL_CLASSES,
  classifyDocument,
  extractInputPostId,
  urlSha256,
  type Classification,
} from './contract.js';

interface Attempt extends Classification {
  schema_version: '1.0';
  candidate: 'candidate-b';
  url: string;
  url_sha256: string;
  channel: 'http' | 'browser-dom';
  started_at: string;
  ended_at: string;
  duration_ms: number;
  http_status: number | null;
  final_url_sha256: string | null;
  error_category: string | null;
}

interface FinalResult {
  schema_version: '1.0';
  candidate: 'candidate-b';
  url: string;
  url_sha256: string;
  input_post_id: string;
  observed_post_id: string | null;
  post_id_matches: boolean;
  title_present: boolean;
  body_present: boolean;
  response_class: Classification['response_class'];
  control_hit: boolean;
  channel: 'http' | 'browser-dom';
  status: Classification['status'];
  request_count: number;
  started_at: string;
  ended_at: string;
  duration_ms: number;
  http_status: number | null;
  error_category: string | null;
}

interface CliOptions {
  input: string;
  outputDir: string;
  limit: number;
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
  if (!input || !outputDir || !Number.isInteger(limit) || limit < 1) {
    throw new Error('必须提供 --input、--output-dir，且 --limit 必须为正整数');
  }
  return { input: resolve(input), outputDir: resolve(outputDir), limit };
}

function now(): string {
  return new Date().toISOString();
}

function requestUrl(request: Request): string {
  const value = request.userData['inputUrl'];
  if (typeof value !== 'string') throw new Error('请求缺少 inputUrl');
  return value;
}

function makeAttempt(
  url: string,
  channel: 'http' | 'browser-dom',
  startedAt: string,
  started: number,
  finalUrl: string,
  httpStatus: number | null,
  document: string,
): Attempt {
  const classification = classifyDocument(finalUrl, httpStatus, document, extractInputPostId(url));
  return {
    schema_version: '1.0',
    candidate: 'candidate-b',
    url,
    url_sha256: urlSha256(url),
    channel,
    started_at: startedAt,
    ended_at: now(),
    duration_ms: Math.round(performance.now() - started),
    http_status: httpStatus,
    final_url_sha256: urlSha256(finalUrl),
    ...classification,
    error_category: classification.status === 'success' ? null : classification.response_class,
  };
}

function makeErrorAttempt(
  url: string,
  channel: 'http' | 'browser-dom',
  startedAt: string,
  started: number,
  error: unknown,
): Attempt {
  return {
    schema_version: '1.0',
    candidate: 'candidate-b',
    url,
    url_sha256: urlSha256(url),
    channel,
    started_at: startedAt,
    ended_at: now(),
    duration_ms: Math.round(performance.now() - started),
    http_status: null,
    final_url_sha256: null,
    observed_post_id: null,
    post_id_matches: false,
    title_present: false,
    body_present: false,
    response_class: 'error',
    status: 'failed',
    error_category: error instanceof Error ? error.name : 'UnknownError',
  };
}

function requestsFor(urls: string[], channel: 'http' | 'browser'): Array<{ url: string; uniqueKey: string; userData: object }> {
  return urls.map((url) => ({
    url,
    uniqueKey: `${channel}:${urlSha256(url)}`,
    userData: { inputUrl: url },
  }));
}

async function runHttp(urls: string[], outputDir: string): Promise<Map<string, Attempt>> {
  const attempts = new Map<string, Attempt>();
  const starts = new Map<string, { at: string; tick: number }>();
  const crawler = new CheerioCrawler({
    maxConcurrency: 1,
    maxRequestRetries: 0,
    retryOnBlocked: false,
    useSessionPool: false,
    requestHandlerTimeoutSecs: 45,
    preNavigationHooks: [
      async ({ request }) => {
        starts.set(requestUrl(request), { at: now(), tick: performance.now() });
      },
    ],
    requestHandler: async ({ request, response, body }) => {
      const url = requestUrl(request);
      const start = starts.get(url) ?? { at: now(), tick: performance.now() };
      const document = Buffer.isBuffer(body) ? body.toString('utf8') : String(body);
      const finalUrl = request.loadedUrl ?? url;
      const capture = join(outputDir, 'captures', `${urlSha256(url)}-http.html`);
      mkdirSync(resolve(capture, '..'), { recursive: true });
      writeFileSync(capture, document, 'utf8');
      attempts.set(url, makeAttempt(url, 'http', start.at, start.tick, finalUrl, response.statusCode ?? null, document));
    },
    failedRequestHandler: async ({ request }, error) => {
      const url = requestUrl(request);
      const start = starts.get(url) ?? { at: now(), tick: performance.now() };
      attempts.set(url, makeErrorAttempt(url, 'http', start.at, start.tick, error));
    },
  });
  await crawler.run(requestsFor(urls, 'http'));
  return attempts;
}

async function runBrowser(urls: string[], outputDir: string): Promise<Map<string, Attempt>> {
  const attempts = new Map<string, Attempt>();
  if (urls.length === 0) return attempts;
  const starts = new Map<string, { at: string; tick: number }>();
  const crawler = new PlaywrightCrawler({
    maxConcurrency: 1,
    maxRequestRetries: 0,
    retryOnBlocked: false,
    useSessionPool: false,
    requestHandlerTimeoutSecs: 60,
    launchContext: { launchOptions: { headless: true } },
    preNavigationHooks: [
      async ({ request }) => {
        starts.set(requestUrl(request), { at: now(), tick: performance.now() });
      },
    ],
    requestHandler: async ({ request, page, response }) => {
      const url = requestUrl(request);
      const start = starts.get(url) ?? { at: now(), tick: performance.now() };
      await page.waitForTimeout(5_000);
      const document = await page.content();
      const finalUrl = page.url();
      const capture = join(outputDir, 'captures', `${urlSha256(url)}-browser.html`);
      mkdirSync(resolve(capture, '..'), { recursive: true });
      writeFileSync(capture, document, 'utf8');
      attempts.set(url, makeAttempt(url, 'browser-dom', start.at, start.tick, finalUrl, response?.status() ?? null, document));
    },
    failedRequestHandler: async ({ request }, error) => {
      const url = requestUrl(request);
      const start = starts.get(url) ?? { at: now(), tick: performance.now() };
      attempts.set(url, makeErrorAttempt(url, 'browser-dom', start.at, start.tick, error));
    },
  });
  await crawler.run(requestsFor(urls, 'browser'));
  return attempts;
}

function writeJsonl(path: string, records: object[]): void {
  writeFileSync(path, `${records.map((record) => JSON.stringify(record)).join('\n')}\n`, 'utf8');
}

async function main(): Promise<void> {
  const options = parseArgs(process.argv.slice(2));
  const allUrls = readFileSync(options.input, 'utf8')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (options.limit > allUrls.length) throw new Error('limit 超出输入清单范围');
  const urls = allUrls.slice(0, options.limit);
  mkdirSync(options.outputDir, { recursive: true });

  const overallStarts = new Map(urls.map((url) => [url, { at: now(), tick: performance.now() }]));
  const httpAttempts = await runHttp(urls, options.outputDir);
  const fallbackUrls = urls.filter((url) => httpAttempts.get(url)?.status !== 'success');
  const browserAttempts = await runBrowser(fallbackUrls, options.outputDir);
  const events: Attempt[] = [];
  const results: FinalResult[] = [];

  for (const url of urls) {
    const attempts = [httpAttempts.get(url), browserAttempts.get(url)].filter((item): item is Attempt => item !== undefined);
    if (attempts.length === 0) throw new Error(`URL 没有产生请求事件: ${urlSha256(url)}`);
    events.push(...attempts);
    const final = attempts.at(-1)!;
    const overall = overallStarts.get(url)!;
    const result: FinalResult = {
      schema_version: '1.0',
      candidate: 'candidate-b',
      url,
      url_sha256: urlSha256(url),
      input_post_id: extractInputPostId(url),
      observed_post_id: final.observed_post_id,
      post_id_matches: final.post_id_matches,
      title_present: final.title_present,
      body_present: final.body_present,
      response_class: final.response_class,
      control_hit: attempts.some((attempt) => CONTROL_CLASSES.has(attempt.response_class)),
      channel: final.channel,
      status: final.status,
      request_count: attempts.length,
      started_at: overall.at,
      ended_at: now(),
      duration_ms: Math.round(performance.now() - overall.tick),
      http_status: final.http_status,
      error_category: final.error_category,
    };
    results.push(result);
    console.log(JSON.stringify({
      url_sha256: result.url_sha256,
      status: result.status,
      response_class: result.response_class,
      channel: result.channel,
    }));
  }
  writeJsonl(join(options.outputDir, 'url-results.jsonl'), results);
  writeJsonl(join(options.outputDir, 'request-events.jsonl'), events);
  const require = createRequire(import.meta.url);
  const environment = {
    schema_version: '1.0',
    candidate: 'candidate-b',
    access_mode: 'anonymous',
    operating_system: `${process.platform}-${process.arch}`,
    node_version: process.version,
    crawlee_version: (require('crawlee/package.json') as { version: string }).version,
    playwright_version: (require('playwright/package.json') as { version: string }).version,
    input_count: urls.length,
    input_file_sha256: createHash('sha256').update(readFileSync(options.input)).digest('hex'),
  };
  writeFileSync(join(options.outputDir, 'environment.json'), `${JSON.stringify(environment, null, 2)}\n`, 'utf8');
}

await main();
