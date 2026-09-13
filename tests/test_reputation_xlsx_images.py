"""口碑Excel独立原图、比例、留白及缺图回归。"""

from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from openpyxl import load_workbook
from openpyxl.utils.units import EMU_to_pixels, points_to_pixels
from PIL import Image

from threadsnap.reputation import ReputationService


class ReputationXlsxImagesTest(unittest.TestCase):
    """只覆盖导出器，不重跑采集、调度或映射验证。"""

    def test_original_bytes_separate_anchors_and_missing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = SimpleNamespace(
                id="frozen-run", planned_date="2026-09-13",
                platform_codes=["dongchedi", "autohome", "yiche"],
            )
            results, evidence, originals = [], {}, []
            sizes = [(3000, 450), (1280, 1600), (160, 80)]
            for row in range(2):
                for index, code in enumerate(run.platform_codes):
                    identity = f"vehicle-{row}-{code}"
                    results.append(SimpleNamespace(
                        id=identity, vehicle_id=f"vehicle-{row}", platform_code=code,
                        role="focus", series_name="车系", vehicle_name=f"车型{row}",
                        evidence_required=code != "yiche", error_message=None,
                        metrics={"score": {"raw": "4.50", "tone": "positive"}},
                    ))
                    if row == 1 and code != "dongchedi":
                        continue
                    path = root / f"{identity}.png"
                    Image.new("RGB", sizes[index], (index * 80, 100, row * 100)).save(path)
                    content = path.read_bytes()
                    evidence[identity] = SimpleNamespace(
                        id=f"evidence-{identity}", metric_region_path=str(path),
                        metric_region_sha256=hashlib.sha256(content).hexdigest(),
                    )
                    if row == 1:
                        # 存在证据记录但磁盘内容改变，必须给出文字而不是嵌入坏图。
                        path.write_bytes(b"corrupt")
                    else:
                        originals.append(content)
            target = root / "images.xlsx"
            service = object.__new__(ReputationService)
            service._create_xlsx(run, results, evidence, target)
            with zipfile.ZipFile(target) as archive:
                embedded = [archive.read(name) for name in archive.namelist()
                            if name.startswith("xl/media/")]
                self.assertCountEqual(originals, embedded)
                self.assertEqual(sizes, [Image.open(io.BytesIO(data)).size for data in embedded])
            sheet = load_workbook(target).active
            self.assertEqual(3, len(sheet._images))
            self.assertEqual({20, 21, 22}, {item.anchor._from.col for item in sheet._images})
            for picture, size in zip(sheet._images, sizes, strict=True):
                anchor = picture.anchor
                width, height = anchor.ext.cx / 9525, anchor.ext.cy / 9525
                self.assertAlmostEqual(size[0] / size[1], width / height, places=5)
                self.assertLessEqual(width, 552)
                self.assertLessEqual(height, 480)
                self.assertEqual(12, EMU_to_pixels(anchor._from.colOff))
                self.assertEqual(12, EMU_to_pixels(anchor._from.rowOff))
                self.assertGreaterEqual(points_to_pixels(sheet.row_dimensions[2].height), height + 24)
                self.assertLessEqual(sheet.row_dimensions[2].height, 409)
            self.assertEqual("4.50", sheet["E2"].value)
            self.assertEqual("00E2F0D9", sheet["E2"].fill.fgColor.rgb)
            self.assertIn("校验失败", sheet["T3"].value)
            self.assertIn("证据缺失", sheet["V3"].value)
            self.assertEqual("本项未要求截图", sheet["W3"].value)
            self.assertIn("3000×450", sheet["U2"].comment.text)
            self.assertFalse((root / "xlsx-previews").exists())

