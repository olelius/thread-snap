# Linux 双候选 2000 条测试运行器

该运行器保持两个固定候选不变：

- 候选 A：Scrapling 0.4.12；
- 候选 B：Crawlee 3.18.0 + Playwright 1.62.1。

两个候选按顺序使用同一份 2000 条 URL 清单和同一套测试账号，分别建立持久登录会话，结果互不拼接。每个候选的一小时窗口包含浏览器启动和登录时间。

目标登录页默认是手机验证码模式；两个候选会显式点击“密码登录”，确认账号和密码输入框可见后再提交，并在 `login-result.json` 记录 `password_login_selected`。

## 配置

复制 `poc/linux/config.example.json` 为包根目录的 `config.json`，填写明文 `account` 和 `password`。完整 URL 放在包根目录 `input-urls.txt`，前 `expected_count` 条必须互不重复。

`config.json` 是本地运行配置，不进入 Git、日志、结果或标准源码压缩包。直接交付目录会把该文件作为压缩包旁的明文 sidecar；`deploy.sh` 解压后再复制到运行目录。

默认每个候选并发数为 8。Linux 预跑后应依据 `resource-metrics.csv` 调整，两个候选必须继续使用各自固定技术。

## Linux 执行

目标基线为 CentOS Stream 10、x86_64、glibc 2.39。当前源码运行包会在 Linux 主机联网安装锁定依赖和匹配浏览器；它用于尽快完成真实主机验证，后续最终阶段 2.5 包仍需在兼容 Linux 环境归档离线依赖。

```bash
chmod +x poc/linux/*.sh
./poc/linux/preflight.sh
./poc/linux/install.sh
./poc/linux/start.sh
./poc/linux/healthcheck.sh
./poc/linux/run-all.sh round-1
```

## 先做独立联通测试

首次部署到服务器时先执行：

```bash
./poc/linux/test-connectivity.sh
```

如果密码提交后明确要求手机验证码，先在当前 SSH 终端分别初始化两个隔离会话：

```bash
./poc/linux/bootstrap-sms-session.sh candidate-a
./poc/linux/bootstrap-sms-session.sh candidate-b
./poc/linux/test-connectivity.sh
```

短信初始化会从帖子地址构造同源 `/login-required?redirect=...` 入口，避免先等待文章页全部资源加载；登录成功后的内容判定仍使用原始帖子 ID。该入口把首次导航及 Scrapling 随后的稳定性检查都限定为 `domcontentloaded`，候选 B 则通过 Crawlee 的 `gotoOptions.waitUntil` 使用相同条件；`navigation_action=...wait_until_domcontentloaded` 表示该条件已生效。终端继续用 `navigation_target`、`navigation_document`、`navigation_event` 和 `navigation_pending` 报告脱敏后的主文档生命周期与后台资源类型，但这些后台请求不再阻塞页面动作。

点击后脚本等待 5 秒并输出 `sms_send_evidence`：`network_events` 只保留 XHR/fetch 的方法、响应状态和不含查询参数的路径，`countdown_visible`、`verification_visible` 与 `warning_markers` 记录可见页面反馈；不记录手机号、请求体、响应体或验证码。`sms_request_clicked` 只表示发送按钮点击已经完成，是否已被平台接受以 `sms_send_evidence` 为准。

若出现可视验证码，脚本不会提前等待短信码，而是输出候选独立的 CDP 端口。以候选 A 的默认端口 `9222` 为例，在 Windows 新开一个 PowerShell 并保持运行：

```powershell
ssh -N -L 9222:127.0.0.1:9222 root@<服务器地址>
```

随后在 Windows Chrome 打开 `chrome://inspect/#devices`，点击 `Configure`，加入 `localhost:9222`，再对登录页目标点击 `inspect`，在服务器原浏览器上下文中完成人工验证。候选 B 默认使用 `9223`：

```powershell
ssh -N -L 9223:127.0.0.1:9223 root@<服务器地址>
```

CDP 只监听服务器回环地址并经 SSH 隧道访问，不需要在服务器安装桌面、Xvfb、VNC 或 noVNC。端口可通过 `THREADSNAP_CANDIDATE_A_CDP_PORT` 和 `THREADSNAP_CANDIDATE_B_CDP_PORT` 临时覆盖。短信初始化会放行滑块背景、拼图和验证码素材所需的图片资源，只继续丢弃媒体与字体；普通登录诊断和2000条吞吐访问仍使用原有资源策略。脚本检测到可视验证消失且发送控件进入倒计时后，才提示输入当次短信码；十分钟内没有取得这两个信号则本次初始化失败，不把验证码页误判为短信已发送。

动态码不写入 `config.json`、标准输出、结果文件或持久浏览器状态。短信初始化不再加载候选旧 `user_data_dir` 或旧 Cookie，而是在本次 `.runtime/sms-bootstrap/<timestamp>/<candidate>/browser-profile` 中建立全新资料；只有短信登录完成且原始帖子取得 ID 与内容证明后，才关闭浏览器并把整份新资料提升为该候选的 `profile_dir`。失败时旧资料保持原状，并输出 `error_stage` 与只含文档字节数、输入框/表单/短信标签数量的 `login_page_evidence`。两个候选必须分别完成一次，不能共用状态文件。

再次执行 `test-connectivity.sh` 时，准备阶段会重建两个 `profiles/connectivity-candidate-*` 隔离目录，并分别从 `config.json` 中 Candidate A/B 的 `profile_dir` 复制当前 `storage-state.json`。这样联通测试复用刚完成的认证，又不直接改写主会话；若源状态不存在，旧的联通副本会被删除。`prepare.log` 中的 `session_state_copied` 应对两个候选均为 `true`，该日志不包含 Cookie 或状态内容。

Candidate A 的普通登录确认和逐 URL 访问使用 Scrapling 原有 `page_setup`，把首次导航及框架随后固定的完整 `load` 等待映射为 `domcontentloaded`，避免页面长期后台资源占满单 URL 超时；DOM 就绪后仍执行配置中的短等待并按帖子 ID 与标题/正文证明判断成功。候选异常退出且尚未写入登录结果时，联通包会记录 `runner_failed_before_login_result` 及退出码，而不是保留初始化占位状态。

该入口只用于当前 PoC 测试。正式项目采用人工续期、自动接码、外部会话托管还是其他方式仍为未决项，本脚本不构成正式方案。

该脚本最多访问 `connectivity-urls.txt` 中的 3 条已验证样本，不启动 2000 条任务。它依次记录：

- Linux 和浏览器运行时预检；
- DNS、TCP、TLS、普通 HTTP 基线；
- Scrapling 自动登录和真实帖子访问；
- Crawlee/Playwright 自动登录和真实帖子访问；
- 两个候选的统一结果契约检查。

终端会输出当前 `stage`；浏览器健康检查最多 180 秒，每个候选最多 360 秒，超时后进入统一汇总和诊断打包，不持续静默等待。

无论联通结论是否通过，脚本都会在 `connectivity-results/` 生成一个
`connectivity-<timestamp>.tar.gz` 及对应 `.sha256`。只需把这两个文件复制回开发电脑。
`connectivity-summary.json` 中的 `ready_for_2000=true` 表示当前服务器具备进入 2000 条测试的联通条件；失败时 `next_action` 会指出环境/浏览器、DNS/TCP/TLS/HTTP、登录或内容访问中的下一处排查方向。

联通模式还会为每个候选生成 `login-diagnostic.json`；提交后仍停留在登录或验证页面时，额外生成 `login-page-redacted.png`。诊断只记录最终路径、查询参数名、可见验证控件和标准化提示词；截图前清空输入框并遮盖账号、密码及账号片段，不保存完整 HTML、Cookie 值或凭证。

## login/empty 状态转变诊断

当完整轮次出现登录页或空文档时，先执行：

```bash
./poc/linux/test-access-transition.sh
```

该脚本固定取清单前 500 条、保持两个候选原并发和会话隔离，分别提供最多 20 分钟窗口，不重复启动完整 2000 条。脚本结束后返回 `access-diagnostic-results/access-transition-<timestamp>.tar.gz` 及 `.sha256`。

每个候选结果新增 `access-diagnostics.jsonl`，只为最先出现的最多三条 `login` 和三条 `empty` 保存以下信息：主文档响应状态与目标类别、最终地址类别、DOM 长度和哈希、标题/正文文本长度、脚本/iframe/form 数量、预定义验证标记，以及 Cookie 数量和 Cookie 名称集合哈希。它不保存页面正文、完整最终地址、Cookie 名称、Cookie 值、账号或密码。

`login` 表示导航最终进入登录路径，不属于网络连接错误；`empty` 表示主文档请求有响应，但最终 DOM 没有帖子 ID、标题或正文证明。是否由验证码、挑战脚本、持续负载控制或资源加载造成，应以该诊断文件中的响应链和页面形态判断，不根据 HTTP 200 单独推断。

## fresh-session 单并发诊断

当两个候选都在持续并发约一分钟后转为 HTTP 200 空文档时，先分别对既有隔离会话执行真实文章探测，再决定是否进入单并发诊断。文件修改时间只记录为证据，不再据此要求重复登录。每次只运行一个候选：

```bash
./poc/linux/test-single-concurrency.sh candidate-a

./poc/linux/test-single-concurrency.sh candidate-b
```

脚本先用同一候选、同一会话和清单首条 URL 做一次不计入500条窗口的主动探测。探测确认登录态和文章内容均有效时输出 `session_probe_result=ready;session_action=reuse_existing` 并直接继续；探测实际落入登录类、空文档或运行失败时输出短信初始化命令并停止，不把失败探测混入500条结果。此时按提示执行 `./poc/linux/bootstrap-sms-session.sh <candidate> && ./poc/linux/test-single-concurrency.sh <candidate>`，`&&` 保证全新资料初始化及成功提升完成后才启动诊断。

诊断固定取原清单前 500 条、只把目标候选并发设为 1，保留原框架、资源路由、重试和成功契约，最多运行 40 分钟。`diagnostic-summary.json` 另记录会话文件年龄（仅信息）、主动探测证据，以及是否在 900 秒比例窗口内完成500条；比例字段只用于判断单并发是否还有达到2000条/小时的速度余量，不构成正式吞吐通过结论。

结果压缩包位于 `access-diagnostic-results/single-concurrency-<candidate>-<timestamp>.tar.gz`。A/B 两次诊断必须各自返回压缩包和 `.sha256`，不得复用另一候选会话，也不得把两次诊断拼接为正式2000条轮次。

单独执行：

```bash
./poc/linux/run-poc.sh candidate-a round-1
./poc/linux/run-poc.sh candidate-b round-1
```

结果写入 `results/<candidate>/<round>-<timestamp>/`，包含：

- `environment.json`
- `summary.json`
- `input-urls.txt`
- `url-results.jsonl`
- `request-events.jsonl`
- `access-diagnostics.jsonl`
- `resource-metrics.csv`
- `run.log`
- `SHA256SUMS`

登录验证另写入 `login-result.json`，只记录是否提交、是否登录成功、响应分类及验证页面状态，不记录账号、密码或 Cookie。

若一小时结束时仍有任务未启动，结果以 `deadline_not_started` 和 `request_count=0` 如实保存；该轮不会被判为通过。中断后使用原结果目录直接调用候选运行器时，只处理尚未落盘的 URL。
