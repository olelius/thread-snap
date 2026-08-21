"""本地轻量文字模型的线程与结果契约测试。"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from threadsnap.local_sentiment import LocalSentimentAnalyzer


class _ThreadBoundCallable:
    """模拟只能在同一线程调用的 Paddle Predictor。"""

    def __init__(self, *, utc: bool = False) -> None:
        self.utc = utc
        self.schema: list[str] = []
        self.thread_ids: set[int] = set()

    def _observe_thread(self) -> None:
        self.thread_ids.add(threading.get_ident())

    def set_schema(self, schema: list[str]) -> None:
        self._observe_thread()
        self.schema = schema

    def __call__(self, text: str) -> list[dict[str, Any]]:
        self._observe_thread()
        if not self.utc:
            return [{"评价维度": [{"text": "风云A9"}]}]
        if self.schema and self.schema[0].startswith("负面："):
            label = self.schema[0] if "故障" in text or "不佳" in text else self.schema[1]
        else:
            label = self.schema[0]
        return [{"predictions": [{"label": label, "score": 0.9}]}]


class _ThreadBoundAnalyzer(LocalSentimentAnalyzer):
    def __init__(self, model_home: Path) -> None:
        super().__init__(model_home)
        self.senta = _ThreadBoundCallable()
        self.utc = _ThreadBoundCallable(utc=True)

    def _senta(self, aspects: list[str]) -> _ThreadBoundCallable:
        return self.senta

    def _utc(self) -> _ThreadBoundCallable:
        return self.utc


class _CapturingAnalyzer(LocalSentimentAnalyzer):
    def __init__(self, model_home: Path, *, num_threads: int) -> None:
        super().__init__(model_home, num_threads=num_threads)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _taskflow(self) -> Any:
        def create(task: str, **kwargs: Any) -> _ThreadBoundCallable:
            self.calls.append((task, kwargs))
            return _ThreadBoundCallable(utc=task == "zero_shot_text_classification")

        return create


class LocalSentimentThreadTests(unittest.TestCase):
    def test_taskflows_use_controlled_cpu_thread_budget(self) -> None:
        """两个 Paddle Taskflow 都使用后端限定的 CPU 线程数。"""

        with tempfile.TemporaryDirectory() as directory:
            analyzer = _CapturingAnalyzer(Path(directory), num_threads=2)
            try:
                analyzer._senta(["风云A9"])
                analyzer._utc()
            finally:
                analyzer.close()

        self.assertEqual(2, len(analyzer.calls))
        self.assertEqual([2, 2], [kwargs["num_threads"] for _, kwargs in analyzer.calls])

    def test_validate_and_worker_analysis_share_one_inference_thread(self) -> None:
        """配置测试和后台分析必须在同一专用线程使用 Predictor。"""

        with tempfile.TemporaryDirectory() as directory:
            analyzer = _ThreadBoundAnalyzer(Path(directory))
            try:
                subject = {"brand": "奇瑞", "products": ["风云A9"]}
                analyzer.validate(subject)
                with ThreadPoolExecutor(max_workers=1) as caller:
                    payload, raw, _duration = caller.submit(
                        analyzer.analyze,
                        title="风云A9电池故障",
                        content="售后一直没有解决。",
                        image_count=1,
                        video_count=1,
                        subject=subject,
                    ).result()
            finally:
                analyzer.close()

        self.assertEqual(1, len(analyzer.senta.thread_ids))
        self.assertEqual(analyzer.senta.thread_ids, analyzer.utc.thread_ids)
        self.assertEqual("negative", payload["sentiment"])
        self.assertEqual("not_requested", payload["modalities"]["video_visual"]["status"])
        self.assertEqual(
            {"uie_senta", "utc_sentiment", "utc_category"},
            set(json.loads(raw)),
        )


if __name__ == "__main__":
    unittest.main()
