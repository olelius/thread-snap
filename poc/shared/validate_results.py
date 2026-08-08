"""统一校验两个候选的 JSONL 结果并生成同结构摘要。"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from contract import validate_result


def load_nonempty_lines(path: Path) -> list[str]:
    """读取 UTF-8 文本中的非空行。"""

    return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def load_jsonl(path: Path) -> list[dict]:
    """加载 JSONL，错误中保留精确行号。"""

    records: list[dict] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"第 {line_no} 行不是合法 JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"第 {line_no} 行必须是 JSON 对象")
        records.append(value)
    return records


def validate_file(records: list[dict], expected_urls: list[str], candidate: str) -> list[str]:
    """验证记录集合与输入清单的一一对应关系。"""

    errors: list[str] = []
    actual_urls: list[str] = []
    for index, record in enumerate(records, start=1):
        actual_urls.append(record.get("url", ""))
        errors.extend(f"记录 {index}: {message}" for message in validate_result(record, candidate))
    duplicate_urls = sorted(url for url, count in Counter(actual_urls).items() if count > 1)
    if duplicate_urls:
        errors.append(f"结果包含 {len(duplicate_urls)} 个重复 URL")
    expected_set = set(expected_urls)
    actual_set = set(actual_urls)
    if missing := expected_set - actual_set:
        errors.append(f"结果缺少 {len(missing)} 个输入 URL")
    if extra := actual_set - expected_set:
        errors.append(f"结果包含 {len(extra)} 个清单外 URL")
    return errors


def build_summary(records: list[dict], candidate: str, input_count: int, errors: list[str]) -> dict:
    """按 PoC 硬门禁字段生成候选无关的汇总。"""

    status_counts = Counter(record.get("status") for record in records)
    response_counts = Counter(record.get("response_class") for record in records)
    success_count = status_counts["success"]
    id_match_count = sum(record.get("post_id_matches") is True for record in records)
    proof_count = sum(record.get("title_present") is True or record.get("body_present") is True for record in records)
    unrecovered_controls = sum(record.get("status") == "blocked" for record in records)
    denominator = input_count or 1
    return {
        "schema_version": "1.0",
        "candidate": candidate,
        "input_count": input_count,
        "result_count": len(records),
        "success_count": success_count,
        "status_counts": dict(sorted(status_counts.items())),
        "response_class_counts": dict(sorted(response_counts.items())),
        "final_completion_rate": success_count / denominator,
        "post_id_match_rate": id_match_count / denominator,
        "content_proof_rate": proof_count / denominator,
        "unrecovered_control_count": unrecovered_controls,
        "contract_error_count": len(errors),
        "passed": not errors
        and len(records) == input_count
        and success_count == input_count
        and id_match_count == input_count
        and proof_count == input_count
        and unrecovered_controls == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-list", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    all_inputs = load_nonempty_lines(args.input_list)
    if args.expected_count < 1 or args.expected_count > len(all_inputs):
        raise ValueError("expected-count 超出输入清单范围")
    expected_urls = all_inputs[: args.expected_count]
    records = load_jsonl(args.results)
    errors = validate_file(records, expected_urls, args.candidate)
    summary = build_summary(records, args.candidate, len(expected_urls), errors)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
