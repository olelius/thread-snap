# Linux 双候选 2000 条测试运行器

该运行器保持两个固定候选不变：

- 候选 A：Scrapling 0.4.12；
- 候选 B：Crawlee 3.18.0 + Playwright 1.62.1。

两个候选按顺序使用同一份 2000 条 URL 清单和同一套测试账号，分别建立持久登录会话，结果互不拼接。每个候选的一小时窗口包含浏览器启动和登录时间。

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
