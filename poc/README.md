# ThreadSnap 采集框架 PoC

本目录只保存技术选型阶段的可复现代码和合成测试夹具。真实 URL、页面响应、逐 URL 结果和运行日志继续放在被 Git 忽略的 `artifacts/poc/` 或 `artifacts/runtime/`。

## 目录

- `shared/`：确定性抽样、统一结果契约、校验器和跨候选分类夹具；
- `candidate-a/`：Scrapling 的 HTTP 优先、动态页面回退冒烟；
- `candidate-b/`：Crawlee CheerioCrawler 的 HTTP 优先、PlaywrightCrawler 回退冒烟。

当前代码只覆盖阶段 1 的最小访问冒烟和统一结果验证，不是正式业务采集器，也不代表第一版功能完成。

## Python 环境

项目 Python 固定使用仓库根目录 `.vevn`：

```powershell
python -m venv .vevn
.\.vevn\Scripts\python.exe -m pip install -r .\poc\candidate-a\requirements.lock
```

除创建虚拟环境本身外，不使用全局 Python 安装或运行项目依赖。

## 固定首轮清单

```powershell
.\.vevn\Scripts\python.exe .\poc\shared\select_inputs.py `
  --pool .\artifacts\poc\inputs\throughput-urls.txt `
  --output .\artifacts\poc\inputs\round-1-urls.txt `
  --manifest .\artifacts\poc\inputs\round-1-manifest.json `
  --seed threadsnap-poc-round-1-20260808-v1 `
  --count 2000
```

抽样算法按 `SHA-256(seed + NUL + URL)` 排序取前 N 条，并强制使用 LF 写出，因此相同输入、种子和脚本版本在 Python/Node 和 Windows/Linux 上都能复现同一清单。

## 冒烟与校验

候选 A：

```powershell
.\.vevn\Scripts\python.exe .\poc\candidate-a\src\smoke.py `
  --input .\artifacts\poc\inputs\round-1-urls.txt `
  --output-dir .\artifacts\poc\results\candidate-a\smoke-001 `
  --limit 3
```

候选 B：

```powershell
npm.cmd --prefix .\poc\candidate-b ci
npm.cmd --prefix .\poc\candidate-b run smoke -- `
  --input ..\..\artifacts\poc\inputs\round-1-urls.txt `
  --output-dir ..\..\artifacts\poc\results\candidate-b\smoke-001 `
  --limit 3
```

统一校验：

```powershell
.\.vevn\Scripts\python.exe .\poc\shared\validate_results.py `
  --input-list .\artifacts\poc\inputs\round-1-urls.txt `
  --results .\artifacts\poc\results\candidate-a\smoke-001\url-results.jsonl `
  --candidate candidate-a `
  --expected-count 3 `
  --summary .\artifacts\poc\results\candidate-a\smoke-001\summary.json
```

校验器只在结果满足统一字段、URL 对应、状态一致性、帖子 ID 匹配和内容证明规则时退出 0。登录页、验证码、挑战页、限流页和异常空响应不会计为成功。
