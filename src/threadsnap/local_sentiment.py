"""基于 PaddleNLP 轻量任务模型的本地文字舆情分析。"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic
from typing import Any

LOCAL_MODEL_CODE = "paddlenlp-local-text-nano-v1"
LOCAL_MODEL_NAME = "PaddleNLP 本地轻量文字分析（Nano）"

_SENTA_SCHEMA = [{"评价维度": ["观点词", "情感倾向[正向,负向,未提及]"]}]
_CATEGORY_LABELS = OrderedDict(
    [
        ("产品客诉：真实车主反馈质量故障或硬件缺陷", "product_complaint"),
        ("产品吐槽：使用体验不佳或对产品不满", "product_criticism"),
        ("服务投诉：售后或门店服务问题", "service_complaint"),
        ("品牌吐槽：对品牌形象不满", "brand_criticism"),
        ("竞品攻击：竞品水平恶意抹黑品牌", "competitor_attack"),
        ("其他负面内容", "other"),
    ]
)
_SENTIMENT_LABELS = OrderedDict(
    [
        ("负面：故障、缺陷、不满、投诉或贬损", "negative"),
        ("非负面：正面、中性、赞扬或无明确不满", "non_negative"),
    ]
)


def _plain(value: Any) -> Any:
    """把 Paddle/Numpy 标量递归转换成可持久化的原生 JSON 值。"""

    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except (TypeError, ValueError):
            pass
    return value


def _subject_values(subject: dict[str, Any]) -> list[str]:
    values = [str(subject.get("brand") or "").strip()]
    values.extend(str(value).strip() for value in subject.get("products") or [])
    return list(dict.fromkeys(value for value in values if value))


def _contains_subject(text: str, subject: str) -> bool:
    compact_text = re.sub(r"\s+", "", text).casefold()
    compact_subject = re.sub(r"\s+", "", subject).casefold()
    return bool(compact_subject and compact_subject in compact_text)


def _sentence_for(text: str, needles: list[str]) -> str:
    sentences = [item.strip() for item in re.split(r"(?<=[。！？!?；;\n])", text) if item.strip()]
    for sentence in sentences:
        if any(needle and needle in sentence for needle in needles):
            return sentence[:300]
    return (sentences[0] if sentences else text.strip())[:300]


def _relation_values(relations: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    for key, value in relations.items():
        if str(key).startswith(prefix) and isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _extract_opinions(
    node: dict[str, Any], *, root_subject: str, source_text: str
) -> list[dict[str, str]]:
    """从 UIE-Senta 的嵌套关系中收集评价维度、观点和极性。"""

    output: list[dict[str, str]] = []
    relations = node.get("relations")
    if not isinstance(relations, dict):
        return output
    sentiments = _relation_values(relations, "情感倾向")
    opinions = _relation_values(relations, "观点词")
    if sentiments:
        opinion_texts = [str(item.get("text") or "").strip() for item in opinions]
        dimension = str(node.get("text") or root_subject).strip()
        evidence = _sentence_for(
            source_text,
            [value for value in opinion_texts if value] or [dimension, root_subject],
        )
        for sentiment in sentiments:
            output.append(
                {
                    "subject": root_subject,
                    "dimension": dimension,
                    "opinion": "、".join(value for value in opinion_texts if value),
                    "sentiment": str(sentiment.get("text") or "").strip(),
                    "evidence": evidence,
                }
            )
    for value in relations.values():
        if not isinstance(value, list):
            continue
        for child in value:
            if isinstance(child, dict):
                output.extend(
                    _extract_opinions(child, root_subject=root_subject, source_text=source_text)
                )
    return output


class LocalSentimentAnalyzer:
    """进程内复用并串行调用两个 Nano 任务模型。"""

    def __init__(self, model_home: Path):
        self.model_home = model_home
        self._lock = threading.RLock()
        # Paddle Predictor 不能跨创建线程复用；配置测试和后台 Worker 都统一投递到这里。
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="threadsnap-local-sentiment",
        )
        self._senta_by_aspects: OrderedDict[tuple[str, ...], Any] = OrderedDict()
        self._category_model: Any | None = None

    def close(self) -> None:
        """停止专用推理线程；调用前应先停止舆情 Worker。"""

        self._executor.shutdown(wait=True, cancel_futures=True)

    def _taskflow(self) -> Any:
        # PaddleNLP 在首次 import 时冻结缓存目录，因此必须先设置。
        os.environ["PPNLP_HOME"] = str(self.model_home)
        from paddlenlp import Taskflow

        return Taskflow

    def _senta(self, aspects: list[str]) -> Any:
        key = tuple(aspects)
        existing = self._senta_by_aspects.get(key)
        if existing is not None:
            self._senta_by_aspects.move_to_end(key)
            return existing
        model = self._taskflow()(
            "sentiment_analysis",
            model="uie-senta-nano",
            schema=_SENTA_SCHEMA,
            aspects=aspects,
            split_sentence=True,
            batch_size=8,
        )
        self._senta_by_aspects[key] = model
        while len(self._senta_by_aspects) > 4:
            self._senta_by_aspects.popitem(last=False)
        return model

    def _utc(self) -> Any:
        if self._category_model is None:
            self._category_model = self._taskflow()(
                "zero_shot_text_classification",
                model="utc-nano",
                schema=list(_SENTIMENT_LABELS),
                single_label=True,
                pred_threshold=0.0,
                batch_size=1,
            )
        return self._category_model

    def validate(self, subject: dict[str, Any]) -> int:
        """加载模型并执行一次本地最小推理，返回毫秒耗时。"""

        return self._executor.submit(self._validate, subject).result()

    def _validate(self, subject: dict[str, Any]) -> int:
        """在固定推理线程内加载并验证两个任务模型。"""

        aspects = _subject_values(subject)
        if not aspects:
            raise ValueError("本地模型至少需要一个品牌或重点产品。")
        started = monotonic()
        probe = f"{aspects[0]}使用体验不错。"
        with self._lock:
            senta_result = self._senta(aspects)(probe)
            utc = self._utc()
            utc.set_schema(list(_SENTIMENT_LABELS))
            sentiment_result = utc("产品使用体验不佳。")
            utc.set_schema(list(_CATEGORY_LABELS))
            category_result = utc("产品使用体验不佳。")
        if not all(
            isinstance(result, list) for result in (senta_result, sentiment_result, category_result)
        ):
            raise ValueError("本地模型返回格式异常。")
        return round((monotonic() - started) * 1000)

    def analyze(
        self,
        *,
        title: str,
        content: str,
        image_count: int,
        video_count: int,
        subject: dict[str, Any],
    ) -> tuple[dict[str, Any], str, int]:
        """只使用标题和正文，返回与在线模型一致的规范化结果。"""

        return self._executor.submit(
            self._analyze,
            title=title,
            content=content,
            image_count=image_count,
            video_count=video_count,
            subject=subject,
        ).result()

    def _analyze(
        self,
        *,
        title: str,
        content: str,
        image_count: int,
        video_count: int,
        subject: dict[str, Any],
    ) -> tuple[dict[str, Any], str, int]:
        """在固定推理线程内执行一次文字分析。"""

        aspects = _subject_values(subject)
        if not aspects:
            raise ValueError("本地模型至少需要一个品牌或重点产品。")
        text = "\n".join(value.strip() for value in (title, content) if value.strip())
        started = monotonic()
        with self._lock:
            raw_senta = self._senta(aspects)(text) if text else []
            utc = self._utc()
            utc.set_schema(list(_SENTIMENT_LABELS))
            raw_sentiment = utc(text) if text else []

        root_items: list[dict[str, Any]] = []
        if raw_senta and isinstance(raw_senta[0], dict):
            for value in raw_senta[0].values():
                if isinstance(value, list):
                    root_items.extend(item for item in value if isinstance(item, dict))

        matched_subjects = [value for value in aspects if _contains_subject(text, value)]
        opinions: list[dict[str, str]] = []
        for item in root_items:
            root_subject = str(item.get("text") or "").strip()
            extracted = _extract_opinions(
                item,
                root_subject=root_subject,
                source_text=text,
            )
            if extracted and root_subject:
                matched_subjects.append(root_subject)
            opinions.extend(extracted)
        matched_subjects = list(dict.fromkeys(matched_subjects))
        subject_relevance = bool(matched_subjects)
        sentiment_predictions = (
            raw_sentiment[0].get("predictions", [])
            if raw_sentiment and isinstance(raw_sentiment[0], dict)
            else []
        )
        sentiment_label = (
            str(sentiment_predictions[0].get("label") or "") if sentiment_predictions else ""
        )
        sentiment = _SENTIMENT_LABELS.get(sentiment_label) if subject_relevance else None
        if subject_relevance and sentiment is None:
            raise ValueError("UTC-Nano 未返回有效情感分类。")
        negative = [item for item in opinions if item["sentiment"] == "负向"]
        primary_category = None
        if sentiment == "negative":
            category_text = "\n".join(item["evidence"] for item in negative) or text
            with self._lock:
                utc = self._utc()
                utc.set_schema(list(_CATEGORY_LABELS))
                raw_category = utc(category_text)
            predictions = (
                raw_category[0].get("predictions", [])
                if raw_category and isinstance(raw_category[0], dict)
                else []
            )
            label = str(predictions[0].get("label") or "") if predictions else ""
            primary_category = _CATEGORY_LABELS.get(label, "other")
        else:
            raw_category = []

        evidence = list(
            dict.fromkeys(item["evidence"] for item in (negative or opinions) if item["evidence"])
        )
        if not evidence and matched_subjects:
            evidence = [_sentence_for(text, matched_subjects)]
        if not subject_relevance:
            summary = "标题和正文中未识别出与配置品牌或重点产品相关的明确内容。"
        elif sentiment == "negative":
            summary = (
                f"本地文字模型识别内容与{'、'.join(matched_subjects)}相关，"
                f"存在负面倾向。主要依据：{evidence[0] if evidence else '未提取到观点原句'}"
            )
        else:
            summary = (
                f"本地文字模型识别内容与{'、'.join(matched_subjects)}相关，未识别出明确负面倾向。"
            )

        def media_coverage(count: int) -> dict[str, Any]:
            return {
                "status": "not_requested" if count else "absent",
                "expected_count": count,
                "processed_count": 0,
                "items": [],
            }

        payload = {
            "subject_relevance": subject_relevance,
            "matched_subjects": matched_subjects,
            "sentiment": sentiment,
            "primary_category": primary_category,
            "secondary_categories": [],
            "modalities": {
                "text": {
                    "status": "processed" if text else "absent",
                    "evidence": evidence,
                },
                "image": media_coverage(image_count),
                "video_visual": media_coverage(video_count),
                "video_audio": media_coverage(video_count),
            },
            "summary": summary,
        }
        raw = json.dumps(
            {
                "uie_senta": _plain(raw_senta),
                "utc_sentiment": _plain(raw_sentiment),
                "utc_category": _plain(raw_category),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return payload, raw, round((monotonic() - started) * 1000)
