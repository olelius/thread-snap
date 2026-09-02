---
status: accepted
---

# 以平台无关组件接入腾讯验证码纯协议求解

## Context

ADR 0058 已把易车账号失效、详情挑战、腾讯验证码和限流分开，但腾讯验证码仍进入
Stealthy 或人工恢复。2026-09-02 的隔离研究已用普通 HTTP、本地图像算法和自研 TDC
IR/VM 在两个全新 challenge 取得腾讯业务 `errorCode="0"`，并在同一易车
FetcherSession 关闭 `/WafCaptcha -> 原详情正文` 门禁。

本次用户明确要求把该结果接入生产，同时要求腾讯验证码能力保持平台无关：易车只拥有
自身 WAF 文档、`seqid`、四行回调和正文重载；以后其他平台遇到同类腾讯验证码时，应
调用同一解题合同，而不是复制逆向实现。

功能分支上的生产实现又取得两级现时证据：共享组件独立处理全新腾讯 challenge，5 个
网络请求、4.038 秒、95 个 opcode、74 个 handler，业务验证通过；随后使用当前易车加密
Session 按既有80条有界输入运行，在第60个详情命中 WAF 后自动求解、回调并返回正文，
60/60 均形成内容证明，整轮24.028秒。

## Decision

- 新增 `threadsnap.tencent_captcha` 平台无关包。调用方注入 AppId、入口 URL 和最小 HTTP
  transport；返回值只包含当次 `ticket/randstr` 与脱敏运行摘要。
- Python 编排 prehandle、双图下载、Pillow/NumPy/SciPy 位移识别、MD5 PoW、verify 和
  严格响应分类。图片、`sess`、坐标、PoW、`collect/eks` 与票据每次重新取得或计算。
- TDC 继续逐 challenge 下载，但只作为 AST 和 payload 输入。预构建 Node Worker 完成
  直接/间接外壳归一化、结构 handler 映射、IR 编译和自研 VM 执行；原始 TDC 主程序不
  进入执行路径。handler IR 是可版本化的共享基线，未知结构按漂移关闭本轮。
- Node Worker 源码与锁文件进入仓库，Babel 分析依赖由 esbuild 预构建为 wheel 内 bundle；
  运行环境只需要 Node.js，不携带 `node_modules`。目标 CentOS 离线包增加 `nodejs` RPM。
- 易车专属逻辑保留在 `collectors.yiche_waf`：从当前控制文档提取 `seqid`，调用共享解题器，
  再由同一 FetcherSession 向 `/WafCaptcha` 提交四行正文并重载原 URL。适配器版本升级为
  `yiche-community-v8-tencent-protocol-solver`。
- 易车同一采集器实例的验证码处理使用单飞锁。其他线程观察到已完成代次后直接重载，
  不重复创建 challenge。腾讯链每轮固定为 prehandle、双图、TDC 和 verify 共5个网络请求，
  不对失败 challenge 自动重复求解。
- prehandle、图片几何、TDC、verify 或易车 `seqid`/回调门漂移时，以稳定错误码停止自动链；
  结构漂移立即打开进程内15分钟熔断，其他连续两次失败后熔断。易车把结果交回现有
  `PLATFORM_CAPTCHA_REQUIRED`/`waiting_for_auth` 恢复路径，保留原批次和剩余 URL。
- Cookie、图片、TDC、`sess`、`collect/eks`、PoW 答案、`ticket/randstr/seqid` 只在内存或
  自动清理的临时目录存在。日志只记录阶段、稳定错误码、请求数、耗时和结构计数。

## Consequences

- 易车正常验证码不再先启动 Stealthy 浏览器，成功后在原采集调用内继续，不创建替代批次，
  Worker 的 FIFO、检查点和已完成 URL 去重合同保持不变。
- 共享组件不引用易车域名、WAF 路径或易车 Cookie；其他平台可提供自己的 AppId、入口 URL、
  transport 和站点回调适配器复用同一逆向结果。
- ADR 0058 继续管理账号失效、详情挑战、限流和自动链失败后的人工恢复；本决策替代其中
  “腾讯验证码先尝试 Stealthy”的生产分支。ADR 0059 仍只管理隔离取样上限。
- 当前实时证据关闭功能开发门，但不替代易车事前冻结的正式 `500 / 500` 生产验收。
- 2026-09-02 的并发4真实批次取得一个95-opcode随机变体：其中二级helper对象把
  `helperA.key`别名为`helperB.alias`。目录器现于每轮AST替换前重新收集helper，最多12轮
  收敛；冻结失败样本由误报的76个handler恢复为75个既有handler，并由合成二级别名回归
  锁定`length`原语结构签名。该修正扩展等价外壳归一化，不放宽未知handler漂移门。

## Rejected alternatives

- **把逆向代码直接写进易车采集器**：会复制腾讯协议、图像和 TDC 逻辑，后续平台难以复用。
- **继续把 PoC 目录当生产依赖**：该目录被 Git 忽略，包含原始证据、临时路径和研究工具，
  不具备版本、安装和敏感材料生命周期合同。
- **运行原始 TDC 脚本**：会把供应商动态代码带入执行路径，并丢失结构漂移门。
- **目标服务器运行期执行 npm 安装**：破坏现有纯离线发布；预构建 bundle 与 Node RPM 可由
  现有离线包校验和安装。
