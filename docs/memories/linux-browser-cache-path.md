# Linux 浏览器缓存路径必须贯穿安装与运行

**根因**：`install.sh` 在 `PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers` 下安装浏览器后，所有健康检查、联通和吞吐入口都必须在候选启动前导出同一路径；否则 Playwright 会回退到用户级 `~/.cache/ms-playwright` 并报告浏览器可执行文件不存在。

**坑**：浏览器健康检查通过只证明带正确环境变量的检查入口可启动，不能证明后续候选入口继承了同一个路径。CentOS 的 fallback build 警告与本次失败无直接因果关系。

**杠杆**：先比较 `install.sh`、`healthcheck.sh`、`test-connectivity.sh` 和 `run-poc.sh` 中 `PLAYWRIGHT_BROWSERS_PATH` 的导出位置，再读取候选日志中实际查找的浏览器绝对路径；包内路径应始终指向 `<package>/.runtime/browsers`。
