/** Candidate B：用 Crawlee 登录导出的 Cookie 执行 CheerioCrawler HTTP 采集，并在会话失效时有界重建。 */

import { createHash } from 'node:crypto';
import { chmodSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { fileURLToPath } from 'node:url';
import { CheerioCrawler, Configuration, LogLevel, log, type Request, type Session } from 'crawlee';
import {
  classifyDocument,
  extractInputPostId,
  urlSha256,
  type Classification,
} from './contract.js';
import {
  loadConfig,
  prepareIsolatedProfile,
  storageStatePath,
  verifyLogin,
  type TestConfig,
} from './throughput.js';

type ResponseClass = Classification['response_class'] | 'session_state_unusable';
const RECOVERABLE = new Set<ResponseClass>(['empty', 'login', 'session_state_unusable']);
const NON_RECOVERABLE = new Set<ResponseClass>(['captcha', 'challenge', 'rate_limited']);
const PAUSE_CLASSES = new Set<ResponseClass>([...RECOVERABLE, ...NON_RECOVERABLE]);

interface CliOptions {
  config: string;
  input: string;
  gateInput: string;
  outputDir: string;
  initialStorageState: string | null;
  offset: number;
  limit: number;
  maxRecoveries: number;
  timeoutSeconds: number;
  windowSeconds: number;
}

export interface HttpResult extends Classification {
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
  session_ordinal: number;
  segment_kind: 'gate' | 'bulk';
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
  response_class: Classification['response_class'];
  status: Classification['status'];
  error_category: string | null;
  session_ordinal: number;
  segment_kind: 'gate' | 'bulk';
}

export interface SegmentOutcome {
  results: HttpResult[];
  events: RequestEvent[];
  pause_reason: ResponseClass | null;
  remaining_count: number;
  duration_ms: number;
  cookie_metadata: { storage_cookie_count: number; usable_cookie_count: number };
}

interface SessionOutcome {
  success: boolean;
  storageState: string;
}

interface RecoveryEvent extends Record<string, unknown> {
  event: 'session_gate' | 'session_refresh';
}

export interface RecoveryOutcome {
  finalResults: HttpResult[];
  requestEvents: RequestEvent[];
  recoveryEvents: RecoveryEvent[];
  remainingCount: number;
  stopReason: string | null;
}

function parseInteger(values: Map<string, string>, name: string, fallback: number, min: number, max: number): number {
  const value = Number.parseInt(values.get(name) ?? String(fallback), 10);
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new Error(`${name} 必须为 ${min}..${max} 的整数`);
  }
  return value;
}

function parseArgs(argv: string[]): CliOptions {
  const values = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith('--') || value === undefined) throw new Error(`参数格式错误: ${key ?? '<empty>'}`);
    values.set(key, value);
  }
  const config = values.get('--config');
  const input = values.get('--input');
  const gateInput = values.get('--gate-input');
  const outputDir = values.get('--output-dir');
  if (!config || !input || !gateInput || !outputDir) {
    throw new Error('必须提供 --config、--input、--gate-input 和 --output-dir');
  }
  const initial = values.get('--initial-storage-state');
  return {
    config: resolve(config),
    input: resolve(input),
    gateInput: resolve(gateInput),
    outputDir: resolve(outputDir),
    initialStorageState: initial ? resolve(initial) : null,
    offset: parseInteger(values, '--offset', 0, 0, 1_999),
    limit: parseInteger(values, '--limit', 2_000, 1, 2_000),
    maxRecoveries: parseInteger(values, '--max-recoveries', 2, 0, 5),
    timeoutSeconds: parseInteger(values, '--timeout-seconds', 30, 1, 300),
    windowSeconds: parseInteger(values, '--window-seconds', 3_600, 1, 86_400),
  };
}

function utcNow(): string {
  return new Date().toISOString();
}

function readUrls(path: string): string[] {
  return readFileSync(path, 'utf8').replace(/^\uFEFF/u, '').split(/\r?\n/u).map((line) => line.trim()).filter(Boolean);
}

function selectedUrls(path: string, offset: number, limit: number): string[] {
  const all = readUrls(path);
  if (offset + limit > all.length) throw new Error('offset + limit 超出输入清单范围');
  const urls = all.slice(offset, offset + limit);
  if (new Set(urls).size !== urls.length) throw new Error('测试范围含重复 URL');
  const hosts = new Set(urls.map((url) => new URL(url).host.toLowerCase()));
  if (hosts.size !== 1) throw new Error('测试范围必须为同一主机');
  for (const url of urls) extractInputPostId(url);
  return urls;
}

function gateUrls(path: string): string[] {
  const urls = readUrls(path);
  if (urls.length !== 3 || new Set(urls).size !== 3) throw new Error('gate-input 必须含 3 条不同 URL');
  for (const url of urls) extractInputPostId(url);
  return urls;
}

interface StoredCookie {
  name: string;
  value: string;
  domain?: string;
  path?: string;
  expires?: number;
  httpOnly?: boolean;
  secure?: boolean;
  sameSite?: 'Strict' | 'Lax' | 'None';
}

type SessionCookies = Parameters<Session['setCookies']>[0];

function loadCookies(storageState: string, targetUrl: string): {
  cookies: SessionCookies;
  metadata: { storage_cookie_count: number; usable_cookie_count: number };
} {
  const state = JSON.parse(readFileSync(storageState, 'utf8')) as { cookies?: StoredCookie[] };
  if (!Array.isArray(state.cookies)) throw new Error('storage-state.json 缺少 cookies');
  const host = new URL(targetUrl).hostname.toLowerCase();
  const nowSeconds = Date.now() / 1_000;
  const usable: SessionCookies = state.cookies.filter((cookie) => {
    const domain = (cookie.domain ?? host).replace(/^\./u, '').toLowerCase();
    const domainMatches = host === domain || host.endsWith(`.${domain}`);
    const unexpired = cookie.expires === undefined || cookie.expires < 0 || cookie.expires > nowSeconds;
    return Boolean(cookie.name) && domainMatches && unexpired;
  }).map((cookie) => ({
    name: cookie.name,
    value: cookie.value,
    domain: cookie.domain,
    path: cookie.path ?? '/',
    expires: cookie.expires,
    httpOnly: cookie.httpOnly,
    secure: cookie.secure,
    sameSite: cookie.sameSite?.toLowerCase() as 'strict' | 'lax' | 'none' | undefined,
  })) as SessionCookies;
  return {
    cookies: usable,
    metadata: { storage_cookie_count: state.cookies.length, usable_cookie_count: usable.length },
  };
}

function requestInputUrl(request: Request): string {
  const value = request.userData['inputUrl'];
  if (typeof value !== 'string') throw new Error('请求缺少 inputUrl');
  return value;
}

function resultPair(
  url: string,
  finalUrl: string,
  httpStatus: number,
  document: string,
  startedAt: string,
  startedTick: number,
  sessionOrdinal: number,
  segmentKind: 'gate' | 'bulk',
): { result: HttpResult; event: RequestEvent } {
  const classification = classifyDocument(finalUrl, httpStatus, document, extractInputPostId(url));
  const endedAt = utcNow();
  const durationMs = Math.round(performance.now() - startedTick);
  const errorCategory = classification.status === 'success' ? null : classification.response_class;
  return {
    result: {
      schema_version: '1.0', candidate: 'candidate-b', url, url_sha256: urlSha256(url),
      input_post_id: extractInputPostId(url), ...classification,
      control_hit: PAUSE_CLASSES.has(classification.response_class), channel: 'http', request_count: 1,
      started_at: startedAt, ended_at: endedAt, duration_ms: durationMs,
      http_status: httpStatus, error_category: errorCategory,
      session_ordinal: sessionOrdinal, segment_kind: segmentKind,
    },
    event: {
      schema_version: '1.0', candidate: 'candidate-b', url, url_sha256: urlSha256(url), channel: 'http',
      started_at: startedAt, ended_at: endedAt, duration_ms: durationMs, http_status: httpStatus,
      final_url_sha256: urlSha256(finalUrl), body_bytes: Buffer.byteLength(document),
      response_class: classification.response_class, status: classification.status,
      error_category: errorCategory, session_ordinal: sessionOrdinal, segment_kind: segmentKind,
    },
  };
}

function errorPair(
  url: string,
  error: unknown,
  startedAt: string,
  startedTick: number,
  sessionOrdinal: number,
  segmentKind: 'gate' | 'bulk',
): { result: HttpResult; event: RequestEvent } {
  const endedAt = utcNow();
  const durationMs = Math.round(performance.now() - startedTick);
  const category = error instanceof Error ? error.name : 'UnknownError';
  const base = {
    schema_version: '1.0' as const, candidate: 'candidate-b' as const, url, url_sha256: urlSha256(url),
    channel: 'http' as const, started_at: startedAt, ended_at: endedAt, duration_ms: durationMs,
    http_status: null, response_class: 'error' as const, status: 'failed' as const,
    error_category: category, session_ordinal: sessionOrdinal, segment_kind: segmentKind,
  };
  return {
    result: {
      ...base, input_post_id: extractInputPostId(url), observed_post_id: null, post_id_matches: false,
      title_present: false, body_present: false, control_hit: false, request_count: 1,
    },
    event: { ...base, final_url_sha256: null, body_bytes: 0 },
  };
}

export async function runHttpSegment(
  urls: string[],
  storageState: string,
  timeoutSeconds: number,
  sessionOrdinal: number,
  segmentKind: 'gate' | 'bulk',
  storageDirectory: string,
): Promise<SegmentOutcome> {
  if (urls.length === 0) throw new Error('HTTP segment 不能为空');
  const { cookies, metadata } = loadCookies(storageState, urls[0]!);
  if (cookies.length === 0) throw new Error('session_state_unusable');
  const started = performance.now();
  const results = new Map<string, HttpResult>();
  const events = new Map<string, RequestEvent>();
  const starts = new Map<string, { at: string; tick: number }>();
  let pauseReason: ResponseClass | null = null;
  let crawler: CheerioCrawler;
  const configuration = new Configuration({
    purgeOnStart: true,
    persistStorage: true,
    storageClientOptions: { localDataDirectory: storageDirectory },
  });
  crawler = new CheerioCrawler({
    minConcurrency: 1,
    maxConcurrency: 1,
    maxRequestRetries: 0,
    retryOnBlocked: false,
    useSessionPool: true,
    persistCookiesPerSession: true,
    sessionPoolOptions: {
      maxPoolSize: 1,
      sessionOptions: { maxUsageCount: urls.length + 100, maxErrorScore: urls.length + 100 },
    },
    requestHandlerTimeoutSecs: timeoutSeconds + 5,
    navigationTimeoutSecs: timeoutSeconds,
    // 平台在会话控制发生时会把响应标成 text/plain；必须让框架把正文交给统一分类器。
    additionalMimeTypes: ['text/plain'],
    preNavigationHooks: [async ({ request, session }) => {
      const url = requestInputUrl(request);
      starts.set(url, { at: utcNow(), tick: performance.now() });
      if (session && session.userData['authenticatedCookiesSeeded'] !== true) {
        session.setCookies(cookies, url);
        session.userData['authenticatedCookiesSeeded'] = true;
      }
    }],
    requestHandler: async ({ request, response, body }) => {
      const url = requestInputUrl(request);
      const timing = starts.get(url) ?? { at: utcNow(), tick: performance.now() };
      const document = Buffer.isBuffer(body) ? body.toString('utf8') : String(body);
      const pair = resultPair(
        url, request.loadedUrl ?? url, response.statusCode ?? 0, document,
        timing.at, timing.tick, sessionOrdinal, segmentKind,
      );
      results.set(url, pair.result);
      events.set(url, pair.event);
      if (PAUSE_CLASSES.has(pair.result.response_class)) {
        pauseReason = pair.result.response_class;
        await crawler.autoscaledPool?.abort();
      }
    },
    failedRequestHandler: async ({ request }, error) => {
      const url = requestInputUrl(request);
      const timing = starts.get(url) ?? { at: utcNow(), tick: performance.now() };
      const pair = errorPair(url, error, timing.at, timing.tick, sessionOrdinal, segmentKind);
      results.set(url, pair.result);
      events.set(url, pair.event);
    },
  }, configuration);
  await crawler.run(urls.map((url) => ({
    url,
    uniqueKey: `${segmentKind}:${sessionOrdinal}:${urlSha256(url)}`,
    userData: { inputUrl: url },
  })));
  const completed = urls.filter((url) => results.has(url));
  if (completed.length !== urls.length && pauseReason === null) {
    throw new Error(`CheerioCrawler 缺少 ${urls.length - completed.length} 条结果`);
  }
  return {
    results: completed.map((url) => results.get(url)!),
    events: completed.map((url) => events.get(url)!),
    pause_reason: pauseReason,
    remaining_count: urls.length - completed.length,
    duration_ms: Math.round(performance.now() - started),
    cookie_metadata: metadata,
  };
}

export async function executeRecoveryControl(options: {
  urls: string[];
  gates: string[];
  maxRecoveries: number;
  deadline: number;
  initialStorageState: string | null;
  obtainSession: (ordinal: number, reason: string) => Promise<SessionOutcome>;
  executeSegment: (
    urls: string[], state: string, ordinal: number, kind: 'gate' | 'bulk',
  ) => Promise<SegmentOutcome>;
}): Promise<RecoveryOutcome> {
  const finalByUrl = new Map<string, HttpResult>();
  const requestEvents: RequestEvent[] = [];
  const recoveryEvents: RecoveryEvent[] = [];
  let remaining = [...options.urls];
  let recoveryCount = 0;
  let sessionOrdinal = 1;
  let sessionSource = options.initialStorageState ? 'provided' : 'fresh_login';
  let currentState = options.initialStorageState ?? '';
  let stopReason: string | null = null;
  let pendingTriggerUrl: string | null = null;

  if (!options.initialStorageState) {
    const opened = await options.obtainSession(sessionOrdinal, 'initial');
    if (!opened.success) {
      return { finalResults: [], requestEvents, recoveryEvents, remainingCount: remaining.length, stopReason: 'initial_login_failed' };
    }
    currentState = opened.storageState;
  }

  while (remaining.length > 0 && performance.now() < options.deadline) {
    let gate: SegmentOutcome;
    try {
      gate = await options.executeSegment(options.gates, currentState, sessionOrdinal, 'gate');
    } catch (error) {
      if (!(error instanceof Error) || error.message !== 'session_state_unusable') throw error;
      gate = { results: [], events: [], pause_reason: 'session_state_unusable', remaining_count: 3, duration_ms: 0,
        cookie_metadata: { storage_cookie_count: 0, usable_cookie_count: 0 } };
    }
    requestEvents.push(...gate.events);
    const gateOk = gate.results.length === options.gates.length && gate.results.every((item) => item.status === 'success');
    recoveryEvents.push({
      event: 'session_gate', session_ordinal: sessionOrdinal, session_source: sessionSource,
      success: gateOk, result_count: gate.results.length,
      response_class_counts: countBy(gate.results.map((item) => item.response_class)),
      cookie_metadata: gate.cookie_metadata,
    });
    if (!gateOk) {
      const reason: ResponseClass | 'gate_failed' = gate.pause_reason ?? 'gate_failed';
      if (reason !== 'gate_failed' && RECOVERABLE.has(reason) && recoveryCount < options.maxRecoveries) {
        recoveryCount += 1;
        sessionOrdinal += 1;
        const opened = await options.obtainSession(sessionOrdinal, reason);
        recoveryEvents.push({ event: 'session_refresh', session_ordinal: sessionOrdinal, reason,
          recovery_scope: 'gate', success: opened.success, trigger_recovered: false });
        if (!opened.success) { stopReason = 'session_refresh_failed'; break; }
        currentState = opened.storageState;
        sessionSource = 'recovery_login';
        continue;
      }
      stopReason = reason !== 'gate_failed' && NON_RECOVERABLE.has(reason)
        ? reason
        : (reason !== 'gate_failed' && RECOVERABLE.has(reason) ? 'max_recoveries_exhausted' : 'gate_failed');
      break;
    }

    let segment: SegmentOutcome;
    try {
      segment = await options.executeSegment(remaining, currentState, sessionOrdinal, 'bulk');
    } catch (error) {
      if (!(error instanceof Error) || error.message !== 'session_state_unusable') throw error;
      segment = { results: [], events: [], pause_reason: 'session_state_unusable', remaining_count: remaining.length,
        duration_ms: 0, cookie_metadata: { storage_cookie_count: 0, usable_cookie_count: 0 } };
    }
    requestEvents.push(...segment.events);

    if (pendingTriggerUrl && segment.results.length > 0) {
      const first = segment.results[0]!;
      if (first.url === pendingTriggerUrl && !RECOVERABLE.has(first.response_class)) {
        const refresh = [...recoveryEvents].reverse().find((event) => event.event === 'session_refresh' && event['trigger_recovered'] !== true);
        if (refresh) refresh['trigger_recovered'] = true;
        pendingTriggerUrl = null;
      }
    }

    if (segment.pause_reason) {
      const reason = segment.pause_reason;
      if (segment.results.length === 0) {
        if (RECOVERABLE.has(reason) && recoveryCount < options.maxRecoveries) {
          recoveryCount += 1;
          sessionOrdinal += 1;
          const opened = await options.obtainSession(sessionOrdinal, reason);
          recoveryEvents.push({ event: 'session_refresh', session_ordinal: sessionOrdinal, reason,
            recovery_scope: 'bulk_state', success: opened.success, trigger_recovered: false });
          if (!opened.success) { stopReason = 'session_refresh_failed'; break; }
          currentState = opened.storageState;
          sessionSource = 'recovery_login';
          continue;
        }
        stopReason = RECOVERABLE.has(reason) ? 'max_recoveries_exhausted' : reason;
        break;
      }
      const control = segment.results.at(-1)!;
      for (const result of segment.results.slice(0, -1)) finalByUrl.set(result.url, result);
      remaining = remaining.slice(segment.results.length - 1);
      if (RECOVERABLE.has(reason) && recoveryCount < options.maxRecoveries) {
        pendingTriggerUrl = control.url;
        recoveryCount += 1;
        sessionOrdinal += 1;
        const opened = await options.obtainSession(sessionOrdinal, reason);
        recoveryEvents.push({ event: 'session_refresh', session_ordinal: sessionOrdinal, reason,
          recovery_scope: 'bulk_control', success: opened.success,
          trigger_url_sha256: control.url_sha256, trigger_recovered: false });
        if (!opened.success) { finalByUrl.set(control.url, control); stopReason = 'session_refresh_failed'; break; }
        currentState = opened.storageState;
        sessionSource = 'recovery_login';
        continue;
      }
      finalByUrl.set(control.url, control);
      stopReason = RECOVERABLE.has(reason) ? 'max_recoveries_exhausted' : reason;
      break;
    }

    for (const result of segment.results) finalByUrl.set(result.url, result);
    remaining = remaining.slice(segment.results.length);
  }

  if (remaining.length > 0 && stopReason === null) stopReason = 'window_exhausted';
  return {
    finalResults: options.urls.filter((url) => finalByUrl.has(url)).map((url) => finalByUrl.get(url)!),
    requestEvents,
    recoveryEvents,
    remainingCount: options.urls.length - finalByUrl.size,
    stopReason,
  };
}

function countBy(values: string[]): Record<string, number> {
  const counts = new Map<string, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function writeJson(path: string, value: object): void {
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

function writeJsonl(path: string, values: object[]): void {
  const content = values.length > 0 ? `${values.map((value) => JSON.stringify(value)).join('\n')}\n` : '';
  writeFileSync(path, content, 'utf8');
}

function writeChecksums(outputDir: string): string {
  const names = ['environment.json', 'input-urls.txt', 'recovery-events.jsonl', 'request-events.jsonl', 'summary.json', 'url-results.jsonl'];
  const lines = names.map((name) => `${createHash('sha256').update(readFileSync(join(outputDir, name))).digest('hex')}  ${name}\n`);
  const path = join(outputDir, 'SHA256SUMS');
  writeFileSync(path, lines.join(''), 'utf8');
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}

function summarize(outcome: RecoveryOutcome, inputCount: number, durationMs: number): Record<string, unknown> {
  const successCount = outcome.finalResults.filter((item) => item.status === 'success').length;
  const refreshes = outcome.recoveryEvents.filter((event) => event.event === 'session_refresh');
  return {
    schema_version: '1.0', candidate: 'candidate-b', mode: 'bounded-session-recovery',
    input_count: inputCount, final_result_count: outcome.finalResults.length, success_count: successCount,
    remaining_count: outcome.remainingCount, final_valid_rate: Number((successCount / inputCount).toFixed(6)),
    result_coverage_rate: Number((outcome.finalResults.length / inputCount).toFixed(6)),
    response_class_counts: countBy(outcome.finalResults.map((item) => item.response_class)),
    http_status_counts: countBy(outcome.finalResults.filter((item) => item.http_status !== null).map((item) => String(item.http_status))),
    duration_ms: durationMs,
    effective_urls_per_second: durationMs > 0 ? Number((successCount / (durationMs / 1_000)).toFixed(6)) : 0,
    request_count: outcome.requestEvents.length,
    request_amplification: Number((outcome.requestEvents.length / inputCount).toFixed(6)),
    request_metric_scope: 'collector_http_gate_bulk_and_retry_excludes_browser_login_subrequests',
    session_refresh_count: refreshes.length,
    successful_session_refresh_count: refreshes.filter((event) => event['success'] === true).length,
    recovered_bulk_control_count: refreshes.filter((event) => event['trigger_recovered'] === true).length,
    stop_reason: outcome.stopReason,
    meets_2000_per_hour_speed: successCount / Math.max(durationMs / 1_000, 0.001) >= 2_000 / 3_600,
    meets_correctness_gate: successCount === inputCount && outcome.finalResults.length === inputCount,
  };
}

async function establishSession(config: TestConfig, probeUrl: string, sessionDir: string): Promise<SessionOutcome> {
  mkdirSync(sessionDir, { recursive: false });
  const profileDir = join(sessionDir, 'browser-profile');
  prepareIsolatedProfile(profileDir);
  const login = await verifyLogin(config, profileDir, probeUrl, sessionDir);
  const state = storageStatePath(profileDir);
  const success = login['logged_in'] === true;
  if (success) chmodSync(state, 0o600);
  writeJson(join(sessionDir, 'session-result.json'), {
    schema_version: '1.0', candidate: 'candidate-b', success,
    response_class: login['response_class'], verification_required: login['verification_required'],
    storage_state_written: success,
  });
  return { success, storageState: state };
}

async function main(): Promise<number> {
  const options = parseArgs(process.argv.slice(2));
  const config = loadConfig(options.config);
  const urls = selectedUrls(options.input, options.offset, options.limit);
  const gates = gateUrls(options.gateInput);
  mkdirSync(options.outputDir, { recursive: false });
  mkdirSync(join(options.outputDir, 'sessions'), { recursive: false });
  mkdirSync(join(options.outputDir, 'segments'), { recursive: false });
  writeFileSync(join(options.outputDir, 'input-urls.txt'), `${urls.join('\n')}\n`, 'utf8');
  log.setLevel(LogLevel.WARNING);
  const startedAt = utcNow();
  const started = performance.now();
  let segmentOrdinal = 0;
  const outcome = await executeRecoveryControl({
    urls,
    gates,
    maxRecoveries: options.maxRecoveries,
    deadline: started + options.windowSeconds * 1_000,
    initialStorageState: options.initialStorageState,
    obtainSession: async (ordinal, reason) => {
      const sessionDir = join(options.outputDir, 'sessions', `session-${String(ordinal).padStart(3, '0')}`);
      let result: SessionOutcome;
      try {
        result = await establishSession(config, gates[0]!, sessionDir);
      } catch (error) {
        const errorCategory = error instanceof Error ? error.name : 'UnknownError';
        writeJson(join(sessionDir, 'session-result.json'), {
          schema_version: '1.0', candidate: 'candidate-b', success: false, error_category: errorCategory,
        });
        result = { success: false, storageState: storageStatePath(join(sessionDir, 'browser-profile')) };
      }
      process.stdout.write(`${JSON.stringify({ event: 'session_refresh', session_ordinal: ordinal, reason, success: result.success })}\n`);
      return result;
    },
    executeSegment: async (segmentUrls, state, ordinal, kind) => {
      segmentOrdinal += 1;
      return runHttpSegment(
        segmentUrls, state, options.timeoutSeconds, ordinal, kind,
        join(options.outputDir, 'segments', `segment-${String(segmentOrdinal).padStart(3, '0')}`),
      );
    },
  });
  const durationMs = Math.round(performance.now() - started);
  const summary = summarize(outcome, urls.length, durationMs);
  const require = createRequire(import.meta.url);
  const environment = {
    schema_version: '1.0', candidate: 'candidate-b', mode: 'bounded-session-recovery',
    operating_system: `${process.platform}-${process.arch}`, node_version: process.version,
    crawlee_version: (require('crawlee/package.json') as { version: string }).version,
    started_at: startedAt, ended_at: utcNow(), source_input_file_sha256: createHash('sha256').update(readFileSync(options.input)).digest('hex'),
    selected_input_sha256: createHash('sha256').update(readFileSync(join(options.outputDir, 'input-urls.txt'))).digest('hex'),
    input_offset: options.offset, input_count: urls.length, gate_input_count: gates.length,
    max_recoveries: options.maxRecoveries, window_seconds: options.windowSeconds, concurrency: 1,
    browser_used_for_session_bootstrap_only: true, collector: 'CheerioCrawler', session_pool_size: 1,
  };
  writeJsonl(join(options.outputDir, 'url-results.jsonl'), outcome.finalResults);
  writeJsonl(join(options.outputDir, 'request-events.jsonl'), outcome.requestEvents);
  writeJsonl(join(options.outputDir, 'recovery-events.jsonl'), outcome.recoveryEvents);
  writeJson(join(options.outputDir, 'summary.json'), summary);
  writeJson(join(options.outputDir, 'environment.json'), environment);
  summary['checksums_sha256'] = writeChecksums(options.outputDir);
  process.stdout.write(`${JSON.stringify(summary)}\n`);
  return summary['meets_correctness_gate'] === true ? 0 : 6;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const exitCode = await main();
  process.exitCode = exitCode;
}
