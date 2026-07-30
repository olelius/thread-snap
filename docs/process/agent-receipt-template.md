# Agent 短回执模板

仅用于确有必要的多 Agent 调查或独立 worktree 实现。详细过程放入 `artifacts/runtime/agents/<task>/`，主线程先消费短回执。

```yaml
verdict: confirmed | rejected | blocked
relevant_to: <关闭哪个当前阶段门或验收条件>
baseline_identity: <commit、输入清单哈希、构建或部署身份>
evidence_scope: <检查范围、已知总量、排除项、穷尽或抽样声明>
verification: <精确命令或请求入口、退出状态、关键结果>
artifact_path: <artifacts/runtime/agents/...>
invalidate_if: <哪些代码、输入或环境变化会使证据失效>
needs_main_now: yes | no
```

## 回执要求

- 正向存在性结论可使用精确文件与行号；否定或完备性结论必须说明搜索范围和分母。
- `verdict: confirmed` 只在声明的覆盖范围内成立，抽样结果不得升级成全量结论。
- 失败或超时使用 `blocked`，并说明当前阶段门是否继续阻塞。
- runtime artifact 是临时证据，不是活动账本、链档或长期事实 owner。
- 主线程在高风险、冲突、抽查失败、回执不足或失效条件无法判断时打开完整 artifact；其他情况不重复读取全部过程。
- 多个分支通过后，仍需在整合基线真实驱动组合目标路径。
