import { describe, expect, it } from 'vitest';
import {
  executeRecoveryControl,
  type HttpResult,
  type SegmentOutcome,
} from '../src/bounded-session-recovery.js';
import { urlSha256 } from '../src/contract.js';

function result(url: string, responseClass: HttpResult['response_class'] = 'post'): HttpResult {
  const success = responseClass === 'post';
  const id = url.split('/').at(-1)!;
  return {
    schema_version: '1.0', candidate: 'candidate-b', url, url_sha256: urlSha256(url), input_post_id: id,
    observed_post_id: success ? id : null, post_id_matches: success, title_present: success, body_present: success,
    response_class: responseClass, control_hit: !success, channel: 'http', status: success ? 'success' : 'blocked',
    request_count: 1, started_at: new Date(0).toISOString(), ended_at: new Date(0).toISOString(),
    duration_ms: 1, http_status: 200, error_category: success ? null : responseClass,
    session_ordinal: 1, segment_kind: 'bulk',
  };
}

function segment(results: HttpResult[], pauseReason: SegmentOutcome['pause_reason'] = null): SegmentOutcome {
  return {
    results, events: [], pause_reason: pauseReason, remaining_count: 0, duration_ms: 1,
    cookie_metadata: { storage_cookie_count: 2, usable_cookie_count: 2 },
  };
}

const gates = [
  'https://TARGET/ugc/article/1000000000000000001',
  'https://TARGET/ugc/article/1000000000000000002',
  'https://TARGET/ugc/article/1000000000000000003',
];

describe('Candidate B 有界 Session 恢复', () => {
  it('新会话通过门禁后重新处理触发 URL，并继续剩余队列', async () => {
    const urls = [
      'https://TARGET/ugc/article/2000000000000000001',
      'https://TARGET/ugc/article/2000000000000000002',
      'https://TARGET/ugc/article/2000000000000000003',
    ];
    let bulkCalls = 0;
    const outcome = await executeRecoveryControl({
      urls, gates, maxRecoveries: 2, deadline: performance.now() + 10_000, initialStorageState: 'initial.json',
      obtainSession: async (ordinal) => ({ success: true, storageState: `session-${ordinal}.json` }),
      executeSegment: async (requested, _state, ordinal, kind) => {
        if (kind === 'gate') return segment(requested.map((url) => result(url)));
        bulkCalls += 1;
        if (bulkCalls === 1) return segment([result(requested[0]!), result(requested[1]!, 'login')], 'login');
        expect(ordinal).toBe(2);
        expect(requested[0]).toBe(urls[1]);
        return segment(requested.map((url) => result(url)));
      },
    });
    expect(outcome.finalResults.map((item) => item.url)).toEqual(urls);
    expect(outcome.stopReason).toBeNull();
    expect(outcome.recoveryEvents.some((event) => event.event === 'session_refresh' && event['trigger_recovered'] === true)).toBe(true);
  });

  it('验证码为不可恢复控制，立即停止且不新建会话', async () => {
    const urls = ['https://TARGET/ugc/article/3000000000000000001'];
    let refreshes = 0;
    const outcome = await executeRecoveryControl({
      urls, gates, maxRecoveries: 2, deadline: performance.now() + 10_000, initialStorageState: 'initial.json',
      obtainSession: async () => { refreshes += 1; return { success: true, storageState: 'unused.json' }; },
      executeSegment: async (requested, _state, _ordinal, kind) => kind === 'gate'
        ? segment(requested.map((url) => result(url)))
        : segment([result(requested[0]!, 'captcha')], 'captcha'),
    });
    expect(outcome.stopReason).toBe('captcha');
    expect(outcome.finalResults[0]?.response_class).toBe('captcha');
    expect(refreshes).toBe(0);
  });

  it('恢复额度耗尽后保留控制结果并停止', async () => {
    const urls = ['https://TARGET/ugc/article/4000000000000000001'];
    const outcome = await executeRecoveryControl({
      urls, gates, maxRecoveries: 0, deadline: performance.now() + 10_000, initialStorageState: 'initial.json',
      obtainSession: async () => ({ success: true, storageState: 'unused.json' }),
      executeSegment: async (requested, _state, _ordinal, kind) => kind === 'gate'
        ? segment(requested.map((url) => result(url)))
        : segment([result(requested[0]!, 'empty')], 'empty'),
    });
    expect(outcome.stopReason).toBe('max_recoveries_exhausted');
    expect(outcome.remainingCount).toBe(0);
  });
});
