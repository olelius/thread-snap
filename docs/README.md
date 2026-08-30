# ThreadSnap 文档索引

## 1. 目的

本文件是 ThreadSnap 项目文档的统一入口，用于让新的开发任务、Codex 对话和人工维护者快速找到当前有效规范。

仓库文档不会全部自动加载到每个对话上下文。进入项目后应先遵循根目录 `AGENTS.md` 的强制读取顺序，再根据任务类型读取本索引中的相关文件。

## 2. 项目事实来源

不同类型的事实由不同文件负责：

| 事实类型 | 主要来源 |
|---|---|
| 长期项目规则、Git 工作流 | `AGENTS.md` |
| 统一领域术语 | `CONTEXT.md` |
| 功能范围、业务规则、验收条件 | `docs/design/product-design.md` |
| 已确认技术边界、候选方案和部署规则 | `docs/design/technical-route.md` |
| 已接受的具体架构决策 | `docs/adr/` |
| 当前活动任务、验证证据、下一步、用户待裁决项 | `WORKLOG.md` |
| 跨任务工作线的当前口径和决策链 | `docs/chains/` |
| 流程控制、验证阶梯和 Agent 回执 | `docs/process/` |
| 已证实的可复用根因、坑和杠杆 | `docs/memories/` |
| 已冻结且确有保留价值的历史记录 | `docs/project-notes/` |
| 采集框架 PoC 样本、阶段、指标和结果格式 | `docs/research/collector-stack-poc-plan.md` |
| 汽车之家与易车接入样本、阶段、指标和结果格式 | `docs/research/later-platform-onboarding-plan.md` |
| 舆情反馈 PoC 样本、模态覆盖、失败边界和结果格式 | `docs/research/sentiment-analysis-poc-plan.md` |
| 舆情反馈 PoC 的真实 URL、模型用量和结构结果 | `docs/research/sentiment-analysis-poc-results.md` |
| 圈子页面证据、成果合成、分片和资源门禁 PoC | `docs/research/circle-screenshot-poc-plan.md` |
| 圈子页面证据与关联截图成果 PoC 的事实结果 | `docs/research/circle-screenshot-poc-results.md` |
| 第一版后端安装、配置、启动和验证 | `docs/deployment/backend-v1.md` |
| 第一版前端安装、开发、构建和同源发布 | `docs/deployment/frontend-v1.md` |
| 第一版 Linux 离线制包、目录、安装、验证、备份和回滚 | `docs/deployment/linux-v1.md` |
| 已接收 PoC 输入的数量、环境摘要和哈希 | `docs/research/poc-input-intake-2026-08-08.md` |
| 通用技术背景与方案比较 | `docs/research/collection-and-antibot-landscape.md` |
| 甲方输入模板 | `docs/templates/poc/` |

当前分支的 Git 状态和上述仓库文件优先于历史对话、全局记忆、旧提交说明或单独的口头总结。

## 3. 任务读取矩阵

### 3.1 查询当前进度或下一步

必须读取：

1. 当前 Git 状态；
2. `AGENTS.md`；
3. `WORKLOG.md` 最新条目；
4. `docs/design/product-design.md`。

### 3.2 需求、功能或验收设计

必须读取：

1. `CONTEXT.md`；
2. `docs/design/product-design.md`；
3. `WORKLOG.md` 最新条目；
4. 与变更相关的已接受 ADR。

### 3.3 技术设计、实现、重构或部署

必须读取：

1. `CONTEXT.md`；
2. `docs/design/product-design.md`；
3. `docs/design/technical-route.md`；
4. `WORKLOG.md` 最新条目；
5. 与实现范围相关的已接受 ADR。

触及跨任务工作线时，还必须读取 `docs/chains/` 中对应链档。

### 3.4 PoC、平台采集器或性能测试

必须读取：

1. 技术实现任务要求的全部文件；
2. `docs/chains/first-platform-delivery.md`；
3. `docs/research/collector-stack-poc-plan.md`；
4. `docs/templates/poc/README.md`；
5. 甲方已填写并保存在本地 `artifacts/poc/inputs/` 的真实清单。

`docs/research/collection-and-antibot-landscape.md`用于了解候选技术背景，不直接替代 PoC 计划和已接受决策。

### 3.4.1 汽车之家或易车接入验证

必须读取：

1. 技术实现任务要求的全部文件；
2. `docs/chains/later-platform-delivery.md`；
3. `docs/research/later-platform-onboarding-plan.md`；
4. `docs/adr/0043-use-project-discovered-500-sample-gate-for-later-platforms.md`、`docs/adr/0044-separate-local-adapter-publication-from-formal-sample-acceptance.md` 与 `docs/adr/0045-preserve-cross-forum-feed-items.md`；
5. 涉及口碑映射时额外读取 `docs/chains/reputation-inspection.md`；
6. Git外 `artifacts/poc/inputs/later-platforms/` 中当次真实来源与冻结样本。

首平台的 `docs/templates/poc/` 和2000条外部输入合同不直接套用于后续两个平台；后续平台由项目从社区页面分别生成500条冻结样本与功能子集。

### 3.5 舆情反馈设计、PoC 或实现

必须读取：

1. 技术实现任务要求的全部文件；
2. `docs/chains/sentiment-analysis.md`；
3. `docs/adr/0022-use-hosted-multimodal-api-for-sentiment-feedback.md`；
4. `docs/adr/0023-use-validated-runtime-config-for-sentiment-service.md`；
5. `docs/adr/0025-add-deepseek-cloud-text-sentiment-option.md`；
6. `docs/adr/0027-use-bounded-clean-correction-and-structural-recovery.md`；
7. `docs/research/sentiment-analysis-poc-plan.md`；
8. `docs/adr/0038-freeze-ai-and-screenshot-options-per-batch.md`；
9. 执行 PoC 时读取 Git 外的 `artifacts/poc/inputs/sentiment-analysis/` 真实样本。

### 3.6 圈子页面证据与关联截图成果设计、PoC 或实现

必须读取：

1. 技术实现任务要求的全部文件；
2. `docs/chains/circle-screenshot-artifacts.md`；
3. `docs/chains/first-platform-delivery.md`；
4. `docs/chains/sentiment-analysis.md`；
5. `docs/adr/0026-use-synchronized-page-evidence-and-related-screenshot-artifacts.md`；
6. `docs/adr/0031-render-negative-artifacts-on-full-page-evidence.md`；
7. `docs/adr/0038-freeze-ai-and-screenshot-options-per-batch.md`；
8. `docs/research/circle-screenshot-poc-plan.md`；
9. `docs/research/circle-screenshot-poc-results.md`；
10. 执行 PoC 时读取 Git 外的 `artifacts/poc/inputs/circle-screenshot/` 真实样本。

### 3.7 垂媒口碑巡检设计、PoC 或实现

必须读取：

1. 需求、功能或技术任务要求的全部文件；
2. `docs/chains/reputation-inspection.md`；
3. `docs/adr/0032-separate-reputation-inspection-from-post-extraction.md`；
4. `docs/adr/0033-preserve-full-reputation-page-and-derived-metric-region.md`；
5. `docs/adr/0034-use-quarantined-two-phase-deletion-for-reputation-batches.md`；
6. `docs/adr/0035-prioritize-official-reputation-runs-without-preemption.md`；
7. `docs/adr/0036-isolate-synthetic-reputation-test-runs.md`；
8. `docs/adr/0037-retain-only-reputation-metric-region-evidence.md`；
9. `docs/adr/0039-use-score-page-review-article-count.md`；
10. 执行平台适配或页面证据 PoC 时读取该工作线约定的 Git 外真实样本。

## 4. 已接受 ADR

| ADR | 决策 |
|---|---|
| `docs/adr/0001-extraction-service-owns-extraction-data.md` | 提取功能服务持续拥有提取领域数据 |
| `docs/adr/0002-plaintext-platform-credentials-for-internal-validation.md` | 已被 ADR 0007 替代的历史明文凭证决策 |
| `docs/adr/0003-package-poc-for-linux-before-formal-development.md` | 已被 ADR 0011 替代的历史开发前置门禁 |
| `docs/adr/0004-treat-platform-controls-as-poc-outcome-gate.md` | 平台风控影响按 PoC 结果门禁判定 |
| `docs/adr/0005-adopt-forged-in-prod-workflow-control.md` | 采用 forged-in-prod 方法并按 Codex 能力建立唯一账本和流程门禁 |
| `docs/adr/0006-split-collector-access-poc-from-v1-functional-acceptance.md` | 当前先执行采集框架访问 PoC，第一版完整功能仍在后续开发与验收 |
| `docs/adr/0007-official-login-and-encrypted-platform-session.md` | 不保存平台账号密码，通过官方页面建立加密 Session，并优先有界自动刷新 |
| `docs/adr/0008-v1-backend-exposes-frontend-and-integration-apis.md` | 第一版独立后端同时提供前端 API 和稳定集成 API，后续现有后端直接复用集成接口 |
| `docs/adr/0009-global-scheduler-and-platform-fifo.md` | 一个全局调度源创建批次，执行时按平台严格 FIFO 隔离认证阻塞 |
| `docs/adr/0010-versioned-tag-driven-xlsx-templates.md` | 多模板使用不可变版本和稳定英文标签驱动 XLSX 导出 |
| `docs/adr/0011-adopt-python-backend-before-deferred-linux-gate.md` | 采用 Python 第一版后端，CentOS 三轮暂缓但保留为最终部署门禁 |
| `docs/adr/0012-reuse-vite-shadcn-admin-ui-baseline.md` | 第一版采用 Vite React 技术栈并选择性复用 shadcn-admin UI 基线 |
| `docs/adr/0013-separate-schedule-nodes-from-extraction-rules.md` | 每周计划节点只引用可复用自动提取规则，各配置页面保持唯一编辑归属 |
| `docs/adr/0014-use-controlled-cdp-screencast-for-auth.md` | 第一版平台人工认证使用后端封装的 CDP Screencast 和完整指针输入，不暴露原始 CDP 入口 |
| `docs/adr/0015-select-explicit-circles-per-extraction-rule.md` | 自动提取规则明确多选平台圈子，新来源不自动扩张旧规则范围 |
| `docs/adr/0016-merge-multiple-rules-per-schedule-node.md` | 同一计划节点可选择多条规则，触发时合并为一个批次并按圈子取最大目标数 |
| `docs/adr/0017-package-v1-as-fully-offline-systemd-nginx-release.md` | 第一版采用完整离线包、systemd、显示服务与 Nginx 部署 |
| `docs/adr/0018-use-headless-wayland-on-centos-stream-10.md` | CentOS Stream 10 使用 Weston 无头 Wayland 运行完整 Chromium |
| `docs/adr/0019-distinguish-circle-feed-sources-and-live-baselines.md` | 同圈最新回复/最新发布作为独立来源，清洁配置草稿跟随服务器版本 |
| `docs/adr/0020-use-short-source-keys-in-xlsx-tags.md` | 历史方案：XLSX 模板使用 22 位可逆来源键（已由 ADR 0021 替代） |
| `docs/adr/0021-persist-platform-neutral-export-keys.md` | XLSX 模板使用全平台统一的 10 位持久化来源键 |
| `docs/adr/0022-use-hosted-multimodal-api-for-sentiment-feedback.md` | 舆情反馈使用在线多模态 API、URL 直传和异步持久任务 |
| `docs/adr/0023-use-validated-runtime-config-for-sentiment-service.md` | 舆情模型服务使用加密、显式测试且受控端点的运行时配置 |
| `docs/adr/0024-add-local-text-sentiment-option.md` | 舆情反馈增加随离线包部署的 PaddleNLP 本地轻量文字选项 |
| `docs/adr/0025-add-deepseek-cloud-text-sentiment-option.md` | 舆情反馈增加独立凭证的 DeepSeek 云端纯文字选项 |
| `docs/adr/0026-use-synchronized-page-evidence-and-related-screenshot-artifacts.md` | 用同一冻结页面清单生成原始证据，并按关联圈子成果组合成版本化截图成果 |
| `docs/adr/0027-use-bounded-clean-correction-and-structural-recovery.md` | 云端舆情使用干净纠正上下文，并只恢复可唯一证明的单括号结构错误 |
| `docs/adr/0031-render-negative-artifacts-on-full-page-evidence.md` | 关联截图在完整原始页面副本上沿用负面框选，不再裁片拼接 |
| `docs/adr/0032-separate-reputation-inspection-from-post-extraction.md` | 垂媒口碑巡检使用独立业务模块和批次，不作为帖子提取批次的附属结果 |
| `docs/adr/0033-preserve-full-reputation-page-and-derived-metric-region.md` | 已被 ADR 0037 替代的历史双截图证据方案 |
| `docs/adr/0034-use-quarantined-two-phase-deletion-for-reputation-batches.md` | 口碑巡检批次使用删除清单、同盘隔离区和数据库提交边界完成可恢复删除 |
| `docs/adr/0035-prioritize-official-reputation-runs-without-preemption.md` | 每日正式口碑巡检在平台容量队列中非抢占优先，补跑和其他任务保持普通FIFO |
| `docs/adr/0036-isolate-synthetic-reputation-test-runs.md` | 手动合成口碑运行只存在于隔离测试环境，复用正式处理链但不污染正式批次、基线或调度 |
| `docs/adr/0037-retain-only-reputation-metric-region-evidence.md` | 口碑巡检在稳定DOM边界上只保留一张指标区域PNG，并由前端、XLSX和证据包复用 |
| `docs/adr/0038-freeze-ai-and-screenshot-options-per-batch.md` | AI 分析与圈子页面截图按规则版本或手动批次冻结，原始页面捕获不注入改像素 CSS |
| `docs/adr/0039-use-score-page-review-article-count.md` | 口碑第四指标读取评分页评价文章总数，清除并替代车型圈子帖子总量 |
| `docs/adr/0040-add-recurring-window-schedule-nodes.md` | 循环计划按同日时间段和分钟间隔触发，并使用独立循环批次类型复用既有页面能力 |
| `docs/adr/0041-separate-recurring-run-list-navigation.md` | 循环计划批次使用独立侧边栏和列表/详情路由，同时复用既有批次组件与业务能力 |
| `docs/adr/0042-allow-cross-type-same-second-schedules.md` | 每周与循环计划允许同秒创建独立批次，同类型仍保持触发点唯一并由运行期兜底 |
| `docs/adr/0043-use-project-discovered-500-sample-gate-for-later-platforms.md` | 汽车之家与易车各用项目从社区发现并冻结的500条样本完成新增适配器验收 |
| `docs/adr/0044-separate-local-adapter-publication-from-formal-sample-acceptance.md` | 分离本地适配器发布与正式样本验收，已交付平台注册为可用且默认停用 |
| `docs/adr/0045-preserve-cross-forum-feed-items.md` | 汽车之家圈子列表中的跨论坛聚合帖保留为来源快照结果，并分别保存发现来源与原始归属 |
| `docs/adr/0046-require-autohome-session-for-like-count.md` | 汽车之家帖子点赞数必须由登录会话证明，匿名占位零值不进入新快照 |
| `docs/adr/0047-use-account-login-and-direct-http-for-yiche.md` | 易车使用账号登录门禁和直连 HTTP 采集，三平台普通采集均不使用浏览器回退 |
| `docs/adr/0048-treat-primary-comments-as-nonblocking-post-enrichment.md` | 汽车之家与易车把一级评论作为非阻塞帖子附属快照，不再作为整帖有效性门禁 |
| `docs/adr/0049-unify-configurable-platform-internal-concurrency.md` | 三个已接入平台统一使用1～8的可配置内部总并发，默认值仍分别保留 |
| `docs/adr/0050-freeze-circle-candidates-without-replacement.md` | 圈子任务冻结来源前 N 个候选，网络错误只重试原 URL，不使用后续帖子补位 |
| `docs/adr/0051-separate-session-capture-from-collection-probe.md` | 平台人工认证只获取并保存 Session，真实圈子与帖子访问由采集任务在原 URL 判断 |

ADR 状态为 `accepted` 时对当前项目生效。后续改变决策时应新增 ADR 或明确记录替代关系，不直接删除历史决策依据。

## 5. PoC 模板和本地产物

### 5.1 进入 Git 的模板

- `docs/templates/poc/README.md`
- `docs/templates/poc/throughput-urls-template.txt`
- `docs/templates/poc/functional-samples-template.csv`
- `docs/templates/poc/threadsnap-poc-client-input-templates-v1.0.zip`

当前采集框架 PoC 只必需 `throughput-urls.txt`；`functional-samples.csv` 是后续第一版功能回归的可选基准，不是运行结果。

以上模板只适用于懂车帝首平台历史PoC。汽车之家与易车的500条验收清单和功能样本由项目按后续平台计划生成，不要求外部填写这些模板。

### 5.2 不进入 Git 的真实输入和产物

统一放在：

```text
artifacts/poc/
├── inputs/
├── packages/
└── results/
```

具体命名、保留期限和结果文件结构见 PoC 计划。

舆情反馈 PoC 使用 `inputs/sentiment-analysis/`、`results/sentiment-qwen3-5-omni-plus/<round-id>/` 和 `results/sentiment-qwen3-5-omni-plus-image-text/<round-id>/`；完整签名 URL、原始模型响应和 API 配置只保存在 Git 外本地产物中。

圈子页面截图 PoC 使用 `inputs/circle-screenshot/` 和 `results/circle-screenshot/<round-id>/`；原始全页图片、完整标注页、浏览器追踪和资源指标均保存在 Git 外；历史轮次的卡片裁剪与合成分片继续作为冻结证据保留。

## 6. 文档维护规则

- 动代码时更新 `WORKLOG.md` 最新条目；纯文档或只读任务不为凑流程追加账本。
- 修改功能范围或验收条件时，同步更新产品设计和相关链档。
- 修改技术决策时，同步更新技术路线、相关 ADR 和相关链档。
- 修改采集框架 PoC 阶段、指标、输入或结果结构时，同步更新采集 PoC 计划、模板说明和 `docs/chains/first-platform-delivery.md`。
- 修改汽车之家或易车接入阶段、可用状态、500条样本、输入责任、认证访问模式或结果结构时，同步更新后续平台接入计划、`docs/chains/later-platform-delivery.md`、ADR 0043、ADR 0044、ADR 0045、ADR 0046 和 ADR 0047；涉及口碑映射或指标时同时核对 `docs/chains/reputation-inspection.md`。
- 修改舆情反馈 PoC 阶段、输入、模态覆盖或结果结构时，同步更新舆情 PoC 计划和 `docs/chains/sentiment-analysis.md`。
- 修改圈子页面证据、关联成果合成、分片或资源门禁时，同步更新截图 PoC 计划和 `docs/chains/circle-screenshot-artifacts.md`，并核对首个平台与舆情工作线。
- 修改垂媒口碑巡检范围、阶段门、比较、证据或汇报规则时，同步更新 `docs/chains/reputation-inspection.md`。
- 详细执行过程和长日志写入被忽略的 `artifacts/runtime/`，账本只保留恢复所需证据入口。
- 调研结论成为正式决策前，必须经过真实样本或环境验证并写入技术路线或 ADR。
- 项目记忆只记录已发生、可复用的根因、坑和杠杆，不记录普通提交历史。
- 发现文档冲突时，先修正唯一 owner 文档并记录取舍，再开始或继续实现。

## 7. 新任务启动检查

开始新任务前确认：

1. 工作目录为正确的 ThreadSnap 仓库；
2. 当前分支、远程同步状态和工作区修改已检查；
3. 已读取 `AGENTS.md` 和 `WORKLOG.md` 最新条目；
4. 已按任务读取矩阵加载 owner 文档和相关链档；
5. 未确认的平台接口、字段、访问条件和性能结论仍标记为待验证；
6. 已确定当前阶段门、关键路径、写 owner 和验证路径，再判断是否需要并行；
7. 本次代码修改会同步更新账本，对应口径修改会同步更新唯一 owner 文档；
8. PoC 原始输入、测试包和结果仍位于 `artifacts/poc/`，runtime 证据仍位于 `artifacts/runtime/`，没有进入 Git。
