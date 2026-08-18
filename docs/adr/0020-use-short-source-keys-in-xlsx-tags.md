---
status: superseded
---

# XLSX 模板使用可逆短来源键

> 本决策已由 ADR 0021 替代；这里保留 22 位可逆来源键方案的历史依据。

## Context

ADR 0019 为区分同圈不同列表顺序，把模板标签改为 `platform.<platform_code>.source.<source_id>.<field>`。该格式能够稳定寻址，但同时重复平台代码、固定单词和 36 位 UUID，标签过长；来源名称字段还形成 `source.<source_id>.source.name` 的重复层次。`vehicle.name` 又与当前“来源名称”领域术语冲突。第一版正式数据会在交付前清理，没有需要保留的模板版本或导出记录。

## Decision

1. 新模板统一生成 `source.<source_key>.<field>` 标签。
2. `source_key` 使用来源 UUID 全部 128 位的无填充 URL-safe Base64 编码，固定 22 位，可逆还原且不采用存在碰撞可能的截断摘要。
3. 来源自身字段在新标签中使用 `id`、`name`、`list_order`、`list_order_name`；解析后映射到现有 `source.*` 字段语义。其他后缀保持 `circle.*`、`post.*` 和 `comments.*`。
4. 删除 `vehicle.name` 字段，不再生成或解析该字段。
5. 只接受短来源键格式；`platform.<platform_code>.source.<source_id>.<field>` 与 `platform.<platform_code>.circle.<circle_id>.<field>` 均不进入解析器。

## Consequences

- 新标签不重复平台代码和 UUID 文本，来源名称示例由 `platform.dongchedi.source.<uuid>.source.name` 缩短为 `source.<22位短键>.name`。
- 标签仍只依赖稳定来源身份，不依赖可修改或可能重复的用户来源名称，也无需数据库迁移或新增可编辑别名。
- 解析器只有一种标签格式，不新增数据库迁移或兼容分支；清理数据后创建的模板统一使用短标签。
