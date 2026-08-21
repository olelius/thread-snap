"""在线多模态舆情配置、持久任务、模型客户端与人工修订。"""

from __future__ import annotations

import hashlib
import json
import socket
import threading
from copy import deepcopy
from ipaddress import ip_address, ip_network
from time import monotonic
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from .errors import DomainError
from .local_sentiment import LOCAL_MODEL_CODE, LOCAL_MODEL_NAME, LocalSentimentAnalyzer
from .models import (
    ExtractionRun,
    ManualSentimentRevision,
    PostSnapshot,
    SentimentAnalysis,
    SentimentConfig,
    utc_now,
)
from .poc.sentiment import (
    parse_feedback_text,
    parse_sse_lines_with_completion,
    stable_url_hash,
)
from .schemas import ManualSentimentRevisionCreate, SentimentConfigUpdate
from .session_store import SessionStore

HOSTED_MODEL_CODE = "qwen3.5-omni-plus-2026-03-15"
MODEL_CODES = (HOSTED_MODEL_CODE, LOCAL_MODEL_CODE)
MODEL_PROFILES = {
    HOSTED_MODEL_CODE: {
        "name": "千问 Omni Plus（云端多模态）",
        "provider": "hosted",
        "input_mode": "multimodal",
    },
    LOCAL_MODEL_CODE: {
        "name": LOCAL_MODEL_NAME,
        "provider": "local",
        "input_mode": "text_only",
    },
}
HOSTED_PROMPT_VERSION = "v2"
LOCAL_PIPELINE_VERSION = "local-v1"
CATEGORIES = (
    "product_complaint",
    "product_criticism",
    "service_complaint",
    "brand_criticism",
    "competitor_attack",
    "other",
)
MANUAL_ALLOWED_STATUSES = frozenset(
    {"analysis_completed", "analysis_partial", "analysis_failed", "analysis_disabled"}
)
DEFAULT_PRODUCTS = [
    "A9",
    "A9L",
    "QQ3 EV",
    "T9L",
    "T11",
    "T9",
    "艾瑞泽8",
    "艾瑞泽8PRO",
    "瑞虎8",
    "瑞虎8PLUS",
    "瑞虎8PRO",
    "瑞虎9",
    "瑞虎7L",
    "风云T7",
]
PROXY_FAKE_IP_NETWORK = ip_network("198.18.0.0/15")
SENTIMENT_WORKER_CONCURRENCY = 2


def model_profile(model_code: str) -> dict[str, str]:
    try:
        return MODEL_PROFILES[model_code]
    except KeyError as exc:
        raise ValueError(f"不支持的舆情模型：{model_code}") from exc


def analysis_version(model_code: str) -> str:
    return (
        LOCAL_PIPELINE_VERSION
        if model_profile(model_code)["provider"] == "local"
        else HOSTED_PROMPT_VERSION
    )


class TextCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["absent", "processed", "unprocessed"]
    evidence: list[str] = Field(default_factory=list)


class MediaItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_index: int = Field(ge=0)
    url_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal[
        "absent",
        "processed",
        "speech",
        "silent",
        "no_speech",
        "inaccessible",
        "unrecognizable",
        "unprocessed",
    ]
    evidence: list[str] = Field(default_factory=list)


class MediaCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    expected_count: int = Field(ge=0)
    processed_count: int = Field(ge=0)
    items: list[MediaItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts(self) -> "MediaCoverage":
        if self.status == "not_requested":
            if self.processed_count != 0 or self.items:
                raise ValueError("未请求分析的媒体不得包含处理结果")
            return self
        if len(self.items) != self.expected_count:
            raise ValueError("媒体 items 数量必须等于 expected_count")
        if self.processed_count > self.expected_count:
            raise ValueError("processed_count 不得超过 expected_count")
        actual_processed = sum(
            item.status in {"processed", "speech", "silent", "no_speech"} for item in self.items
        )
        if self.processed_count != actual_processed:
            raise ValueError("processed_count 与逐媒体处理状态不一致")
        if self.expected_count == 0 and self.status != "absent":
            raise ValueError("没有媒体输入时覆盖状态必须为 absent")
        if self.expected_count > 0 and self.status == "absent":
            raise ValueError("存在媒体输入时覆盖状态不得为 absent")
        return self


class VisualCoverage(MediaCoverage):
    status: Literal[
        "absent",
        "processed",
        "inaccessible",
        "unrecognizable",
        "unprocessed",
        "not_requested",
    ]


class AudioCoverage(MediaCoverage):
    status: Literal[
        "absent",
        "processed",
        "speech",
        "silent",
        "no_speech",
        "inaccessible",
        "unrecognizable",
        "unprocessed",
        "not_requested",
    ]


class Modalities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: TextCoverage
    image: VisualCoverage
    video_visual: VisualCoverage
    video_audio: AudioCoverage


class SentimentFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_relevance: bool
    matched_subjects: list[str] = Field(default_factory=list)
    sentiment: Literal["negative", "non_negative"] | None
    primary_category: (
        Literal[
            "product_complaint",
            "product_criticism",
            "service_complaint",
            "brand_criticism",
            "competitor_attack",
            "other",
        ]
        | None
    )
    secondary_categories: list[
        Literal[
            "product_complaint",
            "product_criticism",
            "service_complaint",
            "brand_criticism",
            "competitor_attack",
            "other",
        ]
    ] = Field(default_factory=list)
    modalities: Modalities
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_result(self) -> "SentimentFeedback":
        if not self.subject_relevance:
            if (
                self.sentiment is not None
                or self.primary_category is not None
                or self.secondary_categories
            ):
                raise ValueError("不相关结果的情感和负面类型必须为空")
        elif self.sentiment == "negative" and self.primary_category is None:
            raise ValueError("负面结果必须包含 primary_category")
        elif self.sentiment == "non_negative" and (
            self.primary_category is not None or self.secondary_categories
        ):
            raise ValueError("非负面结果不得包含负面类型")
        elif self.sentiment is None:
            raise ValueError("相关结果必须包含 sentiment")
        if self.primary_category in self.secondary_categories:
            raise ValueError("次要类型不得重复主要类型")
        if len(set(self.secondary_categories)) != len(self.secondary_categories):
            raise ValueError("次要类型不得重复")
        return self


def deduplicate_media_urls(values: list[str] | None) -> list[str]:
    """按忽略查询及已知路径签名的稳定媒体身份去重，并保留首个 URL。"""

    output: list[str] = []
    observed: set[str] = set()
    for value in values or []:
        identity = stable_url_hash(value)
        if identity in observed:
            continue
        observed.add(identity)
        output.append(value)
    return output


def sentiment_input_hash(post: PostSnapshot, model_code: str) -> str:
    """只对实际模型输入计算稳定哈希，媒体签名查询不影响继承。"""

    payload: dict[str, Any] = {
        "title": post.title or "",
        "content": post.content or "",
    }
    if model_profile(model_code)["input_mode"] == "multimodal":
        payload["images"] = [
            stable_url_hash(value) for value in deduplicate_media_urls(post.image_urls)
        ]
        payload["videos"] = [
            stable_url_hash(value) for value in deduplicate_media_urls(post.video_urls)
        ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_modality_identity(feedback: SentimentFeedback, post: PostSnapshot) -> None:
    """核对模型逐媒体索引和稳定 URL 哈希确实对应本次输入。"""

    has_text = bool((post.title or "").strip() or (post.content or "").strip())
    if has_text == (feedback.modalities.text.status == "absent"):
        raise ValueError("文字覆盖状态与实际标题、正文输入不一致")
    expected = {
        "image": [stable_url_hash(value) for value in deduplicate_media_urls(post.image_urls)],
        "video_visual": [
            stable_url_hash(value) for value in deduplicate_media_urls(post.video_urls)
        ],
        "video_audio": [
            stable_url_hash(value) for value in deduplicate_media_urls(post.video_urls)
        ],
    }
    for name, hashes in expected.items():
        coverage = getattr(feedback.modalities, name)
        if coverage.expected_count != len(hashes):
            raise ValueError(f"{name}.expected_count 与实际输入数量不一致")
        if coverage.status == "not_requested":
            if coverage.items or coverage.processed_count:
                raise ValueError(f"{name} 未请求分析时不得包含处理结果")
            continue
        observed = {item.input_index: item.url_hash for item in coverage.items}
        if set(observed) != set(range(len(hashes))):
            raise ValueError(f"{name}.items 的输入索引不完整或重复")
        if any(observed[index] != value for index, value in enumerate(hashes)):
            raise ValueError(f"{name}.items 的 URL 哈希与实际输入不一致")


def normalize_feedback_payload(
    payload: dict[str, Any], post: PostSnapshot
) -> tuple[dict[str, Any], bool]:
    """只修复可由输入契约唯一确定的提供方 JSON 形状，不改写观点字段。"""

    normalized = deepcopy(payload)
    changed = False
    matched_subjects = normalized.get("matched_subjects")
    if isinstance(matched_subjects, list):
        normalized_subjects: list[Any] = []
        for item in matched_subjects:
            if isinstance(item, dict):
                value = item.get("product") or item.get("brand")
                if isinstance(value, str) and value.strip():
                    normalized_subjects.append(value.strip())
                    changed = True
                    continue
            normalized_subjects.append(item)
        normalized["matched_subjects"] = normalized_subjects
    if normalized.get("sentiment") == "non_negative":
        if normalized.get("primary_category") is not None:
            normalized["primary_category"] = None
            changed = True
        if normalized.get("secondary_categories"):
            normalized["secondary_categories"] = []
            changed = True
    modalities = normalized.get("modalities")
    if not isinstance(modalities, dict):
        return normalized, changed

    text = modalities.get("text")
    if isinstance(text, dict):
        if isinstance(text.get("evidence"), str):
            text["evidence"] = [text["evidence"]]
            changed = True
        if text.get("status") == "present":
            text["status"] = "processed"
            changed = True

    expected = {
        "image": [stable_url_hash(value) for value in deduplicate_media_urls(post.image_urls)],
        "video_visual": [
            stable_url_hash(value) for value in deduplicate_media_urls(post.video_urls)
        ],
        "video_audio": [
            stable_url_hash(value) for value in deduplicate_media_urls(post.video_urls)
        ],
    }
    for name, expected_hashes in expected.items():
        coverage = modalities.get(name)
        if not isinstance(coverage, dict):
            continue
        if not expected_hashes and coverage.get("status") == "skipped":
            coverage["status"] = "absent"
            changed = True
        elif (
            expected_hashes
            and coverage.get("status") == "present"
            and coverage.get("processed_count") == coverage.get("expected_count")
        ):
            coverage["status"] = "processed"
            changed = True
        items = coverage.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("evidence"), str):
                item["evidence"] = [item["evidence"]]
                changed = True
            # 提供方偶尔把“已处理且与主题相关”写成 relevant。覆盖层只表达
            # 是否成功处理；当汇总状态和计数均明确为已处理时可唯一归一为 processed。
            if (
                item.get("status") in {"relevant", "present"}
                and coverage.get("status") == "processed"
                and coverage.get("processed_count") == coverage.get("expected_count")
            ):
                item["status"] = "processed"
                changed = True
        if not expected_hashes or len(items) != len(expected_hashes):
            continue
        indexes = {
            item.get("input_index")
            for item in items
            if isinstance(item, dict) and isinstance(item.get("input_index"), int)
        }
        if indexes == set(range(1, len(expected_hashes) + 1)):
            for item in items:
                item["input_index"] -= 1
            changed = True
            indexes = set(range(len(expected_hashes)))
        # URL 哈希和输入数量均由后端掌握。模型只需用完整、不重复的索引关联
        # 观点与依据；避免让模型抄写 64 位冗余标识成为任务成败条件。
        if indexes == set(range(len(expected_hashes))):
            for item in items:
                expected_hash = expected_hashes[item["input_index"]]
                if item.get("url_hash") != expected_hash:
                    item["url_hash"] = expected_hash
                    changed = True
    return normalized, changed


def validate_public_https_base_url(value: str, *, resolve: bool) -> str:
    """限制模型入口为无凭证、无查询的公网 HTTPS 根地址。"""

    normalized = value.strip().rstrip("/")
    parts = urlsplit(normalized)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise DomainError(
            "SENTIMENT_BASE_URL_INVALID",
            "API 地址必须是无账号、查询参数和片段的公网 HTTPS 地址。",
        )
    try:
        literal_host = ip_address(parts.hostname)
    except ValueError:
        literal_host = None
    if literal_host is not None and not literal_host.is_global:
        raise DomainError(
            "SENTIMENT_HOST_NOT_PUBLIC",
            "API 地址只允许使用公网域名或公网 IP。",
        )
    if resolve:
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    parts.hostname, parts.port or 443, type=socket.SOCK_STREAM
                )
            }
        except OSError as exc:
            raise DomainError("SENTIMENT_HOST_UNRESOLVED", "API 地址域名解析失败。") from exc
        parsed_addresses = [ip_address(value) for value in addresses]
        # Clash/Mihomo 等透明代理的 Fake-IP 模式会把公网域名映射到 RFC 2544
        # 基准网段；仅对“域名解析结果”兼容该网段，直接填写该网段 IP 仍在上方拒绝。
        if not parsed_addresses or any(
            not address.is_global and address not in PROXY_FAKE_IP_NETWORK
            for address in parsed_addresses
        ):
            raise DomainError(
                "SENTIMENT_HOST_NOT_PUBLIC",
                "API 地址只允许解析到公网 IP。",
            )
    return normalized


def build_prompt(
    post: PostSnapshot, config: SentimentConfig, subject_snapshot: dict[str, Any] | None = None
) -> str:
    images = [stable_url_hash(value) for value in deduplicate_media_urls(post.image_urls)]
    videos = [stable_url_hash(value) for value in deduplicate_media_urls(post.video_urls)]
    subject = subject_snapshot or {
        "brand": config.brand,
        "products": config.products,
        "supplement": config.supplement or "",
    }
    return f"""只返回一个标准 JSON 对象，不使用 Markdown，不联网搜索。
判定对象配置：{json.dumps(subject, ensure_ascii=False)}。
请结合语境自行识别品牌、产品、服务和常见别名；内容与判定对象无关时 subject_relevance=false。
对判定对象不利为 negative，中性或正面为 non_negative。负面主要类型仅允许：{json.dumps(CATEGORIES, ensure_ascii=False)}。
只分析标题、正文、全部图片和全部视频，不分析评论。逐项报告文字、图片、视频画面和视频音频的实际处理状态与中文事实依据。

标题：{post.title or ""}
正文：{post.content or ""}
图片 URL 哈希：{json.dumps(images)}
视频 URL 哈希：{json.dumps(videos)}

返回字段：subject_relevance、matched_subjects、sentiment、primary_category、secondary_categories、modalities、summary。
不相关时 sentiment 与 primary_category 为 null；负面必须有 primary_category；次要类型不得重复主要类型。
modalities.text 包含 status/evidence；modalities.image、video_visual、video_audio 均包含 status、expected_count、processed_count、items。
每个 items 项包含 input_index、对应 url_hash、status、evidence，items 数量必须等于 expected_count。
所有 evidence 必须是 JSON 字符串数组，即使只有一条也不得直接返回字符串。
每种媒体的 input_index 均从 0 开始连续编号；没有输入的模态必须返回 status=absent、expected_count=0、processed_count=0、items=[]，不得使用 skipped。
视频音频 status 只使用 absent、speech、silent、no_speech、inaccessible、unrecognizable 或 unprocessed。
expected_count：image={len(images)}，video_visual={len(videos)}，video_audio={len(videos)}。"""


def build_request(
    post: PostSnapshot,
    config: SentimentConfig,
    *,
    tiny_test: bool = False,
    subject_snapshot: dict[str, Any] | None = None,
    model_code: str | None = None,
) -> dict[str, Any]:
    if tiny_test:
        content: list[dict[str, Any]] = [
            {"type": "text", "text": '只返回 JSON 对象：{"ok":true}。'}
        ]
    else:
        image_urls = deduplicate_media_urls(post.image_urls)
        video_urls = deduplicate_media_urls(post.video_urls)
        content = [
            *({"type": "image_url", "image_url": {"url": value}} for value in image_urls),
            *({"type": "video_url", "video_url": {"url": value}} for value in video_urls),
            {"type": "text", "text": build_prompt(post, config, subject_snapshot)},
        ]
    return {
        "model": model_code or config.model_code,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["text"],
        "response_format": {"type": "json_object"},
        "stream": True,
        "stream_options": {"include_usage": True},
    }


class SentimentModelClient:
    """窄 OpenAI 兼容客户端：不跟随重定向，不自动重试。"""

    def request(
        self, base_url: str, api_key: str, body: dict[str, Any]
    ) -> tuple[str, dict[str, Any] | None, str | None, int]:
        endpoint = base_url.rstrip("/") + "/chat/completions"
        started = monotonic()
        timeout = httpx.Timeout(connect=20.0, read=600.0, write=60.0, pool=20.0)
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            with client.stream(
                "POST",
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise ModelRequestError(
                        "模型入口返回重定向，已阻止跨地址发送凭证。",
                        status_code=response.status_code,
                        config_error=True,
                    )
                if response.status_code >= 400:
                    response_text = response.read().decode("utf-8", errors="replace")[:2000].lower()
                    model_error = response.status_code in {400, 404} and "model" in response_text
                    input_too_large = response.status_code in {400, 413} and any(
                        marker in response_text
                        for marker in ("limit", "length", "too large", "too long")
                    )
                    retry_after = response.headers.get("retry-after")
                    try:
                        retry_after_seconds = (
                            max(1.0, min(float(retry_after), 300.0)) if retry_after else None
                        )
                    except ValueError:
                        retry_after_seconds = None
                    raise ModelRequestError(
                        f"模型接口返回 HTTP {response.status_code}",
                        status_code=response.status_code,
                        retryable=response.status_code == 429 or response.status_code >= 500,
                        config_error=response.status_code in {401, 403} or model_error,
                        input_too_large=input_too_large,
                        retry_after_seconds=retry_after_seconds,
                    )
                request_id = response.headers.get("x-request-id") or response.headers.get(
                    "x-dashscope-request-id"
                )
                text, usage, chunks, done_seen = parse_sse_lines_with_completion(
                    response.iter_lines()
                )
        duration_ms = round((monotonic() - started) * 1000)
        finish_reasons: list[str] = []
        for chunk in chunks:
            choices = chunk.get("choices")
            if not isinstance(choices, list):
                continue
            finish_reasons.extend(
                str(choice["finish_reason"])
                for choice in choices
                if isinstance(choice, dict) and choice.get("finish_reason") is not None
            )
        if not done_seen or not finish_reasons:
            raise ModelRequestError(
                "模型流式响应在正常结束前中断。",
                retryable=True,
                response_incomplete=True,
                raw_response=text,
                usage=usage,
                request_id=request_id,
                duration_ms=duration_ms,
            )
        if finish_reasons[-1] != "stop":
            response_incomplete = finish_reasons[-1] in {"length", "max_tokens"}
            raise ModelRequestError(
                f"模型流式响应异常结束：{finish_reasons[-1]}",
                retryable=response_incomplete,
                response_incomplete=response_incomplete,
                raw_response=text,
                usage=usage,
                request_id=request_id,
                duration_ms=duration_ms,
            )
        return text, usage, request_id, duration_ms


class ModelRequestError(RuntimeError):
    """模型传输错误的受控分类；仅截断审计场景携带已生成正文。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        config_error: bool = False,
        input_too_large: bool = False,
        retry_after_seconds: float | None = None,
        response_incomplete: bool = False,
        raw_response: str = "",
        usage: dict[str, Any] | None = None,
        request_id: str | None = None,
        duration_ms: int | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.config_error = config_error
        self.input_too_large = input_too_large
        self.retry_after_seconds = retry_after_seconds
        self.response_incomplete = response_incomplete
        self.raw_response = raw_response
        self.usage = usage
        self.request_id = request_id
        self.duration_ms = duration_ms


def _is_truncated_json_error(exc: Exception, raw_response: str) -> bool:
    """只识别缺少响应尾部的 JSON，不把普通结构校验失败变成付费重试。"""

    if not isinstance(exc, json.JSONDecodeError):
        return False
    stripped = raw_response.rstrip()
    if not stripped:
        return False
    stack: list[str] = []
    in_string = False
    escaped = False
    mismatched_delimiter = False
    for character in stripped:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            stack.append(character)
        elif character in "]}":
            expected = "[" if character == "]" else "{"
            if not stack or stack[-1] != expected:
                mismatched_delimiter = True
                break
            stack.pop()
    if mismatched_delimiter:
        return False
    if exc.msg.startswith("Unterminated string"):
        return in_string
    return exc.pos >= len(stripped) - 1 and bool(stack)


def _failed_attempt(
    *,
    attempt: int,
    exc: Exception,
    raw_response: str,
    request_id: str | None,
    usage: dict[str, Any] | None,
    duration_ms: int | None,
) -> dict[str, Any]:
    """形成不含凭证的单次失败审计记录。"""

    return {
        "attempt": attempt,
        "error_code": "MODEL_STREAM_INCOMPLETE",
        "error_message": f"{type(exc).__name__}: {exc}"[:2000],
        "raw_response": raw_response or None,
        "provider_request_id": request_id,
        "usage": usage,
        "duration_ms": duration_ms,
        "recorded_at": utc_now().isoformat(),
    }


class SentimentService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        secrets: SessionStore,
        event_publisher: Callable[..., Any] | None = None,
        client: SentimentModelClient | None = None,
        local_analyzer: LocalSentimentAnalyzer | None = None,
    ):
        self.factory = factory
        self.secrets = secrets
        self.event_publisher = event_publisher
        self.client = client or SentimentModelClient()
        self.local_analyzer = local_analyzer

    @staticmethod
    def ensure_default(db: Session) -> SentimentConfig:
        config = db.get(SentimentConfig, 1)
        if not config:
            config = SentimentConfig(id=1, products=list(DEFAULT_PRODUCTS))
            db.add(config)
            db.flush()
        return config

    def get_config(self) -> dict[str, Any]:
        with self.factory.begin() as db:
            return self.config_dict(self.ensure_default(db))

    @staticmethod
    def config_dict(config: SentimentConfig) -> dict[str, Any]:
        return {
            "revision": config.revision,
            "enabled": config.enabled,
            "api_base_url": config.base_url,
            "api_key_configured": bool(config.encrypted_api_key),
            "model_code": config.model_code,
            "available_models": list(MODEL_CODES),
            "model_name": model_profile(config.model_code)["name"],
            "model_provider": model_profile(config.model_code)["provider"],
            "model_input_mode": model_profile(config.model_code)["input_mode"],
            "validation_status": config.validation_status,
            "validation_error": config.validation_error,
            "validated_at": config.validated_at,
            "subject": {
                "brand": config.brand,
                "products": config.products,
                "supplement": config.supplement,
                "version": config.subject_version,
            },
        }

    def update_config(self, value: SentimentConfigUpdate) -> dict[str, Any]:
        profile = model_profile(value.model_code)
        base_url = value.api_base_url.strip().rstrip("/")
        if profile["provider"] == "hosted" and base_url:
            base_url = validate_public_https_base_url(base_url, resolve=False)
        with self.factory.begin() as db:
            config = self.ensure_default(db)
            if value.revision != config.revision:
                raise DomainError(
                    "SENTIMENT_CONFIG_REVISION_CONFLICT",
                    "舆情配置已更新，请刷新后重试。",
                    status_code=409,
                )
            key_changed = value.api_key is not None
            connection_changed = (
                base_url != config.base_url or value.model_code != config.model_code or key_changed
            )
            subject_changed = (
                value.subject.brand.strip() != config.brand
                or value.subject.products != config.products
                or (value.subject.supplement or "").strip() != (config.supplement or "")
            )
            if value.api_key is not None:
                config.encrypted_api_key = self.secrets.encrypt_secret(value.api_key.strip())
            if (
                value.enabled
                and not connection_changed
                and (
                    config.validation_status != "valid"
                    or (
                        profile["provider"] == "hosted"
                        and (not config.encrypted_api_key or not base_url)
                    )
                )
            ):
                raise DomainError(
                    "SENTIMENT_CONFIG_NOT_VALIDATED",
                    "连接配置必须先保存并通过连接测试，之后才能启用分析。",
                    status_code=409,
                )
            was_enabled = config.enabled
            # 连接参数一旦变化，保存新值并自动关闭；新连接测试通过后再显式开启。
            config.enabled = value.enabled and not connection_changed
            config.base_url = base_url
            config.model_code = value.model_code
            config.brand = value.subject.brand.strip()
            config.products = value.subject.products
            config.supplement = (value.subject.supplement or "").strip() or None
            config.revision += 1
            if subject_changed:
                config.subject_version += 1
            if connection_changed:
                config.validation_status = "unverified"
                config.validation_error = None
                config.validated_at = None
            if was_enabled and not config.enabled:
                db.execute(
                    update(SentimentAnalysis)
                    .where(SentimentAnalysis.status == "analysis_queued")
                    .values(status="analysis_disabled", finished_at=utc_now())
                )
                db.execute(
                    update(PostSnapshot)
                    .where(PostSnapshot.analysis_status == "analysis_queued")
                    .values(analysis_status="analysis_disabled", sentiment_updated_at=utc_now())
                )
            elif not was_enabled and config.enabled:
                db.execute(
                    update(SentimentAnalysis)
                    .where(SentimentAnalysis.status == "analysis_paused")
                    .values(status="analysis_queued", error_code=None, error_message=None)
                )
                db.execute(
                    update(PostSnapshot)
                    .where(PostSnapshot.analysis_status == "analysis_paused")
                    .values(analysis_status="analysis_queued", sentiment_updated_at=utc_now())
                )
            return self.config_dict(config)

    def test_connection(self) -> dict[str, Any]:
        with self.factory() as db:
            config = self.ensure_default(db)
            profile = model_profile(config.model_code)
            if profile["provider"] == "hosted" and (
                not config.base_url or not config.encrypted_api_key
            ):
                raise DomainError(
                    "SENTIMENT_CONFIG_INCOMPLETE", "请先保存 API 地址和 API Key。", status_code=409
                )
            config_id = config.id
            revision = config.revision
            subject = {
                "brand": config.brand,
                "products": list(config.products),
                "supplement": config.supplement or "",
            }
            if profile["provider"] == "hosted":
                base_url = validate_public_https_base_url(config.base_url, resolve=True)
                api_key = self.secrets.decrypt_secret(config.encrypted_api_key)
                body = build_request(PostSnapshot(), config, tiny_test=True)
        try:
            if profile["provider"] == "local":
                if not self.local_analyzer:
                    raise ValueError("本地文字模型运行器未初始化。")
                duration_ms = self.local_analyzer.validate(subject)
                request_id = None
            else:
                text, _usage, request_id, duration_ms = self.client.request(base_url, api_key, body)
                parsed, _strict, _recovered = parse_feedback_text(text)
                if parsed.get("ok") is not True:
                    raise ValueError("测试响应缺少 ok=true")
        except (httpx.HTTPError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            with self.factory.begin() as db:
                config = db.get(SentimentConfig, config_id)
                if config and config.revision == revision:
                    config.validation_status = "invalid"
                    config.validation_error = str(exc)[:1000]
                    config.validated_at = utc_now()
            raise DomainError("SENTIMENT_CONNECTION_FAILED", f"连接测试失败：{exc}") from exc
        with self.factory.begin() as db:
            config = db.get(SentimentConfig, config_id)
            if not config or config.revision != revision:
                raise DomainError(
                    "SENTIMENT_CONFIG_CHANGED", "测试期间配置已变化，请重新测试。", status_code=409
                )
            config.validation_status = "valid"
            config.validation_error = None
            config.validated_at = utc_now()
        return {"status": "valid", "request_id": request_id, "duration_ms": duration_ms}

    def enqueue_for_post(self, db: Session, post: PostSnapshot, platform_code: str) -> None:
        """新帖子入库时决定禁用、继承、精确复用或排队。"""

        config = self.ensure_default(db)
        input_hash = sentiment_input_hash(post, config.model_code)
        if config.enabled and config.validation_status == "valid":
            status = "analysis_queued"
        elif config.validation_status == "invalid":
            # 运行期间配置失效后，采集仍可能继续入库；这些任务应等待配置恢复，
            # 不能混入用户主动关闭分析时产生的永久禁用任务。
            status = "analysis_paused"
        else:
            status = "analysis_disabled"
        analysis = SentimentAnalysis(
            post_id=post.id,
            platform_code=platform_code,
            platform_post_id=post.platform_post_id,
            input_hash=input_hash,
            status=status,
            config_revision=config.revision,
            subject_version=config.subject_version,
            subject_snapshot={
                "brand": config.brand,
                "products": list(config.products),
                "supplement": config.supplement or "",
            },
            model_code=config.model_code,
            prompt_version=analysis_version(config.model_code),
        )
        if status in {"analysis_disabled", "analysis_paused"}:
            if status == "analysis_paused":
                analysis.error_code = "MODEL_CONFIG_ERROR"
                analysis.error_message = "模型运行配置失效，等待重新测试。"
            post.analysis_status = status
            post.sentiment_updated_at = utc_now()
            db.add(analysis)
            db.flush()
            return
        # 内容未变化时，继承同一平台帖子身份的最后一条仍有效人工结论。
        latest_revision = db.scalar(
            select(ManualSentimentRevision)
            .join(PostSnapshot, PostSnapshot.id == ManualSentimentRevision.post_id)
            .join(SentimentAnalysis, SentimentAnalysis.post_id == PostSnapshot.id)
            .where(
                SentimentAnalysis.platform_code == platform_code,
                PostSnapshot.platform_post_id == post.platform_post_id,
                SentimentAnalysis.input_hash == input_hash,
                PostSnapshot.id != post.id,
            )
            .order_by(ManualSentimentRevision.created_at.desc())
            .limit(1)
        )
        previous = (
            latest_revision if latest_revision and latest_revision.action == "set_result" else None
        )
        if previous:
            analysis.status = "analysis_completed"
            analysis.finished_at = utc_now()
            post.analysis_status = analysis.status
            post.sentiment_result = previous.result
            post.sentiment_source = "inherited_manual"
            inherited = ManualSentimentRevision(
                post_id=post.id,
                action="set_result",
                result=previous.result,
                primary_category=previous.primary_category,
                secondary_categories=previous.secondary_categories,
                note=previous.note,
                inherited_from_revision_id=previous.id,
            )
            db.add(inherited)
        else:
            reused = db.scalar(
                select(SentimentAnalysis)
                .where(
                    SentimentAnalysis.platform_code == platform_code,
                    SentimentAnalysis.platform_post_id == post.platform_post_id,
                    SentimentAnalysis.input_hash == input_hash,
                    SentimentAnalysis.subject_version == config.subject_version,
                    SentimentAnalysis.prompt_version == analysis_version(config.model_code),
                    SentimentAnalysis.model_code == config.model_code,
                    SentimentAnalysis.status == "analysis_completed",
                    SentimentAnalysis.result.is_not(None),
                )
                .order_by(SentimentAnalysis.finished_at.desc())
            )
            if reused:
                analysis.status = "analysis_completed"
                analysis.result = reused.result
                analysis.matched_subjects = reused.matched_subjects
                analysis.primary_category = reused.primary_category
                analysis.secondary_categories = reused.secondary_categories
                analysis.summary = reused.summary
                analysis.modalities = reused.modalities
                analysis.reused_from_analysis_id = reused.id
                analysis.finished_at = utc_now()
                post.sentiment_result = reused.result
                post.sentiment_source = "ai"
            post.analysis_status = analysis.status
        post.sentiment_updated_at = utc_now()
        db.add(analysis)
        db.flush()

    def manual_revision(
        self, run_id: str, post_id: str, value: ManualSentimentRevisionCreate
    ) -> dict[str, Any]:
        with self.factory.begin() as db:
            post = db.get(PostSnapshot, post_id)
            if not post or post.run_id not in _related_run_ids(db, run_id):
                raise DomainError("POST_NOT_FOUND", "指定帖子快照不存在。", status_code=404)
            analysis = db.scalar(
                select(SentimentAnalysis).where(SentimentAnalysis.post_id == post.id)
            )
            if post.analysis_status not in MANUAL_ALLOWED_STATUSES:
                raise DomainError(
                    "SENTIMENT_MANUAL_CONFLICT",
                    "排队、分析中或暂停状态暂不允许人工修正。",
                    status_code=409,
                )
            if value.action == "restore_ai":
                if not analysis or analysis.status != "analysis_completed" or not analysis.result:
                    raise DomainError(
                        "SENTIMENT_AI_RESULT_UNAVAILABLE",
                        "当前帖子没有可恢复的完整 AI 结论。",
                        status_code=409,
                    )
                revision = ManualSentimentRevision(
                    post_id=post.id, action="restore_ai", note=value.note
                )
                post.sentiment_result = analysis.result
                post.sentiment_source = "ai"
            else:
                self._validate_manual(value)
                revision = ManualSentimentRevision(
                    post_id=post.id,
                    action="set_result",
                    result=value.result,
                    primary_category=value.primary_category,
                    secondary_categories=list(dict.fromkeys(value.secondary_categories)),
                    note=(value.note or "").strip() or None,
                )
                post.sentiment_result = value.result
                post.sentiment_source = "manual"
            post.sentiment_updated_at = utc_now()
            db.add(revision)
            db.flush()
            return self.detail_dict(db, post)

    @staticmethod
    def _validate_manual(value: ManualSentimentRevisionCreate) -> None:
        if value.result is None:
            raise DomainError("SENTIMENT_RESULT_REQUIRED", "人工修正必须选择结论。")
        if value.result == "negative" and value.primary_category is None:
            raise DomainError("SENTIMENT_CATEGORY_REQUIRED", "负面结论必须选择主要类型。")
        if value.result != "negative" and (
            value.primary_category is not None or value.secondary_categories
        ):
            raise DomainError("SENTIMENT_CATEGORY_INVALID", "非负面或不相关结论不填写负面类型。")
        if value.primary_category in value.secondary_categories:
            raise DomainError("SENTIMENT_CATEGORY_DUPLICATED", "次要类型不得重复主要类型。")

    @staticmethod
    def detail_dict(db: Session, post: PostSnapshot) -> dict[str, Any]:
        analysis = db.scalar(select(SentimentAnalysis).where(SentimentAnalysis.post_id == post.id))
        revisions = list(
            db.scalars(
                select(ManualSentimentRevision)
                .where(ManualSentimentRevision.post_id == post.id)
                .order_by(ManualSentimentRevision.created_at.desc())
            )
        )
        active = next((item for item in revisions if item.action == "set_result"), None)
        return {
            "analysis_status": post.analysis_status,
            "result": post.sentiment_result,
            "source": post.sentiment_source,
            "summary": analysis.summary if analysis else None,
            "matched_subjects": analysis.matched_subjects if analysis else [],
            "primary_category": (
                active.primary_category
                if post.sentiment_source in {"manual", "inherited_manual"} and active
                else analysis.primary_category
                if analysis
                else None
            ),
            "secondary_categories": (
                active.secondary_categories
                if post.sentiment_source in {"manual", "inherited_manual"} and active
                else analysis.secondary_categories
                if analysis
                else []
            ),
            "modalities": analysis.modalities if analysis else None,
            "model_code": analysis.model_code if analysis else None,
            "provider_request_id": analysis.provider_request_id if analysis else None,
            "duration_ms": analysis.duration_ms if analysis else None,
            "error_code": analysis.error_code if analysis else None,
            "error_message": analysis.error_message if analysis else None,
            "updated_at": post.sentiment_updated_at,
            "can_manual_correct": post.analysis_status in MANUAL_ALLOWED_STATUSES,
            "can_restore_ai": bool(
                analysis and analysis.status == "analysis_completed" and analysis.result
            ),
            "manual_history": [
                {
                    "id": item.id,
                    "action": item.action,
                    "result": item.result,
                    "primary_category": item.primary_category,
                    "secondary_categories": item.secondary_categories,
                    "note": item.note,
                    "inherited": bool(item.inherited_from_revision_id),
                    "created_at": item.created_at,
                }
                for item in revisions
            ],
        }


class SentimentWorker:
    """与提取 Worker 分离、固定小并发的持久任务执行器。"""

    def __init__(
        self,
        service: SentimentService,
        poll_seconds: float = 1.0,
        concurrency: int = SENTIMENT_WORKER_CONCURRENCY,
        media_resolver: Callable[[str, str], dict[str, Any]] | None = None,
    ):
        self.service = service
        self.poll_seconds = poll_seconds
        self.concurrency = max(1, min(concurrency, SENTIMENT_WORKER_CONCURRENCY))
        self.media_resolver = media_resolver
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.claim_lock = threading.Lock()
        self.rate_limit_lock = threading.Lock()
        self.rate_limit_until = 0.0

    def start(self) -> None:
        if any(thread.is_alive() for thread in self.threads):
            return
        self.recover_interrupted()
        self.stop_event.clear()
        self.threads = [
            threading.Thread(
                target=self._loop,
                name=f"threadsnap-sentiment-{index + 1}",
                daemon=True,
            )
            for index in range(self.concurrency)
        ]
        for thread in self.threads:
            thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=10)

    def recover_interrupted(self) -> None:
        with self.service.factory.begin() as db:
            db.execute(
                update(SentimentAnalysis)
                .where(SentimentAnalysis.status == "analysis_running")
                .values(status="analysis_queued", started_at=None)
            )
            db.execute(
                update(PostSnapshot)
                .where(PostSnapshot.analysis_status == "analysis_running")
                .values(analysis_status="analysis_queued")
            )

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                progressed = self.process_once()
            except Exception:
                progressed = False
            if not progressed:
                self.stop_event.wait(self.poll_seconds)

    def _wait_for_rate_limit(self) -> bool:
        """让两个消费者共享提供方 429 冷却窗口。"""

        while not self.stop_event.is_set():
            with self.rate_limit_lock:
                delay = max(0.0, self.rate_limit_until - monotonic())
            if delay <= 0:
                return True
            if self.stop_event.wait(delay):
                return False
        return False

    def _extend_rate_limit(self, delay: float) -> None:
        with self.rate_limit_lock:
            self.rate_limit_until = max(self.rate_limit_until, monotonic() + delay)

    def process_once(self) -> bool:
        # SQLite 不支持 SKIP LOCKED；只串行化很短的领取事务，模型请求仍可并发执行。
        with self.claim_lock:
            with self.service.factory.begin() as db:
                config = self.service.ensure_default(db)
                if not config.enabled or config.validation_status != "valid":
                    return False
                analysis = db.scalar(
                    select(SentimentAnalysis)
                    .where(SentimentAnalysis.status == "analysis_queued")
                    .order_by(SentimentAnalysis.created_at)
                    .limit(1)
                )
                if not analysis:
                    return False
                post = db.get(PostSnapshot, analysis.post_id)
                if not post:
                    db.delete(analysis)
                    return True
                analysis.status = "analysis_running"
                # 尚未成功请求的旧排队任务在领取时绑定当前提示词实现，避免记录版本失真。
                analysis.prompt_version = analysis_version(analysis.model_code)
                analysis.started_at = utc_now()
                post.analysis_status = analysis.status
                analysis_id = analysis.id
                post_id = post.id
                attempt_failures = list(analysis.attempt_failures or [])
        if model_profile(analysis.model_code)["provider"] == "local":
            return self._process_local(
                analysis_id,
                post_id,
                post,
                analysis.subject_snapshot,
                attempt_failures,
            )
        try:
            base_url = validate_public_https_base_url(config.base_url, resolve=True)
            api_key = self.service.secrets.decrypt_secret(config.encrypted_api_key or b"")
        except Exception as exc:
            self._record_failure(
                analysis_id,
                post_id,
                ModelRequestError(f"模型运行配置不可用：{exc}", config_error=True),
            )
            return True
        try:
            if self.media_resolver and deduplicate_media_urls(post.video_urls):
                resolved = self.media_resolver(post.run_id, post.id)
                fresh_video_urls = resolved.get("video_urls")
                if not isinstance(fresh_video_urls, list) or not fresh_video_urls:
                    raise ValueError("视频播放地址刷新结果为空")
                # post 已离开领取事务；这里只替换本次请求输入，不改写历史快照。
                post.video_urls = [str(value) for value in fresh_video_urls]
            body = build_request(
                post,
                config,
                subject_snapshot=analysis.subject_snapshot,
                model_code=analysis.model_code,
            )
        except Exception as exc:
            self._record_failure(
                analysis_id,
                post_id,
                ValueError(f"模型输入准备失败：{exc}"),
            )
            return True
        raw = ""
        retry_count = 0
        transport_retries = 0
        incomplete_retries = 0
        while True:
            if not self._wait_for_rate_limit():
                return False
            try:
                raw, usage, request_id, duration_ms = self.service.client.request(
                    base_url, api_key, body
                )
            except (httpx.HTTPError, RuntimeError) as exc:
                if isinstance(exc, ModelRequestError) and exc.response_incomplete:
                    raw = exc.raw_response
                    if incomplete_retries < 1:
                        attempt_failures.append(
                            _failed_attempt(
                                attempt=retry_count + 1,
                                exc=exc,
                                raw_response=raw,
                                request_id=exc.request_id,
                                usage=exc.usage,
                                duration_ms=exc.duration_ms,
                            )
                        )
                        incomplete_retries += 1
                        retry_count += 1
                        if self.stop_event.wait(1.0):
                            return False
                        continue
                    self._record_failure(
                        analysis_id,
                        post_id,
                        exc,
                        raw_response=raw,
                        retry_count=retry_count,
                        attempt_failures=attempt_failures,
                    )
                    return True
                retryable = isinstance(exc, httpx.HTTPError) or (
                    isinstance(exc, ModelRequestError) and exc.retryable
                )
                rate_limited = isinstance(exc, ModelRequestError) and exc.status_code == 429
                retry_limit = 1 if rate_limited else 3
                if retryable and transport_retries < retry_limit:
                    delay = (
                        exc.retry_after_seconds or 30.0
                        if rate_limited
                        else float(2**transport_retries)
                    )
                    if rate_limited:
                        self._extend_rate_limit(delay)
                    elif self.stop_event.wait(delay):
                        return False
                    transport_retries += 1
                    retry_count += 1
                    continue
                self._record_failure(
                    analysis_id,
                    post_id,
                    exc,
                    raw_response=raw,
                    retry_count=retry_count,
                    attempt_failures=attempt_failures,
                )
                return True
            try:
                payload, _strict, recovered = parse_feedback_text(raw)
                payload, normalized = normalize_feedback_payload(payload, post)
                feedback = SentimentFeedback.model_validate(payload)
                validate_modality_identity(feedback, post)
            except (ValueError, json.JSONDecodeError, ValidationError) as exc:
                if _is_truncated_json_error(exc, raw) and incomplete_retries < 1:
                    attempt_failures.append(
                        _failed_attempt(
                            attempt=retry_count + 1,
                            exc=exc,
                            raw_response=raw,
                            request_id=request_id,
                            usage=usage,
                            duration_ms=duration_ms,
                        )
                    )
                    incomplete_retries += 1
                    retry_count += 1
                    if self.stop_event.wait(1.0):
                        return False
                    continue
                self._record_failure(
                    analysis_id,
                    post_id,
                    exc,
                    raw_response=raw,
                    retry_count=retry_count,
                    attempt_failures=attempt_failures,
                    stream_incomplete=_is_truncated_json_error(exc, raw),
                )
                return True
            status = self._coverage_status(feedback)
            result = "unrelated" if not feedback.subject_relevance else feedback.sentiment
            break
        self._store_success(
            analysis_id=analysis_id,
            post_id=post_id,
            feedback=feedback,
            status=status,
            result=result,
            raw=raw,
            attempt_failures=attempt_failures,
            locally_recovered=recovered or normalized,
            request_id=request_id,
            usage=usage,
            retry_count=retry_count,
            duration_ms=duration_ms,
        )
        return True

    def _process_local(
        self,
        analysis_id: str,
        post_id: str,
        post: PostSnapshot,
        subject_snapshot: dict[str, Any],
        attempt_failures: list[dict[str, Any]],
    ) -> bool:
        """执行本地文字模型；媒体只计数，不解析、不刷新也不参与推理。"""

        analyzer = self.service.local_analyzer
        if not analyzer:
            self._record_failure(
                analysis_id,
                post_id,
                ModelRequestError("本地文字模型运行器未初始化。", config_error=True),
            )
            return True
        try:
            payload, raw, duration_ms = analyzer.analyze(
                title=post.title or "",
                content=post.content or "",
                image_count=len(deduplicate_media_urls(post.image_urls)),
                video_count=len(deduplicate_media_urls(post.video_urls)),
                subject=subject_snapshot,
            )
        except Exception as exc:
            self._record_failure(
                analysis_id,
                post_id,
                ModelRequestError(f"本地文字模型执行失败：{exc}", config_error=True),
            )
            return True
        try:
            feedback = SentimentFeedback.model_validate(payload)
            validate_modality_identity(feedback, post)
        except (ValidationError, ValueError) as exc:
            self._record_failure(
                analysis_id,
                post_id,
                ValueError(f"本地文字模型结果校验失败：{exc}"),
            )
            return True
        status = self._coverage_status(feedback)
        result = "unrelated" if not feedback.subject_relevance else feedback.sentiment
        self._store_success(
            analysis_id=analysis_id,
            post_id=post_id,
            feedback=feedback,
            status=status,
            result=result,
            raw=raw,
            attempt_failures=attempt_failures,
            locally_recovered=False,
            request_id=None,
            usage={"provider": "local", "billable_tokens": 0},
            retry_count=0,
            duration_ms=duration_ms,
        )
        return True

    def _store_success(
        self,
        *,
        analysis_id: str,
        post_id: str,
        feedback: SentimentFeedback,
        status: str,
        result: str | None,
        raw: str,
        attempt_failures: list[dict[str, Any]],
        locally_recovered: bool,
        request_id: str | None,
        usage: dict[str, Any] | None,
        retry_count: int,
        duration_ms: int,
    ) -> None:
        """统一持久化在线或本地模型的完整结果。"""

        with self.service.factory.begin() as db:
            analysis = db.get(SentimentAnalysis, analysis_id)
            post = db.get(PostSnapshot, post_id)
            if not analysis or not post:
                return
            analysis.status = status
            analysis.result = result
            analysis.matched_subjects = feedback.matched_subjects
            analysis.primary_category = feedback.primary_category
            analysis.secondary_categories = feedback.secondary_categories
            analysis.summary = feedback.summary
            analysis.modalities = feedback.modalities.model_dump()
            analysis.raw_response = raw
            analysis.attempt_failures = attempt_failures
            analysis.locally_recovered = locally_recovered
            analysis.provider_request_id = request_id
            analysis.usage = usage
            analysis.retry_count = retry_count
            analysis.duration_ms = duration_ms
            analysis.finished_at = utc_now()
            post.analysis_status = status
            if status == "analysis_completed":
                post.sentiment_result = result
                post.sentiment_source = "ai"
            post.sentiment_updated_at = utc_now()
        if self.service.event_publisher:
            self.service.event_publisher("sentiment.changed", post_id, status=status)

    @staticmethod
    def _coverage_status(feedback: SentimentFeedback) -> str:
        modalities = feedback.modalities
        complete = modalities.text.status in {"absent", "processed"}
        complete = complete and all(
            item.status == "not_requested" or item.expected_count == item.processed_count
            for item in (modalities.image, modalities.video_visual, modalities.video_audio)
        )
        complete = complete and modalities.image.status in {
            "absent",
            "processed",
            "not_requested",
        }
        complete = complete and modalities.video_visual.status in {
            "absent",
            "processed",
            "not_requested",
        }
        complete = complete and modalities.video_audio.status in {
            "absent",
            "processed",
            "speech",
            "silent",
            "no_speech",
            "not_requested",
        }
        return "analysis_completed" if complete else "analysis_partial"

    def _record_failure(
        self,
        analysis_id: str,
        post_id: str,
        exc: Exception,
        *,
        raw_response: str = "",
        retry_count: int = 0,
        attempt_failures: list[dict[str, Any]] | None = None,
        stream_incomplete: bool = False,
    ) -> None:
        config_error = isinstance(exc, httpx.HTTPError) or (
            isinstance(exc, ModelRequestError) and exc.config_error
        )
        input_too_large = isinstance(exc, ModelRequestError) and exc.input_too_large
        status = (
            "analysis_paused"
            if config_error
            else "analysis_partial"
            if input_too_large
            else "analysis_failed"
        )
        with self.service.factory.begin() as db:
            analysis = db.get(SentimentAnalysis, analysis_id)
            post = db.get(PostSnapshot, post_id)
            if analysis:
                analysis.status = status
                response_incomplete = stream_incomplete or (
                    isinstance(exc, ModelRequestError) and exc.response_incomplete
                )
                if config_error:
                    analysis.error_code = "MODEL_CONFIG_ERROR"
                elif response_incomplete:
                    analysis.error_code = "MODEL_STREAM_INCOMPLETE"
                else:
                    analysis.error_code = "MODEL_RESPONSE_ERROR"
                analysis.error_message = f"{type(exc).__name__}: {exc}"[:2000]
                analysis.raw_response = (
                    raw_response
                    or (exc.raw_response if isinstance(exc, ModelRequestError) else "")
                    or None
                )
                analysis.attempt_failures = list(attempt_failures or [])
                if isinstance(exc, ModelRequestError):
                    analysis.provider_request_id = exc.request_id
                    analysis.usage = exc.usage
                    analysis.duration_ms = exc.duration_ms
                analysis.retry_count = retry_count
                analysis.finished_at = utc_now()
            if post:
                post.analysis_status = status
                post.sentiment_updated_at = utc_now()
            if config_error:
                config = db.get(SentimentConfig, 1)
                if config:
                    config.enabled = False
                    config.validation_status = "invalid"
                    config.validation_error = str(exc)[:1000]
                    config.validated_at = utc_now()
                db.execute(
                    update(SentimentAnalysis)
                    .where(SentimentAnalysis.status == "analysis_queued")
                    .values(
                        status="analysis_paused",
                        error_code="MODEL_CONFIG_ERROR",
                        error_message="模型连接配置失效，等待重新测试。",
                    )
                )
                db.execute(
                    update(PostSnapshot)
                    .where(PostSnapshot.analysis_status == "analysis_queued")
                    .values(analysis_status="analysis_paused", sentiment_updated_at=utc_now())
                )


def sentiment_summary(db: Session, post: PostSnapshot) -> dict[str, Any]:
    """供帖子列表和详情复用的有效舆情视图。"""

    return SentimentService.detail_dict(db, post)


def _related_run_ids(db: Session, run_id: str) -> list[str]:
    """在本模块内解析补提关系，避免与 RunService 形成循环依赖。"""

    current = db.get(ExtractionRun, run_id)
    if not current:
        return []
    while current.related_run_id:
        parent = db.get(ExtractionRun, current.related_run_id)
        if not parent:
            break
        current = parent
    result = [current.id]
    cursor = 0
    while cursor < len(result):
        children = db.scalars(
            select(ExtractionRun.id).where(ExtractionRun.related_run_id == result[cursor])
        )
        result.extend(item for item in children if item not in result)
        cursor += 1
    return result
