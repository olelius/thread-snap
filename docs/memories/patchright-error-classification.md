# Patchright通用Error必须在适配器边界分类

**根因**：Patchright 的页面导航、DOM 执行和截图等操作会抛出通用 `Error`；若适配器直接把该异常交给领域层，领域层只能看到类型名，既丢失具体阶段和底层文本，也不会进入只识别 `ReputationAdapterError(retryable=True)` 的一次有界重试。

**坑**：前端“真实页面验证异常：Error”不是平台返回内容，也不能据此判断为映射、Session、指标解析或证据文件故障。先检查结果的 `error_code`、`attempt_count` 和对应执行项证据目录；目录尚未创建说明失败早于证据写入。

**杠杆**：在 `DongchediReputationAdapter._visit()` 的 Patchright 边界维护当前阶段，把通用浏览器错误连同车型、阶段、类型和底层文本写入服务日志，再转换为不携带底层细节的稳定可重试业务错误；上下文关闭失败只记录日志，不能覆盖已确定的业务结果或原始异常。
