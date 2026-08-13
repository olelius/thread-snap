---
status: accepted
supersedes: 0003-package-poc-for-linux-before-formal-development.md
---

# 在暂缓 Linux 三轮门禁期间采用 Python 后端技术栈

原 ADR 0003 把目标 Linux 三轮 2000 条门禁设为正式业务开发前置条件。2026-08-14，用户明确要求先完成第一版后端，并暂时不处理 CentOS 三轮门禁。与此同时，懂车帝动态圈子列表、分页终止、最新回复顺序、固定 2000 条有效样本、字段级 HTTP API 和 Windows 真实端到端链路已经形成可复核证据。

## Decision

- 第一版提取后端采用 Python 3.11+、FastAPI、SQLAlchemy 2、Alembic、Scrapling/curl_cffi、Patchright、openpyxl 和 cryptography。
- 第一版单进程部署使用 SQLite、一个全局调度线程和一个持久平台 FIFO Worker；业务表与迁移契约不依赖 SQLite 私有 JSON 类型，后续确有多进程或多实例需要时再评审 PostgreSQL 和外部队列。
- `/api/v1` 与 `/internal/v1` 位于同一后端并共用应用层；集成接口增加回环地址限制，不引入第二个业务后端。
- 懂车帝列表采用直接 HTTP 优先，SSR 条目不足时才使用服务器浏览器补全；详情和最多十条一级评论使用结构化 HTTP JSON 接口。
- 服务端 Session 加密持久化，认证异常先对既有 Session 有界刷新一次；仍需人工操作时进入 `waiting_for_auth`，认证状态通过真实圈子样本校验后再恢复对应平台队列。
- 目标 CentOS 的连续三轮 2000 条门禁暂缓，不再阻塞本次后端编码和 Windows 验证；它仍是最终 Linux 部署、依赖兼容、进程管理和性能验收门禁，当前结果不得表述为已通过该门禁。

## Evidence used for the provisional selection

- 圈子 `24729` 已验证 42 页、1259 个唯一动态候选，页 43 为空，跨页顺序符合最新回复；本地清单 SHA-256 为 `81acb993abf36d8ef19e6c9464d1f5dbab03b3bf84cfe778b4393ae64876d0d1`。
- 事前固定 2000 条有效样本的 URL 清单 SHA-256 为 `24f921036677c8d1ce933a81ec10d15a700c765fccf3401121a99787f0f9f21e`。
- 正式采集器对同一圈子取得 30/30 条有效结果、0 失败，运行摘要 SHA-256 为 `87c10faa23e1a9043015581c56215a917d98ac56c6ca10f4877e64bdca5c44ae`。
- 数据库迁移、双接口、圈子验证、真实提取、结果查询、模板上传和 XLSX 下载的端到端摘要 SHA-256 为 `c256ba7aa13fa8862d749459b34ed0f1fdccd497589908e10a670fb9a3077510`。

## Consequences

- 后端可以按已确认产品契约交付和供前端联调，不再维持“语言、数据库和 Worker 组件未确认”的冲突状态。
- SQLite 选择只覆盖第一版单进程内部验证，不证明未来多平台并行、多进程 Worker 或高可用部署能力。
- CentOS 三轮门禁、Linux 浏览器依赖、服务管理和离线安装包仍需后续独立完成；失败时必须修复正式后端或部署方案，不能用 Windows 结果覆盖。
- ADR 0003 的打包、凭证隔离和 Linux 证据规则继续有效；仅“必须在正式编码前通过”的时间顺序被本 ADR 替代。
