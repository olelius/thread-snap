/** 候选 B：使用 Crawlee/Playwright 持久认证会话执行定量吞吐测试。 */

import { createHash } from 'node:crypto';
import {
  appendFileSync, chmodSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync,
} from 'node:fs';
import { dirname, isAbsolute, resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { createInterface } from 'node:readline/promises';
import { PlaywrightCrawler } from 'crawlee';
import type { Cookie, Page, Response } from 'playwright';
import { classifyDocument, CONTROL_CLASSES, extractInputPostId, urlSha256, type Classification } from './contract.js';
import {
  ACCESS_DIAGNOSTIC_CLASSES,
  ACCESS_DIAGNOSTIC_LIMIT_PER_CLASS,
  buildAccessDiagnostic,
  summarizeDocumentResponse,
} from './access-diagnostic.js';

interface CandidateConfig {
  concurrency?: number;
  profile_dir?: string;
}

interface TestConfig {
  account: string;
  password: string;
  input_file: string;
  expected_count: number;
  window_seconds: number;
  headless?: boolean;
  wait_ms?: number;
  max_attempts?: number;
  retry_delay_ms?: number;
  request_timeout_ms?: number;
  capture_login_diagnostic?: boolean;
  candidate_b: CandidateConfig;
}

interface CliOptions {
  config: string;
  outputDir: string;
  bootstrapSms: boolean;
  manualCaptchaCdpPort: number;
}

interface Attempt extends Classification {
  schema_version: '1.0';
  candidate: 'candidate-b';
  url: string;
  url_sha256: string;
  attempt: number;
  channel: 'browser-dom';
  started_at: string;
  ended_at: string;
  duration_ms: number;
  http_status: number | null;
  final_url_sha256: string | null;
  error_category: string | null;
}

const SECONDARY_SMS_MARKER = '为保证账号安全，请使用手机验证码登录';
const LOGIN_REASON_MARKERS = [
  SECONDARY_SMS_MARKER,
  '短信验证码', '获取验证码', '发送验证码', '手机验证', '手机号验证',
  '验证码', '验证中心', '安全验证', '滑动验证', '向右滑动',
  '账号或密码错误', '账号不存在', '密码错误', '登录失败', '操作频繁', '请稍后重试',
] as const;
const VERIFICATION_REASON_MARKERS = new Set<string>(LOGIN_REASON_MARKERS.slice(0, 11));
const VISUAL_VERIFICATION_SELECTOR = [
  'iframe[src*="captcha" i]', '[class*="captcha" i]', '[id*="captcha" i]',
  '[class*="verify" i]', '[id*="verify" i]', '[class*="slider" i]',
].join(', ');
const MANUAL_VERIFICATION_TIMEOUT_MS = 600_000;

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
  channel: 'browser-dom';
  status: Classification['status'];
  request_count: number;
  started_at: string;
  ended_at: string;
  duration_ms: number;
  http_status: number | null;
  error_category: string | null;
}

function parseArgs(argv: string[]): CliOptions {
  const values = new Map<string, string>();
  let bootstrapSms = false;
  for (let index = 0; index < argv.length;) {
    const key = argv[index];
    if (key === '--bootstrap-sms') {
      bootstrapSms = true;
      index += 1;
      continue;
    }
    const value = argv[index + 1];
    if (!key?.startsWith('--') || value === undefined) throw new Error(`参数格式错误: ${key ?? ''}`);
    values.set(key, value);
    index += 2;
  }
  const config = values.get('--config');
  const outputDir = values.get('--output-dir');
  if (!config || !outputDir) throw new Error('缺少 --config 或 --output-dir');
  const manualCaptchaCdpPort = Number(values.get('--manual-captcha-cdp-port') ?? 0);
  if (!Number.isInteger(manualCaptchaCdpPort) || manualCaptchaCdpPort < 0 || manualCaptchaCdpPort > 65535) {
    throw new Error('manual-captcha-cdp-port 必须是 0 或 1024..65535 的整数');
  }
  if (manualCaptchaCdpPort > 0 && manualCaptchaCdpPort < 1024) {
    throw new Error('manual-captcha-cdp-port 必须是 0 或 1024..65535 的整数');
  }
  return { config: resolve(config), outputDir: resolve(outputDir), bootstrapSms, manualCaptchaCdpPort };
}

type StoredCookies = Parameters<ReturnType<Page['context']>['addCookies']>[0];

async function readSmsCode(candidate: string): Promise<string> {
  const terminal = process.stdin.isTTY === true;
  const prompt = terminal ? `[${candidate}] 请输入手机收到的 4-8 位验证码: ` : '';
  const reader = createInterface({ input: process.stdin, output: process.stdout, terminal });
  try {
    const code = (await reader.question(prompt)).trim();
    if (!/^[0-9]{4,8}$/u.test(code)) throw new Error('短信验证码必须是 4-8 位数字');
    return code;
  } finally {
    reader.close();
  }
}

function buildSmsLoginUrl(postUrl: string): string {
  const parsed = new URL(postUrl);
  const loginUrl = new URL('/login-required', parsed.origin);
  loginUrl.searchParams.set('redirect', `${parsed.pathname}${parsed.search}`);
  return loginUrl.toString();
}

async function firstVisible(page: Page, selector: string): Promise<ReturnType<Page['locator']>> {
  const locator = page.locator(selector);
  await locator.first().waitFor({ state: 'attached', timeout: 10_000 });
  const count = Math.min(await locator.count(), 20);
  for (let index = 0; index < count; index += 1) {
    const item = locator.nth(index);
    if (await item.isVisible()) return item;
  }
  throw new Error('未找到可见登录控件');
}

async function clickFirstVisibleText(page: Page, labels: readonly string[]): Promise<string> {
  for (const label of labels) {
    const options = page.getByText(label, { exact: true });
    const count = Math.min(await options.count(), 10);
    for (let index = 0; index < count; index += 1) {
      const option = options.nth(index);
      if (await option.isVisible()) {
        await option.click({ timeout: 10_000 });
        return label;
      }
    }
  }
  throw new Error('未找到可见登录操作');
}

function positiveInt(value: unknown, name: string, min = 1, max = Number.MAX_SAFE_INTEGER): number {
  if (!Number.isInteger(value) || (value as number) < min || (value as number) > max) {
    throw new Error(`${name} 必须是 ${min}..${max} 的整数`);
  }
  return value as number;
}

function loadConfig(path: string): TestConfig {
  const value = JSON.parse(readFileSync(path, 'utf8')) as Partial<TestConfig>;
  if (!value || typeof value !== 'object') throw new Error('配置根节点必须是对象');
  if (typeof value.account !== 'string' || !value.account) throw new Error('account 必须是非空字符串');
  if (typeof value.password !== 'string' || !value.password) throw new Error('password 必须是非空字符串');
  if (typeof value.input_file !== 'string' || !value.input_file) throw new Error('input_file 必须是非空字符串');
  positiveInt(value.expected_count, 'expected_count');
  positiveInt(value.window_seconds, 'window_seconds');
  if (!value.candidate_b || typeof value.candidate_b !== 'object') throw new Error('candidate_b 必须是对象');
  positiveInt(value.candidate_b.concurrency ?? 8, 'candidate_b.concurrency', 1, 64);
  return value as TestConfig;
}

function relativeToConfig(configPath: string, value: string): string {
  return isAbsolute(value) ? value : resolve(dirname(configPath), value);
}

function storageStatePath(profileDir: string): string {
  return resolve(profileDir, 'storage-state.json');
}

function launchOptions(config: TestConfig, cdpPort = 0): Record<string, unknown> {
  const options: Record<string, unknown> = { headless: config.headless ?? true };
  if (cdpPort > 0) {
    options.args = [
      '--remote-debugging-address=127.0.0.1',
      `--remote-debugging-port=${cdpPort}`,
    ];
  }
  return options;
}

function loadStorageCookies(profileDir: string): StoredCookies {
  const path = storageStatePath(profileDir);
  if (!existsSync(path)) return [];
  const state = JSON.parse(readFileSync(path, 'utf8')) as { cookies?: unknown };
  if (!Array.isArray(state.cookies)) throw new Error('候选 B storage-state.json 缺少 cookies');
  return state.cookies as StoredCookies;
}

function prepareIsolatedProfile(profileDir: string): void {
  rmSync(profileDir, { recursive: true, force: true });
  mkdirSync(profileDir, { recursive: true, mode: 0o700 });
}

function promoteIsolatedProfile(source: string, target: string, backup: string): void {
  if (source === target || source === backup || target === backup) {
    throw new Error('会话资料目录必须彼此独立');
  }
  if (!existsSync(resolve(source, 'storage-state.json'))) {
    throw new Error('新会话资料缺少 storage-state.json');
  }
  mkdirSync(dirname(target), { recursive: true });
  rmSync(backup, { recursive: true, force: true });
  const hadTarget = existsSync(target);
  if (hadTarget) renameSync(target, backup);
  try {
    renameSync(source, target);
  } catch (error) {
    if (hadTarget && existsSync(backup) && !existsSync(target)) renameSync(backup, target);
    throw error;
  }
  rmSync(backup, { recursive: true, force: true });
}

function loadUrls(configPath: string, config: TestConfig): { inputPath: string; urls: string[] } {
  const inputPath = relativeToConfig(configPath, config.input_file);
  const all = readFileSync(inputPath, 'utf8').replace(/^\uFEFF/, '').split(/\r?\n/u).map((line) => line.trim()).filter(Boolean);
  if (all.length < config.expected_count) {
    throw new Error(`输入只有 ${all.length} 条，少于 expected_count=${config.expected_count}`);
  }
  const urls = all.slice(0, config.expected_count);
  if (new Set(urls).size !== urls.length) throw new Error('测试范围内含重复 URL');
  for (const url of urls) extractInputPostId(url);
  return { inputPath, urls };
}

function utcNow(): string {
  return new Date().toISOString();
}

function appendJsonl(path: string, record: object): void {
  appendFileSync(path, `${JSON.stringify(record)}\n`, 'utf8');
}

function loadCompleted(path: string): Set<string> {
  const completed = new Set<string>();
  try {
    const lines = readFileSync(path, 'utf8').split(/\r?\n/u).filter((line) => line.trim());
    for (const [index, line] of lines.entries()) {
      const value = JSON.parse(line) as { url?: unknown };
      if (typeof value.url !== 'string') throw new Error(`已有结果第 ${index + 1} 行缺少 URL`);
      if (completed.has(value.url)) throw new Error(`已有结果第 ${index + 1} 行 URL 重复`);
      completed.add(value.url);
    }
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code !== 'ENOENT') throw error;
  }
  return completed;
}

function failedResult(url: string, requestCount: number, category: string, startedAt = utcNow(), durationMs = 0): FinalResult {
  return {
    schema_version: '1.0', candidate: 'candidate-b', url, url_sha256: urlSha256(url),
    input_post_id: extractInputPostId(url), observed_post_id: null, post_id_matches: false,
    title_present: false, body_present: false, response_class: 'error', control_hit: false,
    channel: 'browser-dom', status: 'failed', request_count: requestCount,
    started_at: startedAt, ended_at: utcNow(), duration_ms: durationMs,
    http_status: null, error_category: category,
  };
}

function loginFailureResult(url: string, responseClass: Classification['response_class']): FinalResult {
  const isControl = CONTROL_CLASSES.has(responseClass);
  return {
    ...failedResult(url, 0, 'login_initialization_failed'),
    response_class: isControl ? responseClass : 'error',
    control_hit: isControl,
    status: isControl ? 'blocked' : 'failed',
  };
}

async function anyVisible(page: Page, selector: string): Promise<boolean> {
  const locator = page.locator(selector);
  const count = Math.min(await locator.count(), 10);
  for (let index = 0; index < count; index += 1) {
    if (await locator.nth(index).isVisible()) return true;
  }
  return false;
}

async function smsCountdownVisible(page: Page): Promise<boolean> {
  const controls = page.getByText(/(?:重新获取|重新发送|\d{1,3}\s*(?:s|秒))/u);
  const count = Math.min(await controls.count(), 100);
  for (let index = 0; index < count; index += 1) {
    const control = controls.nth(index);
    if (!await control.isVisible()) continue;
    const text = (await control.innerText()).trim();
    if (text.includes('重新获取') || text.includes('重新发送') || /\d{1,3}\s*(?:s|秒)/u.test(text)) return true;
  }
  return false;
}

async function waitForCdpPort(port: number, timeoutMs = 10_000): Promise<boolean> {
  const deadline = performance.now() + timeoutMs;
  while (performance.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`, { signal: AbortSignal.timeout(1_000) });
      if (response.ok) return true;
    } catch {
      // 浏览器启动后的短暂连接失败属于预期轮询状态。
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 250));
  }
  return false;
}

interface ManualVerificationResult {
  visual_verification_required: boolean;
  manual_verification_completed: boolean;
  sms_send_confirmed: boolean;
}

async function waitForManualVisualVerification(
  page: Page, candidate: string, cdpPort: number,
): Promise<ManualVerificationResult> {
  let verificationVisible = await anyVisible(page, VISUAL_VERIFICATION_SELECTOR);
  let countdownVisible = await smsCountdownVisible(page);
  if (!verificationVisible) {
    return {
      visual_verification_required: false,
      manual_verification_completed: false,
      sms_send_confirmed: countdownVisible,
    };
  }
  if (cdpPort < 1024 || cdpPort > 65535) throw new Error('检测到可视验证，但没有有效的回环 CDP 端口');
  if (!await waitForCdpPort(cdpPort)) throw new Error('Chromium 回环 CDP 端口尚未就绪');

  console.log(`visual_verification_required=${candidate}`);
  console.log(`cdp_endpoint=http://127.0.0.1:${cdpPort}`);
  console.log(`windows_tunnel=ssh -N -L ${cdpPort}:127.0.0.1:${cdpPort} root@<服务器地址>`);
  console.log('windows_browser=chrome://inspect/#devices');
  console.log(`manual_verification_waiting=${candidate};timeout_seconds=${MANUAL_VERIFICATION_TIMEOUT_MS / 1_000}`);

  const deadline = performance.now() + MANUAL_VERIFICATION_TIMEOUT_MS;
  let challengeCleared = false;
  while (performance.now() < deadline) {
    verificationVisible = await anyVisible(page, VISUAL_VERIFICATION_SELECTOR);
    countdownVisible = await smsCountdownVisible(page);
    if (!verificationVisible && countdownVisible) {
      console.log(`manual_verification_completed=${candidate}`);
      console.log(`sms_send_confirmed=${candidate}`);
      return {
        visual_verification_required: true,
        manual_verification_completed: true,
        sms_send_confirmed: true,
      };
    }
    if (!verificationVisible && !challengeCleared) {
      challengeCleared = true;
      console.log(`visual_verification_cleared=${candidate};waiting_for_sms_confirmation=true`);
    } else if (verificationVisible) {
      challengeCleared = false;
    }
    await page.waitForTimeout(500);
  }
  throw new Error('人工可视验证或短信发送确认等待超时');
}

async function collectLoginDiagnostic(
  page: Page,
  config: TestConfig,
  outputDir: string,
): Promise<Record<string, unknown>> {
  const bodyText = await page.locator('body').innerText({ timeout: 5_000 }).catch(() => '');
  const reasonMarkers = LOGIN_REASON_MARKERS.filter((marker) => bodyText.includes(marker));
  const selectorMap = {
    sms_code_input: 'input[name="code"], input[placeholder*="验证码"]',
    captcha_frame: 'iframe[src*="captcha" i]',
    captcha_container: '[class*="captcha" i], [id*="captcha" i]',
    verification_container: '[class*="verify" i], [id*="verify" i]',
    slider_container: '[class*="slide" i], [class*="slider" i]',
    account_input: 'input[name="account"]',
    password_input: 'input[name="password"]',
  };
  const visibleSelectors: Record<string, boolean> = {};
  for (const [name, selector] of Object.entries(selectorMap)) {
    visibleSelectors[name] = await anyVisible(page, selector).catch(() => false);
  }
  const parsedUrl = new URL(page.url());
  const secrets = [
    config.account,
    config.password,
    config.account.slice(0, 3),
    config.account.slice(-4),
  ].filter(Boolean);
  let pageTitle = (await page.title().catch(() => '')).slice(0, 120);
  for (const secret of secrets) pageTitle = pageTitle.split(secret).join('[REDACTED]');
  const verificationRequired = reasonMarkers.some((marker) => VERIFICATION_REASON_MARKERS.has(marker))
    || ['sms_code_input', 'captcha_frame', 'captcha_container', 'verification_container', 'slider_container']
      .some((name) => visibleSelectors[name] === true);
  const diagnostic: Record<string, unknown> = {
    schema_version: '1.0',
    candidate: 'candidate-b',
    final_path: parsedUrl.pathname,
    query_keys: [...new Set(parsedUrl.searchParams.keys())].sort(),
    page_title: pageTitle,
    reason_markers: reasonMarkers,
    secondary_sms_required: bodyText.includes(SECONDARY_SMS_MARKER),
    visible_selectors: visibleSelectors,
    verification_visible: verificationRequired,
    screenshot: null,
    screenshot_error: null,
  };
  if (config.capture_login_diagnostic && (parsedUrl.pathname.includes('/login') || verificationRequired)) {
    try {
      await page.evaluate(({ values }: { values: string[] }) => {
        document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('input, textarea').forEach((element) => {
          element.value = '';
          element.setAttribute('value', '');
        });
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          for (const secret of values) {
            if (secret) node.textContent = (node.textContent ?? '').split(secret).join('[REDACTED]');
          }
        }
      }, { values: secrets });
      const screenshotName = 'login-page-redacted.png';
      await page.screenshot({ path: resolve(outputDir, screenshotName), fullPage: true });
      diagnostic['screenshot'] = screenshotName;
    } catch (error) {
      diagnostic['screenshot_error'] = error instanceof Error ? error.name : 'unknown_error';
    }
  }
  return diagnostic;
}

async function verifyLogin(
  config: TestConfig, profileDir: string, probeUrl: string, outputDir: string,
): Promise<Record<string, unknown>> {
  let result: Record<string, unknown> | undefined;
  const storedCookies = loadStorageCookies(profileDir);
  const crawler = new PlaywrightCrawler({
    maxConcurrency: 1,
    maxRequestRetries: 0,
    retryOnBlocked: false,
    useSessionPool: false,
    requestHandlerTimeoutSecs: 90,
    launchContext: {
      userDataDir: profileDir,
      launchOptions: launchOptions(config),
    },
    preNavigationHooks: [
      async ({ page }) => {
        if (storedCookies.length > 0) await page.context().addCookies(storedCookies);
      },
    ],
    requestHandler: async ({ page }) => {
      await page.waitForTimeout(2_000);
      let submitted = false;
      let passwordLoginSelected = false;
      if (page.url().includes('/login-required')) {
        const passwordOptions = page.getByText('密码登录', { exact: true });
        const optionCount = Math.min(await passwordOptions.count(), 10);
        for (let index = 0; index < optionCount; index += 1) {
          const option = passwordOptions.nth(index);
          if (await option.isVisible()) {
            await option.click({ timeout: 5_000 });
            passwordLoginSelected = true;
            await page.waitForTimeout(500);
            break;
          }
        }
        const accountInput = page.locator('input[name="account"]');
        const passwordInput = page.locator('input[name="password"]');
        await accountInput.waitFor({ state: 'visible', timeout: 10_000 });
        await passwordInput.waitFor({ state: 'visible', timeout: 10_000 });
        await accountInput.fill(config.account);
        await passwordInput.fill(config.password);
        await page.getByRole('button', { name: '登录', exact: true }).click({ timeout: 10_000 });
        submitted = true;
        await page.waitForTimeout(10_000);
      }
      const htmlDocument = await page.content();
      const classification = classifyDocument(page.url(), 200, htmlDocument, extractInputPostId(probeUrl));
      const diagnostic = await collectLoginDiagnostic(page, config, outputDir).catch((error: unknown) => ({
        schema_version: '1.0',
        candidate: 'candidate-b',
        verification_visible: false,
        screenshot: null,
        screenshot_error: error instanceof Error ? error.name : 'unknown_error',
      }));
      if (config.capture_login_diagnostic) {
        writeFileSync(resolve(outputDir, 'login-diagnostic.json'), `${JSON.stringify(diagnostic, null, 2)}\n`, 'utf8');
      }
      const verificationRequired = diagnostic['verification_visible'] === true;
      result = {
        schema_version: '1.0', candidate: 'candidate-b', submitted,
        password_login_selected: passwordLoginSelected,
        logged_in: classification.status === 'success' && !verificationRequired,
        verification_required: verificationRequired,
        response_class: classification.response_class,
        status: classification.status,
        diagnostic_file: config.capture_login_diagnostic ? 'login-diagnostic.json' : null,
      };
    },
  });
  await crawler.run([{ url: probeUrl, uniqueKey: `login:${urlSha256(probeUrl)}` }]);
  if (!result) throw new Error('候选 B 登录运行未生成结果');
  writeFileSync(resolve(outputDir, 'login-result.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  return result;
}

async function bootstrapSmsSession(
  config: TestConfig, sessionProfileDir: string, probeUrl: string, cdpPort: number,
): Promise<Record<string, unknown>> {
  let result: Record<string, unknown> | undefined;
  const crawler = new PlaywrightCrawler({
    maxConcurrency: 1,
    maxRequestRetries: 0,
    retryOnBlocked: false,
    useSessionPool: false,
    requestHandlerTimeoutSecs: 900,
    launchContext: {
      userDataDir: sessionProfileDir,
      launchOptions: launchOptions(config, cdpPort),
    },
    preNavigationHooks: [
      async ({ page }, gotoOptions) => {
        gotoOptions.waitUntil = 'domcontentloaded';
        console.log('navigation_action=candidate-b;action=wait_until_domcontentloaded');
        const pendingByType = new Map<string, number>();
        const changePending = (kind: string, delta: number): void => {
          pendingByType.set(kind, Math.max(0, (pendingByType.get(kind) ?? 0) + delta));
        };
        page.on('request', (request) => changePending(request.resourceType(), 1));
        page.on('requestfinished', (request) => changePending(request.resourceType(), -1));
        page.on('requestfailed', (request) => changePending(request.resourceType(), -1));
        page.on('response', (response) => {
          if (response.request().resourceType() !== 'document') return;
          const path = new URL(response.url()).pathname;
          const target = path.includes('/login') ? 'login' : path.includes('/article/') ? 'post' : 'other';
          console.log(`navigation_document=candidate-b;status=${response.status()};target=${target}`);
        });
        page.on('domcontentloaded', async () => {
          console.log('navigation_event=candidate-b;event=domcontentloaded');
          if (!page.url().includes('/login-required')) return;
          await page.waitForTimeout(250);
          if (page.isClosed()) return;
          const pending = [...pendingByType.entries()]
            .filter(([, count]) => count > 0)
            .sort(([left], [right]) => left.localeCompare(right))
            .map(([kind, count]) => `${kind}:${count}`)
            .join(',') || 'none';
          console.log(`navigation_pending=candidate-b;types=${pending}`);
        });
        page.on('load', () => console.log('navigation_event=candidate-b;event=load'));
        await page.route('**/*', async (route) => {
          const kind = route.request().resourceType();
          if (['media', 'font'].includes(kind)) await route.abort();
          else await route.continue();
        });
      },
    ],
    requestHandler: async ({ page }) => {
      let smsRequested = false;
      let smsSendEvidence: Record<string, unknown> | null = null;
      let visualVerificationRequired = false;
      let manualVerificationCompleted = false;
      let smsSendConfirmed = false;
      let submitted = false;
      let errorCategory: string | null = null;
      let errorStage: string | null = null;
      let loginPageEvidence: Record<string, unknown> | null = null;
      let classification: Classification = {
        observed_post_id: null,
        post_id_matches: false,
        title_present: false,
        body_present: false,
        response_class: 'error',
        status: 'failed',
      };
      try {
        await page.waitForTimeout(2_000);
        if (page.url().includes('/login-required')) {
          errorStage = 'inspect_login_page';
          const htmlDocument = await page.content();
          const smsLabelCount = await page.getByText('验证码登录', { exact: true }).count()
            + await page.getByText('手机验证码登录', { exact: true }).count();
          loginPageEvidence = {
            document_bytes: Buffer.byteLength(htmlDocument, 'utf8'),
            input_count: await page.locator('input').count(),
            form_count: await page.locator('form').count(),
            sms_label_count: smsLabelCount,
          };
          console.log(`sms_login_page_evidence=candidate-b;${JSON.stringify(loginPageEvidence)}`);
          let switched = false;
          for (const label of ['验证码登录', '手机验证码登录']) {
            const options = page.getByText(label, { exact: true });
            const count = Math.min(await options.count(), 10);
            for (let index = 0; index < count; index += 1) {
              const option = options.nth(index);
              if (await option.isVisible()) {
                await option.click({ timeout: 10_000 });
                await page.waitForTimeout(500);
                switched = true;
                break;
              }
            }
            if (switched) break;
          }

          errorStage = 'wait_sms_controls';
          const accountInput = await firstVisible(page, 'input[name="account"], input[placeholder*="手机号"]');
          const codeInput = await firstVisible(page, 'input[name="code"], input[placeholder*="验证码"]');
          await accountInput.evaluate((element) => element.setAttribute('autocomplete', 'off'));
          await codeInput.evaluate((element) => element.setAttribute('autocomplete', 'off'));
          await codeInput.evaluate((element) => element.closest('form')?.setAttribute('autocomplete', 'off'));
          const smsNetworkEvents: Array<Record<string, unknown>> = [];
          page.on('request', (request) => {
            if (!['xhr', 'fetch'].includes(request.resourceType())) return;
            smsNetworkEvents.push({
              phase: 'request', type: request.resourceType(), method: request.method(), path: new URL(request.url()).pathname,
            });
          });
          page.on('response', (response) => {
            if (!['xhr', 'fetch'].includes(response.request().resourceType())) return;
            smsNetworkEvents.push({
              phase: 'response', type: response.request().resourceType(), status: response.status(), path: new URL(response.url()).pathname,
            });
          });
          await accountInput.fill(config.account);
          errorStage = 'request_sms';
          console.log('sms_page_ready=candidate-b');
          smsNetworkEvents.length = 0;
          await clickFirstVisibleText(page, ['获取验证码', '发送验证码']);
          smsRequested = true;
          await page.waitForTimeout(5_000);
          console.log('sms_request_clicked=candidate-b');
          const bodyText = await page.locator('body').innerText({ timeout: 5_000 });
          const warningMarkers = ['操作频繁', '请稍后重试', '发送失败', '请求过于频繁', '安全验证', '滑动验证']
            .filter((marker) => bodyText.includes(marker));
          const countdownVisible = await smsCountdownVisible(page);
          const verificationVisible = await anyVisible(page, VISUAL_VERIFICATION_SELECTOR);
          smsSendEvidence = {
            network_events: smsNetworkEvents.slice(0, 20), countdown_visible: countdownVisible,
            verification_visible: verificationVisible, warning_markers: warningMarkers,
          };
          console.log(`sms_send_evidence=candidate-b;${JSON.stringify(smsSendEvidence)}`);
          const verificationResult = await waitForManualVisualVerification(page, 'candidate-b', cdpPort);
          visualVerificationRequired = verificationResult.visual_verification_required;
          manualVerificationCompleted = verificationResult.manual_verification_completed;
          smsSendConfirmed = verificationResult.sms_send_confirmed;
          if (!smsSendConfirmed) throw new Error('短信发送尚未取得倒计时确认');
          errorStage = 'read_sms_code';
          let code = await readSmsCode('candidate-b');
          await codeInput.fill(code);
          code = '';
          await clickFirstVisibleText(page, ['登录/注册', '登录']);
          submitted = true;
          errorStage = 'verify_authenticated_post';
          await page.waitForTimeout(10_000);
        }
        const htmlDocument = await page.content();
        classification = classifyDocument(page.url(), 200, htmlDocument, extractInputPostId(probeUrl));
        if (classification.status === 'success') {
          const path = storageStatePath(sessionProfileDir);
          await page.context().storageState({ path });
          chmodSync(path, 0o600);
          errorStage = null;
        }
      } catch (error) {
        errorCategory = error instanceof Error ? error.name : 'unknown_error';
      }
      result = {
        schema_version: '1.0',
        candidate: 'candidate-b',
        mode: 'interactive_sms_bootstrap',
        sms_requested: smsRequested,
        sms_send_evidence: smsSendEvidence,
        visual_verification_required: visualVerificationRequired,
        manual_verification_completed: manualVerificationCompleted,
        sms_send_confirmed: smsSendConfirmed,
        submitted,
        logged_in: classification.status === 'success',
        response_class: classification.response_class,
        status: classification.status,
        error_category: errorCategory,
        error_stage: errorStage,
        login_page_evidence: loginPageEvidence,
      };
    },
  });
  console.log('navigation_target=candidate-b;target=login');
  await crawler.run([{ url: buildSmsLoginUrl(probeUrl), uniqueKey: `sms-bootstrap:${urlSha256(probeUrl)}` }]);
  if (!result) throw new Error('候选 B 短信初始化未生成结果');
  return result;
}

async function main(): Promise<number> {
  const runStarted = performance.now();
  const options = parseArgs(process.argv.slice(2));
  const config = loadConfig(options.config);
  const { inputPath, urls } = loadUrls(options.config, config);
  const candidate = config.candidate_b;
  const concurrency = candidate.concurrency ?? 8;
  const maxAttempts = positiveInt(config.max_attempts ?? 2, 'max_attempts', 1, 5);
  const waitMs = positiveInt(config.wait_ms ?? 1_000, 'wait_ms', 0, 60_000);
  const requestTimeoutMs = positiveInt(config.request_timeout_ms ?? 45_000, 'request_timeout_ms', 1_000, 300_000);
  mkdirSync(options.outputDir, { recursive: true });
  const resultsPath = resolve(options.outputDir, 'url-results.jsonl');
  const eventsPath = resolve(options.outputDir, 'request-events.jsonl');
  const diagnosticsPath = resolve(options.outputDir, 'access-diagnostics.jsonl');
  if (!existsSync(diagnosticsPath)) writeFileSync(diagnosticsPath, '', 'utf8');
  const completed = loadCompleted(resultsPath);
  const urlSet = new Set(urls);
  for (const url of completed) if (!urlSet.has(url)) throw new Error('已有结果包含本轮清单外 URL');
  const pending = urls.filter((url) => !completed.has(url));
  const profileDir = relativeToConfig(options.config, candidate.profile_dir ?? 'profiles/candidate-b');
  mkdirSync(profileDir, { recursive: true });
  process.env['CRAWLEE_STORAGE_DIR'] = resolve(options.outputDir, 'crawlee-storage');

  if (options.bootstrapSms) {
    const bootstrapProfileDir = resolve(options.outputDir, 'browser-profile');
    prepareIsolatedProfile(bootstrapProfileDir);
    console.log('bootstrap_profile=candidate-b;mode=fresh_isolated');
    const result = await bootstrapSmsSession(
      config, bootstrapProfileDir, urls[0]!, options.manualCaptchaCdpPort,
    );
    result['bootstrap_profile_mode'] = 'fresh_isolated';
    result['session_promoted'] = false;
    if (result['logged_in'] === true) {
      try {
        promoteIsolatedProfile(bootstrapProfileDir, profileDir, resolve(options.outputDir, 'previous-profile'));
        result['session_promoted'] = true;
        console.log('session_promoted=candidate-b;value=true');
      } catch (error) {
        result['status'] = 'failed';
        result['error_category'] = error instanceof Error ? error.name : 'unknown_error';
        result['error_stage'] = 'promote_session_profile';
      }
    }
    writeFileSync(resolve(options.outputDir, 'sms-bootstrap-result.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
    return result['logged_in'] === true && result['session_promoted'] === true ? 0 : 5;
  }

  const environment = {
    schema_version: '1.0', candidate: 'candidate-b', access_mode: 'authenticated',
    node_version: process.version, input_file: inputPath, expected_count: urls.length,
    concurrency, window_seconds: config.window_seconds,
    package_lock_sha256: createHash('sha256').update(readFileSync(resolve(import.meta.dirname, '..', 'package-lock.json'))).digest('hex'),
  };
  writeFileSync(resolve(options.outputDir, 'runner-environment.json'), `${JSON.stringify(environment, null, 2)}\n`, 'utf8');

  const loginResult = await verifyLogin(config, profileDir, urls[0]!, options.outputDir);
  if (loginResult['logged_in'] !== true) {
    const rawClass = String(loginResult['response_class'] ?? 'error');
    const responseClass = ['post', 'rate_limited', 'captcha', 'challenge', 'login', 'empty', 'error'].includes(rawClass)
      ? rawClass as Classification['response_class']
      : 'error';
    for (const url of pending) appendJsonl(resultsPath, loginFailureResult(url, responseClass));
    return 4;
  }

  const startedByUrl = new Map<string, { iso: string; perf: number }>();
  const controlHits = new Map<string, boolean>();
  const finalized = new Set(completed);
  let deadlineReached = false;
  const requests = pending.map((url) => ({ url, uniqueKey: `throughput:${urlSha256(url)}` }));
  const storedCookies = loadStorageCookies(profileDir);
  const diagnosticCounts = new Map<string, number>();
  let diagnosticSequence = 0;
  const documentResponsesByPage = new WeakMap<Page, Array<Record<string, unknown>>>();
  const instrumentedPages = new WeakSet<Page>();

  const maybeRecordAccessDiagnostic = async (optionsForDiagnostic: {
    responseClass: string;
    attempt: number;
    inputUrl: string;
    finalUrl: string;
    httpStatus: number | null;
    document: string;
    page: Page;
  }): Promise<void> => {
    if (!ACCESS_DIAGNOSTIC_CLASSES.has(optionsForDiagnostic.responseClass)) return;
    const count = diagnosticCounts.get(optionsForDiagnostic.responseClass) ?? 0;
    if (count >= ACCESS_DIAGNOSTIC_LIMIT_PER_CLASS) return;
    const nextCount = count + 1;
    diagnosticCounts.set(optionsForDiagnostic.responseClass, nextCount);
    diagnosticSequence += 1;
    let cookies: Cookie[] = [];
    let cookieShapeAvailable = true;
    try {
      cookies = await optionsForDiagnostic.page.context().cookies();
    } catch {
      cookieShapeAvailable = false;
    }
    appendJsonl(diagnosticsPath, buildAccessDiagnostic({
      candidate: 'candidate-b',
      trigger: nextCount === 1
        ? `first_${optionsForDiagnostic.responseClass}`
        : `sample_${optionsForDiagnostic.responseClass}_${nextCount}`,
      sequence: diagnosticSequence,
      attempt: optionsForDiagnostic.attempt,
      inputUrl: optionsForDiagnostic.inputUrl,
      finalUrl: optionsForDiagnostic.finalUrl,
      httpStatus: optionsForDiagnostic.httpStatus,
      responseClass: optionsForDiagnostic.responseClass,
      document: optionsForDiagnostic.document,
      cookies,
      cookieShapeAvailable,
      mainDocumentResponses: documentResponsesByPage.get(optionsForDiagnostic.page) ?? [],
    }));
  };

  const crawler = new PlaywrightCrawler({
    minConcurrency: Math.min(2, concurrency),
    maxConcurrency: concurrency,
    maxRequestRetries: maxAttempts - 1,
    retryOnBlocked: false,
    useSessionPool: false,
    requestHandlerTimeoutSecs: Math.ceil(requestTimeoutMs / 1000) + 10,
    launchContext: {
      userDataDir: profileDir,
      launchOptions: launchOptions(config),
    },
    preNavigationHooks: [
      async ({ page }) => {
        documentResponsesByPage.set(page, []);
        if (!instrumentedPages.has(page)) {
          page.on('response', (response: Response) => {
            if (response.request().resourceType() !== 'document') return;
            const evidence = documentResponsesByPage.get(page);
            if (evidence && evidence.length < 10) {
              evidence.push(summarizeDocumentResponse(response.url(), response.status()));
            }
          });
          instrumentedPages.add(page);
        }
        if (storedCookies.length > 0) await page.context().addCookies(storedCookies);
        await page.route('**/*', async (route) => {
          const kind = route.request().resourceType();
          if (['image', 'media', 'font', 'stylesheet'].includes(kind)) await route.abort();
          else await route.continue();
        });
      },
    ],
    requestHandler: async ({ request, page, response }) => {
      const url = request.url;
      const timing = startedByUrl.get(url) ?? { iso: utcNow(), perf: performance.now() };
      startedByUrl.set(url, timing);
      const attemptStartedAt = utcNow();
      const attemptStarted = performance.now();
      await page.waitForTimeout(waitMs);
      const document = await page.content();
      const httpStatus = response?.status() ?? null;
      const classification = classifyDocument(page.url(), httpStatus, document, extractInputPostId(url));
      const attempt = request.retryCount + 1;
      await maybeRecordAccessDiagnostic({
        responseClass: classification.response_class,
        attempt,
        inputUrl: url,
        finalUrl: page.url(),
        httpStatus,
        document,
        page,
      });
      const event: Attempt = {
        schema_version: '1.0', candidate: 'candidate-b', url, url_sha256: urlSha256(url), attempt,
        channel: 'browser-dom', started_at: attemptStartedAt, ended_at: utcNow(),
        duration_ms: Math.round(performance.now() - attemptStarted), http_status: httpStatus,
        final_url_sha256: urlSha256(page.url()), ...classification,
        error_category: classification.status === 'success' ? null : classification.response_class,
      };
      appendJsonl(eventsPath, event);
      const hadControl = (controlHits.get(url) ?? false) || CONTROL_CLASSES.has(classification.response_class);
      controlHits.set(url, hadControl);
      const retryable = classification.status !== 'success'
        && !(httpStatus !== null && httpStatus >= 400 && httpStatus < 500 && httpStatus !== 429
          && !CONTROL_CLASSES.has(classification.response_class))
        && attempt < maxAttempts
        && !deadlineReached;
      if (retryable) throw new Error(`retry:${classification.response_class}`);
      const result: FinalResult = {
        schema_version: '1.0', candidate: 'candidate-b', url, url_sha256: urlSha256(url),
        input_post_id: extractInputPostId(url), observed_post_id: classification.observed_post_id,
        post_id_matches: classification.post_id_matches, title_present: classification.title_present,
        body_present: classification.body_present, response_class: classification.response_class,
        control_hit: hadControl, channel: 'browser-dom', status: classification.status,
        request_count: attempt, started_at: timing.iso, ended_at: utcNow(),
        duration_ms: Math.round(performance.now() - timing.perf), http_status: httpStatus,
        error_category: event.error_category,
      };
      appendJsonl(resultsPath, result);
      finalized.add(url);
      process.stdout.write(`${JSON.stringify({ url_sha256: result.url_sha256, status: result.status })}\n`);
    },
    errorHandler: async ({ request }, error) => {
      const url = request.url;
      if (String(error.message).startsWith('retry:')) return;
      const event: Attempt = {
        schema_version: '1.0', candidate: 'candidate-b', url, url_sha256: urlSha256(url),
        attempt: request.retryCount + 1, channel: 'browser-dom', started_at: utcNow(), ended_at: utcNow(),
        duration_ms: 0, http_status: null, final_url_sha256: null, observed_post_id: null,
        post_id_matches: false, title_present: false, body_present: false, response_class: 'error',
        status: 'failed', error_category: error.name || 'network_error',
      };
      appendJsonl(eventsPath, event);
    },
    failedRequestHandler: async ({ request }) => {
      if (finalized.has(request.url)) return;
      const timing = startedByUrl.get(request.url) ?? { iso: utcNow(), perf: performance.now() };
      const result = failedResult(
        request.url,
        request.retryCount + 1,
        deadlineReached ? 'deadline_interrupted' : 'network_error',
        timing.iso,
        Math.round(performance.now() - timing.perf),
      );
      result.control_hit = controlHits.get(request.url) ?? false;
      appendJsonl(resultsPath, result);
      finalized.add(request.url);
    },
  });

  const remainingWindowMs = Math.max(0, config.window_seconds * 1_000 - (performance.now() - runStarted));
  if (remainingWindowMs === 0) deadlineReached = true;
  const deadlineTimer = setTimeout(() => {
    deadlineReached = true;
    void crawler.teardown();
  }, remainingWindowMs);
  try {
    await crawler.run(requests);
  } catch (error) {
    if (!deadlineReached) throw error;
  } finally {
    clearTimeout(deadlineTimer);
  }

  for (const url of urls) {
    if (finalized.has(url)) continue;
    appendJsonl(resultsPath, failedResult(url, 0, 'deadline_not_started'));
    finalized.add(url);
  }

  return 0;
}

const exitCode = await main();
process.exitCode = exitCode;
process.stdout.write(`runner_complete=candidate-b;exit_code=${exitCode}\n`, () => process.exit(exitCode));
