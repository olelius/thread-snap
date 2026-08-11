import { describe, expect, it } from 'vitest';
import { buildSummary, type FinalResult } from '../src/http-throughput.js';
import { urlSha256 } from '../src/contract.js';

function result(url: string, status: FinalResult['status'], responseClass: FinalResult['response_class']): FinalResult {
  const postId = url.split('/').at(-1)!;
  const success = status === 'success';
  return {
    schema_version: '1.0',
    candidate: 'candidate-b',
    url,
    url_sha256: urlSha256(url),
    input_post_id: postId,
    observed_post_id: success ? postId : null,
    post_id_matches: success,
    title_present: success,
    body_present: success,
    response_class: responseClass,
    control_hit: false,
    channel: 'http',
    status,
    request_count: 1,
    started_at: new Date(0).toISOString(),
    ended_at: new Date(0).toISOString(),
    duration_ms: 100,
    http_status: 200,
    error_category: success ? null : responseClass,
  };
}

describe('纯 HTTP 批量摘要', () => {
  it('只按有效结果计算速度并记录首次控制', () => {
    const first = result('https://TARGET/ugc/article/1111111111111111111', 'success', 'post');
    const second = result('https://TARGET/ugc/article/2222222222222222222', 'failed', 'empty');
    const summary = buildSummary(
      [first, second],
      new Map([[first.url, 100], [second.url, 250]]),
      1000,
      1,
    );
    expect(summary.success_count).toBe(1);
    expect(summary.effective_urls_per_second).toBe(1);
    expect(summary.first_control?.response_class).toBe('empty');
    expect(summary.meets_correctness_gate).toBe(false);
    expect(summary.direct_http_only).toBe(true);
  });
});
