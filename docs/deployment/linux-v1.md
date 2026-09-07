# ThreadSnap 第一版 Linux 离线部署包

## 1. 包类型

ThreadSnap 正式目标包为 `fully-offline`：

- `backend/`：ThreadSnap 自身 wheel；
- `wheelhouse/`：全部 Python 运行依赖 wheel；
- `frontend/`：已经完成 Vite 生产构建的静态文件；
- `browsers/`：与锁定 Patchright 版本匹配的 Linux Chromium；
- `models/paddlenlp/`：已经下载并转换完成的 UIE-Senta-Nano 与 UTC-Nano 本地文字模型；
- `rpms/`：Python、Node.js 22+、Nginx、Weston 和 Chromium 系统共享库及其 RPM 依赖，并包含本地仓库元数据；
- `SYSTEM-PACKAGES.txt`：目标机向本地 RPM 仓库请求的顶层运行组件，避免强制安装全部递归 RPM；
- `deploy/`：主机检查、安装、systemd、Nginx、验证、备份与回滚脚本；
- `SHA256SUMS`：包内逐文件校验；压缩包旁另有整体 `.sha256`。

正式目标服务器安装阶段不访问 PyPI、Chromium 下载源或 DNF 仓库。获取依赖只发生在一台与目标服务器相同发行版、架构和 Python 基线的 Linux 制包机上。

## 2. 目录选择

Linux 使用挂载点，不使用 Windows 盘符。上传或安装前执行：

```bash
bash deploy/inspect-host.sh /tmp/threadsnap-host-report.txt
```

重点查看 `lsblk`、`findmnt`、`df -hT` 和 `df -Pi`：

| 内容 | 默认路径 | 规则 |
|---|---|---|
| 不可变程序版本 | `/opt/threadsnap/releases/` | 放系统盘即可，版本之间通过软链接切换 |
| 当前版本 | `/opt/threadsnap/current` | 指向当前 release |
| 配置和密钥 | `/etc/threadsnap/threadsnap.env` | `root:threadsnap`、`0640` |
| SQLite、模板、导出、加密 Profile、本地模型 | `/var/lib/threadsnap` | 持续增长的数据与模型；优先放空间充足的独立数据盘 |
| 浏览器运行时 | `/opt/threadsnap/browsers` | 随离线包安装，不写入用户 home 缓存 |
| 备份 | `/var/backups/threadsnap` | 最终副本应复制到另一文件系统或备份主机 |
| 服务日志 | systemd journal | 使用 `journalctl -u threadsnap` 查询 |

若 `/var` 所在文件系统空间有限，而服务器存在 `/data` 独立 SSD 挂载点，安装时使用：

```bash
sudo bash deploy/install.sh --data-dir /data/threadsnap --server-name HOST
```

不要把持久数据放在 release 目录；升级或回滚只切换程序，数据目录保持不变。建议初始为数据盘预留至少 50 GiB，并根据批次、图片/视频 URL、XLSX 模板和导出增长量调整。

## 3. 从源码生成制包输入包

在 Windows 开发机仓库根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\build-linux-deployment-package.ps1 -Version 0.1.0
```

输出到 `artifacts/releases/`。该 `linux-builder.tar.gz` 不是正式安装包，因为 Windows 环境不负责证明 Linux wheels、Chromium 和 RPM 的目标兼容性。

## 4. 在兼容 Linux 制包机生成最终离线包

制包机必须与目标机保持相同的 CentOS Stream 主版本、x86_64 架构和 Python 次版本，并允许在制包阶段联网：

```bash
sha256sum -c threadsnap-0.1.0-linux-builder.tar.gz.sha256
tar -xzf threadsnap-0.1.0-linux-builder.tar.gz
cd threadsnap-0.1.0-linux-builder

sudo dnf install -y python3 python3-pip dnf-plugins-core
sudo bash deploy/assemble-offline-package.sh "$PWD/output"
```

制包脚本会：

1. 校验输入包全部文件；
2. 为 CentOS Stream 10 制包阶段安装 EPEL 配置并启用 CRB，以解析 Weston 闭包；
3. 下载并冻结 Python wheelhouse；
4. 在临时虚拟环境中执行纯离线安装与 `pip check`；
5. 使用离线安装后的 PaddleNLP 下载并转换 UIE-Senta-Nano 与 UTC-Nano，执行一次真实本地推理后写入 `models/paddlenlp/`；
6. 下载锁定 Patchright 对应的完整 Linux Chromium，并跳过未使用的 headless shell；
7. 使用 `dnf download --resolve --alldeps` 收集含 Node.js 22+ 在内的系统 RPM 闭包，并用 `createrepo_c` 生成包内本地仓库元数据；
8. 记录顶层系统组件清单，让目标 DNF 复用已安装的兼容版本并只补齐缺失依赖；
9. 生成新的逐文件校验清单和压缩包整体校验值；
9. 输出 `*-centos-stream-10-x86_64-offline.tar.gz`。

## 5. 目标服务器纯离线安装

把最终 `.tar.gz` 和 `.tar.gz.sha256` 上传到临时目录，例如 `/var/tmp/threadsnap-upload/`：

```bash
cd /var/tmp/threadsnap-upload
sha256sum -c threadsnap-0.1.0-centos-stream-10-x86_64-offline.tar.gz.sha256
tar -xzf threadsnap-0.1.0-centos-stream-10-x86_64-offline.tar.gz
cd threadsnap-0.1.0-centos-stream-10-x86_64-offline

bash deploy/inspect-host.sh /tmp/threadsnap-host-report.txt
sudo bash deploy/install.sh --data-dir /var/lib/threadsnap --server-name HOST
```

安装脚本执行以下动作：

- 从包内本地 RPM 仓库安装 Python、Node.js 22+、Nginx、Weston 和共享库，禁用所有外部 DNF 仓库；
- 建立 `threadsnap` 系统账号；
- 在新 release 中建立虚拟环境并从本地 wheelhouse 安装；
- 从包内复制 Chromium；
- 从包内复制已转换的 PaddleNLP 模型到持久数据目录，不在目标机联网下载；
- 首次生成 Fernet 密钥，升级时保留原密钥；
- 安装并启动 Weston 无头 Wayland、ThreadSnap 单进程和独立 `threadsnap-nginx` 服务；
- 设置 SELinux 程序、静态文件、回环代理和非标准 HTTP 端口策略；
- 执行健康检查，失败时恢复上一程序版本。

防火墙只向受控内网或 VPN 网段开放 Nginx 端口。FastAPI `8000` 和 CDP 均保持本机访问，Wayland socket 只允许 `threadsnap` 用户访问。

## 6. 验证

```bash
sudo bash /opt/threadsnap/current/deploy/verify.sh
sudo systemctl status threadsnap threadsnap-wayland threadsnap-nginx --no-pager
sudo journalctl -u threadsnap -n 200 --no-pager
```

脚本检查 systemd、Nginx、SPA、API、`/internal/v1` 屏蔽、端口绑定、Fernet 配置、Node.js 22+、腾讯验证码运行时bundle、Wayland有头Chromium启动，并在完整验证模式下以目标服务账号离线执行本地文字模型推理。此后仍需真实执行：

1. 前端创建认证任务；
2. Dialog 收到非空连续画面；
3. 鼠标、滚轮、键盘和粘贴可用；
4. 保存结构有效的 Session；
5. 等待批次自动继续；
6. 确认原批次在原 URL 执行真实采集访问门禁并继续；
7. 在最终主机连续执行三轮固定 2000 URL 验收。

## 7. 备份、升级和回滚

一致性备份会短暂停止 ThreadSnap，并同时保存数据目录和 Fernet 配置：

```bash
sudo bash /opt/threadsnap/current/deploy/backup.sh /BACKUP_MOUNT/threadsnap
```

部署新包时再次运行新包内 `deploy/install.sh`。安装器保留 `current` 和 `previous` 链接。程序级回滚：

```bash
sudo bash /opt/threadsnap/current/deploy/rollback-release.sh
```

恢复完整数据备份：

```bash
sudo bash /opt/threadsnap/current/deploy/restore-backup.sh \
  /BACKUP_MOUNT/threadsnap/threadsnap-backup-YYYYMMDD-HHMMSS.tar.gz --confirm
```

程序回滚不会自动降级 Alembic 数据库；涉及不兼容迁移时使用与旧程序匹配的完整备份恢复。

### 7.1 兼容应用最小升级

既有服务器已经完成完整离线安装后，可以在以下条件全部成立时使用应用最小包，而不重新组装完整离线包：

1. 当前 release、作为基线的完整离线包及其整体 SHA-256 均已核对；
2. 从基线提交到目标提交的服务器运行依赖和部署输入均无变化：逐项比较 `pyproject.toml`、服务器运行组件的依赖清单及锁文件、`deploy/linux/` 和 Windows 制包脚本，并核对目标代码没有新增这些清单之外的服务器运行依赖。Python、Node.js、Chromium、RPM、模型和系统库的既有版本仍满足目标版本要求；任一服务器运行依赖新增或变更、部署输入变化或证据缺失时，该路径门禁保持关闭；
3. 前端 `package.json`/lock 独立审计，不等同于服务器依赖清单。两者均未变化时据实记录；任一变化时，必须逐项核对直接依赖、传递依赖和 npm 脚本，证明变更仅用于浏览器侧模块及其构建，目标服务器仍只发布静态资源，不新增 SSR、Node 服务、运行时 npm 安装或其他服务器依赖。兼容元数据显式记录 `frontend_manifests_unchanged=false`，绑定基线/目标提交、变更清单和审计证据；仅设置此字段不构成门禁通过；
4. 最小包来自干净目标提交，在该提交的前端目录完成 `npm ci`、`npm run check` 和 `npm run build` 并保留成功日志；只包含 ThreadSnap 自身 wheel、Vite 生产文件、随资源发布的第三方许可证、一次性安装/验证脚本与说明、兼容元数据和逐文件 SHA-256，不含 wheelhouse、Chromium、RPM、模型、凭证或 `node_modules`。检查压缩包内实际文件与构建产物一致、许可证完整入包，不以本机旧 dist 或既有 `node_modules` 代替本次构建证据；
5. 目标机文件系统支持 reflink，能够从当前不可变 release 建立独立的写时复制新 release；
6. 七类任务 `extraction_runs`、`circle_tasks`、`validation_jobs`、`sentiment_analyses`、`reputation_mapping_validation_runs`、`reputation_runs`、`reputation_delete_jobs` 均无活动。提取批次和圈子任务的 `queued`、`running`、`waiting_for_auth` 均阻止切换，其他类按各自状态枚举核对，未知或未识别的非终态同样阻止切换；逐类保留计数、状态和查询证据，不以单一 Worker 空闲代替七类检查。SQLite 完整性和当前/目标 Alembic 版本通过预检。

该路径只允许对 reflink 新 release 执行 `pip --no-index --no-deps --force-reinstall` 以替换 ThreadSnap 自身 wheel，前端直接替换为包内生产文件；不得运行 DNF、解析 wheelhouse、复制浏览器或模型。最终切换按以下顺序完成：停机前重查七类任务空闲，先停止 Nginx，再停止后端；停机后再次检查七类状态，确认没有预检后新入队或运行任务，再生成带完整性、Alembic 和 SHA-256 的 SQLite 备份；设置旧 release 为 `previous`、原子切换 `current`；依次启动并等待后端 `8000`、Nginx `8088`，完整验证窗口使用临时运行配置暂停调度与 Worker，并隔离外部请求和写入；执行完整 `deploy/verify.sh`、维护请求拦截探测及历史表校验后，恢复原运行配置与 Nginx，开放正常调度和入口，再单独验证公网。停机后空闲门未通过时保持旧 release 并恢复原服务；写入尚未开放时，备份后的迁移、切换、启动或验收失败同时恢复旧 release 和停机数据库。写入开放后，禁止用停机时的旧数据库备份覆盖当前数据库；无迁移的兼容更新可回退程序但保留新写入，其他情况停止自动回退并保留现场。

最小包不是新的安装基线：服务器仍须保留最近一次已校验的完整离线包、既有补充运行时离线包、当前/上一 release 和数据库备份，用于新机安装、服务器依赖变化、部署脚本变化和运行时修复。每次最小升级脚本是绑定明确基线提交、目标提交、数据库版本和包哈希的一次性受审产物；前端清单变化须通过上述独立审计，不得静默跳过原兼容性门禁，项目尚未提供可跳过这些门禁的通用“快速升级”命令。
