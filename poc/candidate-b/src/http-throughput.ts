/** Candidate B：使用 Crawlee CheerioCrawler + SessionPool 执行纯 HTTP 批量预筛。 */

import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { fileURLToPath } from 'node:url';
import {
  CheerioCrawler,
  Configuration,
  LogLevel,
  log,
  type Request,
} from 'crawlee';
import {
  CONTROL_CLASSES,
  classifyDocument,
  extractInputPostId,
  urlSha256,
  type Classification,
} from './contract.js';

type ResponseClass = Classification['response_class'];
type ResultStatus = Classification['status'];

export interface FinalResult extends Classification {
  schema_version: '1.0';
  candidate: 'candidate-b';
  url: string;
  url_sha256: string;
  input_post_id: string;
  control_hit: boolean;
  channel: 'http';
  request_count: 1;
  started_at: string;
  ended_at: string;
  duration_ms: number;
  http_status: number | null;
  error_category: string | null;
}

interface RequestEvent {
  schema_version: '1.0';
  candidate: 'candidate-b';
  url: string;
  url_sha256: string;
  channel: 'http';
  started_at: string;
  ended_at: string;
  duration_ms: number;
  http_status: number | null;
  final_url_sha256: string | null;
  body_bytes: number;
  response_class: ResponseClass;
  status: ResultStatus;
  error_category: string | null;
}

interface CliOptions {
  input: string;
  outputDir: string;
  limit: number;
  concurrency: number;
  timeoutSeconds: number;
}

interface Summary {
  schema_version: '1.0';
  candidate: 'candidate-b';
  access_mode: 'anonymous-direct-http';
  direct_http_only: boolean;
  concurrency: number;
  input_count: number;
  result_count: number;
  success_count: number;
  final_valid_rate: number;
  duration_ms: number;
  processed_urls_per_second: number;
  effective_urls_per_second: number;
  p50_duration_ms: number;
  p95_duration_ms: number;
  request_count: number;
  request_amplification: number;
  channel_counts: Record<string, number>;
  response_class_counts: Record<string, number>;
  first_control: { url_sha256: string; response_class: ResponseClass; completed_offset_ms: number } | null;
  meets_2000_per_hour_speed: boolean;
  meets_correctness_gate: boolean;
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
  const limit = Number.parseInt(values.get('--limit') ?? '500', 10);
  const concurrency = Number.parseInt(values.get('--concurrency') ?? '1', 10);
  const timeoutSeconds = Number.parseInt(values.get('--timeout-seconds') ?? '30', 10);
  if (!input || !outputDir || ![limit, concurrency, timeoutSeconds].every((value) => Number.isInteger(value) && value > 0)) {
    throw new Error('必须提供 --input、--output-dir，且 limit、concurrency、timeout-seconds 必须为正整数');
  }
  return { input: resolve(input), outputDir: resolve(outputDir), limit, concurrency, timeoutSeconds };
}

function now(): string {
  return new Date().toISOString();
}

function inputUrl(request: Request): string {
  const value = request.userData['inputUrl'];
  if (typeof value !== 'string') throw new Error('请求缺少 inputUrl');
  return value;
}

function percentile(values: number[], quantile: number): number {
  if (values.length === 0) return 0;
  const ordered = [...values].sort((left, right) => left - right);
  const position = (ordered.length - 1) * quantile;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  const lowerValue = ordered[lower]!;
  const upperValue = ordered[upper]!;
  if (lower === upper) return lowerValue;
  return Math.round(lowerValue + (upperValue - lowerValue) * (position - lower));
}

function countBy(values: string[]): Record<string, number> {
  const counts = new Map<string, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

export function buildSummary(
  results: FinalResult[],
  completionOffsetsMs: Map<string, number>,
  durationMs: number,
  concurrency: number,
): Summary {
  const successCount = results.filter((item) => item.status === 'success').length;
  const requestCount = results.reduce((total, item) => total + item.request_count, 0);
  const controlClasses = new Set<ResponseClass>(['rate_limited', 'captcha', 'challenge', 'login', 'empty']);
  const controls = results.filter((item) => controlClasses.has(item.response_class));
  controls.sort((left, right) => completionOffsetsMs.get(left.url)! - completionOffsetsMs.get(right.url)!);
  const firstControl = controls[0];
  const effectiveRate = durationMs > 0 ? successCount / (durationMs / 1000) : 0;
  const channelCounts = countBy(results.map((item) => item.channel));
  return {
    schema_version: '1.0',
    candidate: 'candidate-b',
    access_mode: 'anonymous-direct-http',
    direct_http_only: Object.keys(channelCounts).length === 1 && channelCounts['http'] === results.length,
    concurrency,
    input_count: results.length,
    result_count: results.length,
    success_count: successCount,
    final_valid_rate: results.length > 0 ? Number((successCount / results.length).toFixed(6)) : 0,
    duration_ms: durationMs,
    processed_urls_per_second: durationMs > 0 ? Number((results.length / (durationMs / 1000)).toFixed(6)) : 0,
    effective_urls_per_second: Number(effectiveRate.toFixed(6)),
    p50_duration_ms: percentile(results.map((item) => item.duration_ms), 0.50),
    p95_duration_ms: percentile(results.map((item) => item.duration_ms), 0.95),
    request_count: requestCount,
    request_amplification: results.length > 0 ? Number((requestCount / results.length).toFixed(6)) : 0,
    channel_counts: channelCounts,
    response_class_counts: countBy(results.map((item) => item.response_class)),
    first_control: firstControl
      ? {
          url_sha256: firstControl.url_sha256,
          response_class: firstControl.response_class,
          completed_offset_ms: completionOffsetsMs.get(firstControl.url)!,
        }
      : null,
    meets_2000_per_hour_speed: effectiveRate >= 2000 / 3600,
    meets_correctness_gate: results.length > 0 && successCount === results.length,
  };
}

function makeResult(
  url: string,
  startedAt: string,
  startedTick: number,
  finalUrl: string,
  httpStatus: number,
  document: string,
): { result: FinalResult; event: RequestEvent } {
  const endedAt = now();
  const durationMs = Math.round(performance.now() - startedTick);
  const classification = classifyDocument(finalUrl, httpStatus, document, extractInputPostId(url));
  const errorCategory = classification.status === 'success' ? null : classification.response_class;
  const result: FinalResult = {
    schema_version: '1.0',
    candidate: 'candidate-b',
    url,
    url_sha256: urlSha256(url),
    input_post_id: extractInputPostId(url),
    ...classification,
    control_hit: CONTROL_CLASSES.has(classification.response_class),
    channel: 'http',
    request_count: 1,
    started_at: startedAt,
    ended_at: endedAt,
    duration_ms: durationMs,
    http_status: httpStatus,
    error_category: errorCategory,
  };
  return {
    result,
    event: {
      schema_version: '1.0',
      candidate: 'candidate-b',
      url,
      url_sha256: urlSha256(url),
      channel: 'http',
      started_at: startedAt,
      ended_at: endedAt,
      duration_ms: durationMs,
      http_status: httpStatus,
      final_url_sha256: urlSha256(finalUrl),
      body_bytes: Buffer.byteLength(document),
      response_class: classification.response_class,
      status: classification.status,
      error_category: errorCategory,
    },
  };
}

function makeError(
  url: string,
  startedAt: string,
  startedTick: number,
  error: unknown,
): { result: FinalResult; event: RequestEvent } {
  const endedAt = now();
  const durationMs = Math.round(performance.now() - startedTick);
  const category = error instanceof Error ? error.name : 'UnknownError';
  const result: FinalResult = {
    schema_version: '1.0',
    candidate: 'candidate-b',
    url,
    url_sha256: urlSha256(url),
    input_post_id: extractInputPostId(url),
    observed_post_id: null,
    post_id_matches: false,
    title_present: false,
    body_present: false,
    response_class: 'error',
    control_hit: false,
    channel: 'http',
    status: 'failed',
    request_count: 1,
    started_at: startedAt,
    ended_at: endedAt,
    duration_ms: durationMs,
    http_status: null,
    error_category: category,
  };
  return {
    result,
    event: {
      schema_version: '1.0',
      candidate: 'candidate-b',
      url,
      url_sha256: urlSha256(url),
      channel: 'http',
      started_at: startedAt,
      ended_at: endedAt,
      duration_ms: durationMs,
      http_status: null,
      final_url_sha256: null,
      body_bytes: 0,
      response_class: 'error',
      status: 'failed',
      error_category: category,
    },
  };
}

function writeJson(path: string, payload: object): void {
  writeFileSync(path, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
}

function writeJsonl(path: string, records: object[]): void {
  writeFileSync(path, `${records.map((record) => JSON.stringify(record)).join('\n')}\n`, 'utf8');
}

function writeChecksums(outputDir: string): void {
  const names = ['environment.json', 'input-urls.txt', 'request-events.jsonl', 'summary.json', 'url-results.jsonl'];
  const lines = names.map((name) => `${createHash('sha256').update(readFileSync(join(outputDir, name))).digest('hex')}  ${name}\n`);
  writeFileSync(join(outputDir, 'SHA256SUMS'), lines.join(''), 'utf8');
}

async function main(): Promise<void> {
  const options = parseArgs(process.argv.slice(2));
  const allUrls = readFileSync(options.input, 'utf8')
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (options.limit > allUrls.length) throw new Error('limit 超出输入清单范围');
  const urls = allUrls.slice(0, options.limit);
  for (const url of urls) extractInputPostId(url);
  mkdirSync(options.outputDir, { recursive: false });
  writeFileSync(join(options.outputDir, 'input-urls.txt'), `${urls.join('\n')}\n`, 'utf8');

  log.setLevel(LogLevel.WARNING);
  const configuration = new Configuration({
    purgeOnStart: true,
    persistStorage: true,
    storageClientOptions: { localDataDirectory: join(options.outputDir, 'crawlee-storage') },
  });
  const results = new Map<string, FinalResult>();
  const events = new Map<string, RequestEvent>();
  const completionOffsetsMs = new Map<string, number>();
  const runStartedAt = now();
  const runStartedTick = performance.now();
  // 批量 P50/P95 从任务提交时计时，包含队列等待，与 Candidate A 的 Spider 口径一致。
  const starts = new Map(urls.map((url) => [url, { at: runStartedAt, tick: runStartedTick }]));
  const crawler = new CheerioCrawler(
    {
      minConcurrency: options.concurrency,
      maxConcurrency: options.concurrency,
      maxRequestRetries: 0,
      retryOnBlocked: false,
      useSessionPool: true,
      persistCookiesPerSession: true,
      sessionPoolOptions: {
        maxPoolSize: 1,
        sessionOptions: { maxUsageCount: urls.length + 100, maxErrorScore: urls.length + 100 },
      },
      requestHandlerTimeoutSecs: options.timeoutSeconds + 5,
      navigationTimeoutSecs: options.timeoutSeconds,
      requestHandler: async ({ request, response, body }) => {
        const url = inputUrl(request);
        const start = starts.get(url) ?? { at: now(), tick: performance.now() };
        const document = Buffer.isBuffer(body) ? body.toString('utf8') : String(body);
        const pair = makeResult(url, start.at, start.tick, request.loadedUrl ?? url, response.statusCode ?? 0, document);
        results.set(url, pair.result);
        events.set(url, pair.event);
        completionOffsetsMs.set(url, Math.round(performance.now() - runStartedTick));
      },
      failedRequestHandler: async ({ request }, error) => {
        const url = inputUrl(request);
        const start = starts.get(url) ?? { at: now(), tick: performance.now() };
        const pair = makeError(url, start.at, start.tick, error);
        results.set(url, pair.result);
        events.set(url, pair.event);
        completionOffsetsMs.set(url, Math.round(performance.now() - runStartedTick));
      },
    },
    configuration,
  );
  await crawler.run(
    urls.map((url) => ({
      url,
      uniqueKey: `direct-http:${urlSha256(url)}`,
      userData: { inputUrl: url },
    })),
  );
  const durationMs = Math.round(performance.now() - runStartedTick);
  const missing = urls.filter((url) => !results.has(url));
  if (missing.length > 0) throw new Error(`CheerioCrawler 缺少 ${missing.length} 条结果`);
  const orderedResults = urls.map((url) => results.get(url)!);
  const orderedEvents = urls.map((url) => events.get(url)!);
  const summary = buildSummary(orderedResults, completionOffsetsMs, durationMs, options.concurrency);
  const require = createRequire(import.meta.url);
  const environment = {
    schema_version: '1.0',
    candidate: 'candidate-b',
    access_mode: 'anonymous-direct-http',
    operating_system: `${process.platform}-${process.arch}`,
    node_version: process.version,
    crawlee_version: (require('crawlee/package.json') as { version: string }).version,
    started_at: runStartedAt,
    ended_at: now(),
    input_count: urls.length,
    input_file_sha256: createHash('sha256').update(readFileSync(join(options.outputDir, 'input-urls.txt'))).digest('hex'),
    concurrency: options.concurrency,
    browser_started: false,
    crawler: 'CheerioCrawler',
    session_pool_size: 1,
  };
  writeJsonl(join(options.outputDir, 'url-results.jsonl'), orderedResults);
  writeJsonl(join(options.outputDir, 'request-events.jsonl'), orderedEvents);
  writeJson(join(options.outputDir, 'summary.json'), summary);
  writeJson(join(options.outputDir, 'environment.json'), environment);
  writeChecksums(options.outputDir);
  console.log(JSON.stringify(summary));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  await main();
}
