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

短信初始化会从帖子地址构造同源 `/login-required?redirect=...` 入口，避免先等待文章页全部资源加载；登录成功后的内容判定仍使用原始帖子 ID。终端先用 `navigation_target`、`navigation_document` 和 `navigation_event` 报告脱敏后的主文档状态及 `DOMContentLoaded/load` 生命周期，再依次出现 `sms_page_ready=<candidate>` 和 `sms_request_clicked=<candidate>` 并提示输入当次动态码。其中 `sms_request_clicked` 只表示发送按钮点击已经完成，短信送达仍以手机实际接收为准。动态码不写入 `config.json`、标准输出、结果文件或持久浏览器状态；成功后只在各候选的本地 `profile_dir/storage-state.json` 保存复访所需的会话状态，并将文件权限设为 `0600`。两个候选必须分别完成一次，不能共用状态文件。

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
- `resource-metrics.csv`
- `run.log`
- `SHA256SUMS`

登录验证另写入 `login-result.json`，只记录是否提交、是否登录成功、响应分类及验证页面状态，不记录账号、密码或 Cookie。

若一小时结束时仍有任务未启动，结果以 `deadline_not_started` 和 `request_count=0` 如实保存；该轮不会被判为通过。中断后使用原结果目录直接调用候选运行器时，只处理尚未落盘的 URL。
