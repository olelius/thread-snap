"""后续平台 500 条接入验收的文件合同、纯校验器和命令行入口。"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import platform
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Protocol
from urllib.parse import urlsplit

SCHEMA_VERSION = "1.0"
HARNESS_VERSION = "1.0"
PRECHECK_POLICY_VERSION = "1.0"
FORMAL_COUNT = 500
SELECTION_ALGORITHM = (
    "verified stable post ids grouped by source; each source ranks by "
    "sha256(seed + NUL + platform_post_id); stable source round-robin"
)
LIST_ORDERS = frozenset({"latest_reply", "latest_publish"})
SOURCE_STATUSES = frozenset(
    {"verified", "list_order_missing_confirmed", "source_missing_confirmed", "failed"}
)
NORMALIZED_STATUSES = frozenset({"visible", "hidden", "unknown"})
CONTROL_CLASSES = frozenset({"login", "captcha", "challenge", "rate_limited"})
RESPONSE_CLASSES = frozenset(
    {
        "post",
        "not_found",
        "login",
        "captcha",
        "challenge",
        "rate_limited",
        "empty",
        "wrong_post",
        "network_error",
        "timeout",
        "response_invalid",
        "error",
        "not_requested",
    }
)
SCENARIO_TAGS = (
    "text_post",
    "image_post",
    "video_post",
    "mixed_media_post",
    "comments_zero",
    "comments_1_9",
    "comments_10_plus",
    "status_visible",
    "status_hidden_deleted",
    "status_unknown",
    "access_anonymous",
    "access_auth_required",
    "access_auth_expired",
    "platform_control",
    "long_body",
    "special_characters",
    "cross_page_discovery",
    "duplicate_candidate",
    "pagination_end",
)
CORE_RUN_FILES = frozenset(
    {
        "input-urls.txt",
        "url-results.jsonl",
        "request-events.jsonl",
        "summary.json",
        "environment.json",
        "run.log",
        "functional-samples.jsonl",
        "acceptance-manifest.json",
        "sources.json",
    }
)
SENSITIVE_KEYS = frozenset(
    {"password", "cookie", "cookies", "token", "access_token", "refresh_token", "session"}
)


class AcceptanceError(RuntimeError):
    """携带稳定错误码的验收工具异常。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class AcceptanceProvider(Protocol):
    """正式适配器注册表提供给验收工具的最小桥接协议。"""

    platform_code: str
    adapter_version: str

    def discover_sources(
        self, community_seeds: list[dict[str, Any]], evidence_dir: Path
    ) -> list[dict[str, Any]]: ...

    def discover_candidates(
        self,
        sources: list[dict[str, Any]],
        *,
        access_mode: str,
        concurrency: int,
    ) -> dict[str, list[dict[str, Any]]]: ...

    def run_acceptance(
        self,
        urls: list[str],
        *,
        manifest: dict[str, Any],
        access_mode: str,
        concurrency: int,
    ) -> dict[str, Any]: ...


def utc_now() -> str:
    """返回带 UTC 时区的 ISO 8601 时间。"""

    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(payload: bytes) -> str:
    """返回字节内容的小写 SHA-256。"""

    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """流式计算文件 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_git_commit() -> str | None:
    """读取当前工作树提交；非 Git 环境返回空值。"""

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def environment_identity() -> dict[str, Any]:
    """生成不含凭证的轻量运行环境身份。"""

    return {
        "operating_system": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
    }


def _reject_sensitive_keys(value: Any, location: str = "root") -> None:
    """拒绝把明显的可复用凭证字段写入验收产物。"""

    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                raise AcceptanceError("SENSITIVE_FIELD", f"{location} 包含敏感字段 {key!r}")
            _reject_sensitive_keys(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive_keys(item, f"{location}[{index}]")


def _ensure_new_paths(*paths: Path) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise AcceptanceError("OUTPUT_EXISTS", f"冻结或轮次产物已存在：{', '.join(existing)}")


def _write_new(path: Path, payload: bytes) -> None:
    _ensure_new_paths(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def write_json_new(path: Path, value: Any) -> None:
    """以稳定 UTF-8/LF JSON 写入新文件。"""

    _reject_sensitive_keys(value)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    _write_new(path, payload)


def write_jsonl_new(path: Path, records: Iterable[dict[str, Any]]) -> None:
    """以 UTF-8/LF 写入 JSONL 新文件。"""

    items = list(records)
    _reject_sensitive_keys(items)
    payload = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for item in items
    ).encode()
    _write_new(path, payload)


def write_lf_new(path: Path, lines: list[str]) -> str:
    """写入 UTF-8/LF 新文件并返回 SHA-256。"""

    payload = ("\n".join(lines) + "\n").encode()
    _write_new(path, payload)
    return sha256_bytes(payload)


def load_json(path: Path) -> Any:
    """读取 JSON 并把解析错误归一为稳定错误。"""

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError("JSON_INVALID", f"JSON 文件读取失败：{path}：{exc}") from exc


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL，并保留精确行号。"""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise AcceptanceError("JSONL_INVALID", f"JSONL 文件读取失败：{path}：{exc}") from exc
    output: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AcceptanceError(
                "JSONL_INVALID", f"{path} 第 {line_number} 行不是合法 JSON：{exc}"
            ) from exc
        if not isinstance(item, dict):
            raise AcceptanceError("JSONL_INVALID", f"{path} 第 {line_number} 行必须是对象")
        output.append(item)
    return output


def read_urls_strict(path: Path, expected_count: int | None = None) -> list[str]:
    """严格读取冻结 URL：UTF-8、无 BOM、仅 LF、非空、HTTPS、字面唯一。"""

    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise AcceptanceError("INPUT_READ_FAILED", f"输入清单读取失败：{path}：{exc}") from exc
    if payload.startswith(b"\xef\xbb\xbf"):
        raise AcceptanceError("INPUT_ENCODING_INVALID", "冻结清单带有 UTF-8 BOM")
    if b"\r" in payload:
        raise AcceptanceError("INPUT_LINE_ENDING_INVALID", "冻结清单必须只使用 LF")
    if not payload.endswith(b"\n"):
        raise AcceptanceError("INPUT_LINE_ENDING_INVALID", "冻结清单末尾必须保留 LF")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AcceptanceError("INPUT_ENCODING_INVALID", "冻结清单不是 UTF-8") from exc
    raw_lines = text.split("\n")
    if raw_lines[-1] != "":
        raise AcceptanceError("INPUT_LINE_ENDING_INVALID", "冻结清单末尾结构无效")
    lines = raw_lines[:-1]
    if not lines or any(not line or line != line.strip() for line in lines):
        raise AcceptanceError("INPUT_URL_INVALID", "冻结清单包含空行或行首尾空白")
    if expected_count is not None and len(lines) != expected_count:
        raise AcceptanceError(
            "INPUT_COUNT_MISMATCH", f"冻结清单应为 {expected_count} 行，实际为 {len(lines)} 行"
        )
    if len(set(lines)) != len(lines):
        raise AcceptanceError("INPUT_URL_DUPLICATED", "冻结清单包含重复 URL")
    for url in lines:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise AcceptanceError("INPUT_URL_INVALID", f"冻结清单包含非 HTTPS URL：{url!r}")
    return lines


def load_provider(platform_code: str) -> AcceptanceProvider:
    """延迟加载生产采集器注册表中的离线验收桥。"""

    try:
        registry = importlib.import_module("threadsnap.collectors.registry")
    except ModuleNotFoundError as exc:
        if exc.name == "threadsnap.collectors.registry":
            raise AcceptanceError(
                "PROVIDER_REGISTRY_UNAVAILABLE",
                "生产采集器注册表 threadsnap.collectors.registry 尚未进入当前基线。",
            ) from exc
        raise
    factory = getattr(registry, "get_acceptance_provider", None)
    if not callable(factory):
        raise AcceptanceError(
            "PROVIDER_FACTORY_UNAVAILABLE",
            "生产采集器注册表缺少 get_acceptance_provider(platform_code)。",
        )
    provider = factory(platform_code)
    if provider is None:
        raise AcceptanceError("PROVIDER_NOT_FOUND", f"平台 {platform_code} 没有验收 Provider")
    return provider


def _provider_identity(provider: AcceptanceProvider, platform_code: str) -> tuple[str, str]:
    actual_platform = str(getattr(provider, "platform_code", ""))
    adapter_version = str(getattr(provider, "adapter_version", ""))
    if actual_platform != platform_code:
        raise AcceptanceError(
            "PROVIDER_PLATFORM_MISMATCH",
            f"Provider 平台为 {actual_platform!r}，期望 {platform_code!r}",
        )
    if not adapter_version:
        raise AcceptanceError("ADAPTER_VERSION_MISSING", "Provider 未声明 adapter_version")
    return actual_platform, adapter_version


def _validate_provider_execution(
    provider: AcceptanceProvider, *, access_mode: str, concurrency: int
) -> None:
    """在调用生产桥前验证其已声明的访问模式与安全并发。"""

    supported_modes = getattr(provider, "supported_access_modes", None)
    if supported_modes is not None and access_mode not in supported_modes:
        raise AcceptanceError(
            "ACCESS_MODE_UNSUPPORTED", f"Provider 尚未证明访问模式 {access_mode!r}"
        )
    max_concurrency = getattr(provider, "max_concurrency", None)
    if isinstance(max_concurrency, int) and concurrency > max_concurrency:
        raise AcceptanceError(
            "CONCURRENCY_EXCEEDS_PROVIDER_LIMIT",
            f"Provider 安全并发上限为 {max_concurrency}，实际为 {concurrency}",
        )


def _community_seeds(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("community_seeds")
    if not isinstance(payload, list) or not payload:
        raise AcceptanceError("COMMUNITY_SEEDS_INVALID", "社区种子必须是非空对象数组")
    if not all(isinstance(item, dict) for item in payload):
        raise AcceptanceError("COMMUNITY_SEEDS_INVALID", "每条社区种子必须是对象")
    normalized: list[dict[str, Any]] = []
    identities: set[str] = set()
    for index, raw in enumerate(payload, start=1):
        item = dict(raw)
        identity = str(item.get("seed_identity") or "").strip()
        community_url = str(item.get("community_url") or item.get("url") or "").strip()
        if not identity or identity in identities:
            raise AcceptanceError(
                "COMMUNITY_SEED_IDENTITY_INVALID",
                f"社区种子 {index} 的 seed_identity 缺失或重复",
            )
        parsed = urlsplit(community_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise AcceptanceError(
                "COMMUNITY_SEED_URL_INVALID", f"社区种子 {index} 缺少有效 HTTPS URL"
            )
        identities.add(identity)
        item["seed_identity"] = identity
        item["community_url"] = community_url
        normalized.append(item)
    return normalized


def create_sources(
    provider: AcceptanceProvider,
    *,
    platform_code: str,
    community_seed_file: Path,
    output: Path,
    evidence_dir: Path,
    access_mode: str,
) -> dict[str, Any]:
    """由 Provider 证明两个列表关系并固化来源清单。"""

    _, adapter_version = _provider_identity(provider, platform_code)
    _validate_provider_execution(provider, access_mode=access_mode, concurrency=1)
    seeds = _community_seeds(load_json(community_seed_file))
    evidence_dir.mkdir(parents=True, exist_ok=True)
    records = provider.discover_sources(seeds, evidence_dir)
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise AcceptanceError("SOURCE_PROVIDER_INVALID", "discover_sources 必须返回对象数组")
    seed_by_identity = {str(item["seed_identity"]): item for item in seeds}
    expected_keys = {
        (seed_identity, list_order)
        for seed_identity in seed_by_identity
        for list_order in LIST_ORDERS
    }
    expected_relations = len(expected_keys)
    if len(records) != expected_relations:
        raise AcceptanceError(
            "SOURCE_RELATION_INCOMPLETE",
            f"应记录 {expected_relations} 次列表关系尝试，实际为 {len(records)} 次",
        )
    verified_identities: set[str] = set()
    observed_keys: set[tuple[str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(records, start=1):
        item = dict(raw)
        item["platform_code"] = platform_code
        status = item.get("status")
        list_order = item.get("list_order")
        seed_identity = str(item.get("seed_identity") or "")
        if status not in SOURCE_STATUSES:
            raise AcceptanceError("SOURCE_STATUS_INVALID", f"来源 {index} 状态无效：{status!r}")
        if list_order not in LIST_ORDERS:
            raise AcceptanceError(
                "SOURCE_LIST_ORDER_INVALID", f"来源 {index} 列表顺序无效：{list_order!r}"
            )
        relation_key = (seed_identity, str(list_order))
        if relation_key not in expected_keys or relation_key in observed_keys:
            raise AcceptanceError(
                "SOURCE_RELATION_KEY_INVALID",
                f"来源 {index} 的 seed_identity × list_order 未知或重复：{relation_key!r}",
            )
        observed_keys.add(relation_key)
        if item.get("community_url") != seed_by_identity[seed_identity]["community_url"]:
            raise AcceptanceError(
                "SOURCE_COMMUNITY_URL_MISMATCH", f"来源 {index} 的社区 URL 与种子不一致"
            )
        evidence = item.get("relation_evidence")
        if not isinstance(evidence, dict) or not evidence:
            raise AcceptanceError("SOURCE_EVIDENCE_MISSING", f"来源 {index} 缺少关系证据")
        if status == "verified":
            identity = str(item.get("source_identity") or "")
            list_url = str(item.get("normalized_list_url") or "")
            if not identity or identity in verified_identities:
                raise AcceptanceError(
                    "SOURCE_IDENTITY_INVALID", f"来源 {index} 的稳定身份缺失或重复"
                )
            parsed = urlsplit(list_url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise AcceptanceError("SOURCE_URL_INVALID", f"来源 {index} 的规范 URL 无效")
            verified_identities.add(identity)
        normalized.append(item)
    if observed_keys != expected_keys:
        missing = sorted(expected_keys - observed_keys)
        raise AcceptanceError("SOURCE_RELATION_INCOMPLETE", f"缺少来源关系键：{missing!r}")
    document = {
        "schema_version": SCHEMA_VERSION,
        "platform_code": platform_code,
        "generated_at": utc_now(),
        "git_commit": current_git_commit(),
        "adapter_version": adapter_version,
        "harness_version": HARNESS_VERSION,
        "access_mode": access_mode,
        "community_seed_count": len(seeds),
        "relation_attempt_count": len(normalized),
        "verified_source_count": sum(item["status"] == "verified" for item in normalized),
        "failed_relation_count": sum(item["status"] == "failed" for item in normalized),
        "sources": normalized,
    }
    document["passed"] = document["failed_relation_count"] == 0
    write_json_new(output, document)
    return document


def create_discovery(
    provider: AcceptanceProvider,
    *,
    platform_code: str,
    sources_path: Path,
    output: Path,
    events_path: Path,
    access_mode: str,
    concurrency: int,
) -> dict[str, Any]:
    """调用 Provider 发现候选，并校验平台中立的候选外壳。"""

    _, adapter_version = _provider_identity(provider, platform_code)
    _validate_provider_execution(provider, access_mode=access_mode, concurrency=concurrency)
    sources_document = load_json(sources_path)
    if not isinstance(sources_document, dict):
        raise AcceptanceError("SOURCES_INVALID", "sources.json 顶层必须是对象")
    if sources_document.get("platform_code") != platform_code:
        raise AcceptanceError("PLATFORM_MISMATCH", "sources.json 平台不匹配")
    if sources_document.get("access_mode") != access_mode:
        raise AcceptanceError("ACCESS_MODE_CHANGED", "发现访问模式与 sources.json 不一致")
    if sources_document.get("adapter_version") != adapter_version:
        raise AcceptanceError("VERSION_MISMATCH", "发现 Provider 版本与 sources.json 不一致")
    if any(item.get("status") == "failed" for item in sources_document.get("sources", [])):
        raise AcceptanceError("SOURCE_RELATION_FAILED", "来源关系仍有 failed 终态")
    verified = [
        item for item in sources_document.get("sources", []) if item.get("status") == "verified"
    ]
    identities = {str(item["source_identity"]): item for item in verified}
    if not identities:
        raise AcceptanceError("VERIFIED_SOURCE_EMPTY", "没有可进入发现阶段的真实来源")
    raw = provider.discover_candidates(verified, access_mode=access_mode, concurrency=concurrency)
    if not isinstance(raw, dict):
        raise AcceptanceError("DISCOVERY_PROVIDER_INVALID", "discover_candidates 必须返回对象")
    candidates = raw.get("candidates")
    events = raw.get("request_events", [])
    if not isinstance(candidates, list) or not all(isinstance(item, dict) for item in candidates):
        raise AcceptanceError("DISCOVERY_PROVIDER_INVALID", "candidates 必须是对象数组")
    if not isinstance(events, list) or not all(isinstance(item, dict) for item in events):
        raise AcceptanceError("DISCOVERY_PROVIDER_INVALID", "request_events 必须是对象数组")
    normalized: list[dict[str, Any]] = []
    for index, raw_item in enumerate(candidates, start=1):
        item = dict(raw_item)
        item["platform_code"] = platform_code
        identity = str(item.get("source_identity") or "")
        if identity not in identities:
            raise AcceptanceError(
                "CANDIDATE_SOURCE_INVALID", f"候选 {index} 指向未知来源 {identity!r}"
            )
        if item.get("list_order") != identities[identity].get("list_order"):
            raise AcceptanceError("CANDIDATE_LIST_ORDER_INVALID", f"候选 {index} 列表顺序不匹配")
        normalized_url = str(item.get("normalized_url") or "")
        parsed = urlsplit(normalized_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise AcceptanceError("CANDIDATE_URL_INVALID", f"候选 {index} 规范 URL 无效")
        if not str(item.get("platform_post_id") or ""):
            raise AcceptanceError("CANDIDATE_POST_ID_MISSING", f"候选 {index} 缺少稳定帖子 ID")
        if not isinstance(item.get("preflight_valid"), bool):
            raise AcceptanceError("CANDIDATE_PREFLIGHT_INVALID", f"候选 {index} 缺少复核布尔值")
        memberships = item.get("source_memberships") or [identity]
        if not isinstance(memberships, list) or not memberships:
            raise AcceptanceError("CANDIDATE_SOURCE_INVALID", f"候选 {index} 来源集合无效")
        if any(str(value) not in identities for value in memberships):
            raise AcceptanceError("CANDIDATE_SOURCE_INVALID", f"候选 {index} 来源集合含未知来源")
        if identity not in {str(value) for value in memberships}:
            raise AcceptanceError("CANDIDATE_SOURCE_INVALID", f"候选 {index} 主来源不在来源集合中")
        tags = item.get("scenario_tags", [])
        if not isinstance(tags, list) or any(tag not in SCENARIO_TAGS for tag in tags):
            raise AcceptanceError("CANDIDATE_SCENARIO_INVALID", f"候选 {index} 场景标签无效")
        item["source_memberships"] = sorted({str(value) for value in memberships})
        item["source_membership_orders"] = {
            value: str(identities[value]["list_order"]) for value in item["source_memberships"]
        }
        item["url_sha256"] = sha256_bytes(normalized_url.encode())
        item["adapter_version"] = adapter_version
        item["access_mode"] = access_mode
        normalized.append(item)
    write_jsonl_new(output, normalized)
    write_jsonl_new(events_path, events)
    return {
        "schema_version": SCHEMA_VERSION,
        "platform_code": platform_code,
        "candidate_count": len(normalized),
        "preflight_valid_count": sum(item["preflight_valid"] for item in normalized),
        "request_event_count": len(events),
        "candidates_sha256": sha256_file(output),
        "events_sha256": sha256_file(events_path),
    }


def _eligible_candidate(item: dict[str, Any], platform_code: str) -> bool:
    post_id = str(item.get("platform_post_id") or "")
    return bool(
        item.get("platform_code") == platform_code
        and item.get("preflight_valid") is True
        and item.get("preflight_class") == "post"
        and post_id
        and str(item.get("preflight_observed_post_id") or "") == post_id
    )


def _stable_rank(seed: str, post_id: str) -> tuple[bytes, str]:
    payload = seed.encode() + b"\0" + post_id.encode()
    return hashlib.sha256(payload).digest(), post_id


def _merge_eligible_candidates(
    candidates: list[dict[str, Any]], platform_code: str
) -> dict[str, dict[str, Any]]:
    """按稳定帖子 ID 去重，同时保留全部来源成员关系。"""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    url_to_post: dict[str, str] = {}
    for item in candidates:
        if not _eligible_candidate(item, platform_code):
            continue
        post_id = str(item["platform_post_id"])
        normalized_url = str(item.get("normalized_url") or "")
        parsed = urlsplit(normalized_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise AcceptanceError("CANDIDATE_URL_INVALID", f"候选 {post_id} 的规范 URL 无效")
        previous = url_to_post.setdefault(normalized_url, post_id)
        if previous != post_id:
            raise AcceptanceError("CANDIDATE_ID_CONFLICT", "同一规范 URL 映射到了多个稳定帖子 ID")
        grouped[post_id].append(item)
    merged: dict[str, dict[str, Any]] = {}
    for post_id, rows in grouped.items():
        urls = {str(row["normalized_url"]) for row in rows}
        if len(urls) != 1:
            raise AcceptanceError(
                "CANDIDATE_URL_CONFLICT", f"稳定帖子 ID {post_id} 对应多个规范 URL"
            )
        memberships: set[str] = set()
        order_by_source: dict[str, str] = {}
        for row in rows:
            membership_orders = row.get("source_membership_orders")
            membership_orders = membership_orders if isinstance(membership_orders, dict) else {}
            for identity in row.get("source_memberships") or [row["source_identity"]]:
                identity = str(identity)
                memberships.add(identity)
                order_by_source.setdefault(
                    identity, str(membership_orders.get(identity) or row["list_order"])
                )
        base = dict(sorted(rows, key=lambda row: (str(row["source_identity"]),))[0])
        base["source_memberships"] = sorted(memberships)
        base["membership_orders"] = order_by_source
        merged[post_id] = base
    return merged


def _round_robin_select(
    eligible: dict[str, dict[str, Any]], seed: str, count: int
) -> list[dict[str, Any]]:
    queues: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in eligible.values():
        for identity in item["source_memberships"]:
            queues[identity].append(item)
    for items in queues.values():
        items.sort(key=lambda item: _stable_rank(seed, str(item["platform_post_id"])))
    positions = {identity: 0 for identity in queues}
    selected_ids: set[str] = set()
    selected: list[dict[str, Any]] = []
    while len(selected) < count:
        consumed = False
        for identity in sorted(queues):
            items = queues[identity]
            while positions[identity] < len(items):
                item = items[positions[identity]]
                positions[identity] += 1
                consumed = True
                post_id = str(item["platform_post_id"])
                if post_id in selected_ids:
                    continue
                selected_ids.add(post_id)
                output = dict(item)
                output["primary_source_identity"] = identity
                output["primary_list_order"] = item["membership_orders"][identity]
                selected.append(output)
                break
            if len(selected) >= count:
                break
        if not consumed:
            break
    if len(selected) != count:
        raise AcceptanceError(
            "INSUFFICIENT_VALID_POOL",
            f"当前有效稳定帖子 ID 为 {len(eligible)} 个，冻结目标为 {count} 个",
        )
    return selected


def _require_formal_count(value: int, *, field: str) -> None:
    """正式入口的分母只能是代码常量 500。"""

    if value != FORMAL_COUNT:
        raise AcceptanceError(
            "FORMAL_COUNT_FIXED",
            f"{field} 必须固定为 {FORMAL_COUNT}，实际为 {value}",
        )


def freeze_inputs(
    *,
    platform_code: str,
    candidates_path: Path,
    sources_path: Path,
    output: Path,
    manifest_path: Path,
    count: int = FORMAL_COUNT,
    seed: str,
) -> dict[str, Any]:
    """从现时有效候选中确定性冻结稳定帖子 ID 唯一的清单。"""

    _require_formal_count(count, field="count")
    if not seed:
        raise AcceptanceError("FREEZE_ARGUMENT_INVALID", "seed 必须非空")
    _ensure_new_paths(output, manifest_path)
    sources = load_json(sources_path)
    if not isinstance(sources, dict) or sources.get("platform_code") != platform_code:
        raise AcceptanceError("PLATFORM_MISMATCH", "sources.json 平台不匹配")
    candidates = load_jsonl(candidates_path)
    for index, item in enumerate(candidates, start=1):
        if item.get("access_mode") != sources.get("access_mode"):
            raise AcceptanceError(
                "ACCESS_MODE_CHANGED", f"候选 {index} 的访问模式与 sources.json 不一致"
            )
        if item.get("adapter_version") != sources.get("adapter_version"):
            raise AcceptanceError(
                "VERSION_MISMATCH", f"候选 {index} 的适配器版本与 sources.json 不一致"
            )
    eligible = _merge_eligible_candidates(candidates, platform_code)
    if len(eligible) < count:
        raise AcceptanceError(
            "INSUFFICIENT_VALID_POOL",
            f"当前有效稳定帖子 ID 为 {len(eligible)} 个，冻结目标为 {count} 个",
        )
    selected = _round_robin_select(eligible, seed, count)
    urls = [str(item["normalized_url"]) for item in selected]
    if len(set(urls)) != count:
        raise AcceptanceError("INPUT_URL_DUPLICATED", "选择结果中的规范 URL 未保持唯一")
    output_hash = write_lf_new(output, urls)
    source_distribution = Counter(str(item["primary_source_identity"]) for item in selected)
    order_distribution = Counter(str(item["primary_list_order"]) for item in selected)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "platform_code": platform_code,
        "generated_at": utc_now(),
        "freeze_seed": seed,
        "selection_algorithm": SELECTION_ALGORITHM,
        "candidate_count": len(candidates),
        "eligible_count": len(eligible),
        "selected_count": count,
        "distinct_url_count": len(set(urls)),
        "distinct_post_id_count": len({item["platform_post_id"] for item in selected}),
        "source_distribution": dict(sorted(source_distribution.items())),
        "list_order_distribution": dict(sorted(order_distribution.items())),
        "preflight_policy_version": PRECHECK_POLICY_VERSION,
        "access_mode": sources.get("access_mode"),
        "adapter_version": sources.get("adapter_version"),
        "harness_version": HARNESS_VERSION,
        "git_commit": current_git_commit(),
        "environment_identity": environment_identity(),
        "sources_sha256": sha256_file(sources_path),
        "candidates_sha256": sha256_file(candidates_path),
        "acceptance_urls_sha256": output_hash,
        "selected": [
            {
                "input_index": index,
                "url_sha256": sha256_bytes(url.encode()),
                "platform_post_id": str(item["platform_post_id"]),
                "primary_source_identity": str(item["primary_source_identity"]),
                "primary_list_order": str(item["primary_list_order"]),
            }
            for index, (url, item) in enumerate(zip(urls, selected, strict=True))
        ],
    }
    write_json_new(manifest_path, manifest)
    return manifest


def verify_inputs(
    *,
    platform_code: str,
    sources_path: Path,
    urls_path: Path,
    manifest_path: Path,
    expected_count: int = FORMAL_COUNT,
    current_access_mode: str | None = None,
    current_adapter_version: str | None = None,
    current_git_commit_value: str | None = None,
) -> dict[str, Any]:
    """验证冻结分母、哈希、访问模式和版本绑定。"""

    _require_formal_count(expected_count, field="expected_count")
    errors: list[str] = []
    try:
        urls = read_urls_strict(urls_path, expected_count)
        sources = load_json(sources_path)
        manifest = load_json(manifest_path)
        if not isinstance(sources, dict) or not isinstance(manifest, dict):
            raise AcceptanceError("INPUT_DOCUMENT_INVALID", "sources/manifest 顶层必须是对象")
        checks = {
            "platform_code": platform_code,
            "selected_count": expected_count,
            "distinct_url_count": expected_count,
            "distinct_post_id_count": expected_count,
            "acceptance_urls_sha256": sha256_file(urls_path),
            "sources_sha256": sha256_file(sources_path),
            "harness_version": HARNESS_VERSION,
        }
        for key, expected in checks.items():
            if manifest.get(key) != expected:
                errors.append(f"manifest.{key} 与当前输入不一致")
        selected = manifest.get("selected")
        if not isinstance(selected, list) or len(selected) != expected_count:
            errors.append("manifest.selected 分母不一致")
            selected = []
        if selected:
            post_ids = [str(item.get("platform_post_id") or "") for item in selected]
            if "" in post_ids or len(set(post_ids)) != expected_count:
                errors.append("manifest.selected 稳定帖子 ID 缺失或重复")
            for index, (url, item) in enumerate(zip(urls, selected, strict=True)):
                if item.get("input_index") != index:
                    errors.append(f"manifest.selected[{index}] 输入序号不一致")
                if item.get("url_sha256") != sha256_bytes(url.encode()):
                    errors.append(f"manifest.selected[{index}] URL 哈希不一致")
        for key in ("platform_code", "access_mode", "adapter_version"):
            if sources.get(key) != manifest.get(key):
                errors.append(f"sources.{key} 与 manifest 不一致")
        if current_access_mode is not None and manifest.get("access_mode") != current_access_mode:
            errors.append("访问模式已经变化")
        if (
            current_adapter_version is not None
            and manifest.get("adapter_version") != current_adapter_version
        ):
            errors.append("适配器版本已经变化")
        if (
            current_git_commit_value is not None
            and manifest.get("git_commit") != current_git_commit_value
        ):
            errors.append("Git 提交已经变化")
    except AcceptanceError as exc:
        errors.append(f"{exc.code}: {exc.message}")
        urls = []
        manifest = {}
    return {
        "schema_version": SCHEMA_VERSION,
        "platform_code": platform_code,
        "expected_count": expected_count,
        "actual_count": len(urls),
        "manifest_sha256": sha256_file(manifest_path) if manifest_path.exists() else None,
        "errors": errors,
        "passed": not errors,
    }


def create_functional_samples(
    *,
    platform_code: str,
    candidates_path: Path,
    manifest_path: Path,
    output: Path,
) -> dict[str, Any]:
    """从候选观察事实为 19 个场景生成正样本或 not_observed 记录。"""

    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("platform_code") != platform_code:
        raise AcceptanceError("PLATFORM_MISMATCH", "manifest 平台不匹配")
    if manifest.get("candidates_sha256") != sha256_file(candidates_path):
        raise AcceptanceError("CANDIDATE_HASH_MISMATCH", "候选文件与冻结 manifest 不一致")
    candidates = load_jsonl(candidates_path)
    selected_ids = {
        str(item.get("platform_post_id"))
        for item in manifest.get("selected", [])
        if isinstance(item, dict)
    }
    source_count = len(
        {str(item.get("source_identity")) for item in candidates if item.get("source_identity")}
    )
    generated_at = utc_now()
    records: list[dict[str, Any]] = []
    for tag in SCENARIO_TAGS:
        matches = [item for item in candidates if tag in item.get("scenario_tags", [])]
        matches.sort(
            key=lambda item: (
                str(item.get("platform_post_id")) not in selected_ids,
                str(item.get("platform_post_id")),
                str(item.get("normalized_url")),
            )
        )
        if matches:
            item = matches[0]
            url = str(item["normalized_url"])
            observed_facts = item.get("observed_facts")
            evidence_refs = item.get("evidence_refs")
            if not isinstance(observed_facts, dict) or not observed_facts:
                raise AcceptanceError(
                    "FUNCTIONAL_SAMPLE_EVIDENCE_MISSING",
                    f"场景 {tag} 的候选缺少 observed_facts",
                )
            if not isinstance(evidence_refs, list) or not evidence_refs:
                raise AcceptanceError(
                    "FUNCTIONAL_SAMPLE_EVIDENCE_MISSING",
                    f"场景 {tag} 的候选缺少 evidence_refs",
                )
            records.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "platform_code": platform_code,
                    "record_type": "sample",
                    "scenario_tag": tag,
                    "sample_id": sha256_bytes(f"{tag}\0{item['platform_post_id']}".encode())[:16],
                    "url": url,
                    "url_sha256": sha256_bytes(url.encode()),
                    "platform_post_id": str(item["platform_post_id"]),
                    "in_frozen_sample": str(item["platform_post_id"]) in selected_ids,
                    "observed_facts": observed_facts,
                    "evidence_refs": evidence_refs,
                    "confirmed_at": item.get("confirmed_at") or generated_at,
                    "invalidated_if": item.get("invalidated_if")
                    or "平台页面、访问模式、适配器版本或响应字段变化",
                }
            )
        else:
            records.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "platform_code": platform_code,
                    "record_type": "not_observed",
                    "scenario_tag": tag,
                    "searched_candidate_count": len(candidates),
                    "searched_source_count": source_count,
                    "reason": "当前发现池未观察到该场景",
                    "confirmed_at": generated_at,
                }
            )
    write_jsonl_new(output, records)
    observed = sum(item["record_type"] == "sample" for item in records)
    verification = verify_functional_samples(platform_code=platform_code, samples_path=output)
    return {
        "schema_version": SCHEMA_VERSION,
        "platform_code": platform_code,
        "scenario_count": len(SCENARIO_TAGS),
        "observed_count": observed,
        "not_observed_count": len(records) - observed,
        "passed": verification["passed"],
        "output_sha256": sha256_file(output),
    }


def verify_functional_samples(*, platform_code: str, samples_path: Path) -> dict[str, Any]:
    """穷尽复核固定 19 场景及每条观察或未观察证据。"""

    records = load_jsonl(samples_path)
    errors: list[str] = []
    counts = Counter(str(item.get("scenario_tag") or "") for item in records)
    unknown = sorted(set(counts) - set(SCENARIO_TAGS))
    missing = sorted(set(SCENARIO_TAGS) - set(counts))
    duplicated = sorted(tag for tag, count in counts.items() if count != 1)
    if len(records) != len(SCENARIO_TAGS):
        errors.append(f"scenario_count:{len(records)}")
    if unknown:
        errors.append(f"unknown_scenarios:{','.join(unknown)}")
    if missing:
        errors.append(f"missing_scenarios:{','.join(missing)}")
    if duplicated:
        errors.append(f"duplicated_scenarios:{','.join(duplicated)}")
    for index, item in enumerate(records):
        if item.get("platform_code") != platform_code:
            errors.append(f"record[{index}]:platform_mismatch")
        record_type = item.get("record_type")
        if record_type == "sample":
            if not isinstance(item.get("observed_facts"), dict) or not item["observed_facts"]:
                errors.append(f"record[{index}]:observed_facts_missing")
            if not isinstance(item.get("evidence_refs"), list) or not item["evidence_refs"]:
                errors.append(f"record[{index}]:evidence_refs_missing")
        elif record_type == "not_observed":
            if (
                not isinstance(item.get("searched_candidate_count"), int)
                or item["searched_candidate_count"] < 1
            ):
                errors.append(f"record[{index}]:searched_candidate_count_invalid")
            if (
                not isinstance(item.get("searched_source_count"), int)
                or item["searched_source_count"] < 1
            ):
                errors.append(f"record[{index}]:searched_source_count_invalid")
            if not str(item.get("reason") or "").strip():
                errors.append(f"record[{index}]:reason_missing")
        else:
            errors.append(f"record[{index}]:record_type_invalid")
    return {
        "schema_version": SCHEMA_VERSION,
        "platform_code": platform_code,
        "scenario_count": len(records),
        "samples_sha256": sha256_file(samples_path),
        "errors": errors,
        "passed": not errors,
    }


def percentile(values: list[int], quantile: float) -> int | None:
    """使用 nearest-rank 计算整数耗时百分位。"""

    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[index]


def result_contract_errors(
    record: dict[str, Any], *, expected_url: str, expected_post_id: str, input_index: int
) -> tuple[list[str], bool]:
    """重新计算单条结果合同，不信任 Provider 自报的 valid。"""

    errors: list[str] = []
    required = {
        "input_index",
        "url",
        "url_sha256",
        "input_platform_post_id",
        "observed_platform_post_id",
        "post_id_matches",
        "body",
        "image_urls",
        "video_urls",
        "comments",
        "comments_complete",
        "comment_page_end",
        "raw_status",
        "normalized_status",
        "response_class",
        "request_count",
        "duration_ms",
        "access_channel",
        "recovery_count",
        "request_event_refs",
        "contract_errors",
        "final_status",
    }
    missing = sorted(required - record.keys())
    if missing:
        return [f"missing_fields:{','.join(missing)}"], False
    if record["input_index"] != input_index:
        errors.append("input_index_mismatch")
    if record["url"] != expected_url:
        errors.append("input_url_mismatch")
    if record["url_sha256"] != sha256_bytes(expected_url.encode()):
        errors.append("input_hash_mismatch")
    if record["input_platform_post_id"] != expected_post_id:
        errors.append("input_post_id_mismatch")
    if record["response_class"] == "not_requested":
        if record["request_count"] != 0:
            errors.append("not_requested_request_count_invalid")
        if record["request_event_refs"] != []:
            errors.append("not_requested_event_refs_invalid")
        if record["observed_platform_post_id"] is not None:
            errors.append("not_requested_observed_id_invalid")
        errors.append("not_requested")
        if record["final_status"] != "invalid":
            errors.append("final_status_mismatch")
        return errors, False
    identity_ok = bool(
        record["post_id_matches"] is True
        and record["observed_platform_post_id"] == expected_post_id
    )
    if not identity_ok:
        errors.append("wrong_post")
    collections_ok = all(
        isinstance(record[key], list) for key in ("image_urls", "video_urls", "comments")
    )
    if not collections_ok:
        errors.append("collection_type_invalid")
    image_urls = record["image_urls"] if isinstance(record["image_urls"], list) else []
    video_urls = record["video_urls"] if isinstance(record["video_urls"], list) else []
    comments = record["comments"] if isinstance(record["comments"], list) else []
    body = record["body"]
    content_ok = bool((isinstance(body, str) and body.strip()) or image_urls or video_urls)
    if not content_ok:
        errors.append("content_missing")
    if len(comments) > 10:
        errors.append("comment_limit_exceeded")
    page_end = record["comment_page_end"]
    page_end_ok = isinstance(page_end, dict) and (
        len(comments) >= 10 or page_end.get("has_more") is False
    )
    comments_ok = record["comments_complete"] is True and page_end_ok
    if not comments_ok:
        errors.append("comments_incomplete")
    raw_status = record["raw_status"]
    status_ok = isinstance(raw_status, dict) and bool(raw_status)
    if not status_ok:
        errors.append("raw_status_missing")
    if record["normalized_status"] not in NORMALIZED_STATUSES:
        errors.append("normalized_status_invalid")
    response_class = record["response_class"]
    if response_class not in RESPONSE_CLASSES:
        errors.append("response_class_invalid")
    elif response_class != "post":
        errors.append(str(response_class))
    if not isinstance(record["request_count"], int) or record["request_count"] < 1:
        errors.append("request_count_invalid")
    if not isinstance(record["duration_ms"], int) or record["duration_ms"] < 0:
        errors.append("duration_invalid")
    if not isinstance(record["access_channel"], str) or not record["access_channel"]:
        errors.append("access_channel_missing")
    if not isinstance(record["recovery_count"], int) or record["recovery_count"] < 0:
        errors.append("recovery_count_invalid")
    if not isinstance(record["request_event_refs"], list):
        errors.append("request_event_refs_invalid")
    provider_errors = record["contract_errors"]
    if not isinstance(provider_errors, list):
        errors.append("contract_errors_invalid")
    elif provider_errors:
        errors.extend(f"provider:{value}" for value in provider_errors)
    computed_valid = not errors
    expected_status = "valid" if computed_valid else "invalid"
    if record["final_status"] != expected_status:
        errors.append("final_status_mismatch")
        computed_valid = False
    return errors, computed_valid


def evaluate_results(
    *,
    platform_code: str,
    urls: list[str],
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    request_events: list[dict[str, Any]],
    wall_seconds: float | None,
) -> dict[str, Any]:
    """按固定输入分母汇总逐 URL 结果。"""

    errors: list[str] = []
    expected_count = len(urls)
    selected = manifest.get("selected")
    if not isinstance(selected, list) or len(selected) != expected_count:
        errors.append("manifest_selected_count_mismatch")
        selected = []
    actual_urls = [str(record.get("url") or "") for record in records]
    counts = Counter(actual_urls)
    duplicate_urls = sorted(url for url, count in counts.items() if url and count > 1)
    missing_urls = sorted(set(urls) - set(actual_urls))
    extra_urls = sorted(set(actual_urls) - set(urls))
    if duplicate_urls:
        errors.append(f"result_duplicate:{len(duplicate_urls)}")
    if missing_urls:
        errors.append(f"result_missing:{len(missing_urls)}")
    if extra_urls:
        errors.append(f"result_extra:{len(extra_urls)}")
    records_by_url = {str(record.get("url") or ""): record for record in records}
    valid_count = 0
    durations: list[int] = []
    total_requests = 0
    response_counts: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    for index, url in enumerate(urls):
        record = records_by_url.get(url)
        if record is None or index >= len(selected):
            continue
        expected_post_id = str(selected[index].get("platform_post_id") or "")
        record_errors, valid = result_contract_errors(
            record, expected_url=url, expected_post_id=expected_post_id, input_index=index
        )
        if valid:
            valid_count += 1
        else:
            for error in record_errors:
                failure_counts[error] += 1
            errors.extend(f"result[{index}]:{error}" for error in record_errors)
        if isinstance(record.get("duration_ms"), int):
            durations.append(record["duration_ms"])
        if isinstance(record.get("request_count"), int):
            total_requests += max(0, record["request_count"])
        response_counts[str(record.get("response_class"))] += 1
    unique_terminal_count = sum(counts[url] == 1 for url in urls)
    unrecovered_controls = sum(response_counts[value] for value in CONTROL_CLASSES)
    unrequested_count = response_counts["not_requested"]
    passed = bool(
        not errors
        and len(records) == expected_count
        and unique_terminal_count == expected_count
        and valid_count == expected_count
        and unrecovered_controls == 0
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "platform_code": platform_code,
        "input_count": expected_count,
        "result_count": len(records),
        "unique_terminal_count": unique_terminal_count,
        "valid_count": valid_count,
        "invalid_count": expected_count - valid_count,
        "missing_result_count": len(missing_urls),
        "extra_result_count": len(extra_urls),
        "duplicate_result_count": len(duplicate_urls),
        "unrecovered_control_count": unrecovered_controls,
        "unrequested_count": unrequested_count,
        "response_class_counts": dict(sorted(response_counts.items())),
        "failure_category_counts": dict(sorted(failure_counts.items())),
        "request_event_count": len(request_events),
        "total_platform_request_count": total_requests,
        "request_amplification": round(total_requests / expected_count, 6) if expected_count else 0,
        "p50_duration_ms": percentile(durations, 0.50),
        "p95_duration_ms": percentile(durations, 0.95),
        "wall_seconds": round(wall_seconds, 6) if wall_seconds is not None else None,
        "effective_urls_per_second": round(valid_count / wall_seconds, 6)
        if wall_seconds and wall_seconds > 0
        else None,
        "verification_errors": errors,
        "passed": passed,
    }


def write_checksums(directory: Path) -> None:
    """为轮次全部文件生成排序后的 SHA256SUMS。"""

    checksum_path = directory / "SHA256SUMS"
    _ensure_new_paths(checksum_path)
    files = sorted(
        path for path in directory.rglob("*") if path.is_file() and path != checksum_path
    )
    lines = [f"{sha256_file(path)}  {path.relative_to(directory).as_posix()}" for path in files]
    _write_new(checksum_path, ("\n".join(lines) + "\n").encode())


def verify_checksums(directory: Path) -> list[str]:
    """验证校验清单、路径集合和每个文件内容。"""

    checksum_path = directory / "SHA256SUMS"
    if not checksum_path.is_file():
        return ["checksum_missing"]
    errors: list[str] = []
    entries: dict[str, str] = {}
    try:
        lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return [f"checksum_read_failed:{exc}"]
    for line_number, line in enumerate(lines, start=1):
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            errors.append(f"checksum_line_invalid:{line_number}")
            continue
        digest, relative = parts
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or relative in entries:
            errors.append(f"checksum_path_invalid:{line_number}")
            continue
        entries[relative] = digest
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path != checksum_path
    }
    if set(entries) != actual:
        errors.append("checksum_file_set_mismatch")
    for relative, expected in entries.items():
        path = directory.joinpath(*PurePosixPath(relative).parts)
        if path.is_file() and sha256_file(path) != expected:
            errors.append(f"checksum_mismatch:{relative}")
    return errors


def create_run(
    provider: AcceptanceProvider,
    *,
    platform_code: str,
    sources_path: Path,
    urls_path: Path,
    manifest_path: Path,
    functional_samples_path: Path,
    output_dir: Path,
    concurrency: int,
) -> dict[str, Any]:
    """调用正式 Provider 完成整轮采集，并写入自包含结果目录。"""

    _, adapter_version = _provider_identity(provider, platform_code)
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise AcceptanceError("MANIFEST_INVALID", "manifest 顶层必须是对象")
    access_mode = str(manifest.get("access_mode") or "")
    _validate_provider_execution(provider, access_mode=access_mode, concurrency=concurrency)
    _require_formal_count(int(manifest.get("selected_count") or 0), field="manifest.selected_count")
    samples_report = verify_functional_samples(
        platform_code=platform_code, samples_path=functional_samples_path
    )
    if not samples_report["passed"]:
        raise AcceptanceError("FUNCTIONAL_SAMPLES_INVALID", "; ".join(samples_report["errors"]))
    input_report = verify_inputs(
        platform_code=platform_code,
        sources_path=sources_path,
        urls_path=urls_path,
        manifest_path=manifest_path,
        expected_count=FORMAL_COUNT,
        current_access_mode=access_mode,
        current_adapter_version=adapter_version,
        current_git_commit_value=current_git_commit(),
    )
    if not input_report["passed"]:
        raise AcceptanceError("INPUT_VERIFICATION_FAILED", "; ".join(input_report["errors"]))
    _ensure_new_paths(output_dir)
    urls = read_urls_strict(urls_path, FORMAL_COUNT)
    started_at = utc_now()
    started_perf = time.perf_counter()
    payload = provider.run_acceptance(
        urls,
        manifest=manifest,
        access_mode=access_mode,
        concurrency=concurrency,
    )
    wall_seconds = time.perf_counter() - started_perf
    if not isinstance(payload, dict):
        raise AcceptanceError("RUN_PROVIDER_INVALID", "run_acceptance 必须返回对象")
    records = payload.get("results")
    events = payload.get("request_events", [])
    provider_environment = payload.get("environment", {})
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise AcceptanceError("RUN_PROVIDER_INVALID", "results 必须是对象数组")
    if not isinstance(events, list) or not all(isinstance(item, dict) for item in events):
        raise AcceptanceError("RUN_PROVIDER_INVALID", "request_events 必须是对象数组")
    if not isinstance(provider_environment, dict):
        raise AcceptanceError("RUN_PROVIDER_INVALID", "environment 必须是对象")
    _reject_sensitive_keys(payload)
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(urls_path, output_dir / "input-urls.txt")
    shutil.copyfile(functional_samples_path, output_dir / "functional-samples.jsonl")
    shutil.copyfile(manifest_path, output_dir / "acceptance-manifest.json")
    shutil.copyfile(sources_path, output_dir / "sources.json")
    write_jsonl_new(output_dir / "url-results.jsonl", records)
    write_jsonl_new(output_dir / "request-events.jsonl", events)
    summary = evaluate_results(
        platform_code=platform_code,
        urls=urls,
        manifest=manifest,
        records=records,
        request_events=events,
        wall_seconds=wall_seconds,
    )
    summary.update(
        {
            "started_at": started_at,
            "ended_at": utc_now(),
            "access_mode": access_mode,
            "adapter_version": adapter_version,
            "harness_version": HARNESS_VERSION,
            "git_commit": current_git_commit(),
            "input_sha256": sha256_file(urls_path),
            "manifest_sha256": sha256_file(manifest_path),
            "functional_samples_sha256": sha256_file(functional_samples_path),
            "functional_scenario_count": samples_report["scenario_count"],
            "concurrency": concurrency,
        }
    )
    write_json_new(output_dir / "summary.json", summary)
    environment = {
        "schema_version": SCHEMA_VERSION,
        "platform_code": platform_code,
        "access_mode": access_mode,
        "adapter_version": adapter_version,
        "harness_version": HARNESS_VERSION,
        "git_commit": current_git_commit(),
        "concurrency": concurrency,
        "started_at": started_at,
        "ended_at": summary["ended_at"],
        **environment_identity(),
        "provider": provider_environment,
    }
    write_json_new(output_dir / "environment.json", environment)
    log = (
        f"platform={platform_code}\n"
        f"input_count={len(urls)}\n"
        f"result_count={len(records)}\n"
        f"passed={str(summary['passed']).lower()}\n"
    )
    _write_new(output_dir / "run.log", log.encode())
    write_checksums(output_dir)
    return summary


def verify_run(
    *,
    platform_code: str,
    sources_path: Path,
    urls_path: Path,
    manifest_path: Path,
    functional_samples_path: Path,
    result_dir: Path,
    expected_count: int = FORMAL_COUNT,
    current_access_mode: str | None = None,
    current_adapter_version: str | None = None,
    current_git_commit_value: str | None = None,
) -> dict[str, Any]:
    """只读复核正式轮次的输入绑定、结果合同和 SHA256SUMS。"""

    _require_formal_count(expected_count, field="expected_count")
    errors: list[str] = []
    source_samples = verify_functional_samples(
        platform_code=platform_code, samples_path=functional_samples_path
    )
    errors.extend(f"functional_samples:{value}" for value in source_samples["errors"])
    input_report = verify_inputs(
        platform_code=platform_code,
        sources_path=sources_path,
        urls_path=urls_path,
        manifest_path=manifest_path,
        expected_count=expected_count,
        current_access_mode=current_access_mode,
        current_adapter_version=current_adapter_version,
        current_git_commit_value=current_git_commit_value,
    )
    errors.extend(f"input:{value}" for value in input_report["errors"])
    missing_core = sorted(name for name in CORE_RUN_FILES if not (result_dir / name).is_file())
    errors.extend(f"run_file_missing:{name}" for name in missing_core)
    errors.extend(verify_checksums(result_dir))
    try:
        source_urls = read_urls_strict(urls_path, expected_count)
        run_urls = read_urls_strict(result_dir / "input-urls.txt", expected_count)
        if source_urls != run_urls:
            errors.append("run_input_copy_mismatch")
        manifest = load_json(manifest_path)
        if sha256_file(manifest_path) != sha256_file(result_dir / "acceptance-manifest.json"):
            errors.append("run_manifest_copy_mismatch")
        if sha256_file(sources_path) != sha256_file(result_dir / "sources.json"):
            errors.append("run_sources_copy_mismatch")
        records = load_jsonl(result_dir / "url-results.jsonl")
        events = load_jsonl(result_dir / "request-events.jsonl")
        stored_summary = load_json(result_dir / "summary.json")
        environment = load_json(result_dir / "environment.json")
        run_samples = verify_functional_samples(
            platform_code=platform_code,
            samples_path=result_dir / "functional-samples.jsonl",
        )
        errors.extend(f"run_functional_samples:{value}" for value in run_samples["errors"])
        if source_samples["samples_sha256"] != run_samples["samples_sha256"]:
            errors.append("run_functional_samples_copy_mismatch")
        wall_seconds = (
            stored_summary.get("wall_seconds") if isinstance(stored_summary, dict) else None
        )
        computed = evaluate_results(
            platform_code=platform_code,
            urls=source_urls,
            manifest=manifest,
            records=records,
            request_events=events,
            wall_seconds=wall_seconds,
        )
        for key in (
            "input_count",
            "result_count",
            "unique_terminal_count",
            "valid_count",
            "invalid_count",
            "unrecovered_control_count",
            "request_amplification",
            "p50_duration_ms",
            "p95_duration_ms",
            "passed",
            "unrequested_count",
        ):
            if not isinstance(stored_summary, dict) or stored_summary.get(key) != computed.get(key):
                errors.append(f"summary_mismatch:{key}")
        if not isinstance(environment, dict):
            errors.append("environment_invalid")
        else:
            bindings = {
                "platform_code": platform_code,
                "access_mode": manifest.get("access_mode"),
                "adapter_version": manifest.get("adapter_version"),
                "harness_version": HARNESS_VERSION,
                "git_commit": manifest.get("git_commit"),
            }
            for key, expected in bindings.items():
                if environment.get(key) != expected:
                    errors.append(f"environment_mismatch:{key}")
        errors.extend(f"result:{value}" for value in computed["verification_errors"])
    except (AcceptanceError, OSError, TypeError, ValueError) as exc:
        if isinstance(exc, AcceptanceError):
            errors.append(f"{exc.code}:{exc.message}")
        else:
            errors.append(f"run_read_failed:{type(exc).__name__}:{exc}")
        computed = {"passed": False, "valid_count": 0, "result_count": 0}
    return {
        "schema_version": SCHEMA_VERSION,
        "platform_code": platform_code,
        "expected_count": expected_count,
        "functional_scenario_count": source_samples["scenario_count"],
        "result_count": computed.get("result_count", 0),
        "valid_count": computed.get("valid_count", 0),
        "errors": errors,
        "passed": bool(input_report["passed"] and computed.get("passed") and not errors),
    }


def build_parser() -> argparse.ArgumentParser:
    """构造七个子命令的 CLI。"""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sources = subparsers.add_parser("sources")
    sources.add_argument("--platform", required=True)
    sources.add_argument("--community-seeds", type=Path, required=True)
    sources.add_argument("--output", type=Path, required=True)
    sources.add_argument("--evidence-dir", type=Path, required=True)
    sources.add_argument("--access-mode", choices=("anonymous", "authenticated"), required=True)

    discover = subparsers.add_parser("discover")
    discover.add_argument("--platform", required=True)
    discover.add_argument("--sources", type=Path, required=True)
    discover.add_argument("--output", type=Path, required=True)
    discover.add_argument("--events", type=Path, required=True)
    discover.add_argument("--access-mode", choices=("anonymous", "authenticated"), required=True)
    discover.add_argument("--concurrency", type=int, default=1)

    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--platform", required=True)
    freeze.add_argument("--sources", type=Path, required=True)
    freeze.add_argument("--candidates", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--manifest", type=Path, required=True)
    freeze.add_argument("--seed", required=True)

    samples = subparsers.add_parser("samples")
    samples.add_argument("--platform", required=True)
    samples.add_argument("--candidates", type=Path, required=True)
    samples.add_argument("--manifest", type=Path, required=True)
    samples.add_argument("--output", type=Path, required=True)

    verify_input = subparsers.add_parser("verify-inputs")
    verify_input.add_argument("--platform", required=True)
    verify_input.add_argument("--sources", type=Path, required=True)
    verify_input.add_argument("--urls", type=Path, required=True)
    verify_input.add_argument("--manifest", type=Path, required=True)
    verify_input.add_argument("--current-access-mode")
    verify_input.add_argument("--current-adapter-version")

    run = subparsers.add_parser("run")
    run.add_argument("--platform", required=True)
    run.add_argument("--sources", type=Path, required=True)
    run.add_argument("--urls", type=Path, required=True)
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--functional-samples", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--concurrency", type=int, default=1)

    verify = subparsers.add_parser("verify-run")
    verify.add_argument("--platform", required=True)
    verify.add_argument("--sources", type=Path, required=True)
    verify.add_argument("--urls", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--functional-samples", type=Path, required=True)
    verify.add_argument("--result-dir", type=Path, required=True)
    verify.add_argument("--current-access-mode")
    verify.add_argument("--current-adapter-version")
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行 CLI，并只输出不含凭证的 JSON 摘要。"""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if getattr(args, "concurrency", 1) < 1:
            raise AcceptanceError("CONCURRENCY_INVALID", "concurrency 必须为正整数")
        if args.command == "sources":
            report = create_sources(
                load_provider(args.platform),
                platform_code=args.platform,
                community_seed_file=args.community_seeds,
                output=args.output,
                evidence_dir=args.evidence_dir,
                access_mode=args.access_mode,
            )
        elif args.command == "discover":
            report = create_discovery(
                load_provider(args.platform),
                platform_code=args.platform,
                sources_path=args.sources,
                output=args.output,
                events_path=args.events,
                access_mode=args.access_mode,
                concurrency=args.concurrency,
            )
        elif args.command == "freeze":
            report = freeze_inputs(
                platform_code=args.platform,
                candidates_path=args.candidates,
                sources_path=args.sources,
                output=args.output,
                manifest_path=args.manifest,
                seed=args.seed,
            )
        elif args.command == "samples":
            report = create_functional_samples(
                platform_code=args.platform,
                candidates_path=args.candidates,
                manifest_path=args.manifest,
                output=args.output,
            )
        elif args.command == "verify-inputs":
            report = verify_inputs(
                platform_code=args.platform,
                sources_path=args.sources,
                urls_path=args.urls,
                manifest_path=args.manifest,
                expected_count=FORMAL_COUNT,
                current_access_mode=args.current_access_mode,
                current_adapter_version=args.current_adapter_version,
                current_git_commit_value=current_git_commit(),
            )
        elif args.command == "run":
            report = create_run(
                load_provider(args.platform),
                platform_code=args.platform,
                sources_path=args.sources,
                urls_path=args.urls,
                manifest_path=args.manifest,
                functional_samples_path=args.functional_samples,
                output_dir=args.output,
                concurrency=args.concurrency,
            )
        else:
            report = verify_run(
                platform_code=args.platform,
                sources_path=args.sources,
                urls_path=args.urls,
                manifest_path=args.manifest,
                functional_samples_path=args.functional_samples,
                result_dir=args.result_dir,
                expected_count=FORMAL_COUNT,
                current_access_mode=args.current_access_mode,
                current_adapter_version=args.current_adapter_version,
                current_git_commit_value=current_git_commit(),
            )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report.get("passed", True) else 2
    except AcceptanceError as exc:
        print(
            json.dumps(
                {"passed": False, "error_code": exc.code, "message": exc.message},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
