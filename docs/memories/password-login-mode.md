# 登录页必须显式切换到密码登录

**根因**：目标登录页默认展示手机验证码模式；检测到验证码输入框后点击页面最后一个按钮，不能证明已经切换到账号密码表单。必须点击可见且文字精确为“密码登录”的选项，并等待账号、密码输入框可见后再提交。

**坑**：crawler 报告一次请求成功只表示登录页请求处理完成；若 `login-result.json` 仍为 `logged_in=false` 且逐 URL `request_count=0`，不能解释为帖子访问成功或框架吞吐结果。

**杠杆**：先检查 `login-result.json` 的 `password_login_selected`、`submitted` 和 `logged_in`，再检查逐 URL `request_count`；前两项为真而登录仍失败时才继续分析验证或账号提示。
