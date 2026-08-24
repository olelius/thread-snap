# ADR 0029：按模型能力采用独立结构化输出适配

- 状态：已接受
- 日期：2026-08-24

## 背景

DeepSeek 文字舆情使用 `response_format=json_object` 时，两次真实批次的首次结构违约率均为 3.33%。新批次 `20260824-115511-001` 的一条响应首次少括号、纠正后又形成合法 JSON 中 `summary` 错层，说明针对单一坏 JSON 形状的恢复不能消除生成侧结构缺陷。

对当前正式 `https://api.deepseek.com` 与 `deepseek-v4-flash` 的能力探测确认：普通 `response_format=json_schema` 返回 HTTP 400；`/beta/chat/completions` 的 Strict Tool Calling 会拒绝非法 Schema，7/7 次有效调用均严格通过，其中包含 2 次流式调用和 2 次完整文字舆情合同验证。

## 决定

1. 结构化输出按受控模型单独适配，不把某一提供方能力推定给其他模型。
2. 千问多模态继续使用现有 `response_format=json_object`、普通消息正文聚合、完整模态合同和有界纠正。
3. DeepSeek 文字模型改用 `/beta/chat/completions`，通过单一强制函数 `submit_sentiment_feedback`、`strict=true` 和固定 `tool_choice` 生成结构化参数；流式客户端只接受唯一函数的 `arguments` 与 `finish_reason=tool_calls`。
4. DeepSeek 原生参数只保留模型负责的相关性、命中对象、情感、分类、文字依据和总结。文字处理状态以及图片、视频画面、视频音频未参与分析的数量与状态由后端根据实际输入确定性补齐。
5. Strict Tool 返回仍需从零通过本地 Pydantic、业务关系和输入身份校验。结构正确但关系违约时最多追加一次保留原输入、候选哈希和具体错误的严格工具纠正；传输、429 和流结束规则继续有界，不形成无限循环。
6. Strict Tool 仅作为结构化输出传输，不开放模型自主选工具，不执行外部动作，也不引入 Agent、RAG、联网搜索或多模型裁决。

## 结果

- DeepSeek 的括号、层级、必填字段、类型、枚举和额外字段由提供方严格工具 Schema 在生成阶段约束，不再依赖猜测式坏 JSON 修复。
- 固定 Schema 替代重复格式说明，最小原生参数减少完成 Token；格式纠正调用从正常路径移除。
- 代理若不实现 DeepSeek Beta Strict Tool，配置测试会失败并保持分析关闭，不能静默回退到弱约束后宣称严格输出。
- 本决定替代 ADR 0027 中仅针对 DeepSeek 单括号形状的生产恢复路径；ADR 0027 对历史审计和其他 JSON Object 模型的有界原则仍保留。
