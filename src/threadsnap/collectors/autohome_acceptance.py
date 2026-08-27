"""汽车之家生产适配器到固定 500 条离线验收合同的薄桥。"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .autohome import (
    ADAPTER_VERSION,
    MAX_LIST_PAGES,
    PAGE_SIZE,
    AutohomeCollector,
    parse_circle_url,
)
from .base import AuthenticationRequired, CollectorFailure

FORMAL_COUNT = 500
CONTROL_CODES = frozenset(
    {"PLATFORM_CAPTCHA_REQUIRED", "PLATFORM_CHALLENGE", "PLATFORM_RATE_LIMITED"}
)
CONTROL_CLASSES = frozenset({"login", "captcha", "challenge", "rate_limited"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_evidence(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise CollectorFailure("ACCEPTANCE_EVIDENCE_EXISTS", f"验收证据已存在：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _failure_class(error: BaseException) -> str:
    if isinstance(error, AuthenticationRequired):
        return "login"
    code = error.code if isinstance(error, CollectorFailure) else ""
    return {
        "PLATFORM_CAPTCHA_REQUIRED": "captcha",
        "PLATFORM_CHALLENGE": "challenge",
        "PLATFORM_RATE_LIMITED": "rate_limited",
        "POST_NOT_FOUND": "not_found",
        "POST_ID_MISMATCH": "wrong_post",
        "WRONG_POST": "wrong_post",
        "PLATFORM_NETWORK_ERROR": "network_error",
        "PLATFORM_RESPONSE_EMPTY": "empty",
        "PLATFORM_RESPONSE_INVALID": "response_invalid",
    }.get(code, "error")


def _failure_code(error: BaseException) -> str:
    if isinstance(error, AuthenticationRequired):
        return "PLATFORM_LOGIN_REQUIRED"
    if isinstance(error, CollectorFailure):
        return error.code
    return type(error).__name__


def _failure_message(error: BaseException) -> str:
    if isinstance(error, (AuthenticationRequired, CollectorFailure)):
        return error.message
    return str(error)


def _source_url(community_url: str, list_order: str) -> str:
    source = parse_circle_url(community_url)
    sort = "topic" if list_order == "latest_publish" else "post"
    bbs_type = str(source.raw_status["bbs_type"])
    return (
        f"https://club.autohome.com.cn/bbs/forum-{bbs_type}-{source.external_id}-1.html?sort={sort}"
    )


def _scenario_tags(
    record: dict[str, Any], *, access_mode: str, discovery_tags: set[str]
) -> list[str]:
    content = str(record.get("content") or "")
    images = record.get("image_urls") if isinstance(record.get("image_urls"), list) else []
    videos = record.get("video_urls") if isinstance(record.get("video_urls"), list) else []
    comments = record.get("comments") if isinstance(record.get("comments"), list) else []
    tags = set(discovery_tags)
    if content:
        tags.add("text_post")
    if images:
        tags.add("image_post")
    if videos:
        tags.add("video_post")
    if content and (images or videos):
        tags.add("mixed_media_post")
    if len(comments) == 0:
        tags.add("comments_zero")
    elif len(comments) < 10:
        tags.add("comments_1_9")
    else:
        tags.add("comments_10_plus")
    visibility = record.get("visibility")
    if visibility == "visible":
        tags.add("status_visible")
    elif visibility == "hidden":
        tags.add("status_hidden_deleted")
    elif visibility == "unknown":
        tags.add("status_unknown")
    tags.add("access_auth_required" if access_mode == "authenticated" else "access_anonymous")
    if len(content) >= 1_000:
        tags.add("long_body")
    if any(not character.isascii() or character in "<>/&\"'" for character in content):
        tags.add("special_characters")
    return sorted(tags)


def _record_contract_errors(record: dict[str, Any], expected_post_id: str) -> list[str]:
    """在 Provider 边界先计算一次与纯校验器一致的关键合同。"""

    errors: list[str] = []
    if str(record.get("platform_post_id") or "") != expected_post_id:
        errors.append("wrong_post")
    if not (
        str(record.get("content") or "").strip()
        or record.get("image_urls")
        or record.get("video_urls")
    ):
        errors.append("content_missing")
    comments = record.get("comments")
    raw_status = record.get("raw_status")
    raw_status = raw_status if isinstance(raw_status, dict) else {}
    page_end = raw_status.get("comment_page_end")
    comments = comments if isinstance(comments, list) else []
    if len(comments) > 10:
        errors.append("comment_limit_exceeded")
    if not (
        raw_status.get("comments_complete") is True
        and isinstance(page_end, dict)
        and (len(comments) >= 10 or page_end.get("has_more") is False)
    ):
        errors.append("comments_incomplete")
    if record.get("visibility") not in {"visible", "hidden", "unknown"}:
        errors.append("normalized_status_invalid")
    return errors


class AutohomeAcceptanceProvider:
    """只供 Git 外验收产物使用，不改变平台注册与业务启用状态。"""

    platform_code = "autohome"
    adapter_version = ADAPTER_VERSION
    max_concurrency = 1
    supported_access_modes = frozenset({"anonymous"})

    def __init__(
        self,
        storage_state: dict[str, Any] | None = None,
        *,
        collector_factory: Callable[..., AutohomeCollector] = AutohomeCollector,
    ):
        self.storage_state = storage_state
        self.collector_factory = collector_factory

    def _collector(self, *, access_mode: str, concurrency: int = 1) -> AutohomeCollector:
        if access_mode not in self.supported_access_modes:
            raise CollectorFailure(
                "ACCEPTANCE_ACCESS_MODE_UNSUPPORTED",
                f"汽车之家验收 Provider 尚未证明访问模式 {access_mode!r}",
            )
        if concurrency != self.max_concurrency:
            raise CollectorFailure("ACCEPTANCE_CONCURRENCY_INVALID", "汽车之家验收并发固定为 1。")
        return self.collector_factory(self.storage_state, concurrency=1, browser_headless=False)

    def discover_sources(
        self, community_seeds: list[dict[str, Any]], evidence_dir: Path
    ) -> list[dict[str, Any]]:
        """逐 seed 验证两个真实列表顺序，并为每个关系保存一份证据。"""

        collector = self._collector(access_mode="anonymous")
        records: list[dict[str, Any]] = []
        control_seen = False
        for seed in community_seeds:
            seed_identity = str(seed["seed_identity"])
            community_url = str(seed["community_url"])
            for list_order in ("latest_reply", "latest_publish"):
                normalized_list_url = _source_url(community_url, list_order)
                source_identity = f"{seed_identity}:{list_order}"
                evidence_name = (
                    f"{hashlib.sha256(seed_identity.encode()).hexdigest()[:16]}-{list_order}.json"
                )
                evidence_path = evidence_dir / evidence_name
                evidence: dict[str, Any] = {
                    "adapter_version": self.adapter_version,
                    "community_url": community_url,
                    "confirmed_at": _now(),
                    "list_order": list_order,
                    "normalized_list_url": normalized_list_url,
                    "seed_identity": seed_identity,
                }
                status = "failed"
                if control_seen:
                    evidence.update(
                        {
                            "failure_code": "NOT_REQUESTED_AFTER_CONTROL",
                            "request_count": 0,
                        }
                    )
                else:
                    try:
                        validated = collector.validate_circle(normalized_list_url)
                        if validated.get("sort") != list_order:
                            raise CollectorFailure(
                                "SOURCE_ORDER_MISMATCH", "来源验证返回的列表顺序不一致。"
                            )
                        status = "verified"
                        evidence.update(
                            {
                                "external_id": validated.get("external_id"),
                                "sample_post_id": validated.get("sample_post_id"),
                                "request_count": 2,
                            }
                        )
                    except (AuthenticationRequired, CollectorFailure) as error:
                        response_class = _failure_class(error)
                        evidence.update(
                            {
                                "failure_code": _failure_code(error),
                                "failure_message": _failure_message(error),
                                "request_count": 1,
                                "response_class": response_class,
                            }
                        )
                        control_seen = response_class in CONTROL_CLASSES
                _write_evidence(evidence_path, evidence)
                records.append(
                    {
                        "seed_identity": seed_identity,
                        "community_url": community_url,
                        "source_identity": source_identity,
                        "list_order": list_order,
                        "normalized_list_url": normalized_list_url,
                        "status": status,
                        "relation_evidence": {
                            "path": evidence_name,
                            "relation_sha256": hashlib.sha256(
                                f"{seed_identity}\0{list_order}\0{normalized_list_url}".encode()
                            ).hexdigest(),
                            "request_count": evidence["request_count"],
                        },
                    }
                )
        return records

    def discover_candidates(
        self,
        sources: list[dict[str, Any]],
        *,
        access_mode: str,
        concurrency: int,
    ) -> dict[str, list[dict[str, Any]]]:
        """用生产列表和详情解析器形成候选、预检事实及请求事件。"""

        collector = self._collector(access_mode=access_mode, concurrency=concurrency)
        events: list[dict[str, Any]] = []
        grouped: dict[str, dict[str, Any]] = {}
        pagination_end_ids: set[str] = set()
        for source in sources:
            started = time.perf_counter()
            identity = str(source["source_identity"])
            rows, stop_reason = collector.discover_posts(
                str(source["normalized_list_url"]), MAX_LIST_PAGES * PAGE_SIZE
            )
            events.append(
                {
                    "event_id": len(events) + 1,
                    "stage": "list_discovery",
                    "source_identity": identity,
                    "list_order": source["list_order"],
                    "response_class": "post",
                    "candidate_count": len(rows),
                    "duration_ms": round((time.perf_counter() - started) * 1_000),
                    "stop_reason": stop_reason,
                }
            )
            if rows:
                pagination_end_ids.add(str(rows[-1]["post_id"]))
            for candidate in rows:
                post_id = str(candidate["post_id"])
                item = grouped.setdefault(
                    post_id,
                    {
                        "platform_post_id": post_id,
                        "normalized_url": candidate["url"],
                        "source_identity": identity,
                        "source_memberships": [],
                        "list_order": source["list_order"],
                        "candidate": candidate,
                        "order_indexes": [],
                    },
                )
                if item["normalized_url"] != candidate["url"]:
                    raise CollectorFailure(
                        "ACCEPTANCE_CANDIDATE_URL_CONFLICT",
                        f"帖子 {post_id} 对应多个规范 URL。",
                    )
                item["source_memberships"].append(identity)
                item["order_indexes"].append(int(candidate["order_index"]))

        control_seen = False
        candidates: list[dict[str, Any]] = []
        for item in grouped.values():
            discovery_tags: set[str] = set()
            if len(set(item["source_memberships"])) > 1:
                discovery_tags.add("duplicate_candidate")
            if any(index >= PAGE_SIZE for index in item["order_indexes"]):
                discovery_tags.add("cross_page_discovery")
            if item["platform_post_id"] in pagination_end_ids:
                discovery_tags.add("pagination_end")
            event_id = len(events) + 1
            started = time.perf_counter()
            if control_seen:
                response_class = "not_requested"
                record = None
                error: BaseException | None = None
                request_count = 0
            else:
                try:
                    record = collector.fetch_post(
                        item["normalized_url"], candidate=item["candidate"]
                    )
                    if record is None:
                        error = CollectorFailure("POST_NOT_FOUND", "帖子详情当前不存在。")
                        response_class = "not_found"
                    else:
                        error = None
                        response_class = "post"
                    request_count = 1
                except (AuthenticationRequired, CollectorFailure) as caught:
                    record = None
                    error = caught
                    response_class = _failure_class(caught)
                    request_count = 1
                    control_seen = response_class in CONTROL_CLASSES
            event = {
                "event_id": event_id,
                "stage": "candidate_preflight",
                "url": item["normalized_url"],
                "response_class": response_class,
                "request_count": request_count,
                "duration_ms": round((time.perf_counter() - started) * 1_000),
            }
            if error is not None:
                event["failure_code"] = _failure_code(error)
            events.append(event)
            preflight_errors = (
                _record_contract_errors(record, item["platform_post_id"]) if record else []
            )
            valid = record is not None and response_class == "post" and not preflight_errors
            if response_class == "post" and preflight_errors:
                response_class = "response_invalid"
                event["response_class"] = response_class
                event["contract_errors"] = preflight_errors
            tags = (
                _scenario_tags(record, access_mode=access_mode, discovery_tags=discovery_tags)
                if record is not None
                else sorted(discovery_tags)
            )
            if response_class in CONTROL_CLASSES:
                tags = sorted(set(tags) | {"platform_control"})
                tags.append(
                    "access_auth_expired"
                    if access_mode == "authenticated"
                    else "access_auth_required"
                )
            candidates.append(
                {
                    "source_identity": item["source_identity"],
                    "source_memberships": sorted(set(item["source_memberships"])),
                    "list_order": item["list_order"],
                    "platform_post_id": item["platform_post_id"],
                    "normalized_url": item["normalized_url"],
                    "preflight_valid": valid,
                    "preflight_class": response_class,
                    "preflight_observed_post_id": (
                        record.get("platform_post_id") if record is not None else None
                    ),
                    "scenario_tags": sorted(set(tags)),
                    "observed_facts": {
                        "response_class": response_class,
                        "comment_count": len(record.get("comments", [])) if record else None,
                        "normalized_status": record.get("visibility") if record else None,
                        "has_text": bool(record and record.get("content")),
                        "image_count": len(record.get("image_urls", [])) if record else 0,
                        "video_count": len(record.get("video_urls", [])) if record else 0,
                    },
                    "evidence_refs": [f"request-events.jsonl#{event_id}"],
                    "confirmed_at": _now(),
                }
            )
        return {"candidates": candidates, "request_events": events}

    def run_acceptance(
        self,
        urls: list[str],
        *,
        manifest: dict[str, Any],
        access_mode: str,
        concurrency: int,
    ) -> dict[str, Any]:
        """逐条调用生产详情解析；首个控制响应后给剩余输入保存未请求终态。"""

        if len(urls) != FORMAL_COUNT or manifest.get("selected_count") != FORMAL_COUNT:
            raise CollectorFailure(
                "ACCEPTANCE_FORMAL_COUNT_INVALID", "汽车之家正式验收分母固定为 500。"
            )
        collector = self._collector(access_mode=access_mode, concurrency=concurrency)
        selected = manifest.get("selected")
        if not isinstance(selected, list) or len(selected) != FORMAL_COUNT:
            raise CollectorFailure("ACCEPTANCE_MANIFEST_INVALID", "冻结清单身份分母不一致。")
        events: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        control_seen = False
        for index, url in enumerate(urls):
            expected_post_id = str(selected[index].get("platform_post_id") or "")
            if control_seen:
                results.append(
                    self._terminal_result(
                        index=index,
                        url=url,
                        expected_post_id=expected_post_id,
                        response_class="not_requested",
                        request_count=0,
                        duration_ms=0,
                        event_refs=[],
                        record=None,
                        error_code="NOT_REQUESTED_AFTER_CONTROL",
                    )
                )
                continue
            event_id = len(events) + 1
            started = time.perf_counter()
            try:
                record = collector.fetch_post(url)
                if record is None:
                    error = CollectorFailure("POST_NOT_FOUND", "帖子详情当前不存在。")
                    response_class = "not_found"
                else:
                    error = None
                    response_class = "post"
            except (AuthenticationRequired, CollectorFailure) as caught:
                record = None
                error = caught
                response_class = _failure_class(caught)
            duration_ms = round((time.perf_counter() - started) * 1_000)
            event: dict[str, Any] = {
                "event_id": event_id,
                "stage": "formal_detail",
                "input_index": index,
                "url": url,
                "response_class": response_class,
                "duration_ms": duration_ms,
            }
            if error is not None:
                event["failure_code"] = _failure_code(error)
            events.append(event)
            results.append(
                self._terminal_result(
                    index=index,
                    url=url,
                    expected_post_id=expected_post_id,
                    response_class=response_class,
                    request_count=1,
                    duration_ms=duration_ms,
                    event_refs=[event_id],
                    record=record,
                    error_code=_failure_code(error) if error is not None else None,
                )
            )
            control_seen = response_class in CONTROL_CLASSES
        return {
            "results": results,
            "request_events": events,
            "environment": {
                "collector_class": type(collector).__name__,
                "collector_concurrency": collector.concurrency,
                "formal_count": FORMAL_COUNT,
                "control_stop_policy": "first_control_then_not_requested_terminals",
            },
        }

    @staticmethod
    def _terminal_result(
        *,
        index: int,
        url: str,
        expected_post_id: str,
        response_class: str,
        request_count: int,
        duration_ms: int,
        event_refs: list[int],
        record: dict[str, Any] | None,
        error_code: str | None,
    ) -> dict[str, Any]:
        observed_post_id = record.get("platform_post_id") if record else None
        raw_status = record.get("raw_status") if record else None
        raw_status = dict(raw_status) if isinstance(raw_status, dict) else {}
        if error_code:
            raw_status["failure_code"] = error_code
        raw_status.setdefault("response_class", response_class)
        contract_errors = (
            _record_contract_errors(record, expected_post_id) if record is not None else []
        )
        return {
            "input_index": index,
            "url": url,
            "url_sha256": hashlib.sha256(url.encode()).hexdigest(),
            "input_platform_post_id": expected_post_id,
            "observed_platform_post_id": observed_post_id,
            "post_id_matches": observed_post_id == expected_post_id,
            "body": record.get("content") if record else None,
            "image_urls": list(record.get("image_urls") or []) if record else [],
            "video_urls": list(record.get("video_urls") or []) if record else [],
            "comments": list(record.get("comments") or []) if record else [],
            "comments_complete": bool(raw_status.get("comments_complete")) if record else False,
            "comment_page_end": raw_status.get("comment_page_end") if record else {},
            "raw_status": raw_status,
            "normalized_status": record.get("visibility", "unknown") if record else "unknown",
            "response_class": response_class,
            "request_count": request_count,
            "duration_ms": duration_ms,
            "access_channel": "production_autohome_collector",
            "recovery_count": 0,
            "request_event_refs": event_refs,
            "contract_errors": contract_errors,
            "final_status": (
                "valid" if response_class == "post" and not contract_errors else "invalid"
            ),
        }


def create_autohome_acceptance_provider() -> AutohomeAcceptanceProvider:
    """为注册表提供无副作用的延迟构造入口。"""

    return AutohomeAcceptanceProvider()
