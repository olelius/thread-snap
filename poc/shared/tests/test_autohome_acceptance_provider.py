"""汽车之家生产适配器验收桥的固定分母与止损测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
PROJECT_SRC = Path(__file__).resolve().parents[3] / "src"
sys.path.insert(0, str(PROJECT_SRC))
sys.path.insert(0, str(SHARED))

import later_platform_acceptance as acceptance  # noqa: E402

from threadsnap.collectors import CollectorFailure, get_platform_spec  # noqa: E402
from threadsnap.collectors.autohome_acceptance import (  # noqa: E402
    AutohomeAcceptanceProvider,
)
from threadsnap.collectors.registry import get_acceptance_provider  # noqa: E402


def make_urls(count: int = 500) -> list[str]:
    return [
        f"https://club.autohome.com.cn/bbs/thread/hash{index}/{100000000 + index}-1.html"
        for index in range(count)
    ]


def make_manifest(urls: list[str]) -> dict:
    return {
        "selected_count": len(urls),
        "selected": [
            {
                "input_index": index,
                "platform_post_id": str(100000000 + index),
            }
            for index in range(len(urls))
        ],
    }


class ChallengeCollector:
    """首条详情返回访问验证，其余调用均表示止损失败。"""

    def __init__(self, *_: object, concurrency: int, **__: object):
        self.concurrency = concurrency
        self.visited: list[str] = []

    def fetch_post(self, url: str, **_: object) -> dict:
        self.visited.append(url)
        raise CollectorFailure("PLATFORM_CHALLENGE", "访问验证")


class SourceCollector:
    """只暴露来源桥所需的生产适配器表面。"""

    def __init__(self, *_: object, concurrency: int, **__: object):
        self.concurrency = concurrency
        self.visited: list[str] = []

    def validate_circle(self, url: str) -> dict:
        self.visited.append(url)
        order = "latest_publish" if "sort=topic" in url else "latest_reply"
        return {"sort": order, "external_id": "8232", "sample_post_id": "115934382"}


class AutohomeAcceptanceProviderTests(unittest.TestCase):
    def test_registry_bridge_does_not_open_production_platform_gate(self) -> None:
        spec = get_platform_spec("autohome")
        provider = get_acceptance_provider("autohome")

        self.assertEqual("not_integrated", spec.adapter_status)
        self.assertIsInstance(provider, AutohomeAcceptanceProvider)
        self.assertEqual(500, acceptance.FORMAL_COUNT)
        self.assertEqual(1, provider.max_concurrency)

    def test_source_provider_binds_seed_to_both_orders_and_saves_evidence(self) -> None:
        instances: list[SourceCollector] = []

        def factory(*args: object, **kwargs: object) -> SourceCollector:
            collector = SourceCollector(*args, **kwargs)
            instances.append(collector)
            return collector

        provider = AutohomeAcceptanceProvider(collector_factory=factory)
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            rows = provider.discover_sources(
                [
                    {
                        "seed_identity": "icar-v27",
                        "community_url": (
                            "https://club.autohome.com.cn/bbs/forum-c-8232-1.html?sort=post"
                        ),
                    }
                ],
                evidence,
            )

            self.assertEqual(
                {("icar-v27", "latest_reply"), ("icar-v27", "latest_publish")},
                {(row["seed_identity"], row["list_order"]) for row in rows},
            )
            self.assertEqual(2, len(instances[0].visited))
            self.assertEqual(2, len(list(evidence.glob("*.json"))))

    def test_first_control_stops_requests_and_keeps_500_unique_terminals(self) -> None:
        instances: list[ChallengeCollector] = []

        def factory(*args: object, **kwargs: object) -> ChallengeCollector:
            collector = ChallengeCollector(*args, **kwargs)
            instances.append(collector)
            return collector

        urls = make_urls()
        manifest = make_manifest(urls)
        provider = AutohomeAcceptanceProvider(collector_factory=factory)

        payload = provider.run_acceptance(
            urls,
            manifest=manifest,
            access_mode="anonymous",
            concurrency=1,
        )
        summary = acceptance.evaluate_results(
            platform_code="autohome",
            urls=urls,
            manifest=manifest,
            records=payload["results"],
            request_events=payload["request_events"],
            wall_seconds=1,
        )

        self.assertEqual(1, len(instances[0].visited))
        self.assertEqual(500, len(payload["results"]))
        self.assertEqual(500, summary["unique_terminal_count"])
        self.assertEqual(1, summary["unrecovered_control_count"])
        self.assertEqual(499, summary["unrequested_count"])
        self.assertEqual(1, len(payload["request_events"]))
        self.assertFalse(summary["passed"])

    def test_provider_rejects_any_non_500_run_and_non_one_concurrency(self) -> None:
        provider = AutohomeAcceptanceProvider(collector_factory=ChallengeCollector)
        urls = make_urls(499)
        with self.assertRaises(CollectorFailure) as count_error:
            provider.run_acceptance(
                urls,
                manifest=make_manifest(urls),
                access_mode="anonymous",
                concurrency=1,
            )
        self.assertEqual("ACCEPTANCE_FORMAL_COUNT_INVALID", count_error.exception.code)

        urls = make_urls()
        with self.assertRaises(CollectorFailure) as concurrency_error:
            provider.run_acceptance(
                urls,
                manifest=make_manifest(urls),
                access_mode="anonymous",
                concurrency=2,
            )
        self.assertEqual("ACCEPTANCE_CONCURRENCY_INVALID", concurrency_error.exception.code)


if __name__ == "__main__":
    unittest.main()
