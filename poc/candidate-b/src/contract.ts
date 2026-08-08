import { createHash } from 'node:crypto';

export const CONTROL_CLASSES = new Set(['rate_limited', 'captcha', 'challenge', 'login']);

export type ResponseClass = 'post' | 'rate_limited' | 'captcha' | 'challenge' | 'login' | 'empty' | 'error';
export type ResultStatus = 'success' | 'partial' | 'failed' | 'blocked';

export interface Classification {
  observed_post_id: string | null;
  post_id_matches: boolean;
  title_present: boolean;
  body_present: boolean;
  response_class: ResponseClass;
  status: ResultStatus;
}

export function urlSha256(url: string): string {
  return createHash('sha256').update(url, 'utf8').digest('hex');
}

export function extractInputPostId(url: string): string {
  const match = new URL(url).pathname.match(/\/ugc\/article\/(\d+)(?:\/|$)/);
  if (!match?.[1]) throw new Error('URL 路径不符合 /ugc/article/<post-id> 结构');
  return match[1];
}

function visibleText(document: string): string {
  return document
    .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;|&#160;/gi, ' ')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&amp;/gi, '&')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/\s+/g, ' ')
    .trim();
}

export function classifyDocument(
  finalUrl: string,
  httpStatus: number | null,
  document: string,
  inputPostId: string,
): Classification {
  const lowered = document.toLowerCase();
  const finalLower = finalUrl.toLowerCase();
  const text = visibleText(document);
  const titleMatch = document.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  const title = titleMatch?.[1] ? visibleText(titleMatch[1]) : '';
  let responseClass: ResponseClass;

  if (httpStatus === 429 || lowered.includes('rate limit') || document.includes('请求过于频繁')) {
    responseClass = 'rate_limited';
  } else if (finalLower.includes('/login-required') || lowered.includes('login-required') || document.includes('请登录')) {
    responseClass = 'login';
  } else if (lowered.includes('captcha') || document.includes('验证码')) {
    responseClass = 'captcha';
  } else if (document.includes('_$jsvmprt') || lowered.includes('secsdk-captcha') || lowered.includes('challenge-platform')) {
    responseClass = 'challenge';
  } else if (httpStatus === null || httpStatus >= 400) {
    responseClass = 'error';
  } else if (!text) {
    responseClass = 'empty';
  } else {
    responseClass = 'post';
  }

  const titlePresent = Boolean(title) && responseClass === 'post';
  const bodyPresent = responseClass === 'post' && text.length >= 40;
  // 登录/挑战页可能在 redirect 参数中回显输入 ID；这不是平台帖子标识证据。
  const observedPostId = responseClass === 'post' && document.includes(inputPostId) ? inputPostId : null;
  const postIdMatches = observedPostId === inputPostId;
  let status: ResultStatus;
  if (responseClass === 'post' && postIdMatches && (titlePresent || bodyPresent)) status = 'success';
  else if (responseClass === 'post') status = 'partial';
  else if (CONTROL_CLASSES.has(responseClass)) status = 'blocked';
  else status = 'failed';

  return {
    observed_post_id: observedPostId,
    post_id_matches: postIdMatches,
    title_present: titlePresent,
    body_present: bodyPresent,
    response_class: responseClass,
    status,
  };
}
