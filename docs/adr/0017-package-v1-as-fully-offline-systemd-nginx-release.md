---
status: accepted
related: 0011-adopt-python-backend-before-deferred-linux-gate.md
---

# 第一版采用完整离线包、systemd、Xvfb 与 Nginx 部署

第一版产品闭环已经完成，下一阶段需要在最终 CentOS Stream 10 主机部署并恢复 ADR 0011 保留的 Linux 门禁。正式部署面对新服务器，安装时不应临时从 PyPI 或浏览器下载源解析应用依赖，也不能把 Windows 虚拟环境、Windows Chromium 或开发机状态复制到 Linux。

## Decision

- 正式交付物使用目标特定的 `tar.gz` 完整离线包，不制作 Docker 镜像、应用 RPM/DEB 或单文件可执行程序。
- Windows 开发机只生成包含 ThreadSnap wheel、前端生产构建和部署工具的 `offline-builder-input`；一台与目标机相同 CentOS Stream 主版本、x86_64 架构和 Python 次版本的制包机负责收集 Python wheelhouse、锁定 Patchright 对应的 Linux Chromium，以及 Python、Nginx、Xvfb 和浏览器共享库的 RPM 闭包。
- 最终包标记为 `installable=true` 和 `dependency_mode=fully-offline`，同时包含逐文件 `SHA256SUMS` 与压缩包整体校验值。目标服务器安装时使用 `pip --no-index` 和 `dnf --disablerepo='*'`，不访问应用或系统依赖仓库。
- 不可变程序版本安装到 `/opt/threadsnap/releases/<version>-<commit>`，`/opt/threadsnap/current` 和 `/opt/threadsnap/previous` 用于原子升级和程序级回滚；运行配置放在 `/etc/threadsnap`。
- SQLite、模板、导出和加密浏览器 Profile 默认放在 `/var/lib/threadsnap`。安装前必须用 `lsblk`、`findmnt`、`df -hT` 和 `df -Pi` 核对挂载点、空间与 inode；存在空间更充足的独立数据盘时，通过 `--data-dir` 直接使用其挂载点，例如 `/data/threadsnap`，不把持久数据放进 release 目录。
- systemd 管理一个 Xvfb 服务和一个 ThreadSnap 应用进程。应用仍保持 FastAPI、调度器、事件总线和平台 FIFO Worker 单进程，不增加 Uvicorn worker 或第二实例。
- Nginx 发布前端静态文件，并代理 `/health`、`/api/v1`、SSE 和认证 WebSocket；显式返回 `/internal/v1` 404，保留 WebSocket 子协议头且不在日志中记录完整票据。FastAPI 只监听 `127.0.0.1:8000`，Xvfb 禁止 TCP，原始 CDP 端口不开放。
- 首次安装生成 Fernet 密钥，升级沿用原密钥。备份同时保存数据目录和环境文件，并把最终副本复制到另一文件系统或备份主机；程序回滚不自动执行数据库降级，不兼容迁移使用匹配的完整备份恢复。

## Consequences

- 目标服务器正式安装不需要下载 Chromium、Python 包或 RPM；获取动作集中在可审计的兼容 Linux 制包阶段并由最终校验值冻结。
- 最终包体积显著增加，并绑定 CentOS Stream 主版本、CPU 架构、Python 次版本和 Patchright/Chromium 版本；这些基线变化后需要重新组装和验证离线包。
- Nginx 与 systemd 成为第一版确定的部署组件，Node.js 只存在于前端构建阶段，目标服务器运行期不需要 Node.js。
- 当前仓库可生成制包输入包并验证包结构；最终离线包仍须在兼容 Linux 制包机组装，并在最终主机验证 Xvfb 认证、会话续跑、重启、备份恢复和连续三轮 2000 URL 门禁后，才形成 Linux 部署验收结论。
