import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { classifyDocument } from '../src/contract.js';

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
  for (const item of cases) {
    it(item.name, () => {
      const actual = classifyDocument(item.final_url, item.http_status, item.document, item.input_post_id);
      expect(actual.response_class).toBe(item.expected_response_class);
      expect(actual.status).toBe(item.expected_status);
      if (actual.response_class !== 'post') expect(actual.post_id_matches).toBe(false);
    });
  }
});
