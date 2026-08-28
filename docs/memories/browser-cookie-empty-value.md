# 浏览器Cookie空值不是Session结构缺失

**根因**：浏览器 `storage_state` 可以导出 `value=""` 的合法Cookie；Session结构校验应要求`value`键存在且类型为字符串，而不是用真假值判断非空。

**坑**：用 `all(item.get(key))` 同时检查`name/value/domain/path`会把空值Cookie误判为损坏状态；异常若落入认证浏览器总兜底，还会把门禁后的Session保存问题错误显示成页面加载失败和中继断开。

**杠杆**：先看认证任务的`http_status`、`error_code`和 `SessionStore.validate_state`，再按页面加载、登录门禁、状态结构和加密持久化四个阶段定位；日志只记录平台和异常类型，不记录Cookie内容。
