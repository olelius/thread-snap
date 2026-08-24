"""在线多模态舆情配置、持久任务、模型客户端与人工修订。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import socket
import threading
from copy import deepcopy
from difflib import SequenceMatcher
from ipaddress import ip_address, ip_network
from time import monotonic
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

import httpx
from json_repair import repair_json
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
DEEPSEEK_MODEL_CODE = "deepseek-v4-flash"
MODEL_CODES = (HOSTED_MODEL_CODE, DEEPSEEK_MODEL_CODE, LOCAL_MODEL_CODE)
MODEL_PROFILES = {
    HOSTED_MODEL_CODE: {
        "name": "千问 Omni Plus（云端多模态）",
        "provider": "hosted",
        "service": "aliyun",
        "input_mode": "multimodal",
        "output_mode": "json_object",
    },
    DEEPSEEK_MODEL_CODE: {
        "name": "DeepSeek V4 Flash（云端文字）",
        "provider": "hosted",
        "service": "deepseek",
        "input_mode": "text_only",
        "output_mode": "strict_tool",
    },
    LOCAL_MODEL_CODE: {
        "name": LOCAL_MODEL_NAME,
        "provider": "local",
        "service": "local",
        "input_mode": "text_only",
        "output_mode": "local",
    },
}
HOSTED_PROMPT_VERSION = "v4-clean-correction"
DEEPSEEK_PROMPT_VERSION = "deepseek-text-v5-strict-tool"
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
SENTIMENT_CLOUD_CONCURRENCY_MIN = 1
SENTIMENT_CLOUD_CONCURRENCY_MAX = 64
SENTIMENT_CLOUD_CONCURRENCY_DEFAULT = 8
DEEPSEEK_READ_TIMEOUT_SECONDS = 30.0
DEEPSEEK_TOTAL_TIMEOUT_SECONDS = 60.0
SENTIMENT_WATCHDOG_INTERVAL_SECONDS = 5.0

logger = logging.getLogger(__name__)


def model_profile(model_code: str) -> dict[str, str]:
    try:
        return MODEL_PROFILES[model_code]
    except KeyError as exc:
        raise ValueError(f"不支持的舆情模型：{model_code}") from exc


def analysis_version(model_code: str) -> str:
    profile = model_profile(model_code)
    if profile["provider"] == "local":
        return LOCAL_PIPELINE_VERSION
    if profile["service"] == "deepseek":
        return DEEPSEEK_PROMPT_VERSION
    return HOSTED_PROMPT_VERSION


def model_connection(
    config: SentimentConfig, model_code: str
) -> tuple[str, bytes | None]:
    """读取指定受控模型的独立云端连接，本地模型返回空连接。"""

    service = model_profile(model_code)["service"]
    if service == "aliyun":
        return config.base_url, config.encrypted_api_key
    if service == "deepseek":
        return config.deepseek_base_url, config.deepseek_encrypted_api_key
    return "", None


def set_model_connection(
    config: SentimentConfig,
    model_code: str,
    *,
    base_url: str,
    encrypted_api_key: bytes | None,
) -> None:
    """只更新当前云端提供方的连接，不覆盖其他提供方凭证。"""

    service = model_profile(model_code)["service"]
    if service == "aliyun":
        config.base_url = base_url
        config.encrypted_api_key = encrypted_api_key
    elif service == "deepseek":
        config.deepseek_base_url = base_url
        config.deepseek_encrypted_api_key = encrypted_api_key


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


class DeepSeekTextFeedback(BaseModel):
    """DeepSeek 严格工具只返回需要模型判断的最小文字字段。"""

    model_config = ConfigDict(extra="forbid")

    subject_relevance: bool
    matched_subjects: list[str]
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
    ]
    evidence: list[str]
    summary: str = Field(min_length=1)


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


def complete_text_only_feedback_payload(
    payload: dict[str, Any], post: PostSnapshot
) -> dict[str, Any]:
    """补齐旧版文字合同；仅供历史响应恢复与兼容测试使用。"""

    expected_root = set(SentimentFeedback.model_fields)
    if set(payload) != expected_root:
        missing = sorted(expected_root - set(payload))
        extra = sorted(set(payload) - expected_root)
        raise ValueError(f"根字段不符合合同：missing={missing}, extra={extra}")
    modalities = payload.get("modalities")
    if not isinstance(modalities, dict) or set(modalities) != {"text"}:
        observed = sorted(modalities) if isinstance(modalities, dict) else type(modalities).__name__
        raise ValueError(f"文字模型 modalities 只允许 text，实际为：{observed}")

    completed = deepcopy(payload)
    completed_modalities = completed["modalities"]
    counts = {
        "image": len(deduplicate_media_urls(post.image_urls)),
        "video_visual": len(deduplicate_media_urls(post.video_urls)),
        "video_audio": len(deduplicate_media_urls(post.video_urls)),
    }
    for name, count in counts.items():
        completed_modalities[name] = {
            "status": "not_requested" if count else "absent",
            "expected_count": count,
            "processed_count": 0,
            "items": [],
        }
    return completed


def complete_deepseek_tool_payload(
    payload: dict[str, Any], post: PostSnapshot
) -> dict[str, Any]:
    """把 DeepSeek 最小严格工具参数补成统一舆情合同。"""

    native = DeepSeekTextFeedback.model_validate(payload)
    has_text = bool((post.title or "").strip() or (post.content or "").strip())
    completed: dict[str, Any] = {
        "subject_relevance": native.subject_relevance,
        "matched_subjects": native.matched_subjects,
        "sentiment": native.sentiment,
        "primary_category": native.primary_category,
        "secondary_categories": native.secondary_categories,
        "modalities": {
            "text": {
                "status": "processed" if has_text else "absent",
                "evidence": native.evidence,
            }
        },
        "summary": native.summary,
    }
    counts = {
        "image": len(deduplicate_media_urls(post.image_urls)),
        "video_visual": len(deduplicate_media_urls(post.video_urls)),
        "video_audio": len(deduplicate_media_urls(post.video_urls)),
    }
    for name, count in counts.items():
        completed["modalities"][name] = {
            "status": "not_requested" if count else "absent",
            "expected_count": count,
            "processed_count": 0,
            "items": [],
        }
    return completed


def deepseek_strict_tool(model_test: bool = False) -> dict[str, Any]:
    """返回 DeepSeek Beta Strict Tool 定义，不影响其他模型输出协议。"""

    if model_test:
        name = "submit_connection_test"
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean", "enum": [True]}},
            "required": ["ok"],
            "additionalProperties": False,
        }
    else:
        name = "submit_sentiment_feedback"
        category = {"type": "string", "enum": list(CATEGORIES)}
        schema = {
            "type": "object",
            "properties": {
                "subject_relevance": {"type": "boolean"},
                "matched_subjects": {"type": "array", "items": {"type": "string"}},
                "sentiment": {
                    "anyOf": [
                        {"type": "string", "enum": ["negative", "non_negative"]},
                        {"type": "null"},
                    ]
                },
                "primary_category": {"anyOf": [category, {"type": "null"}]},
                "secondary_categories": {"type": "array", "items": category},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
            },
            "required": [
                "subject_relevance",
                "matched_subjects",
                "sentiment",
                "primary_category",
                "secondary_categories",
                "evidence",
                "summary",
            ],
            "additionalProperties": False,
        }
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "提交结构化舆情结果" if not model_test else "提交连接测试结果",
            "strict": True,
            "parameters": schema,
        },
    }


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


def build_text_only_prompt(
    post: PostSnapshot,
    config: SentimentConfig,
    subject_snapshot: dict[str, Any] | None = None,
) -> str:
    """构造云端文字模型提示词，不包含媒体 URL、哈希或媒体内容。"""

    subject = subject_snapshot or {
        "brand": config.brand,
        "products": config.products,
        "supplement": config.supplement or "",
    }
    return f"""只根据标题和正文进行舆情分析，不联网搜索；图片、视频画面、视频音频均未提供，不得据此形成观点或依据。
判定对象配置：{json.dumps(subject, ensure_ascii=False)}。
请结合文字语境自行识别品牌、产品、服务和常见别名；内容与判定对象无关时 subject_relevance=false。
对判定对象不利为 negative，中性或正面为 non_negative；负面时选择函数 Schema 中最符合语义的主要类型。

标题：{post.title or ""}
正文：{post.content or ""}

不相关时 sentiment 与 primary_category 为 null；负面必须有 primary_category；次要类型不得重复主要类型。
evidence 只保留一至三条简短中文事实，不复述整篇正文；summary 用不超过一百二十个汉字概括内容、相关性和情感结论。
必须调用 submit_sentiment_feedback 提交结果，不在普通消息正文中解释。"""


def build_request(
    post: PostSnapshot,
    config: SentimentConfig,
    *,
    tiny_test: bool = False,
    subject_snapshot: dict[str, Any] | None = None,
    model_code: str | None = None,
) -> dict[str, Any]:
    selected_model = model_code or config.model_code
    profile = model_profile(selected_model)
    if tiny_test:
        if profile["output_mode"] == "strict_tool":
            content: str | list[dict[str, Any]] = (
                "调用 submit_connection_test，并提交 ok=true。"
            )
        else:
            content = [{"type": "text", "text": '只返回 JSON 对象：{"ok":true}。'}]
    elif profile["output_mode"] == "strict_tool":
        content = build_text_only_prompt(post, config, subject_snapshot)
    else:
        image_urls = deduplicate_media_urls(post.image_urls)
        video_urls = deduplicate_media_urls(post.video_urls)
        content = [
            *({"type": "image_url", "image_url": {"url": value}} for value in image_urls),
            *({"type": "video_url", "video_url": {"url": value}} for value in video_urls),
            {"type": "text", "text": build_prompt(post, config, subject_snapshot)},
        ]
    body: dict[str, Any] = {
        "model": selected_model,
        "messages": [{"role": "user", "content": content}],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if profile["output_mode"] == "strict_tool":
        tool = deepseek_strict_tool(model_test=tiny_test)
        body.update(
            {
                "tools": [tool],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": tool["function"]["name"]},
                },
                "thinking": {"type": "disabled"},
                "temperature": 0.1,
                "max_tokens": 4096,
            }
        )
    else:
        body["response_format"] = {"type": "json_object"}
        body["modalities"] = ["text"]
    return body


def build_output_correction_request(
    body: dict[str, Any],
    raw_response: str,
    exc: Exception,
    *,
    input_mode: str,
    contract: str | None = None,
) -> dict[str, Any]:
    """用干净上下文反馈具体错误；只允许一次重新生成。"""

    if isinstance(exc, ValidationError):
        detail = json.dumps(
            exc.errors(include_url=False, include_input=False),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    else:
        detail = f"{type(exc).__name__}: {exc}"
    strict_tool = bool(body.get("tools"))
    if contract is None and not strict_tool:
        modality_contract = (
            "modalities 只能包含 text；text 只能包含 status 和 evidence"
            if input_mode == "text_only"
            else "modalities 必须且只能包含 text、image、video_visual、video_audio"
        )
        contract = (
            "根对象必须且只能包含 subject_relevance、matched_subjects、sentiment、"
            "primary_category、secondary_categories、modalities、summary；"
            f"{modality_contract}。"
        )
    # 不把错误候选作为 assistant 消息再次喂给模型。真实故障已经证明低温度下
    # 这种对话历史会逐字复现同一坏 JSON；这里只保留候选哈希供审计关联。
    response_hash = hashlib.sha256(raw_response.encode("utf-8")).hexdigest()
    correction = deepcopy(body)
    if strict_tool:
        correction_text = (
            "上一次函数参数未通过本地业务关系校验，请根据最初输入重新调用同一函数。\n"
            f"错误候选 SHA-256：{response_hash}\n"
            f"具体错误：{detail[:2000]}\n"
            "不要解释错误；只提交满足函数 JSON Schema 和业务关系的新参数。"
        )
    else:
        correction_text = (
            "上一次响应未通过严格 JSON Schema 校验，请从最初输入重新生成。\n"
            f"错误候选 SHA-256：{response_hash}\n"
            f"具体错误：{detail[:4000]}\n"
            "不要复述或续写错误候选，不要解释错误，不要使用 Markdown，不要添加任何额外字段。\n"
            f"{contract}\n"
            "所有字段、层级、类型、枚举、数组和媒体身份必须严格满足最初给出的合同。"
            "只返回一个完整、可直接解析的标准 JSON 对象。"
        )
    correction["messages"] = [
        *list(body.get("messages") or []),
        {
            "role": "user",
            "content": correction_text,
        },
    ]
    return correction


def repair_missing_modalities_closure(raw_response: str) -> dict[str, Any]:
    """只修复一个可证明的 ``modalities`` 结束括号遗漏。

    提供方曾正常结束流却返回 ``...\"text\": {...},\"summary\":...}``，使
    ``summary`` 落入 ``modalities`` 且根对象未闭合。本函数只构造一个候选：在
    根级 ``summary`` 前补一个右花括号；候选必须立即成为字段集合精确匹配的
    JSON 对象，后续仍需通过完整 Pydantic 与业务关系校验。
    """

    matches = list(re.finditer(r',\s*"summary"\s*:', raw_response))
    if len(matches) != 1:
        raise ValueError("结构修复只接受一个 summary 字段候选")
    marker = matches[0]
    candidate = raw_response[: marker.start()] + "}" + raw_response[marker.start() :]
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("结构修复结果不是 JSON 对象")
    expected_root = set(SentimentFeedback.model_fields)
    if set(payload) != expected_root:
        raise ValueError("结构修复后的根字段不符合舆情合同")
    modalities = payload.get("modalities")
    if not isinstance(modalities, dict) or "summary" in modalities:
        raise ValueError("结构修复后 summary 仍未回到根对象")
    return payload


def _load_json_object_without_duplicates(value: str) -> dict[str, Any]:
    """解析 JSON 对象并拒绝重复字段。"""

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"JSON 修复候选包含重复字段：{key}")
            result[key] = item
        return result

    payload = json.loads(value, object_pairs_hook=reject_duplicate_keys)
    if not isinstance(payload, dict):
        raise ValueError("JSON 修复候选根节点不是对象")
    return payload


def repair_deepseek_tool_json(raw_response: str) -> dict[str, Any]:
    """生成一个只改变 JSON 结构字符的通用 DeepSeek 工具参数候选。"""

    repaired = repair_json(
        raw_response,
        ensure_ascii=False,
        skip_json_loads=True,
    )
    if not isinstance(repaired, str) or not repaired:
        raise ValueError("DeepSeek 工具参数未形成 JSON 修复候选")
    allowed_changes = frozenset("{}[],:\\\"' \t\r\n")
    matcher = SequenceMatcher(a=raw_response, b=repaired, autojunk=False)
    changed = False
    for operation, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        changed = True
        old_fragment = raw_response[old_start:old_end]
        new_fragment = repaired[new_start:new_end]
        if any(char not in allowed_changes for char in old_fragment + new_fragment):
            raise ValueError("JSON 修复候选改变了模型语义字符")
    if not changed:
        raise ValueError("DeepSeek 工具参数没有可证明的结构变化")

    return _load_json_object_without_duplicates(repaired)


def recover_deepseek_tool_payload(
    raw_response: str,
    post: PostSnapshot,
    error_position: int,
) -> dict[str, Any]:
    """从通用修复器与错误点单结构编辑中选出唯一完整合同候选。"""

    serialized_candidates: set[str] = set()
    try:
        repaired = repair_deepseek_tool_json(raw_response)
    except (ValueError, json.JSONDecodeError):
        pass
    else:
        serialized_candidates.add(
            json.dumps(repaired, ensure_ascii=False, separators=(",", ":"))
        )

    structural = "{}[],:\\\"'"
    positions = {
        max(0, min(len(raw_response), value))
        for value in (
            error_position - 2,
            error_position - 1,
            error_position,
            error_position + 1,
            error_position + 2,
            len(raw_response),
        )
    }
    edit_candidates: set[str] = set()
    for position in positions:
        for char in structural:
            edit_candidates.add(raw_response[:position] + char + raw_response[position:])
        if position < len(raw_response) and raw_response[position] in structural:
            edit_candidates.add(raw_response[:position] + raw_response[position + 1 :])
            for char in structural:
                edit_candidates.add(
                    raw_response[:position] + char + raw_response[position + 1 :]
                )
    for candidate in edit_candidates:
        try:
            payload = _load_json_object_without_duplicates(candidate)
        except (ValueError, json.JSONDecodeError):
            continue
        serialized_candidates.add(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )

    valid_candidates: dict[str, dict[str, Any]] = {}
    for serialized in serialized_candidates:
        try:
            native = _load_json_object_without_duplicates(serialized)
            completed = complete_deepseek_tool_payload(native, post)
            feedback = SentimentFeedback.model_validate(completed)
            validate_modality_identity(feedback, post)
        except (ValueError, json.JSONDecodeError, ValidationError):
            continue
        canonical = json.dumps(
            completed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        valid_candidates[canonical] = completed
    if len(valid_candidates) != 1:
        raise ValueError(
            f"DeepSeek 工具参数结构修复没有唯一完整合同候选：{len(valid_candidates)}"
        )
    return next(iter(valid_candidates.values()))


def strict_tool_name(body: dict[str, Any]) -> str | None:
    """识别当前请求是否为单一强制严格工具输出。"""

    tools = body.get("tools")
    if not isinstance(tools, list) or len(tools) != 1:
        return None
    function = tools[0].get("function") if isinstance(tools[0], dict) else None
    if not isinstance(function, dict) or function.get("strict") is not True:
        return None
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return None
    tool_choice = body.get("tool_choice")
    if not isinstance(tool_choice, dict) or tool_choice.get("type") != "function":
        return None
    choice_function = tool_choice.get("function")
    if not isinstance(choice_function, dict) or choice_function.get("name") != name:
        return None
    return name


def aggregate_strict_tool_arguments(
    chunks: list[dict[str, Any]], expected_name: str
) -> str:
    """聚合唯一强制工具的流式参数，不接受普通正文或多个调用。"""

    names: dict[int, list[str]] = {}
    arguments: dict[int, list[str]] = {}
    for chunk in chunks:
        choices = chunk.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            delta = choice.get("delta") if isinstance(choice, dict) else None
            calls = delta.get("tool_calls") if isinstance(delta, dict) else None
            if not isinstance(calls, list):
                continue
            for call in calls:
                if not isinstance(call, dict):
                    continue
                index = call.get("index", 0)
                if not isinstance(index, int):
                    raise ValueError("严格工具调用索引不是整数")
                function = call.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                value = function.get("arguments")
                if isinstance(name, str):
                    names.setdefault(index, []).append(name)
                if isinstance(value, str):
                    arguments.setdefault(index, []).append(value)
    indexes = set(names) | set(arguments)
    if indexes != {0}:
        raise ValueError(f"严格工具调用数量或索引异常：{sorted(indexes)}")
    observed_name = "".join(names.get(0, []))
    if observed_name != expected_name:
        raise ValueError(f"严格工具调用名称异常：{observed_name or 'missing'}")
    raw = "".join(arguments.get(0, []))
    if not raw:
        raise ValueError("严格工具调用缺少 arguments")
    return raw


class SentimentModelClient:
    """窄 OpenAI 兼容客户端：不跟随重定向，不自动重试。"""

    def __init__(self, client: httpx.Client | None = None):
        timeout = httpx.Timeout(connect=20.0, read=600.0, write=60.0, pool=20.0)
        self.client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=SENTIMENT_CLOUD_CONCURRENCY_MAX,
                max_keepalive_connections=SENTIMENT_CLOUD_CONCURRENCY_MAX,
                keepalive_expiry=30.0,
            ),
        )

    def close(self) -> None:
        """关闭共享连接池；应用停止时调用。"""

        self.client.close()

    def request(
        self, base_url: str, api_key: str, body: dict[str, Any]
    ) -> tuple[str, dict[str, Any] | None, str | None, int]:
        tool_name = strict_tool_name(body)
        normalized_base = base_url.rstrip("/")
        endpoint = (
            normalized_base + "/chat/completions"
            if tool_name and normalized_base.endswith("/beta")
            else normalized_base + "/beta/chat/completions"
            if tool_name
            else normalized_base + "/chat/completions"
        )
        request_timeout = httpx.Timeout(
            connect=20.0,
            read=DEEPSEEK_READ_TIMEOUT_SECONDS if tool_name else 600.0,
            write=60.0,
            pool=20.0,
        )
        started = monotonic()
        with self.client.stream(
            "POST",
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=request_timeout,
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
            lines = response.iter_lines()
            if tool_name:
                lines = _iter_sse_lines_with_deadline(
                    lines,
                    started=started,
                    timeout_seconds=DEEPSEEK_TOTAL_TIMEOUT_SECONDS,
                    request_id=request_id,
                )
            text, usage, chunks, done_seen = parse_sse_lines_with_completion(lines)
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
        expected_finish = "tool_calls" if tool_name else "stop"
        if finish_reasons[-1] != expected_finish:
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
        if tool_name:
            try:
                text = aggregate_strict_tool_arguments(chunks, tool_name)
            except ValueError as exc:
                raise ModelRequestError(
                    str(exc),
                    raw_response=text,
                    usage=usage,
                    request_id=request_id,
                    duration_ms=duration_ms,
                ) from exc
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


def _iter_sse_lines_with_deadline(
    lines,
    *,
    started: float,
    timeout_seconds: float,
    request_id: str | None,
):
    """在逐块读取超时之外，为 DeepSeek 流增加不可被心跳绕过的总时限。"""

    for line in lines:
        elapsed = monotonic() - started
        if elapsed > timeout_seconds:
            raise ModelRequestError(
                f"模型流式响应超过 {timeout_seconds:g} 秒总时限。",
                retryable=True,
                request_id=request_id,
                duration_ms=round(elapsed * 1000),
            )
        yield line


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
    error_code: str,
    raw_response: str,
    request_id: str | None,
    usage: dict[str, Any] | None,
    duration_ms: int | None,
) -> dict[str, Any]:
    """形成不含凭证的单次失败审计记录。"""

    return {
        "attempt": attempt,
        "error_code": error_code,
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

    def close(self) -> None:
        """释放模型客户端持有的共享连接池。"""

        close = getattr(self.client, "close", None)
        if callable(close):
            close()

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
        active_base_url, active_key = model_connection(config, config.model_code)
        model_connections = {}
        for model_code in MODEL_CODES:
            base_url, encrypted_key = model_connection(config, model_code)
            model_connections[model_code] = {
                "api_base_url": base_url,
                "api_key_configured": bool(encrypted_key),
            }
        return {
            "revision": config.revision,
            "enabled": config.enabled,
            "api_base_url": active_base_url,
            "api_key_configured": bool(active_key),
            "model_code": config.model_code,
            "available_models": list(MODEL_CODES),
            "model_connections": model_connections,
            "model_name": model_profile(config.model_code)["name"],
            "model_provider": model_profile(config.model_code)["provider"],
            "model_input_mode": model_profile(config.model_code)["input_mode"],
            "cloud_concurrency": config.cloud_concurrency,
            "cloud_concurrency_range": {
                "min": SENTIMENT_CLOUD_CONCURRENCY_MIN,
                "max": SENTIMENT_CLOUD_CONCURRENCY_MAX,
            },
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
        base_url = value.api_base_url.strip().rstrip("/") if profile["provider"] == "hosted" else ""
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
            current_base_url, current_encrypted_key = model_connection(config, value.model_code)
            encrypted_key = current_encrypted_key
            key_changed = value.api_key is not None and profile["provider"] == "hosted"
            if key_changed:
                encrypted_key = self.secrets.encrypt_secret(value.api_key.strip())
            connection_changed = (
                value.model_code != config.model_code
                or (
                    profile["provider"] == "hosted"
                    and (base_url != current_base_url or key_changed)
                )
            )
            subject_changed = (
                value.subject.brand.strip() != config.brand
                or value.subject.products != config.products
                or (value.subject.supplement or "").strip() != (config.supplement or "")
            )
            cloud_concurrency = (
                value.cloud_concurrency
                if value.cloud_concurrency is not None
                else config.cloud_concurrency
            )
            if (
                value.enabled
                and not connection_changed
                and (
                    config.validation_status != "valid"
                    or (
                        profile["provider"] == "hosted"
                        and (not encrypted_key or not base_url)
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
            if profile["provider"] == "hosted":
                set_model_connection(
                    config,
                    value.model_code,
                    base_url=base_url,
                    encrypted_api_key=encrypted_key,
                )
            config.model_code = value.model_code
            config.cloud_concurrency = cloud_concurrency
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
            configured_base_url, configured_key = model_connection(config, config.model_code)
            if profile["provider"] == "hosted" and (
                not configured_base_url or not configured_key
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
                base_url = validate_public_https_base_url(configured_base_url, resolve=True)
                api_key = self.secrets.decrypt_secret(configured_key)
                body = build_request(PostSnapshot(), config, tiny_test=True)
        try:
            if profile["provider"] == "local":
                if not self.local_analyzer:
                    raise ValueError("本地文字模型运行器未初始化。")
                duration_ms = self.local_analyzer.validate(subject)
                request_id = None
            else:
                for output_attempt in range(2):
                    text, _usage, request_id, duration_ms = self.client.request(
                        base_url, api_key, body
                    )
                    try:
                        parsed, _strict, _recovered = parse_feedback_text(text)
                        if set(parsed) != {"ok"} or parsed.get("ok") is not True:
                            raise ValueError("测试响应必须且只能包含 ok=true")
                        break
                    except (ValueError, json.JSONDecodeError) as exc:
                        if output_attempt:
                            raise
                        body = build_output_correction_request(
                            body,
                            text,
                            exc,
                            input_mode=profile["input_mode"],
                            contract="根对象必须且只能包含 ok，且 ok 的值必须为 true。",
                        )
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
    """与提取 Worker 分离、支持运行时调节云端并发的持久任务执行器。"""

    def __init__(
        self,
        service: SentimentService,
        poll_seconds: float = 1.0,
        concurrency: int | None = None,
        media_resolver: Callable[[str, str], dict[str, Any]] | None = None,
    ):
        self.service = service
        self.poll_seconds = poll_seconds
        self.cloud_concurrency = self._bounded_concurrency(
            concurrency if concurrency is not None else SENTIMENT_CLOUD_CONCURRENCY_DEFAULT
        )
        self.model_code = HOSTED_MODEL_CODE
        self.concurrency = self.cloud_concurrency
        self.media_resolver = media_resolver
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.state_condition = threading.Condition(threading.RLock())
        self.started = False
        self.claim_lock = threading.Lock()
        self.active_claims_lock = threading.Lock()
        self.active_claims: dict[int, tuple[str, str]] = {}
        self.rate_limit_lock = threading.Lock()
        self.rate_limit_until = 0.0
        self.next_watchdog_at = 0.0

    def start(self) -> None:
        with self.state_condition:
            if self.started:
                return
        self.recover_interrupted()
        config = self.service.get_config()
        with self.state_condition:
            if self.started:
                return
            self.stop_event.clear()
            self.started = True
            self._apply_runtime_config_locked(
                config["model_code"], config["cloud_concurrency"]
            )
            self._ensure_threads_locked()

    def stop(self) -> None:
        self.stop_event.set()
        with self.state_condition:
            self.state_condition.notify_all()
            threads = list(self.threads)
        for thread in threads:
            thread.join(timeout=10)
        with self.state_condition:
            self.threads.clear()
            self.started = False

    @staticmethod
    def _bounded_concurrency(value: int) -> int:
        return max(
            SENTIMENT_CLOUD_CONCURRENCY_MIN,
            min(value, SENTIMENT_CLOUD_CONCURRENCY_MAX),
        )

    def apply_runtime_config(self, model_code: str, cloud_concurrency: int) -> None:
        """保存配置后立即调整后续任务槽位，不中断已经发出的请求。"""

        with self.state_condition:
            self._apply_runtime_config_locked(model_code, cloud_concurrency)
            if self.started:
                self._ensure_threads_locked()
            self.state_condition.notify_all()

    def _apply_runtime_config_locked(self, model_code: str, cloud_concurrency: int) -> None:
        self.model_code = model_code
        self.cloud_concurrency = self._bounded_concurrency(cloud_concurrency)
        self.concurrency = (
            1 if model_profile(model_code)["provider"] == "local" else self.cloud_concurrency
        )

    def _ensure_threads_locked(self) -> None:
        for index in range(len(self.threads), self.concurrency):
            thread = threading.Thread(
                target=self._loop,
                args=(index,),
                name=f"threadsnap-sentiment-{index + 1}",
                daemon=True,
            )
            self.threads.append(thread)
            thread.start()

    def recover_interrupted(self) -> None:
        """启动时沿用同一有界孤儿恢复规则，避免反复重启无限重排。"""

        self.recover_orphaned()

    def _loop(self, slot: int) -> None:
        while not self.stop_event.is_set():
            with self.state_condition:
                while slot >= self.concurrency and not self.stop_event.is_set():
                    self.state_condition.wait(timeout=self.poll_seconds)
            if self.stop_event.is_set():
                return
            try:
                if slot == 0 and monotonic() >= self.next_watchdog_at:
                    self.recover_orphaned()
                    self.next_watchdog_at = monotonic() + SENTIMENT_WATCHDOG_INTERVAL_SECONDS
                progressed = self.process_once(slot)
            except Exception:
                logger.exception("舆情 Worker 循环执行失败，slot=%s", slot)
                progressed = False
            if not progressed:
                self.stop_event.wait(self.poll_seconds)

    def recover_orphaned(self) -> int:
        """恢复本进程中已无执行线程持有的运行任务，并限制为一次自动恢复。"""

        with self.claim_lock:
            with self.active_claims_lock:
                active_ids = {analysis_id for analysis_id, _post_id in self.active_claims.values()}
            recovered = 0
            with self.service.factory.begin() as db:
                analyses = db.scalars(
                    select(SentimentAnalysis).where(
                        SentimentAnalysis.status == "analysis_running"
                    )
                ).all()
                for analysis in analyses:
                    if analysis.id in active_ids:
                        continue
                    post = db.get(PostSnapshot, analysis.post_id)
                    attempt_failures = list(analysis.attempt_failures or [])
                    orphaned_before = any(
                        item.get("error_code") == "ANALYSIS_WORKER_ORPHANED"
                        for item in attempt_failures
                    )
                    if orphaned_before:
                        analysis.status = "analysis_failed"
                        analysis.error_code = "ANALYSIS_WORKER_ORPHANED"
                        analysis.error_message = "舆情任务连续两次失去执行线程，已停止自动恢复。"
                        analysis.finished_at = utc_now()
                        if post:
                            post.analysis_status = "analysis_failed"
                            post.sentiment_updated_at = utc_now()
                    else:
                        attempt_failures.append(
                            _failed_attempt(
                                attempt=analysis.retry_count + 1,
                                exc=RuntimeError("舆情任务失去执行线程"),
                                error_code="ANALYSIS_WORKER_ORPHANED",
                                raw_response="",
                                request_id=None,
                                usage=None,
                                duration_ms=None,
                            )
                        )
                        analysis.status = "analysis_queued"
                        analysis.started_at = None
                        analysis.finished_at = None
                        analysis.error_code = None
                        analysis.error_message = None
                        analysis.attempt_failures = attempt_failures
                        if post:
                            post.analysis_status = "analysis_queued"
                            post.sentiment_updated_at = utc_now()
                    recovered += 1
            return recovered

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

    def process_once(self, slot: int | None = None) -> bool:
        """处理一条任务；未预期异常也必须结束当前运行态并留下诊断。"""

        thread_id = threading.get_ident()
        try:
            return self._process_once(slot)
        except Exception as exc:
            with self.active_claims_lock:
                claim = self.active_claims.get(thread_id)
            logger.exception(
                "舆情 Worker 未预期异常，analysis_id=%s post_id=%s exception=%s",
                claim[0] if claim else None,
                claim[1] if claim else None,
                type(exc).__name__,
            )
            if claim:
                try:
                    self._record_internal_failure(claim[0], claim[1], exc)
                except Exception:
                    logger.exception(
                        "舆情 Worker 未预期异常落库失败，analysis_id=%s post_id=%s",
                        claim[0],
                        claim[1],
                    )
                return True
            return False
        finally:
            with self.active_claims_lock:
                self.active_claims.pop(thread_id, None)

    def _process_once(self, slot: int | None = None) -> bool:
        # SQLite 不支持 SKIP LOCKED；只串行化很短的领取事务，模型请求仍可并发执行。
        with self.claim_lock:
            if slot is not None:
                with self.state_condition:
                    if slot >= self.concurrency:
                        return False
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
                with self.active_claims_lock:
                    self.active_claims[threading.get_ident()] = (analysis_id, post_id)
        analysis_profile = model_profile(analysis.model_code)
        if analysis_profile["provider"] == "local":
            return self._process_local(
                analysis_id,
                post_id,
                post,
                analysis.subject_snapshot,
                attempt_failures,
            )
        try:
            configured_base_url, configured_key = model_connection(config, analysis.model_code)
            base_url = validate_public_https_base_url(configured_base_url, resolve=True)
            api_key = self.service.secrets.decrypt_secret(configured_key or b"")
        except Exception as exc:
            self._record_failure(
                analysis_id,
                post_id,
                ModelRequestError(f"模型运行配置不可用：{exc}", config_error=True),
            )
            return True
        try:
            if (
                analysis_profile["input_mode"] == "multimodal"
                and self.media_resolver
                and deduplicate_media_urls(post.video_urls)
            ):
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
        output_correction_retries = 0
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
                                error_code="MODEL_STREAM_INCOMPLETE",
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
                structural_error: json.JSONDecodeError | None = None
                payload_completed = False
                try:
                    payload, _strict, recovered = parse_feedback_text(raw)
                except json.JSONDecodeError as exc:
                    if analysis_profile["output_mode"] != "strict_tool":
                        raise
                    payload = recover_deepseek_tool_payload(raw, post, exc.pos)
                    recovered = True
                    structural_error = exc
                    payload_completed = True
                if analysis_profile["output_mode"] == "strict_tool" and not payload_completed:
                    payload = complete_deepseek_tool_payload(payload, post)
                feedback = SentimentFeedback.model_validate(payload)
                validate_modality_identity(feedback, post)
                if structural_error is not None:
                    attempt_failures.append(
                        _failed_attempt(
                            attempt=retry_count + 1,
                            exc=structural_error,
                            error_code="MODEL_RESPONSE_ERROR",
                            raw_response=raw,
                            request_id=request_id,
                            usage=usage,
                            duration_ms=duration_ms,
                        )
                    )
            except (ValueError, json.JSONDecodeError, ValidationError) as exc:
                if output_correction_retries < 1:
                    attempt_failures.append(
                        _failed_attempt(
                            attempt=retry_count + 1,
                            exc=exc,
                            error_code="MODEL_RESPONSE_ERROR",
                            raw_response=raw,
                            request_id=request_id,
                            usage=usage,
                            duration_ms=duration_ms,
                        )
                    )
                    body = build_output_correction_request(
                        body,
                        raw,
                        exc,
                        input_mode=analysis_profile["input_mode"],
                    )
                    output_correction_retries += 1
                    retry_count += 1
                    if self.stop_event.wait(1.0):
                        return False
                    continue
                attempt_failures.append(
                    _failed_attempt(
                        attempt=retry_count + 1,
                        exc=exc,
                        error_code="MODEL_RESPONSE_ERROR",
                        raw_response=raw,
                        request_id=request_id,
                        usage=usage,
                        duration_ms=duration_ms,
                    )
                )
                self._record_failure(
                    analysis_id,
                    post_id,
                    exc,
                    raw_response=raw,
                    retry_count=retry_count,
                    attempt_failures=attempt_failures,
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
            locally_recovered=recovered,
            request_id=request_id,
            usage=usage,
            retry_count=retry_count,
            duration_ms=duration_ms,
        )
        return True

    def _record_internal_failure(
        self,
        analysis_id: str,
        post_id: str,
        exc: Exception,
    ) -> None:
        """保存框架未预期异常；不把它误判成模型格式错误或配置错误。"""

        message = f"舆情任务内部处理异常（{type(exc).__name__}）：{exc}"[:2000]
        with self.service.factory.begin() as db:
            analysis = db.get(SentimentAnalysis, analysis_id)
            post = db.get(PostSnapshot, post_id)
            if analysis:
                analysis.status = "analysis_failed"
                analysis.error_code = "ANALYSIS_INTERNAL_ERROR"
                analysis.error_message = message
                analysis.finished_at = utc_now()
            if post:
                post.analysis_status = "analysis_failed"
                post.sentiment_updated_at = utc_now()
        if self.service.event_publisher:
            self.service.event_publisher(
                "sentiment.changed", post_id, status="analysis_failed"
            )

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
            analysis.error_code = None
            analysis.error_message = None
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
