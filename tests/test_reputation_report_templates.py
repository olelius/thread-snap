"""仅覆盖新增模板的取值、筛选、数学增减与TXT选择，不执行平台采集。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from threadsnap.app import build_router
from threadsnap.errors import DomainError, domain_error_handler
from threadsnap.reputation import ReputationService
from threadsnap.reputation_adapter import ReputationAdapterError
from threadsnap.reputation_autohome import AutohomeReputationAdapter
from threadsnap.reputation_reports import _change, render_report_templates


def metric(raw="4.20", delta="0", state="comparable"):
    return {"raw": raw, "delta": delta, "comparison_status": state}


def row(name="重点甲", platform="dongchedi", role="focus", **metrics):
    return SimpleNamespace(
        vehicle_id=name,
        vehicle_name=name,
        platform_code=platform,
        role=role,
        status="success",
        metrics=metrics,
    )


class ReportTemplatesTest(unittest.TestCase):
    def setUp(self):
        self.run = SimpleNamespace(
            planned_date="2026-09-08", platform_codes=["dongchedi", "autohome", "yiche"]
        )

    def test_detail_uses_review_articles_not_volume_and_preserves_zero(self):
        records = [
            row(
                score=metric(),
                circle_content_count=metric("0", "-10"),
                volume=metric("9999"),
                review_article_count=metric("121", "2"),
                negative_rate=metric("33%", "-1"),
            ),
            row(
                platform="autohome",
                score=metric("4.60", "0.02"),
                review_article_count=metric("180", "0"),
                circle_content_count=metric("7083", "12"),
            ),
            row("竞品乙", role="competitor", score=metric("5", "1")),
        ]
        text = render_report_templates(self.run, records)[0]["text"]
        self.assertIn("懂车帝车友圈露出数(较上日)：0\n-减少(-10)", text)
        self.assertIn("汽车之家论坛数：7083\n-增加(+12)", text)
        self.assertIn("懂车帝口碑帖数量：121\n-增加(+2)", text)
        self.assertIn("汽车之家口碑分：4.60\n-增加(+0.02)", text)
        self.assertNotIn("9999", text)
        self.assertNotIn("竞品乙", text)
        self.assertEqual(text.count("车型："), 1)

    def test_changes_only_include_displayed_comparable_metrics(self):
        records = [
            row("分数变化", score=metric("4.30", "0.10"), rank=metric("2", "0")),
            row(
                "仅圈数变化",
                score=metric(),
                rank=metric("3"),
                circle_content_count=metric("200", "100"),
            ),
            row(
                "仅差评率变化", score=metric(), rank=metric("1"), negative_rate=metric("20%", "-3")
            ),
            row("竞品变化", role="competitor", score=metric("4", "1")),
            row("名次变化", platform="autohome", score=metric(), rank=metric("2", "-1")),
            row("易车持平", platform="yiche", score=metric(), rank=metric("4")),
        ]
        text = render_report_templates(self.run, records)[1]["text"]
        self.assertIn("2026-09-08本品口碑分及排名变动如下：", text)
        self.assertIn("分数变化&口碑分4.30，增加(+0.1)", text)
        self.assertIn("仅差评率变化", text)
        self.assertIn("排名第2，减少(-1)", text)
        for excluded in ("仅圈数变化", "竞品变化", "易车持平"):
            self.assertNotIn(excluded, text)

    def test_missing_baseline_and_scope_change_are_not_zero_changes(self):
        records = [
            row(score=metric("4.2", None, "no_baseline"), rank=metric("3", "2", "not_comparable"))
        ]
        templates = render_report_templates(self.run, records)
        self.assertIn("暂无前日可比数据", templates[0]["text"])
        self.assertEqual(_change(records[0].metrics["rank"]), "口径变化，不作比较")
        self.assertNotIn("重点甲", templates[1]["text"])
        self.assertIn("暂无前日可比数据，未列出车型。", templates[1]["text"])
        self.assertNotIn("持平(0)", templates[0]["text"])

    def test_partial_and_missing_values_are_not_fabricated(self):
        record = row(score=metric(None, None, "not_available"))
        record.status = "partial_success"
        text = render_report_templates(self.run, [record])[0]["text"]
        self.assertIn("数据不完整", text)
        self.assertIn("懂车帝口碑分：—", text)
        empty = render_report_templates(self.run, [row(role="competitor")])
        self.assertIn("本批次无重点车型", empty[0]["text"])

    def test_forum_reads_header_posts_not_list_total_or_members(self):
        target = SimpleNamespace(platform_vehicle_id="8433")
        source = """<div id="js-bbs-info" data-bbsid="8433" data-bbs="c" data-bbsname="零跑A10论坛">
        <div class="bbs-info-count"><span class="count-item"><strong>741</strong>车友</span>
        <span class="count-item"><strong>7083</strong>帖子</span>
        <span class="count-item"><strong>393</strong>认证车主</span></div>
        <a href="//www.autohome.com.cn/8433/#pvareaid=6830259">零跑A10</a></div>
        <script>const total=2607;</script>"""
        url = "https://club.autohome.com.cn/bbs/forum-c-8433-1.html?sort=topic"
        raw, proof = AutohomeReputationAdapter.parse_forum_count(source.encode(), url, target)
        self.assertEqual(raw, "7083")
        self.assertEqual(proof["visible_count"], 7083)
        frozen = {"raw": raw, "value": raw, "source_url": url, "source_measurement": proof}
        self.assertTrue(ReputationService._circle_collection_proven(frozen, "8433", "autohome"))
        zero, _ = AutohomeReputationAdapter.parse_forum_count(
            source.replace("7083", "0").encode(), url, target
        )
        self.assertEqual(zero, "0")
        rounded_raw, rounded_proof = AutohomeReputationAdapter.parse_forum_count(source.replace("7083", "1.6万").encode(), url, target)
        self.assertEqual((rounded_raw, rounded_proof["visible_count"], rounded_proof["quantity_kind"]), ("1.6万", 16000, "rounded"))
        self.assertEqual(_change({**metric("1.6万", "1000"), "quantity_kind": "rounded"}), "按显示值增加(+1000)")
        with self.assertRaises(ReputationAdapterError):
            AutohomeReputationAdapter.parse_forum_count(
                source.replace('data-bbsid="8433"', 'data-bbsid="7853"').encode(), url, target
            )

    def test_selected_txt_matches_payload_and_keeps_original_download(self):
        templates = render_report_templates(self.run, [row(score=metric())])
        with TemporaryDirectory() as tmp:
            original = Path(tmp) / "original.txt"
            original.write_bytes("旧存档含原始汇报\n".encode())
            service = Mock()
            service.get_run.return_value = {"number": "RP-TEST", "report_templates": templates}
            service.get_file.return_value = original
            app = FastAPI()
            app.state.container = SimpleNamespace(reputation=service)
            app.add_exception_handler(DomainError, domain_error_handler)
            app.include_router(build_router("/api/v1", internal=False))
            with TestClient(app) as client:
                for template in templates:
                    response = client.get(
                        "/api/v1/reputation/runs/test/report.txt",
                        params={"template": template["id"]},
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.content, template["text"].encode())
                self.assertEqual(
                    client.get("/api/v1/reputation/runs/test/report.txt").content,
                    original.read_bytes(),
                )
                self.assertEqual(
                    client.get(
                        "/api/v1/reputation/runs/test/report.txt?template=unknown"
                    ).status_code,
                    422,
                )
                service.get_run.return_value["report_templates"] = []
                self.assertEqual(
                    client.get(
                        "/api/v1/reputation/runs/test/report.txt?template=vehicle_detail"
                    ).status_code,
                    409,
                )
            self.assertEqual(original.read_bytes(), "旧存档含原始汇报\n".encode())


if __name__ == "__main__":
    unittest.main()
