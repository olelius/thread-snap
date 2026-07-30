# 项目流控制

本目录是 ThreadSnap 对 `SPHINX998/forged-in-prod` 七种流程模式的 Codex 适配。采用的上游基线为 `31c80e763541e1526aa9f6ca8692bd344ddff62d`，许可说明见 `THIRD_PARTY_NOTICES.md`。

## 七种模式映射

| 上游模式 | ThreadSnap 落点 |
|---|---|
| 唯一任务账本 | 根目录 `WORKLOG.md` |
| 链条口径文档 | `docs/chains/` |
| 记忆 = 根因 + 坑 + 杠杆 | `docs/memories/` |
| 风险分级验证阶梯 | `docs/process/verification-ladder.md` |
| 多 Agent 纪律 | `AGENTS.md` 与 `docs/process/agent-receipt-template.md` |
| 反过度工程硬规则 | `AGENTS.md` |
| 长任务先排关键路径 | `AGENTS.md` |

可复用模板：

- `docs/process/worklog-entry-template.md`
- `docs/process/chain-template.md`
- `docs/process/agent-receipt-template.md`

## 自动化层

流程控制依赖三个层次：

1. **常驻规则**：Codex 通过根目录 `AGENTS.md` 得到唯一账本、恢复和验证规则。
2. **恢复读取**：上下文压缩、新会话或任务恢复后，先读取 `WORKLOG.md` 最新条目，再按 `docs/README.md` 加载对应 owner 文档。
3. **Git 兜底**：`.githooks/pre-commit` 检测已暂存代码变更；若没有同步暂存 `WORKLOG.md`，提交失败并给出修复提示。

Git hook 不是会话结束 hook，不能在上下文压缩前主动触发。它只防止“代码已提交、账本未同步”；恢复质量仍以 `AGENTS.md` 和最新账本条目为主。

## 安装本地 Git hook

Windows PowerShell：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-git-hooks.ps1
```

Linux、macOS、WSL 或 Git Bash：

```sh
sh scripts/install-git-hooks.sh
```

脚本只在当前仓库设置：

```text
core.hooksPath=.githooks
```

不会修改全局 Git 配置，也不会安装依赖。

## 使用纪律

- 最新 `WORKLOG.md` 条目必须让零上下文 Agent 直接知道总目标、证据、下一步和边界。
- 链档维护跨任务当前口径；详细证据不写进链档。
- 只有真实产生复用价值的根因或排障入口才写项目记忆，不创建空壳记忆。
- Agent 长日志放入被忽略的 `artifacts/runtime/`，主线程默认只消费短回执。
- 流程重量跟风险和当前决策门走，不把所有任务机械升级成多 Agent 或重型验证。
