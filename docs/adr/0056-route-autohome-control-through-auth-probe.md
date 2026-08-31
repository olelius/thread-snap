---
status: accepted
---

# 汽车之家平台控制进入正式认证并以单来源探针恢复

## Context

ADR 0055 为汽车之家和易车增加了按需 `StealthySession` 通道。2026-08-31 的固定输入
对照测试给出了汽车之家特定边界：420 个冻结访问中前 56 个返回有效内容，第 57 个进入
`safety.autohome.com.cn/userverify/index`；人工完成页面操作后，同一 Stealthy 原请求复访
仍被分类为 `PLATFORM_CHALLENGE`，最终验证入口为 HTTPS 404。该轮输入清单 SHA-256 为
`318b9c2794179089526607f73facd9c443864da30e526a56c4e6c6027f18c0d4`。

同日正式混合路径则在官方交互 Profile 更新后把既有批次从 `85 / 420` 原位恢复并完成
`420 / 420`。因此现有证据只证明汽车之家普通 Scrapling HTTP 与正式交互认证的组合路径
有效，不支持把一次 Stealthy 导航当作该平台的恢复手段。

此前 `resume_platform` 会同时恢复同批次所有等待来源。Session 更新后若立即按冻结并发
放大请求，既没有先证明原触发 URL 已返回业务内容，也可能在控制刚解除时再次形成突发。

## Decision

- 汽车之家普通列表、详情和 API 继续使用线程局部 Scrapling `FetcherSession`；已分类的
  `PLATFORM_CAPTCHA_REQUIRED` 或 `PLATFORM_CHALLENGE` 不再启动 Stealthy 导航，直接保存
  精确触发 URL 并进入共享 `waiting_for_auth`。
- 正式处理入口继续按错误分流：验证码或访问验证继承当前加密 Profile 并打开原触发 URL；
  `AUTH_REQUIRED` 使用既有登录恢复路径。Session 保存后恢复原任务，不创建替代批次。
- 每个被恢复的批次只把最早等待来源标记为认证恢复探针；同批次其他排队来源持久标记为
  阻塞。Worker 仅领取该探针，实际并发固定为 1，由该来源在原 URL 完成真实采集访问门禁。
- 探针成功、部分成功或确定失败后清除恢复标记并释放同批次其他来源；下一次 Worker 领取
  恢复批次冻结的内部总并发。探针再次进入认证等待或持久重试时保留标记，不放大后续请求。
- 若服务恰在恢复标记事务后中断且只留下阻塞标记，Worker 自动把最早阻塞来源提升为探针，
  避免平台 FIFO 因残留检查点停滞。
- 标记复用 `CircleTask.checkpoint`，不增加数据库列或 Session 格式；现有进程重启恢复和批次
  聚合继续作为唯一事实源。

本决策只替代 ADR 0055 中汽车之家控制页的 Stealthy 恢复部分。易车的受控 Stealthy 通道、
全局浏览器资源预算和通用 Scrapling 传输能力保持原决策。

## Consequences

- 汽车之家适配器升级为 `autohome-club-v9-scrapling-auth-gate`。
- 无控制响应时仍保持全 HTTP 快速路径；控制出现后少一次无效 Chromium 导航，并保留平台
  返回的原始控制分类和触发 URL。
- 认证恢复后的第一阶段最多运行一个来源任务；探针完成后才恢复该批次配置的 1～8 并发。
- 内容门禁由真实来源任务完成，Session 结构可保存、浏览器 HTTP 200 或离开验证页都不单独
  构成采集恢复证明。
- 本轮不增加验证码图像识别或直接提交协议；当前证据门只关闭控制分类、正式认证、原 URL
  探针和渐进恢复合同。
- 该实现保留在 `refactor/restore-scrapling-max` 独立分支，尚未改变 `main` 的运行版本。

## Rejected alternatives

- **汽车之家全部请求使用 StealthySession**：固定轮次在第 57 次仍进入平台控制，且每个请求
  都承担 Chromium 时间和内存成本。
- **Session 保存后立即恢复全部等待来源**：缺少原 URL 内容证明，并可能在控制刚解除时按
  高并发再次形成突发。
- **只用保存状态时间判断恢复成功**：Session 持久化结构与业务端点可访问性属于不同阶段。
- **新增数据库恢复表**：单批次单平台的探针/阻塞关系可由现有持久检查点表达，新增结构不
  提供当前验收所需的额外事实。
