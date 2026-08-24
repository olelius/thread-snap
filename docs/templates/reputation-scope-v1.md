# 口碑巡检车型初始化 CSV Schema v1

文件必须使用 UTF-8（允许 BOM），第一行必须与同目录 `reputation-scope-v1.csv` 完全一致，数据区必须恰好包含 27 行。

| 字段 | 规则 |
|---|---|
| `schema_version` | 固定填写 `reputation-scope-v1` |
| `seed_key` | 不可变内部车型 ID，27 行全局唯一 |
| `series_name` | 车系展示名 |
| `vehicle_name` | 车型展示名 |
| `role` | `focus` 或 `competitor`；分别恰好 14、13 行 |
| `role_order` | 角色组内从 1 开始连续编号 |
| `platform_code` | 当前固定 `dongchedi` |
| `platform_vehicle_id` | 平台稳定车型 ID；导入后仍是待验证映射 |
| `platform_url` | 车型口碑页面 URL |
| `platform_display_name` | 页面可见车型名称 |

初始化命令：

```powershell
& .\.vevn\Scripts\threadsnap.exe reputation-init --file <CSV绝对路径>
```

命令会在数据库中不存在口碑范围时原子创建草稿并保存原始字节 SHA-256；不会把源 CSV 复制进数据目录或仓库。
