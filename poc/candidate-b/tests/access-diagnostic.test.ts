import { describe, expect, it } from 'vitest';
import { buildAccessDiagnostic } from '../src/access-diagnostic.js';

describe('访问失败脱敏诊断', () => {
  it('保留页面形态但不保存原始地址、正文或 Cookie', () => {
    const inputUrl = 'https://TARGET/ugc/article/1234567890123456789?private=query';
    const document = '<html><head><title>安全验证</title><script>byted_acrawler</script></head><body>滑动验证</body></html>';
    const diagnostic = buildAccessDiagnostic({
      candidate: 'candidate-b',
      trigger: 'first_empty',
      sequence: 1,
      attempt: 2,
      inputUrl,
      finalUrl: inputUrl,
      httpStatus: 200,
      responseClass: 'empty',
      document,
      cookies: [{
        name: 'session_name', value: 'secret-cookie-value', domain: 'TARGET', path: '/',
        expires: -1, httpOnly: true, secure: true, sameSite: 'Lax',
      }],
      cookieShapeAvailable: true,
      mainDocumentResponses: [{ status: 200, target: 'post' }],
    });
    const serialized = JSON.stringify(diagnostic);
    expect(diagnostic['final_url_kind']).toBe('post');
    expect(diagnostic['final_url_matches_input']).toBe(true);
    expect(diagnostic['cookie_count']).toBe(1);
    expect(diagnostic['marker_hits']).toEqual(expect.arrayContaining(['verification', 'slider', 'acrawler']));
    expect(serialized).not.toContain(inputUrl);
    expect(serialized).not.toContain(document);
    expect(serialized).not.toContain('session_name');
    expect(serialized).not.toContain('secret-cookie-value');
  });
});
