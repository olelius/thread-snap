"""在线多模态舆情反馈的一次调用 PoC。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

SUBJECTS = [
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
CATEGORIES = [
    "product_complaint",
    "product_criticism",
    "service_complaint",
    "brand_criticism",
    "competitor_attack",
    "other",
]


class TextCoverage(BaseModel):
    """文字模态覆盖结果。"""

    status: Literal["absent", "processed", "unprocessed"]
    evidence: list[str] = Field(default_factory=list)


class MediaItem(BaseModel):
    """单项图片或视频输入的处理结果。"""

    input_index: int = Field(ge=0)
    url_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: str
    evidence: list[str] = Field(default_factory=list)


class MediaCoverage(BaseModel):
    """带数量核对的媒体覆盖结果。"""

    status: str
    expected_count: int = Field(ge=0)
    processed_count: int = Field(ge=0)
    items: list[MediaItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts(self) -> "MediaCoverage":
        if len(self.items) != self.expected_count:
            raise ValueError("items 数量必须等于 expected_count")
        if self.processed_count > self.expected_count:
            raise ValueError("processed_count 不得超过 expected_count")
        return self


class Modalities(BaseModel):
    """PoC 要求模型分别声明各输入模态。"""

    text: TextCoverage
    image: MediaCoverage
    video_visual: MediaCoverage
    video_audio: MediaCoverage


class SentimentFeedback(BaseModel):
    """PoC 的最小结构化舆情反馈。"""

    subject_relevance: bool
    matched_subjects: list[str]
    sentiment: Literal["negative", "non_negative"]
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
    summary: str

    @model_validator(mode="after")
    def validate_sentiment_category(self) -> "SentimentFeedback":
        if self.sentiment == "negative" and self.primary_category is None:
            raise ValueError("负面结果必须包含 primary_category")
        if self.sentiment == "non_negative" and self.primary_category is not None:
            raise ValueError("非负面结果不得包含 primary_category")
        unknown = [item for item in self.matched_subjects if item not in SUBJECTS]
        if unknown:
            raise ValueError(f"matched_subjects 包含范围外对象：{unknown}")
        return self


def load_env_file(path: Path) -> dict[str, str]:
    """读取项目内被 Git 忽略的简单 KEY=VALUE 配置。"""

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def stable_url_hash(url: str) -> str:
    """移除查询及已知 CDN 路径签名后计算稳定媒体 URL 哈希。"""

    parts = urlsplit(url)
    path = parts.path
    netloc = parts.netloc.lower()
    if netloc.endswith("dcarvod.com"):
        match = re.search(r"/[0-9a-fA-F]{32}/[0-9a-fA-F]{8}(/video/.*)", path)
        if match:
            path = match.group(1)
            # 同一视频会在多个 dcarvod CDN 主机上返回等价播放地址；主机也不属于
            # 稳定媒体身份，否则一次帖子会被误当成多个视频送入模型。
            netloc = "dcarvod.com"
    normalized = urlunsplit((parts.scheme.lower(), netloc, path, "", ""))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_prompt(sample: dict[str, Any]) -> str:
    """构造一次请求所需的紧凑 JSON 输出提示词。"""

    image_hashes = [stable_url_hash(url) for url in sample.get("image_urls") or []]
    video_hashes = [stable_url_hash(url) for url in sample.get("video_urls") or []]
    return f"""请只返回一个标准 JSON 对象，不要使用 Markdown。
你是舆情分析人员，判定对象仅限：{json.dumps(SUBJECTS, ensure_ascii=False)}。
无论内容是否命中判定对象，都要实际检查每个输入的文字、图片、视频画面和视频音频，并逐项填写覆盖状态与简短事实依据。

判定规则：
1. 对判定对象不利的信息为 negative；中性或正面信息为 non_negative。
2. negative 的 primary_category 仅允许：{json.dumps(CATEGORIES, ensure_ascii=False)}。
3. non_negative 的 primary_category 必须为 null。
4. 只依据本次输入，不搜索网页，不引用作者历史或评论。
5. evidence 保持简短，只描述本次输入中实际观察到的事实。

帖子标题：{sample.get("title") or ""}
帖子正文：{sample.get("content") or ""}
图片 URL 哈希（按输入顺序）：{json.dumps(image_hashes)}
视频 URL 哈希（按输入顺序）：{json.dumps(video_hashes)}

返回字段必须完整匹配：
{{
  "subject_relevance": true,
  "matched_subjects": ["A9L"],
  "sentiment": "negative 或 non_negative",
  "primary_category": null,
  "secondary_categories": [],
  "modalities": {{
    "text": {{"status": "absent/processed/unprocessed", "evidence": []}},
    "image": {{"status": "absent/processed/inaccessible/unrecognizable/unprocessed", "expected_count": {len(image_hashes)}, "processed_count": 0, "items": []}},
    "video_visual": {{"status": "absent/processed/inaccessible/unrecognizable/unprocessed", "expected_count": {len(video_hashes)}, "processed_count": 0, "items": []}},
    "video_audio": {{"status": "absent/speech/silent/no_speech/inaccessible/unrecognizable/unprocessed", "expected_count": {len(video_hashes)}, "processed_count": 0, "items": []}}
  }},
  "summary": "简短总结"
}}
每个媒体 items 项必须包含 input_index、对应的 url_hash、status 和 evidence；items 数量等于 expected_count。"""


def build_request(sample: dict[str, Any], model: str) -> dict[str, Any]:
    """把图文和视频 URL 合并到一次 Qwen-Omni 请求。"""

    content: list[dict[str, Any]] = []
    for url in sample.get("image_urls") or []:
        content.append({"type": "image_url", "image_url": {"url": url}})
    for url in sample.get("video_urls") or []:
        content.append({"type": "video_url", "video_url": {"url": url}})
    content.append({"type": "text", "text": build_prompt(sample)})
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["text"],
        "response_format": {"type": "json_object"},
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def parse_sse_lines(
    lines: Iterable[str],
) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
    """聚合 OpenAI 兼容流式响应，同时保留可审计的 JSON 块。"""

    content: list[str] = []
    usage: dict[str, Any] | None = None
    chunks: list[dict[str, Any]] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        if not isinstance(chunk, dict):
            continue
        chunks.append(chunk)
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        choices = chunk.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            delta = choice.get("delta") if isinstance(choice, dict) else None
            value = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(value, str):
                content.append(value)
    return "".join(content), usage, chunks


def parse_feedback_text(text: str) -> tuple[dict[str, Any], bool, bool]:
    """解析模型 JSON，并标记是否仅通过移除 Markdown 围栏恢复。"""

    stripped = text.strip()
    try:
        value = json.loads(stripped)
        if not isinstance(value, dict):
            raise ValueError("模型响应不是 JSON 对象")
        return value, True, False
    except json.JSONDecodeError as strict_error:
        candidate = stripped
        if candidate.startswith("```json"):
            candidate = candidate[7:].lstrip()
        elif candidate.startswith("```"):
            candidate = candidate[3:].lstrip()
        decoder = json.JSONDecoder()
        try:
            value, end = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            raise strict_error
        remainder = candidate[end:].strip()
        if remainder != "```" or not isinstance(value, dict):
            raise strict_error
        return value, False, True


def reserve_api_call(ledger_path: Path, round_id: str, maximum: int) -> int:
    """在请求发出前原子记账，阻止脚本重复消耗调用额度。"""

    ledger = {"calls": []}
    if ledger_path.exists():
        loaded = json.loads(ledger_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("calls"), list):
            ledger = loaded
    if len(ledger["calls"]) >= maximum:
        raise RuntimeError(f"千问 API 调用预算已用尽：{len(ledger['calls'])}/{maximum}")
    ledger["calls"].append(
        {"round_id": round_id, "reserved_at": datetime.now(timezone.utc).isoformat()}
    )
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    pending = ledger_path.with_suffix(".tmp")
    pending.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(ledger_path)
    return len(ledger["calls"])


def run_once(sample_path: Path, env_path: Path, results_root: Path) -> Path:
    """执行严格一次、无自动重试的线上多模态冒烟。"""

    config = load_env_file(env_path)
    required = ["DASHSCOPE_API_KEY", "THREADSNAP_AI_BASE_URL", "THREADSNAP_AI_MODEL"]
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise RuntimeError(f"PoC 配置缺少字段：{', '.join(missing)}")
    maximum = int(config.get("THREADSNAP_AI_MAX_API_REQUESTS", "1"))
    retries = int(config.get("THREADSNAP_AI_MAX_RETRIES", "0"))
    if maximum != 1 or retries != 0:
        raise RuntimeError("本轮 PoC 固定要求最大一次调用且不自动重试")

    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    if not isinstance(sample, dict) or len(sample.get("video_urls") or []) != 1:
        raise RuntimeError("模型冒烟样本必须包含且只包含一个已解析视频 URL")

    round_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    round_dir = results_root / round_id
    round_dir.mkdir(parents=True, exist_ok=False)
    ledger_path = results_root / "api-call-ledger.json"
    call_number = reserve_api_call(ledger_path, round_id, maximum)

    video_hashes = [stable_url_hash(url) for url in sample["video_urls"]]
    image_hashes = [stable_url_hash(url) for url in sample.get("image_urls") or []]
    request_body = build_request(sample, config["THREADSNAP_AI_MODEL"])
    prompt = request_body["messages"][0]["content"][-1]["text"]
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    manifest = {
        "round_id": round_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provider": "aliyun-model-studio",
        "model": config["THREADSNAP_AI_MODEL"],
        "api_call_budget": maximum,
        "api_call_number": call_number,
        "automatic_retries": retries,
        "sample_id": sample.get("post_id"),
        "subject": sample.get("subject"),
        "image_count": len(image_hashes),
        "video_count": len(video_hashes),
        "image_url_hashes": image_hashes,
        "video_url_hashes": video_hashes,
        "prompt_sha256": prompt_hash,
        "stream": True,
        "response_format": "json_object",
    }
    (round_dir / "run-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (round_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    started = datetime.now(timezone.utc)
    status = "failed"
    error: str | None = None
    request_id: str | None = None
    response_text = ""
    usage: dict[str, Any] | None = None
    chunks: list[dict[str, Any]] = []
    http_status: int | None = None
    parsed: dict[str, Any] | None = None
    structure_valid = False
    locally_recovered = False
    recovered_structure_valid = False
    endpoint = config["THREADSNAP_AI_BASE_URL"].rstrip("/") + "/chat/completions"
    try:
        timeout = httpx.Timeout(connect=20.0, read=600.0, write=60.0, pool=20.0)
        headers = {
            "Authorization": f"Bearer {config['DASHSCOPE_API_KEY']}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            with client.stream("POST", endpoint, headers=headers, json=request_body) as response:
                http_status = response.status_code
                request_id = response.headers.get("x-request-id") or response.headers.get(
                    "x-dashscope-request-id"
                )
                if response.status_code >= 400:
                    body = response.read().decode("utf-8", errors="replace")[:2000]
                    raise RuntimeError(f"模型接口 HTTP {response.status_code}: {body}")
                response_text, usage, chunks = parse_sse_lines(response.iter_lines())
        parsed, structure_valid, locally_recovered = parse_feedback_text(response_text)
        SentimentFeedback.model_validate(parsed)
        recovered_structure_valid = locally_recovered
        status = "completed" if structure_valid else "completed_with_local_recovery"
    except (
        httpx.HTTPError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        ValidationError,
    ) as exc:
        error = f"{type(exc).__name__}: {exc}"

    finished = datetime.now(timezone.utc)
    duration_ms = round((finished - started).total_seconds() * 1000)
    raw_path = round_dir / "raw-stream.jsonl"
    with raw_path.open("w", encoding="utf-8", newline="\n") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False, separators=(",", ":")) + "\n")
    if response_text:
        (round_dir / "response.txt").write_text(response_text, encoding="utf-8")

    result = {
        "sample_id": sample.get("post_id"),
        "subject": sample.get("subject"),
        "video_url_hashes": video_hashes,
        "provider_request_id": request_id,
        "http_status": http_status,
        "status": status,
        "structure_valid": structure_valid,
        "locally_recovered": locally_recovered,
        "recovered_structure_valid": recovered_structure_valid,
        "duration_ms": duration_ms,
        "usage": usage,
        "error": error,
        "feedback": parsed,
    }
    (round_dir / "results.jsonl").write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    summary = {
        "sample_count": 1,
        "api_calls": 1,
        "automatic_retries": 0,
        "completed": int(status in {"completed", "completed_with_local_recovery"}),
        "failed": int(status == "failed"),
        "structure_valid": int(structure_valid),
        "locally_recovered": int(locally_recovered),
        "recovered_structure_valid": int(recovered_structure_valid),
        "http_status": http_status,
        "duration_ms": duration_ms,
        "usage": usage,
        "video_visual_status": (
            parsed.get("modalities", {}).get("video_visual", {}).get("status") if parsed else None
        ),
        "video_audio_status": (
            parsed.get("modalities", {}).get("video_audio", {}).get("status") if parsed else None
        ),
    }
    (round_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (round_dir / "run.log").write_text(
        "\n".join(
            [
                f"round_id={round_id}",
                "api_calls=1",
                "automatic_retries=0",
                f"http_status={http_status}",
                f"status={status}",
                f"structure_valid={structure_valid}",
                f"duration_ms={duration_ms}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return round_dir


def main() -> None:
    """解析 CLI 参数并输出本轮结果目录。"""

    parser = argparse.ArgumentParser(description="执行一次在线多模态舆情反馈 PoC")
    parser.add_argument(
        "--sample",
        type=Path,
        default=Path("artifacts/poc/inputs/sentiment-analysis/model-smoke-candidate.json"),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path("artifacts/poc/config/sentiment-analysis.env"),
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        default=Path("artifacts/poc/results/sentiment-qwen3-5-omni-plus"),
    )
    args = parser.parse_args()
    try:
        round_dir = run_once(args.sample, args.env_file, args.results_root)
    except Exception as exc:
        print(f"PoC 启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(round_dir.resolve())


if __name__ == "__main__":
    main()
