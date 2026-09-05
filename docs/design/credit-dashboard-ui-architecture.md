# Credit Dashboard UI 架构

## 当前交付

本设计以单张 PNG 为视觉输入，已经建立一套可编辑 Figma 组件库和与其对应的 React 模板。设计稿与代码是两个可独立演进的层：Figma 负责视觉 Token、变体和交接；React 负责数据、状态、请求和可测试渲染。

- Figma 文件：[Credit Score Dashboard — Reconstructed UI](https://www.figma.com/design/rucryRxzxcU0w8XJgSeNAD)
- Figma 页面：`Credit Dashboard`、`Foundations`、`Components`、`Templates`、`Notes / Assumptions`
- 参考构图：`Credit Score Dashboard — Reference Composition`
- 组件模板：`Templates / Credit Score Dashboard`
- 前端目录：`frontend/src/features/credit-dashboard/`
- 字体资产：`frontend/public/fonts/dm-sans/DMSans-Variable.ttf`，许可证副本为同目录 `OFL.txt`

## 组件映射

| Figma 组件 | 代码组件 | 数据/事件入口 |
| --- | --- | --- |
| `SideRail` | `CreditDashboardTemplate` 内 Shell 区域 | 页面路由与导航事件 |
| `TopBar` | `CreditDashboardTemplate` 内 TopBar 区域 | 用户信息与通知事件 |
| `TabPill` | `CreditScoreTabs` | `CreditScoreTab` + `onQueryChange` |
| `SearchField` | `CreditSearchField` | `query.search` |
| `ScoreCard` | `CreditScoreCard` | `CreditScoreSummary` |
| `MetricCard` | `CreditMetricCard` | `CreditMetric[]` |
| `SectionHeader` | `CreditSectionHeader` | 标题、计数、Counters |
| `RecentChangeRow` | `CreditRecentChangeRow` | `CreditChange[]` |
| `CreditCard` | `CreditAccountRow` | `CreditAccount[]` |

Figma 组件的文本、布尔和 Variant 属性已经建立；`MetricCard` 另外提供 `Icon` INSTANCE_SWAP。页面模板使用组件实例而非图片层。

## 前端接口

核心契约位于 `credit-dashboard.types.ts`：

```ts
interface CreditDashboardDataSource {
  getDashboard(query?: CreditDashboardQuery, signal?: AbortSignal): Promise<CreditDashboardData>
}
```

真实接口适配器位于 `credit-dashboard.api.ts`，默认请求：

```text
GET /api/v1/credit-dashboard?tab=transaction_score&search=...
```

当前 ThreadSnap 后端没有信用评分业务端点，因此页面默认使用 `createMockCreditDashboardDataSource()`；接入真实业务时只替换 `dataSource`，组件层保持不变。

## 页面使用

```tsx
import {
  CreditDashboardPage,
  createCreditDashboardDataSource,
} from '@/features/credit-dashboard'

export function CreditDashboardRoute() {
  return <CreditDashboardPage dataSource={createCreditDashboardDataSource('/credit-dashboard')} />
}
```

快速演示可以省略 `dataSource`，页面会显示本地 Mock 数据并保留搜索、Tab、筛选、加载和错误状态。

## 验收边界

- Figma 画板和前端模板保持同一组件命名、Token 命名和数据字段语义。
- Figma 组件库用于设计交接；前端模板用于真实数据接入，不把 PNG 当作运行时资源。
- 生产接入前仍需由业务 owner 确认真实 API 字段、权限、空值规则和响应式断点。
