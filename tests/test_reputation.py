"""口碑巡检独立领域、合成验收运行与交付物测试。"""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image
from sqlalchemy import func, select

from threadsnap.app import create_app
from threadsnap.config import Settings
from threadsnap.models import ExtractionRun
from threadsnap.reputation_dongchedi import ReputationPageResult, normalize_series_url


class ReputationInspectionTest(unittest.TestCase):
    """使用三因子隔离测试配置验证口碑巡检完整纵切。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.settings = Settings(
            database_url=f"sqlite:///{(self.root / 'test.db').as_posix()}",
            data_dir=self.root / "data",
            start_background_services=False,
            runtime_mode="test",
            enable_reputation_synthetic_runs=True,
            reputation_test_database=True,
        )
        self.client_context = TestClient(create_app(self.settings))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def create_run(self, scenario_id: str) -> dict:
        """触发一个固定场景并返回运行详情。"""

        response = self.client.post(
            "/api/v1/reputation/test-runs",
            json={"scenario_id": scenario_id},
        )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def test_synthetic_capability_requires_all_three_guards(self) -> None:
        capability = self.client.get("/api/v1/reputation/capabilities").json()
        self.assertTrue(capability["reputation_synthetic_runs"])
        self.assertEqual(len(capability["scenarios"]), 3)
        self.assertEqual(capability["real_adapter_status"], "available")

        disabled = Settings(
            database_url=f"sqlite:///{(self.root / 'production.db').as_posix()}",
            data_dir=self.root / "production-data",
            start_background_services=False,
            runtime_mode="production",
            enable_reputation_synthetic_runs=True,
            reputation_test_database=True,
        )
        with TestClient(create_app(disabled)) as client:
            self.assertFalse(
                client.get("/api/v1/reputation/capabilities").json()["reputation_synthetic_runs"]
            )
            response = client.post(
                "/api/v1/reputation/test-runs",
                json={"scenario_id": "daily_mixed_changes"},
            )
            self.assertEqual(response.status_code, 404)

    def test_three_scenarios_preserve_counts_colors_and_extraction_domain(self) -> None:
        baseline = self.create_run("baseline_initialization")
        daily = self.create_run("daily_mixed_changes")
        month_end = self.create_run("month_end_mixed_changes")

        self.assertEqual(len(baseline["results"]), 27)
        self.assertEqual(baseline["required_evidence_count"], 27)
        self.assertEqual(daily["required_evidence_count"], 6)
        self.assertEqual(month_end["required_evidence_count"], 27)
        self.assertEqual(daily["status"], "partial_success")
        tones = {
            metric["tone"] for result in daily["results"] for metric in result["metrics"].values()
        }
        self.assertEqual(tones, {"positive", "negative", "neutral"})
        self.assertEqual(
            daily["results"][0]["metrics"]["rank"]["tone"],
            "positive",
            "排名数值下降代表名次上升，应按正向变化着色。",
        )

        with self.client.app.state.container.sessions() as db:
            extraction_count = db.scalar(select(func.count()).select_from(ExtractionRun))
        self.assertEqual(extraction_count, 0)

    def test_txt_xlsx_and_evidence_zip_are_real_traceable_artifacts(self) -> None:
        run = self.create_run("daily_mixed_changes")
        report = self.client.get(run["downloads"]["txt"])
        self.assertEqual(report.status_code, 200)
        self.assertIn("口碑分及排名变动如下", report.content.decode("utf-8"))
        self.assertNotIn("#E2F0D9", report.content.decode("utf-8"))

        xlsx = self.client.get(run["downloads"]["xlsx"])
        xlsx_path = self.root / "result.xlsx"
        xlsx_path.write_bytes(xlsx.content)
        workbook = load_workbook(xlsx_path)
        sheet = workbook["口碑巡检"]
        self.assertEqual(sheet.max_row, 28)
        fills = {
            sheet.cell(row, column).fill.fgColor.rgb for row in range(2, 29) for column in (5, 6, 7)
        }
        self.assertTrue(any(str(value).endswith("E2F0D9") for value in fills))
        self.assertTrue(any(str(value).endswith("F4CCCC") for value in fills))
        self.assertGreater(len(sheet._images), 0)

        archive = self.client.get(run["downloads"]["evidence_zip"])
        zip_path = self.root / "evidence.zip"
        zip_path.write_bytes(archive.content)
        with zipfile.ZipFile(zip_path) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            checksums = bundle.read("SHA256SUMS").decode("utf-8").splitlines()
            self.assertEqual(len(manifest["items"]), 6)
            self.assertEqual(len(checksums), 12)
            digest, name = checksums[0].split("  ", 1)
            self.assertEqual(hashlib.sha256(bundle.read(name)).hexdigest(), digest)

    def test_scope_initialization_and_atomic_mapping_preview(self) -> None:
        csv_path = self.root / "scope.csv"
        headers = [
            "schema_version",
            "seed_key",
            "series_name",
            "vehicle_name",
            "role",
            "role_order",
            "platform_code",
            "platform_vehicle_id",
            "platform_url",
            "platform_display_name",
        ]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for index in range(27):
                focus = index < 14
                order = index + 1 if focus else index - 13
                writer.writerow(
                    {
                        "schema_version": "reputation-scope-v1",
                        "seed_key": f"vehicle-{index + 1:02d}",
                        "series_name": f"车系{index // 5 + 1}",
                        "vehicle_name": f"车型{index + 1:02d}",
                        "role": "focus" if focus else "competitor",
                        "role_order": order,
                        "platform_code": "dongchedi",
                        "platform_vehicle_id": str(10000 + index),
                        "platform_url": (
                            f"https://www.dongchedi.com/auto/series/score/{10000 + index}-x-x-x-x-x"
                        ),
                        "platform_display_name": f"页面车型{index + 1:02d}",
                    }
                )
        scope = self.client.app.state.container.reputation.initialize_scope_csv(csv_path)
        self.assertEqual(len(scope["vehicles"]), 27)
        preview = self.client.post(
            "/api/v1/reputation/scope/mappings/preview",
            json={
                "revision": scope["revision"],
                "platform_code": "dongchedi",
                "rows": [
                    {
                        "vehicle_id": "vehicle-01",
                        "platform_vehicle_id": "duplicate",
                        "platform_url": "bad-url",
                        "platform_display_name": "错误样例",
                    },
                    {
                        "vehicle_id": "vehicle-01",
                        "platform_vehicle_id": "duplicate",
                        "platform_url": "https://example.test/ok",
                        "platform_display_name": "重复样例",
                    },
                ],
            },
        ).json()
        self.assertFalse(preview["valid"])
        before = self.client.get("/api/v1/reputation/scope").json()
        save = self.client.put(
            "/api/v1/reputation/scope/mappings",
            json={
                "revision": scope["revision"],
                "platform_code": "dongchedi",
                "rows": [
                    {
                        "vehicle_id": "vehicle-01",
                        "platform_vehicle_id": "duplicate",
                        "platform_url": "bad-url",
                        "platform_display_name": "错误样例",
                    }
                ],
            },
        )
        self.assertEqual(save.status_code, 400)
        after = self.client.get("/api/v1/reputation/scope").json()
        self.assertEqual(before["revision"], after["revision"])

    def test_real_mapping_validation_binds_live_metrics_and_evidence(self) -> None:
        csv_path = self.root / "real-scope.csv"
        headers = [
            "schema_version",
            "seed_key",
            "series_name",
            "vehicle_name",
            "role",
            "role_order",
            "platform_code",
            "platform_vehicle_id",
            "platform_url",
            "platform_display_name",
        ]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for index in range(27):
                focus = index < 14
                platform_id = str(20000 + index)
                writer.writerow(
                    {
                        "schema_version": "reputation-scope-v1",
                        "seed_key": f"real-{index + 1:02d}",
                        "series_name": f"车系{index // 5 + 1}",
                        "vehicle_name": f"车型{index + 1:02d}",
                        "role": "focus" if focus else "competitor",
                        "role_order": index + 1 if focus else index - 13,
                        "platform_code": "dongchedi",
                        "platform_vehicle_id": platform_id,
                        "platform_url": (
                            f"https://www.dongchedi.com/auto/series/score/{platform_id}-x-x-x-x-x"
                        ),
                        "platform_display_name": f"页面车型{index + 1:02d}",
                    }
                )
        scope = self.client.app.state.container.reputation.initialize_scope_csv(csv_path)
        self.client.app.state.container.session_store.import_state(
            "dongchedi",
            {
                "cookies": [
                    {
                        "name": "fixture",
                        "value": "session",
                        "domain": ".dongchedi.com",
                        "path": "/",
                    }
                ]
            },
        )

        class FakeAdapter:
            def __init__(self, *_args, **_kwargs):
                pass

            def validate_sync(self, targets, output_dir):
                output_dir.mkdir(parents=True)
                values = []
                for index, target in enumerate(targets):
                    target_dir = output_dir / target.vehicle_id
                    target_dir.mkdir()
                    full = target_dir / "full.png"
                    metric = target_dir / "metric.png"
                    Image.new("RGB", (800, 1200), "white").save(full)
                    Image.new("RGB", (600, 240), "white").save(metric)
                    values.append(
                        ReputationPageResult(
                            vehicle_id=target.vehicle_id,
                            platform_vehicle_id=target.platform_vehicle_id,
                            mapping_hash=target.mapping_hash,
                            final_url=target.platform_url,
                            actual_name=target.platform_display_name,
                            score_raw="3.80",
                            rank_raw="4",
                            volume_raw=str(500 + index),
                            rank_scope="同级车评分",
                            measurements=[{"stable": True}] * 3,
                            full_page_path=full,
                            metric_region_path=metric,
                            full_page_sha256=hashlib.sha256(full.read_bytes()).hexdigest(),
                            metric_region_sha256=hashlib.sha256(metric.read_bytes()).hexdigest(),
                            width=800,
                            height=1200,
                            metric_rect={"x": 0, "y": 0, "width": 600, "height": 240},
                            duration_ms=100,
                        )
                    )
                return values

        self.client.app.state.container.reputation.adapter_factory = FakeAdapter
        response = self.client.post(
            "/api/v1/reputation/scope/mapping-validations",
            json={"revision": scope["revision"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        validation = response.json()
        self.assertEqual(validation["succeeded_count"], 27)
        self.assertEqual(validation["failed_count"], 0)
        verified = validation["scope"]["vehicles"]
        self.assertTrue(
            all(row["mappings"]["dongchedi"]["validation_status"] == "verified" for row in verified)
        )
        self.assertEqual(verified[0]["mappings"]["dongchedi"]["latest_metrics"]["volume"], "500")
        evidence = self.client.get(validation["attempts"][0]["metric_region_url"])
        self.assertEqual(evidence.status_code, 200)
        self.assertEqual(evidence.headers["content-type"], "image/png")
        publish = self.client.post(
            "/api/v1/reputation/scope/publish",
            json={
                "revision": validation["scope"]["revision"],
                "initial_review_acknowledged": True,
            },
        )
        self.assertEqual(publish.status_code, 200, publish.text)
        self.assertEqual(publish.json()["published_version"]["version"], 1)
        acceptance = self.client.app.state.container.reputation.create_real_acceptance(
            [validation["id"]]
        )
        self.assertEqual(acceptance["source_type"], "real_acceptance")
        self.assertEqual(acceptance["status"], "success")
        self.assertEqual(len(acceptance["results"]), 27)
        self.assertEqual(acceptance["complete_evidence_count"], 27)

    def test_dongchedi_reputation_url_requires_matching_stable_id(self) -> None:
        url = "https://www.dongchedi.com/auto/series/score/24729-x-x-x-x-x"
        self.assertEqual(normalize_series_url(url, "24729"), url)
        with self.assertRaisesRegex(Exception, "车型ID"):
            normalize_series_url(url, "10170")


if __name__ == "__main__":
    unittest.main()
