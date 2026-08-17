---
status: accepted
related: 0014-use-controlled-cdp-screencast-for-auth.md, 0017-package-v1-as-fully-offline-systemd-nginx-release.md
---

# CentOS Stream 10 使用 Weston 无头 Wayland 运行完整 Chromium

## Context

最终服务器实测为 CentOS Stream 10 x86_64。目标机启用 BaseOS、AppStream、CRB 和 EPEL 后仍不存在 `xorg-x11-server-Xvfb`；CentOS 与 RHEL 10 的发行说明明确记录 Xorg server 已移除。原 ADR 0017 中的 Xvfb 依赖无法在该目标基线上组装 RPM 闭包。

目标平台认证页在浏览器无头模式下返回 HTTP 200 零字节文档，因此认证流程仍需运行完整 Chromium 的有头模式，不能简单切回 `headless=true`。

## Decision

- 保持 ADR 0017 的完整离线包、systemd 单应用进程和 Nginx 边界，仅将显示实现从 Xvfb 修正为 Weston 无头 Wayland。
- 制包阶段启用 CentOS CRB 和 EPEL，离线包收集 Weston 及其 RPM 闭包；目标机安装仍使用 `dnf --disablerepo='*'`，不在线解析依赖。
- systemd 以 `threadsnap` 用户运行独立 `threadsnap-wayland.service`，创建权限为 `0700` 的 `/run/threadsnap-wayland`，并提供固定 `wayland-99` socket 与 `1280 × 800` 输出。
- 认证浏览器和 Session 刷新浏览器检测 `WAYLAND_DISPLAY` 后增加 `--ozone-platform=wayland`，Windows 桌面环境不增加该参数。
- Patchright 只下载完整 Chromium 与 FFmpeg，不再下载当前路径不使用的 Chromium headless shell。

## Consequences

- CentOS Stream 10 不再依赖已移除的 Xorg/Xvfb RPM，也不引入 VNC、CDP 或其他公网显示端口。
- Weston 的 EPEL/CRB RPM 闭包会增加离线包体积，但所有依赖仍由制包阶段冻结并校验。
- Linux 部署验收必须真实验证 Weston 服务、私有 Wayland socket、完整 Chromium 启动、认证画面与输入、会话续跑、重启和吞吐门禁。
