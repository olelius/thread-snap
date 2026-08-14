# 第一版后端运行说明

## 1. 范围

该后端同时提供：

- `/api/v1`：第一版自建前端使用的页面 API；
- `/internal/v1`：后续客户现有后端使用的本机集成 API；
- 全局定时协调器、平台 FIFO Worker、懂车帝采集器、加密 Session、XLSX 模板和导出。

第一版只有懂车帝为 `available`。汽车之家和易车只返回 `not_integrated`，不创建提取任务。

## 2. 本地安装

使用项目虚拟环境：

```powershell
py -3.11 -m venv .vevn
.\.vevn\Scripts\python.exe -m pip install -e ".[dev]"
.\.vevn\Scripts\patchright.exe install chromium
Copy-Item .env.example .env
```

依赖均在 `pyproject.toml` 中使用精确版本。应用启动时自动执行 Alembic `upgrade head`，再写入缺失的平台和全局默认配置。

## 3. 配置

`.env.example` 只包含非敏感示例。默认 SQLite 数据库、模板、导出和自动生成的 Session 密钥都位于被 Git 忽略的 `data/`。

生产或迁移环境应通过 `THREADSNAP_SESSION_FERNET_KEY` 提供独立 Fernet 密钥，并限制 `.env`、数据库、密钥、浏览器 Profile 和导出目录的文件权限。Cookie、storage state 和其他凭证不得进入 Git、日志或前端响应。

## 4. 启动与检查

```powershell
.\.vevn\Scripts\threadsnap.exe serve --host 127.0.0.1 --port 8000
Invoke-RestMethod http://127.0.0.1:8000/health
```

需要让受控内网前端访问时，可以把页面 API 和认证 WebSocket 放在反向代理之后；代理必须阻止 `/internal/v1`。应用本身也拒绝非回环来源访问集成接口。

OpenAPI 页面位于 `http://127.0.0.1:8000/docs`。页面 API 和集成 API 使用相同稳定英文错误码，`message`、`details` 和 `reason` 由后端返回中文。

## 5. 导入已有平台会话

仅在部署初始化或受控运维时使用：

```powershell
.\.vevn\Scripts\threadsnap.exe import-session `
  --platform dongchedi `
  --file C:\SECURE_PATH\storage-state.json
```

正常业务使用 `/api/v1/platforms/dongchedi/auth/tasks` 创建短期认证任务，由前端通过返回的 WebSocket 入口操作服务器官方页面。后端不接收或保存平台账号密码。

懂车帝认证浏览器默认以有头模式运行，因为当前无头模式会收到 HTTP 200 零字节页面。Windows 本地运行时使用当前桌面会话；目标 Linux 部署必须在同一服务进程环境中提供 Xvfb，并在正式部署门禁中真实创建认证任务、确认 Dialog 收到非空画面和“页面可操作”状态。`THREADSNAP_AUTH_BROWSER_HEADLESS=true` 只用于已重新验证目标平台可正常返回认证页面的环境，不是当前推荐配置。

正式浏览器 Profile 保存为 `data/auth-profiles/<platform>/current.profile.enc` 加密归档；任务运行期间才解密到隔离任务目录。圈子样本门禁通过后才原子替换 Profile 和加密 Session，失败时保留旧版本。服务启动会清理异常退出遗留的任务目录，但仍应限制 `data/` 只允许服务账号访问，并确保所有 ThreadSnap 实例使用同一 `THREADSNAP_SESSION_FERNET_KEY`。

## 6. 验证命令

```powershell
.\.vevn\Scripts\python.exe -m unittest discover -s tests -v
.\.vevn\Scripts\ruff.exe format --check src tests
.\.vevn\Scripts\ruff.exe check src tests
.\.vevn\Scripts\python.exe -m compileall -q src tests
.\.vevn\Scripts\python.exe -m pip check
git diff --check
```

目标 CentOS 的连续三轮 2000 条、浏览器系统依赖、服务管理和离线包验证按 ADR 0011 保留为后续部署验收门禁。
