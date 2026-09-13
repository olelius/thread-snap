import assert from 'node:assert/strict'
import test from 'node:test'
import { reputationMetricColumns, reputationMetricLabel } from '../src/features/reputation/reputation-metrics.ts'

test('汽车之家改名但保留字段键和列序，包括旧能力缓存', () => {
  const expected = [['score', '口碑分'], ['rank', '排名'], ['volume', '在售'], ['review_article_count', '口碑量']]
  assert.deepEqual(reputationMetricColumns('autohome'), expected)
  const capabilities = { reputation_platforms: [{ code: 'autohome', supported_metrics: ['score', 'rank', 'volume', 'review_article_count', 'negative_rate', 'circle_content_count'] }] }
  assert.deepEqual(reputationMetricColumns('autohome', capabilities), [...expected, ['circle_content_count', '论坛帖子总数']])
})

test('懂车帝和易车继续使用各自的数量名称', () => {
  assert.equal(reputationMetricLabel('dongchedi', 'volume'), '口碑量')
  assert.equal(reputationMetricLabel('dongchedi', 'review_article_count'), '评价篇数')
  assert.equal(reputationMetricLabel('yiche', 'volume'), '参与人数')
  assert.equal(reputationMetricLabel('yiche', 'owner_review_count'), '车主点评')
})
