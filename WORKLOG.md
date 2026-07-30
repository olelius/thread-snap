# WORKLOG — 唯一任务账本

<!--
规则：
1. 仓库只保留这一份活动任务账本；最新条目永远放在最上方。
2. 动代码必须更新条目；纯讨论、调研或未改代码的任务不记。
3. 每条只保留总目标、当前状态、验证证据、下一步和必要边界。
4. 上下文压缩、新会话或任务恢复后，先读最新条目，不重查其中已有可复核证据的事实。
5. 详细规范、决策和长日志分别归入 owner 文档、ADR 或被忽略的 runtime artifact，不复制到这里。
-->

## ⏳ 待你裁决

- 暂无。

---

## 2026-07-30 — 对齐 forged-in-prod 项目流控制

**总目标**：将 ThreadSnap 的项目恢复、决策传递、验证、多 Agent、反过度工程和长任务控制规则，与 `SPHINX998/forged-in-prod` 的七种模式保持方法一致，同时适配 Codex 和现有仓库文档，不引入 Claude 专用平行配置。

**状态**：✅ 完成

**干到哪了**：

- [x] 固定上游基线为 `31c80e763541e1526aa9f6ca8692bd344ddff62d`；证据：`git ls-remote` 与临时浅克隆的 `git rev-parse HEAD` 一致。
- [x] 核对上游七种模式、五个模板、starter 规则、PowerShell/Unix 安装器和 Claude Stop hook；证据：临时克隆文件树共包含根方法论、`starter/` 和 `templates/`。
- [x] 确认不能直接运行上游 starter；证据：starter 写入 `CLAUDE.md`、`.claude/settings.json` 和 Claude `Stop` hook，会与本项目的 `AGENTS.md` 和现有进度入口形成平行事实源。
- [x] 建立根目录唯一账本、首个平台链档、验证阶梯、记忆门槛、Agent 回执、反过度工程和长任务规则；证据：`docs/process/README.md` 对七种模式逐项映射，旧 `current-progress.md` 已迁移且无残留引用。
- [x] 建立 Codex/Git 兜底；证据：PowerShell 与 Unix 安装脚本均将当前仓库 `core.hooksPath` 校验为 `.githooks`，两个 shell 文件通过 `sh -n`。
- [x] 完成 hook 正反测试；证据：隔离临时仓库中，只有 `sample.py` 时提交退出码为 1，补充并暂存 `WORKLOG.md` 后提交退出码为 0。
- [x] 完成仓库检查；证据：27 个文本文件通过 UTF-8 严格解码，18 个流程必需路径存在，5 个 ADR 均为 `accepted`，PoC/runtime 忽略规则、陈旧路径扫描和 `git diff --check` 通过。
- [x] 修正产品设计末尾遗留的 CSV/XLSX 冲突；证据：功能正文与商务范围现统一为从数据库快照导出 XLSX。

**下一步**：等待甲方提供懂车帝固定样本清单和最终 Linux 主机环境信息，再按 `docs/chains/first-platform-delivery.md` 与 PoC 计划启动两个候选原型。

**边界**：不复制 `.claude/`；不声称 Git pre-commit hook 等同于 Claude 的会话结束 hook；不为尚未发生的事故编造项目记忆。

**关联**：分支 `docs/forged-workflow-control`；ADR `docs/adr/0005-adopt-forged-in-prod-workflow-control.md`。

---

## 2026-07-30 — 完善项目文档读取与事实源规则

**总目标**：让新任务按类型读取正确的仓库事实源，避免只依赖 `AGENTS.md`、历史对话或全局记忆。

**状态**：✅ 完成

**干到哪了**：

- [x] 新增 `docs/README.md` 文档索引并补充 `AGENTS.md` 强制读取矩阵；证据：PR #2 已合并，merge commit 为 `a686ad5c3c38ba2b60319d1ad998796843b5f81f`。
- [x] 完成 UTF-8、引用路径、ADR 状态、PoC 忽略规则和 `git diff --check` 检查。

**下一步**：由本条上方的新任务接管，不再维护第二份当前进度文档。
