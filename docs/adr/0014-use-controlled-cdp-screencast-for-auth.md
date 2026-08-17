---
status: accepted
amended_by: 0018-use-headless-wayland-on-centos-stream-10.md
related: 0007-official-login-and-encrypted-platform-session.md
---

# 平台人工认证采用后端封装的 CDP Screencast

第一版平台人工认证画面采用 Patchright 创建的内部 `CDPSession`。提取后端在既有认证 WebSocket 内启动 `Page.startScreencast`、逐帧执行 `Page.screencastFrameAck`，并通过 CDP 输入域向同一受控 Chromium 页面发送指针事件；前端仍只持有短期认证任务票据和页面 WebSocket，不取得原始 CDP 端口、Target 地址或浏览器凭证。票据通过 `Sec-WebSocket-Protocol` 中不被服务端回显的 `threadsnap-ticket.<ticket>` 候选协议发送，后端只选择固定 `threadsnap-auth` 子协议，避免 URL 查询串进入 Uvicorn 和反向代理访问日志。

认证画面保持 `1280 × 800` 浏览器视口，Screencast 使用 JPEG 质量 85；前端按原始宽高比缩小显示，不主动放大超过源画面。画面发送采用单帧背压，客户端变慢时确认并丢弃未进入发送队列的新帧，不累计过时画面。输入通道覆盖持续移动、按下、释放、拖动、滚轮、普通文本、组合键和粘贴；高频移动在前端按动画帧合并，并在 WebSocket 发送缓冲增长时跳过中间位置。

该方案复用现有 Chromium、Patchright、FastAPI WebSocket、Profile、Session 和认证状态机，不增加 VNC Server、noVNC、websockify、视频编码器、WebRTC 信令或 STUN/TURN 服务。Patchright 作为认证模块直接导入的运行依赖在 `pyproject.toml` 中显式锁定版本，不依赖 Scrapling 的传递依赖关系。

## 取舍

- 旧的定时整帧截图方案在输入空闲超时后才生成 JPEG，形成约 700 毫秒固定等待，且没有持续鼠标移动、按下和释放事件，缺少完整 hover 与拖动体验。
- noVNC 能提供成熟的桌面级输入和增量画面，但需要额外部署虚拟桌面、VNC Server 和 WebSocket 代理，并扩大到整个虚拟桌面控制面。
- WebRTC 的连续视频延迟上限更低，但需要新增画面采集、实时编码、信令、PeerConnection、ICE 和输入数据通道，不属于只替换截图函数的局部改动。
- CDP 直接控制 Chromium 页面，额外组件最少，并与早期 SSH 隧道下已验证的 CDP 浏览器操作路径一致；代价是绑定 Chromium，且 `Page.startScreencast` 属于需要随锁定浏览器版本持续回归的实验接口。

## Consequences

- 原始 CDP 入口继续由后端进程内部持有；任何部署模式都不向客户机或公网开放调试端口。
- 反向代理必须保留 WebSocket 子协议头，但访问日志和错误日志不得记录完整 `Sec-WebSocket-Protocol` 请求头。
- Linux 上仍使用有头 Chromium。目标平台在当前无头模式返回零字节页面，因此目标部署仍需 Xvfb；这是页面运行条件，不是 CDP 传输新增的依赖。
- 第一版固定一个认证连接和一个最新待发画面，避免同一认证任务出现多个并发控制者；断开后仍按既有短期任务规则重新连接。
- 本地延迟冒烟只证明当前 Windows、回环网络和单连接路径可用，不形成公网、目标 Linux、高并发或固定帧率承诺。
- 以后若目标 Chromium 版本使 Screencast 或输入域失去稳定性，应以真实认证路径重新评审 noVNC；只有公网规模、连续高帧率或跨网络质量成为明确需求时才评审 WebRTC。
