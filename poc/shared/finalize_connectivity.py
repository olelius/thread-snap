"""汇总 Linux 网络基线与两个固定候选的低并发联通结果。"""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path


def load_json(path: Path) -> dict:
    """读取诊断 JSON；文件缺失或格式异常时保留可汇总状态。"""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def candidate_summary(result_dir: Path, candidate: str, exit_code: int) -> dict:
    """生成候选联通判断，至少一条真实帖子成功即可证明当前链路可达。"""

    base = result_dir / candidate
    login = load_json(base / "login-result.json")
    summary = load_json(base / "summary.json")
    success_count = int(summary.get("success_count", 0) or 0)
    logged_in = login.get("logged_in") is True
    return {
        "exit_code": exit_code,
        "logged_in": logged_in,
        "verification_required": login.get("verification_required"),
        "result_count": int(summary.get("result_count", 0) or 0),
        "success_count": success_count,
        "status_counts": summary.get("status_counts", {}),
        "response_class_counts": summary.get("response_class_counts", {}),
        "contract_error_count": int(summary.get("contract_error_count", 0) or 0),
        "connected": exit_code == 0
        and logged_in
        and success_count >= 1
        and int(summary.get("contract_error_count", 0) or 0) == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--preflight-exit", type=int, required=True)
    parser.add_argument("--healthcheck-exit", type=int, required=True)
    parser.add_argument("--network-exit", type=int, required=True)
    parser.add_argument("--candidate-a-exit", type=int, required=True)
    parser.add_argument("--candidate-b-exit", type=int, required=True)
    args = parser.parse_args()

    network = load_json(args.result_dir / "network.json")
    candidate_a = candidate_summary(args.result_dir, "candidate-a", args.candidate_a_exit)
    candidate_b = candidate_summary(args.result_dir, "candidate-b", args.candidate_b_exit)
    ready = bool(
        args.preflight_exit == 0
        and args.healthcheck_exit == 0
        and args.network_exit == 0
        and network.get("transport_ready") is True
        and candidate_a["connected"]
        and candidate_b["connected"]
    )
    if ready:
        next_action = "run_2000_url_test"
    elif args.preflight_exit != 0 or args.healthcheck_exit != 0:
        next_action = "repair_linux_runtime_or_browser_dependencies"
    elif args.network_exit != 0 or network.get("transport_ready") is not True:
        next_action = "inspect_dns_tcp_tls_or_http_network_path"
    elif (
        candidate_a["exit_code"] != 0
        or candidate_b["exit_code"] != 0
        or candidate_a["contract_error_count"] != 0
        or candidate_b["contract_error_count"] != 0
    ):
        next_action = "inspect_candidate_runtime_or_contract_error"
    elif not candidate_a["logged_in"] or not candidate_b["logged_in"]:
        next_action = "inspect_login_redirect_or_verification"
    else:
        next_action = "inspect_candidate_content_access_results"

    summary = {
        "schema_version": "1.0",
        "sample_scope": "maximum_3_urls",
        "preflight_exit_code": args.preflight_exit,
        "healthcheck_exit_code": args.healthcheck_exit,
        "network": {
            "exit_code": args.network_exit,
            "transport_ready": network.get("transport_ready", False),
            "dns_ok": network.get("dns", {}).get("ok", False),
            "tcp_ok": network.get("tcp", {}).get("ok", False),
            "tls_ok": network.get("tls", {}).get("ok", False),
            "http_ok": network.get("http", {}).get("ok", False),
            "http_status": network.get("http", {}).get("status"),
        },
        "candidate_a": candidate_a,
        "candidate_b": candidate_b,
        "ready_for_2000": ready,
        "next_action": next_action,
    }
    environment = {
        "schema_version": "1.0",
        "operating_system": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
    }
    (args.result_dir / "connectivity-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.result_dir / "environment.json").write_text(
        json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if ready else 3


if __name__ == "__main__":
    raise SystemExit(main())
