# ThreadSnap 采集框架 PoC

本目录只保存技术选型阶段的可复现代码和合成测试夹具。真实 URL、页面响应、逐 URL 结果和运行日志继续放在被 Git 忽略的 `artifacts/poc/` 或 `artifacts/runtime/`。

## 目录

- `shared/`：确定性抽样、统一结果契约、校验器和跨候选分类夹具；
- `candidate-a/`：Scrapling 的 HTTP 优先、动态页面回退冒烟；
- `candidate-b/`：Crawlee CheerioCrawler 的 HTTP 优先、PlaywrightCrawler 回退冒烟。

当前代码覆盖访问冒烟、浏览器认证、匿名/认证直接 HTTP 预筛和统一结果验证，不是正式业务采集器，也不代表第一版功能完成。

## Python 环境

项目 Python 固定使用仓库根目录 `.vevn`：

```powershell
python -m venv .vevn
.\.vevn\Scripts\python.exe -m pip install -r .\poc\candidate-a\requirements.lock
```

除创建虚拟环境本身外，不使用全局 Python 安装或运行项目依赖。

## 固定首轮清单

```powershell
.\.vevn\Scripts\python.exe .\poc\shared\select_inputs.py `
  --pool .\artifacts\poc\inputs\throughput-urls.txt `
  --output .\artifacts\poc\inputs\round-1-urls.txt `
  --manifest .\artifacts\poc\inputs\round-1-manifest.json `
  --seed threadsnap-poc-round-1-20260808-v1 `
  --count 2000
```

抽样算法按 `SHA-256(seed + NUL + URL)` 排序取前 N 条，并强制使用 LF 写出，因此相同输入、种子和脚本版本在 Python/Node 和 Windows/Linux 上都能复现同一清单。

## 冒烟与校验

候选 A：

```powershell
.\.vevn\Scripts\python.exe .\poc\candidate-a\src\smoke.py `
  --input .\artifacts\poc\inputs\round-1-urls.txt `
  --output-dir .\artifacts\poc\results\candidate-a\smoke-001 `
  --limit 3
```

冷却或故障后的恢复段可用 `--offset <已产生终态数>` 从原固定清单继续；输出会同时
记录原清单SHA-256、偏移量和本段清单SHA-256。恢复段必须独立判定，不能与前段
拼成同一持续轮次。

候选 B：

```powershell
npm.cmd --prefix .\poc\candidate-b ci
npm.cmd --prefix .\poc\candidate-b run smoke -- `
  --input ..\..\artifacts\poc\inputs\round-1-urls.txt `
  --output-dir ..\..\artifacts\poc\results\candidate-b\smoke-001 `
  --limit 3
```

统一校验：

```powershell
.\.vevn\Scripts\python.exe .\poc\shared\validate_results.py `
  --input-list .\artifacts\poc\inputs\round-1-urls.txt `
  --results .\artifacts\poc\results\candidate-a\smoke-001\url-results.jsonl `
  --candidate candidate-a `
  --expected-count 3 `
  --summary .\artifacts\poc\results\candidate-a\smoke-001\summary.json
```

校验器只在结果满足统一字段、URL 对应、状态一致性、帖子 ID 匹配和内容证明规则时退出 0。登录页、验证码、挑战页、限流页和异常空响应不会计为成功。

## 重定向与会话诊断

以下命令保持候选组件不变，只增加框架原生会话、主文档重定向链和 XHR/fetch 摘要：

```powershell
.\.vevn\Scripts\python.exe .\poc\candidate-a\src\diagnose.py `
  --input .\artifacts\poc\inputs\round-1-urls.txt `
  --output-dir .\artifacts\poc\results\candidate-a\diagnostic-001 `
  --limit 3

npm.cmd --prefix .\poc\candidate-b run diagnose -- `
  --input ..\..\artifacts\poc\inputs\round-1-urls.txt `
  --output-dir ..\..\artifacts\poc\results\candidate-b\diagnostic-001 `
  --limit 3
```

诊断文件只保存占位化路径、HTTP 状态、Cookie 数量、Cookie 名称哈希和子请求聚合，不保存 Cookie 值、授权头值、请求体或完整目标 URL。

如需隔离框架内置 Chromium 与本机正式 Chrome，可在两条诊断命令末尾统一追加
`--browser-engine real-chrome`；仍分别由 Scrapling `DynamicSession` 与 Crawlee
`PlaywrightCrawler` 执行，不改变候选技术。

当系统代理使用 fake-IP DNS 时，可从可信 DNS 独立解析目标地址，并通过
`--direct-ip <IP>` 做进程级直连对照。该参数只映射当前输入主机且禁用该浏览器
进程的代理，不修改系统代理；地址不写入诊断 JSONL。

登录成功后可通过 `--profile-dir <目录>` 复用候选自己的持久浏览器配置；该目录
必须位于被 Git 忽略的 `artifacts/poc/profiles/`，诊断命令不再需要账号密码。

## 登录会话初始化

两个候选都从进程环境变量读取同一套测试凭证，凭证值不会写入结果文件：

```powershell
$env:THREADSNAP_PLATFORM_ACCOUNT = '<测试账号>'
$env:THREADSNAP_PLATFORM_PASSWORD = '<测试密码>'

.\.vevn\Scripts\python.exe .\poc\candidate-a\src\login.py `
  --probe-url '<样本 URL>' `
  --profile-dir .\artifacts\poc\profiles\candidate-a-auth `
  --output .\artifacts\poc\results\candidate-a\login-001\result.json `
  --headless

npm.cmd --prefix .\poc\candidate-b run login -- `
  --probe-url '<样本 URL>' `
  --profile-dir ..\..\artifacts\poc\profiles\candidate-b-auth `
  --output ..\..\artifacts\poc\results\candidate-b\login-001\result.json `
  --headless

Remove-Item Env:THREADSNAP_PLATFORM_ACCOUNT
Remove-Item Env:THREADSNAP_PLATFORM_PASSWORD
```

候选配置目录彼此隔离，测试时按 A、B 顺序运行，避免同一账号的并发登录干扰。

## Candidate A 认证直接 HTTP 首版

Candidate A 浏览器认证成功后，`throughput.py` 会在候选隔离 profile 中显式写出
`storage-state.json`。纯 HTTP 探针接受1至2000条同域样本，固定并发1、每URL一次
请求，不启动浏览器或切换兜底；首次出现登录、空文档、验证码、挑战或限流时，
由Spider暂停剩余队列并记录覆盖率和停止原因：

```powershell
.\.vevn\Scripts\python.exe .\poc\candidate-a\src\authenticated_http_probe.py `
  --input .\artifacts\poc\inputs\auth-http-probe-urls.txt `
  --storage-state .\artifacts\poc\inputs\profiles\candidate-a\storage-state.json `
  --output-dir .\artifacts\poc\results\candidate-a\auth-http-001 `
  --limit 3
```

该入口使用 Scrapling `Spider + FetcherSession + Request/Response`、框架
`CrawlStats` 与 `ItemList.to_jsonl()`；项目逻辑只补充帖子真实性、HTTP 200 控制页
分类、脱敏事件、摘要和校验清单。Cookie 名称和值不会写入输出或日志。

出现 `empty/login` 后需要验证自动恢复时，使用有界恢复入口。它先暂停旧 Spider，
使用 Scrapling `AsyncDynamicSession` 在新隔离 profile 中重新登录，再执行固定3条
纯 HTTP 门禁；门禁通过后从触发 URL 本身重新处理，而不是跳过触发项：

```powershell
.\.vevn\Scripts\python.exe .\poc\candidate-a\src\bounded_session_recovery.py `
  --config .\artifacts\poc\inputs\auth-http-bootstrap-config.json `
  --input .\artifacts\poc\inputs\round-1-urls.txt `
  --gate-input .\artifacts\poc\inputs\auth-http-probe-urls.txt `
  --initial-storage-state .\artifacts\poc\inputs\profiles\candidate-a\storage-state.json `
  --output-dir .\artifacts\poc\results\candidate-a\bounded-recovery-001 `
  --limit 2000 `
  --max-recoveries 2
```

`captcha/challenge/rate_limited`、重新登录失败、门禁失败、超过恢复次数或超过窗口
都会保留终态并结束；不会无限重登。门禁和重试均计入采集HTTP请求数及请求放大率，
不同 Session 的结果只在该有界恢复轮次中按逐 URL 最终结果汇总，原始控制尝试仍保留
在 `request-events.jsonl`。该HTTP指标不包含浏览器重新登录过程中的页面子请求；
Session刷新次数单独统计。

## Linux 2000 条认证吞吐运行器

Linux 入口、明文配置模板、安装/健康检查、资源采样和结果目录说明见
`poc/linux/README.md`。两个固定候选分别使用：

```text
poc/candidate-a/src/throughput.py
poc/candidate-b/src/throughput.ts
```

在 Windows 生成标准源码压缩包及可直接复制目录：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-linux-poc-package.ps1 `
  -Version <版本> `
  -RuntimeConfig .\artifacts\poc\inputs\linux-run-config.json `
  -InputFile .\artifacts\poc\inputs\round-1-urls.txt `
  -ConnectivityInputFile .\artifacts\poc\inputs\connectivity-urls.txt
```

标准压缩包不含账号密码；`copy-to-linux/config.json` 是本地明文 sidecar，整个
`artifacts/poc/` 均由 Git 忽略。目标 Linux 的真实结果必须由脚本生成，不用本机
单条合成端到端或理论吞吐替代。
