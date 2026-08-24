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
from sqlalchemy import func, select

from threadsnap.app import create_app
from threadsnap.config import Settings
from threadsnap.models import ExtractionRun


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
        self.assertEqual(capability["real_adapter_status"], "not_configured")

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
                client.get("/api/v1/reputation/capabilities").json()[
                    "reputation_synthetic_runs"
                ]
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
            metric["tone"]
            for result in daily["results"]
            for metric in result["metrics"].values()
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
        fills = {sheet.cell(row, column).fill.fgColor.rgb for row in range(2, 29) for column in (5, 6, 7)}
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
                        "platform_vehicle_id": f"platform-{index + 1:02d}",
                        "platform_url": f"https://example.test/{index + 1}",
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


if __name__ == "__main__":
    unittest.main()
