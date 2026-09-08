import type { ReputationCapabilities, ReputationResult } from '@/lib/types'

export type ReputationMetricKey = keyof ReputationResult['metrics']

const labels: Record<ReputationMetricKey, string> = {
  score: '口碑分', rank: '排名', volume: '口碑量',
  review_article_count: '评价篇数', negative_rate: '差评率', circle_content_count: '圈内内容数',
}
const coreMetrics: ReputationMetricKey[] = ['score', 'rank', 'volume', 'review_article_count', 'negative_rate']

/** 以服务端平台注册能力构造列组；未知能力不凭平台名称猜测新增指标。 */
export function reputationMetricColumns(platformCode: string, capabilities?: Pick<ReputationCapabilities, 'reputation_platforms'>): Array<[ReputationMetricKey, string]> {
  const keys = capabilities?.reputation_platforms.find((platform) => platform.code === platformCode)?.supported_metrics ?? coreMetrics
  return keys.filter((key): key is ReputationMetricKey => Object.prototype.hasOwnProperty.call(labels, key)).map((key) => [key, platformCode === 'autohome' && key === 'circle_content_count' ? '论坛帖子总数' : labels[key]])
}
