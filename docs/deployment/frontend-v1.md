# 第一版前端运行说明

## 1. 范围与来源

第一版前端位于 `frontend/`，采用 React、TypeScript、Vite、shadcn/ui、Tailwind CSS、TanStack Router、TanStack Query、TanStack Table、Lucide 和 Motion for React。浏览器只调用同源 `/api/v1`，不调用 `/internal/v1`，也不保存平台 Session 或认证票据。

应用外壳和 UI 原语选择性复用 MIT 许可的 `satnaing/shadcn-admin`：

- 固定提交：`e16c87f213a5ba5e45964e9b67c792105ec74d26`；
- 上游版本：`2.2.1`；
- 来源与裁剪记录：`frontend/THIRD_PARTY_NOTICES.md`；
- 许可证副本：`frontend/LICENSE`。

## 2. 本地安装与开发

后端先按 `docs/deployment/backend-v1.md` 启动在 `127.0.0.1:8000`，然后运行：

```powershell
Set-Location frontend
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1
```

开发服务器默认位于 `http://127.0.0.1:5173`，Vite 将 `/api` 和 `/health` 代理到本地后端。业务状态由 HTTP API 返回，SSE 只发送变化信号，认证画面与输入使用 WebSocket。

## 3. 生产构建

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run build
```

静态产物生成在 `frontend/dist/`，该目录与 `node_modules/` 都被 Git 忽略。发布时使用同一个受控内网源：

1. `/` 返回 `frontend/dist/`，并为 SPA 路由回退到 `index.html`；
2. `/api/v1`、`/api/v1/events` 和 `/api/v1/auth/.../stream` 转发到 FastAPI；
3. SSE 转发关闭代理缓冲并保留长连接；
4. WebSocket 转发保留 Upgrade/Connection 头；
5. `/internal/v1` 不通过前端入口发布。

第一版 Linux 部署依据 ADR 0017 固定使用 Nginx 和 systemd。前端生产构建直接进入完整离线包，前端静态文件在目标服务器运行期不依赖 Node.js；后端腾讯验证码IR组件按ADR 0060使用离线包安装的系统Node.js。Nginx 配置、同源代理、SSE、WebSocket、`/internal/v1` 屏蔽和 SPA 回退模板位于 `deploy/linux/nginx/threadsnap.conf`，完整流程见 `docs/deployment/linux-v1.md`。

## 4. 验证

```powershell
Set-Location frontend
npm.cmd run check
npm.cmd run build
```

真实页面验收还需启动前后端并覆盖：提取列表、新建提取 Sheet、批次详情、帖子快照 Sheet、五个配置标签、平台认证 Dialog、深浅主题、导航收缩、配置草稿离页保护，以及 1024、768 和低于 768 像素的响应式边界。控制台应无 error/warning，页面正文不产生横向溢出；数据表格允许在自己的容器内横向滚动。
