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
| PoC 样本、阶段、指标和结果格式 | `docs/research/collector-stack-poc-plan.md` |
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

## 4. 已接受 ADR

| ADR | 决策 |
|---|---|
| `docs/adr/0001-extraction-service-owns-extraction-data.md` | 提取功能服务持续拥有提取领域数据 |
| `docs/adr/0002-plaintext-platform-credentials-for-internal-validation.md` | 已被 ADR 0007 替代的历史明文凭证决策 |
| `docs/adr/0003-package-poc-for-linux-before-formal-development.md` | 正式功能开发前完成 Linux PoC 打包与最终主机测试 |
| `docs/adr/0004-treat-platform-controls-as-poc-outcome-gate.md` | 平台风控影响按 PoC 结果门禁判定 |
| `docs/adr/0005-adopt-forged-in-prod-workflow-control.md` | 采用 forged-in-prod 方法并按 Codex 能力建立唯一账本和流程门禁 |
| `docs/adr/0006-split-collector-access-poc-from-v1-functional-acceptance.md` | 当前先执行采集框架访问 PoC，第一版完整功能仍在后续开发与验收 |
| `docs/adr/0007-official-login-and-encrypted-platform-session.md` | 不保存平台账号密码，通过官方页面建立加密 Session，并优先有界自动刷新 |
| `docs/adr/0008-v1-backend-exposes-frontend-and-integration-apis.md` | 第一版独立后端同时提供前端 API 和稳定集成 API，后续现有后端直接复用集成接口 |

ADR 状态为 `accepted` 时对当前项目生效。后续改变决策时应新增 ADR 或明确记录替代关系，不直接删除历史决策依据。

## 5. PoC 模板和本地产物

### 5.1 进入 Git 的模板

- `docs/templates/poc/README.md`
- `docs/templates/poc/throughput-urls-template.txt`
- `docs/templates/poc/functional-samples-template.csv`
- `docs/templates/poc/threadsnap-poc-client-input-templates-v1.0.zip`

当前采集框架 PoC 只必需 `throughput-urls.txt`；`functional-samples.csv` 是后续第一版功能回归的可选基准，不是运行结果。

### 5.2 不进入 Git 的真实输入和产物

统一放在：

```text
artifacts/poc/
├── inputs/
├── packages/
└── results/
```

具体命名、保留期限和结果文件结构见 PoC 计划。

## 6. 文档维护规则

- 动代码时更新 `WORKLOG.md` 最新条目；纯文档或只读任务不为凑流程追加账本。
- 修改功能范围或验收条件时，同步更新产品设计和相关链档。
- 修改技术决策时，同步更新技术路线、相关 ADR 和相关链档。
- 修改 PoC 阶段、指标、输入或结果结构时，同步更新 PoC 计划、模板说明和 `docs/chains/first-platform-delivery.md`。
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
