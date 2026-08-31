---
status: accepted
---

# 为平台控制增加按需 Scrapling Stealthy 通道

## Context

ADR 0054 已把三平台普通 HTML/JSON 请求统一到 Scrapling `FetcherSession`，但该类只提供
普通 HTTP、TLS 浏览器拟态与 Cookie Session；Scrapling 用于降低浏览器自动化检测的
`StealthySession`、指纹修补和 Cloudflare 处理并未进入正式路径。这与本工作树“利用
Scrapling 改善平台控制频率”的目标不一致。

另一方面，全部详情和 API 都改为浏览器会放弃已经验证的纯 HTTP 吞吐，并显著增加 Chromium
数量。汽车之家当前观测到的是平台自有 `userverify` 数字图片页面，易车当前观测到的是腾讯
验证码控制文档；它们不应被误报成 Scrapling 内置 Cloudflare Turnstile 已经自动解决。

## Decision

- 保留线程局部 `FetcherSession` 作为默认快速通道；普通批次若未遇到控制，全程不启动浏览器。
- 传输资源池显式携带内存态执行作用域键；当前使用 `single-user + platform + default`
  默认值，不新增租户、权限、数据库字段或 Session 格式。CookieStore 与普通 HTTP Session
  仍归单个资源池私有，后续按客户拆分资源所有权时不需要修改平台适配器调用合同。
- 进程级 `BrowserResourceBudget` 默认只允许一个 `StealthySession` 运行。许可只共享容量，不
  共享 Cookie、浏览器上下文或账号状态；两个平台同时遇到控制时串行取得许可。
- 每次真实导航使用一个短生命周期私有 `StealthySession`。它继承当前资源池 Cookie，使用
  `zh-CN`、`Asia/Shanghai`、WebRTC 约束、Canvas 噪声、WebGL 和完整验证资源加载；处理后把
  浏览器 Cookie 回灌当前 CookieStore，并在归还进程许可前关闭 Chromium。这样控制事件之间
  多付一次约数百毫秒冷启动，但不会让闲置浏览器长期占用数百 MiB，也不会形成跨平台状态污染。
- 只有适配器已经确认响应属于验证码或访问验证时才进入 Stealthy 通道；同一资源池、同一控制
  事件的其他并发线程通过导航尝试代次复用首个结果，不重复打开浏览器。
- `solve_cloudflare=True` 只在响应包含 Cloudflare challenge 标记时启用。汽车之家自有数字
  验证和易车腾讯验证码使用 Stealthy 浏览器环境尝试取得平台可自行放行的状态，但仍由原控制
  分类器核对。浏览器自身返回 HTTP 200 只代表页面可导航；原业务请求复访并通过既有分类器后，
  适配器才调用确认接口推进“已验证代次”。复访仍是控制页时继续进入既有 `waiting_for_auth`。
- Stealthy 导航不再无条件追加固定 1000ms 等待；默认依赖 `load_dom` 与对应 challenge 处理器，
  后续平台证据需要额外等待时只调整集中式导航策略，不复制适配器方法。
- 普通 FetcherSession 收到的 Set-Cookie 从线程私有 CookieJar 合并进共享 CookieStore，避免
  同一平台不同采集线程继续使用过期状态。
- ThreadSnap 继续拥有数据库批次、平台 FIFO、并发上限、候选冻结、持久检查点、限流冷却、
  认证等待和结果提交；Stealthy 通道只负责一次受保护页面导航与运行期 Cookie 交接。

本决策收窄 ADR 0047 与 ADR 0054 中“三平台后台绝不启动浏览器”的表述：普通请求仍是纯
HTTP，已分类的平台控制允许一次延迟创建、串行且有界的 Scrapling 浏览器恢复。

## Consequences

- 汽车之家适配器升级为 `autohome-club-v8-scrapling-stealth`，易车升级为
  `yiche-community-v6-scrapling-stealth`；懂车帝当前普通接口没有同类验证码分类，保持
  `dongchedi-dynamic-v7-scrapling`，其页面像素证据仍按既有专用流程执行。
- 浏览器资源只在真实控制出现后产生，进程级默认峰值为一个；每次导航结束即关闭，成功回灌后
  同批次剩余快速请求沿用新 Cookie。
- 内存指标区分 HTTP 请求数、浏览器尝试、同事件复用、可复访响应、导航失败和经业务分类器确认
  的恢复数；统计不包含 URL、Cookie 或账号值。后续 SaaS 资源调度可替换预算实现，并以现有
  执行作用域键扩展所有权，无需重写采集器恢复流程和合同测试。
- 当前实现改善浏览器指纹与验证状态连续性，但不等同于通用图片 OCR、腾讯验证码求解器或
  任意平台控制绕过。自动能力以原 URL 复访取得有效内容作为唯一成功证明。
- 数据库结构、加密 Session 格式和前端操作保持不变；跨批次持久化完整浏览器 Profile 仍由
  既有认证流程负责。
- 本决策只存在于独立 `refactor/restore-scrapling-max` 分支，合入 `main` 前不代表当前生产
  版本已经启用。

## Rejected alternatives

- **所有请求统一使用 StealthySession**：浏览器数量、资源和吞吐成本过高，API 请求也失去
  已验证的直接 JSON 合同。
- **任意控制页都打开多个并发浏览器**：会放大同一风控事件，且不同页面产生的 Cookie 状态
  互相覆盖。
- **对所有页面盲目启用 solve_cloudflare**：Scrapling 源码会在非 Cloudflare 页面报告没有
  找到对应 challenge；平台自有图片验证码与腾讯验证码不属于该处理器。
- **浏览器返回 HTTP 200 就视为恢复成功**：验证码页本身也可能是 HTTP 200，必须回到原请求
  并通过既有内容与身份合同。
- **长期保留每个平台的 Stealthy 浏览器**：热复用可节省约数百毫秒冷启动，但当前实测单个
  完整浏览器进程组会占用约 0.5 GiB；短生命周期更符合后续多客户容量上限，控制事件稀少时
  总体成本更低。
