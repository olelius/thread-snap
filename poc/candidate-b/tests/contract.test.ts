import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { classifyDocument, extractInputPostId } from '../src/contract.js';

interface Case {
  name: string;
  final_url: string;
  http_status: number;
  input_post_id: string;
  document: string;
  expected_response_class: string;
  expected_status: string;
}

const here = dirname(fileURLToPath(import.meta.url));
const cases = JSON.parse(
  readFileSync(resolve(here, '../../shared/classification-cases.json'), 'utf8'),
) as Case[];

describe('统一响应分类', () => {
  it('支持两种真实帖子路径', () => {
    const postId = '1234567890123456789';
    expect(extractInputPostId(`https://TARGET/article/${postId}`)).toBe(postId);
    expect(extractInputPostId(`https://TARGET/ugc/article/${postId}`)).toBe(postId);
  });

  for (const item of cases) {
    it(item.name, () => {
      const actual = classifyDocument(item.final_url, item.http_status, item.document, item.input_post_id);
      expect(actual.response_class).toBe(item.expected_response_class);
      expect(actual.status).toBe(item.expected_status);
      if (actual.response_class !== 'post') expect(actual.post_id_matches).toBe(false);
    });
  }
});
