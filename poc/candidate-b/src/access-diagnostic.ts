/** 为访问失败保存不含页面正文和 Cookie 值的结构化诊断。 */

import { createHash } from 'node:crypto';
import type { Cookie } from 'playwright';

export const ACCESS_DIAGNOSTIC_CLASSES = new Set(['login', 'empty']);
export const ACCESS_DIAGNOSTIC_LIMIT_PER_CLASS = 3;

const ACCESS_MARKERS = [
  ['login_required', 'login-required'],
  ['passport', 'passport'],
  ['captcha', 'captcha'],
  ['verify_center', 'verifycenter'],
  ['verification', '安全验证'],
  ['slider', '滑动验证'],
  ['operation_frequent', '操作频繁'],
  ['retry_later', '请稍后重试'],
  ['secsdk', 'secsdk'],
  ['acrawler', 'byted_acrawler'],
  ['ttwid', 'ttwid'],
] as const;

function sha256(value: string): string {
  return createHash('sha256').update(value).digest('hex');
}

export function finalUrlKind(url: string): 'login' | 'post' | 'other' {
  const path = new URL(url).pathname.toLowerCase();
  if (path.includes('/login')) return 'login';
  if (path.includes('/article/')) return 'post';
  return 'other';
}

export function summarizeDocumentResponse(url: string, status: number): Record<string, unknown> {
  return { status, target: finalUrlKind(url) };
}

function textLength(document: string): number {
  const withoutScripts = document.replace(/<(?:script|style)\b[^>]*>[\s\S]*?<\/(?:script|style)>/giu, ' ');
  return withoutScripts.replace(/<[^>]+>/gu, ' ').replace(/\s+/gu, ' ').trim().length;
}

export function buildAccessDiagnostic(options: {
  candidate: 'candidate-b';
  trigger: string;
  sequence: number;
  attempt: number;
  inputUrl: string;
  finalUrl: string;
  httpStatus: number | null;
  responseClass: string;
  document: string;
  cookies: Cookie[];
  cookieShapeAvailable: boolean;
  mainDocumentResponses: Array<Record<string, unknown>>;
}): Record<string, unknown> {
  const names = [...new Set(options.cookies.map((cookie) => cookie.name).filter(Boolean))].sort();
  const title = options.document.match(/<title\b[^>]*>([\s\S]*?)<\/title>/iu)?.[1]?.replace(/\s+/gu, ' ').trim() ?? '';
  const folded = options.document.toLocaleLowerCase();
  return {
    schema_version: '1.0',
    candidate: options.candidate,
    trigger: options.trigger,
    sequence: options.sequence,
    attempt: options.attempt,
    url_sha256: sha256(options.inputUrl),
    http_status: options.httpStatus,
    response_class: options.responseClass,
    final_url_kind: finalUrlKind(options.finalUrl),
    final_url_matches_input: options.finalUrl === options.inputUrl,
    document_length: options.document.length,
    document_sha256: sha256(options.document),
    body_text_length: textLength(options.document),
    title_length: title.length,
    script_count: options.document.match(/<script\b/giu)?.length ?? 0,
    iframe_count: options.document.match(/<iframe\b/giu)?.length ?? 0,
    form_count: options.document.match(/<form\b/giu)?.length ?? 0,
    marker_hits: ACCESS_MARKERS.filter(([, marker]) => folded.includes(marker.toLocaleLowerCase())).map(([name]) => name),
    main_document_responses: options.mainDocumentResponses.slice(0, 10),
    cookie_shape_available: options.cookieShapeAvailable,
    cookie_count: options.cookies.length,
    cookie_name_set_sha256: sha256(names.join('\n')),
  };
}
