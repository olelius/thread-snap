# 第三方来源说明

ThreadSnap 前端选择性复用了 `satnaing/shadcn-admin` 的主题、响应式 Sidebar 与
shadcn/ui 基础组件源代码，并在其上实现本项目业务页面。

- 上游仓库：https://github.com/satnaing/shadcn-admin
- 固定提交：`e16c87f213a5ba5e45964e9b67c792105ec74d26`
- 上游版本：`2.2.1`
- 许可证：MIT
- 上游作者：Sat Naing
- 本地许可证副本：`frontend/LICENSE`

未复用 Clerk、示例登录、用户管理、图表、示例数据与无关 SaaS 页面。

工作区命令面板使用 Headless UI React 的无样式 `Dialog` 与 `Transition` 原语：

- 上游仓库：https://github.com/tailwindlabs/headlessui
- 当前包：`@headlessui/react@2.2.10`
- 许可证：MIT
- 使用边界：只负责命令面板焦点管理、遮罩关闭与过渡，不替换既有 Radix/shadcn 业务控件。
