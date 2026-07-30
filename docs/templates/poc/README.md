# ThreadSnap PoC 甲方测试清单填写说明

- 模板版本：1.0
- 适用范围：第一版懂车帝 PoC

本目录包含甲方需要填写并返回的两份 PoC 输入模板：

1. `throughput-urls-template.txt`：用于 2000 URL/小时吞吐测试；
2. `functional-samples-template.csv`：用于功能模块、状态和字段正确性测试。

项目提供的可直接发送压缩包为：

`threadsnap-poc-client-input-templates-v1.0.zip`

填写完成后建议另存为：

- `throughput-urls.txt`
- `functional-samples.csv`

不要覆盖仓库中的模板文件。

## 1. 吞吐 URL 清单

文件：`throughput-urls-template.txt`

填写规则：

- 使用 UTF-8 纯文本；
- 每行填写一个完整帖子 URL；
- 删除模板中的 `URL_000001` 等占位内容；
- 至少提供 2000 个不同 URL；
- URL 必须在测试开始前由甲方确认有效；
- 不得通过重复 URL 补足数量；
- 不填写标题、序号、逗号、备注或其他列；
- URL 中不得包含账号、密码、Cookie、令牌等凭证；
- 空行可以忽略，但建议删除。

示意：

```text
https://TARGET/thread/000001
https://TARGET/thread/000002
```

上面的地址仅用于说明格式，不属于测试数据。

## 2. 功能样本清单

文件：`functional-samples-template.csv`

每行对应一个功能验证样本。CSV 使用 UTF-8 编码，第一行字段名不得修改。

| 字段 | 必填 | 填写规则 |
|---|---|---|
| `sample_id` | 是 | 甲方自定义唯一编号，例如 `SAMPLE_001` |
| `module` | 是 | 功能模块或样本类型，例如 `normal_post`、`hidden_post`、`comments_lt_10` |
| `url` | 是 | 完整帖子 URL |
| `expected_visibility` | 是 | `visible`、`hidden` 或 `unknown` |
| `expected_body_present` | 是 | `yes`、`no` 或 `unknown` |
| `comment_case` | 是 | 一级评论档位：`zero`、`less_than_10`、`at_least_10` 或 `unknown` |
| `login_required` | 是 | `yes`、`no` 或 `unknown` |
| `confirmed_at` | 是 | 人工确认时间，使用带时区 ISO 8601，例如 `2026-07-30T14:30:00+08:00` |
| `notes` | 否 | 补充说明；内容含逗号、双引号或换行时使用标准 CSV 引号 |

示意行：

```csv
SAMPLE_001,normal_post,https://TARGET/thread/000001,visible,yes,less_than_10,no,2026-07-30T14:30:00+08:00,普通可见帖子
```

示意行不写入正式清单。

## 3. 模块覆盖规则

- 同一模块可以提供多条样本；
- 某个模块只有一条样本时仍可测试，但结论只适用于该样本；
- 建议覆盖正常帖子、评论少于十条、评论不少于十条、隐藏或删除状态、图片、视频、长正文和特殊字符；
- 未登录优先；确需登录的样本在 `login_required` 中标记；
- 测试开始前重新确认 URL、可见状态和评论档位，避免样本状态已经变化。

## 4. 返回前检查

- 两个文件均使用 UTF-8；
- 吞吐清单至少包含 2000 个不同且有效的完整 URL；
- 功能样本 CSV 没有修改字段名；
- 没有保留 `URL_000001` 等占位内容；
- 没有账号、密码、Cookie 或令牌；
- 文件可以正常打开且没有乱码。

## 5. 项目收到文件后的固定路径

甲方返回文件后，由项目负责人统一保存为：

```text
artifacts/poc/inputs/throughput-urls.txt
artifacts/poc/inputs/functional-samples.csv
```

该目录只在本地保存，不提交 Git。
