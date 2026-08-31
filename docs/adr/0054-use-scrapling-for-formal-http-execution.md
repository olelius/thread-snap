---
status: accepted
---

# 正式普通 HTTP 请求统一由 Scrapling 执行

## Context

PoC 已用 Scrapling `Spider + FetcherSession` 证明认证 Session 交接、纯 HTTP 详情与评论
请求可行，正式后端也一直把 Scrapling 作为选定采集框架依赖。但三平台生产采集器与懂车帝
口碑差评率接口后来直接创建 `curl_cffi.requests.Session`，Scrapling 只留在 PoC 目录和依赖
清单。`direct_http` 被误读成“直接调用 curl-cffi”，实际它只表示后台不启动浏览器。

直接 Session 与框架 Session 并存造成 Cookie 作用域、线程生命周期、响应字段和重试语义各自
维护，也让技术路线所称的 Python/FastAPI/Scrapling 正式后端与运行代码不一致。另一方面，
ThreadSnap 已经拥有数据库批次、平台 FIFO、固定候选、持久退避、认证等待和不可变历史；把这些
再次迁入 Scrapling Spider 的进程内队列会产生第二套事实源。

## Decision

- 懂车帝、汽车之家、易车生产采集器以及懂车帝口碑适配器的全部普通 HTML/JSON 请求统一
  通过 Scrapling 0.4.12 `FetcherSession` 执行；正式 `src/threadsnap` 不再直接导入
  `curl_cffi`。
- 新增统一同步传输层，负责按线程创建 `FetcherSession`、从浏览器 storage state 按域名、
  路径、协议和有效期选择 Cookie、保留服务端 Set-Cookie，并把 Scrapling Response 适配为
  既有采集器的 `status_code/content/text/json/url/headers/history` 最小合同。
- `FetcherSession(retries=1)` 表示框架只执行一次请求；三次即时重试、持久网络退避、限流
  冷却和固定候选仍由现有适配器与 Worker 明确控制，避免框架隐藏重试扩大请求数。
- ThreadSnap 继续拥有批次创建、平台 FIFO、跨来源并发上限、候选冻结、检查点、认证等待、
  结果提交和历史持久化。Scrapling Spider 不接管这套领域调度；Scrapling 在正式运行时拥有
  HTTP Session、TLS/浏览器指纹传输、Cookie 注入、请求执行和响应对象。
- `direct_http` 传输标识保持不变，因为后台帖子采集仍不启动 Chromium。Patchright 继续只
  用于人工认证/CDP Screencast、Session 刷新和明确开启的页面/口碑截图证据；这些可交互或
  像素证据任务不改用 FetcherSession。
- Worker 在圈子任务池、来源验证、认证刷新后临时采集器结束时显式关闭全部线程 Session；
  口碑服务在正式巡检和映射验证结束时同样关闭传输资源。
- `curl-cffi==0.16.0` 暂时保留显式锁定，因为它仍是 Scrapling FetcherSession 的实际 TLS
  引擎和离线 wheelhouse 组成部分；保留依赖不表示业务代码直接调用它。

## Consequences

- 正式普通 HTTP 请求路径与既有 Scrapling 技术选型重新一致，四处直接 curl-cffi 入口收敛
  为一个可测试传输层；平台解析、业务错误分类、并发上限和数据库结构不变。
- 适配器版本升级为 `dongchedi-dynamic-v7-scrapling`、
  `autohome-club-v7-scrapling`、`yiche-community-v5-scrapling` 与
  `dongchedi-reputation-v9-scrapling`，使新批次能够追溯传输实现变化。
- Scrapling 进程内 Spider 的 URL 去重、优先队列、AutoThrottle 和 checkpoint 不成为生产
  批次事实；后续只有在不复制 ThreadSnap 持久状态、且能证明额外收益时才单独评审某个无
  业务状态的批内请求图。
- 本决策先在独立 worktree 和分支验证；未合入 `main` 前不代表当前生产服务已经切换。

## Rejected alternatives

- **继续直接使用 curl-cffi 并只在文档中称为 Scrapling**：运行时所有权与技术路线继续不一致。
- **把 ThreadSnap 批次、FIFO 和检查点整体交给 Spider**：会产生第二套队列与恢复事实，服务
  重启、认证等待和不可变批次边界都需要重写。
- **所有请求改成 Scrapling 动态浏览器**：普通详情/API 会启动额外 Chromium，改变已验证的
  纯 HTTP 吞吐和平台控制边界。
- **让 Scrapling 自动重试再叠加现有重试**：实际请求次数变得不可预测，并削弱限流止损证据。
