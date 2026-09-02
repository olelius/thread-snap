"""调用预构建 Node Worker，把当次 TDC 编译为自研 IR 并执行。"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TdcRuntimeResult:
    """TDC 自研运行时生成的提交材料及结构摘要。"""

    collect: str
    eks: str
    opcode_count: int
    handler_count: int


class TdcRuntimeError(RuntimeError):
    """TDC 解析、IR 编译或环境运行失败。"""


class TdcRuntime:
    """平台无关的腾讯 TDC 运行时入口。"""

    _STAGES = (
        "normalize-tdc-payload",
        "deobfuscate-tdc-interpreter",
        "catalog-tdc-primitives",
        "extend-tdc-handler-ir",
        "build-tdc-ir-runtime",
        "run-node-tdc-standalone",
    )

    def __init__(self, *, node_binary: str = "node", timeout_seconds: float = 15.0) -> None:
        self.node_binary = node_binary
        self.timeout_seconds = timeout_seconds
        self.root = Path(__file__).resolve().parent / "js"

    def required_asset_paths(self) -> tuple[Path, ...]:
        """返回部署验证所需的IR基线和全部预构建入口。"""

        return (self.root / "tdc-handler-ir-v2.json",) + tuple(
            self.root / "dist" / f"{stage}.js" for stage in self._STAGES
        )

    def _run(self, stage: str, *args: Path | str) -> None:
        script = self.root / "dist" / f"{stage}.js"
        if not script.is_file():
            raise TdcRuntimeError(f"腾讯 TDC 运行时缺少构建产物：{stage}")
        try:
            subprocess.run(
                [self.node_binary, str(script), *(str(value) for value in args)],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                cwd=self.root,
            )
        except FileNotFoundError as exc:
            raise TdcRuntimeError("腾讯 TDC 运行时没有找到 Node.js。") from exc
        except subprocess.TimeoutExpired as exc:
            raise TdcRuntimeError(f"腾讯 TDC 阶段超时：{stage}") from exc
        except subprocess.CalledProcessError as exc:
            lines = (exc.stderr or exc.stdout or type(exc).__name__).strip().splitlines()
            detail = next(
                (line.strip() for line in lines if line.strip().startswith(("Error:", "TypeError:"))),
                lines[-1] if lines else type(exc).__name__,
            )
            raise TdcRuntimeError(f"腾讯 TDC 阶段失败：{stage}: {detail[:300]}") from exc

    def evaluate(self, tdc_source: bytes, *, drag_css_px: float, entry_url: str) -> TdcRuntimeResult:
        """只执行生成后的自研 VM；当次原始 TDC 仅作为解析输入。"""

        if shutil.which(self.node_binary) is None:
            raise TdcRuntimeError("腾讯 TDC 运行时没有找到 Node.js。")
        baseline = self.root / "tdc-handler-ir-v2.json"
        if not baseline.is_file():
            raise TdcRuntimeError("腾讯 TDC 运行时缺少 handler IR 基线。")
        with tempfile.TemporaryDirectory(prefix="threadsnap-tencent-tdc-") as temporary:
            work = Path(temporary)
            raw = work / "tdc.js"
            normalized = work / "tdc-normalized.js"
            interpreter = work / "tdc-interpreter.js"
            catalog = work / "tdc-catalog.json"
            extended = work / "tdc-handler-ir.json"
            runtime = work / "tdc-runtime.js"
            report = work / "tdc-runtime-report.json"
            raw_result = work / "tdc-runtime-result.json"
            raw.write_bytes(tdc_source)
            self._run(self._STAGES[0], raw, normalized)
            self._run(self._STAGES[1], normalized, interpreter)
            self._run(self._STAGES[2], interpreter, catalog)
            self._run(self._STAGES[3], baseline, catalog, "candidate", extended)
            self._run(self._STAGES[4], normalized, interpreter, extended, "candidate", runtime)
            self._run(
                self._STAGES[5], runtime, report, str(drag_css_px), raw_result, entry_url
            )
            runtime_result = json.loads(raw_result.read_text(encoding="utf-8"))
            runtime_report = json.loads(report.read_text(encoding="utf-8"))
            catalog_data = json.loads(catalog.read_text(encoding="utf-8"))
            extended_data = json.loads(extended.read_text(encoding="utf-8"))
            collect = runtime_result.get("secondData")
            info = runtime_result.get("info")
            eks = info.get("info") if isinstance(info, dict) else None
            if (
                not isinstance(collect, str)
                or not collect
                or not isinstance(eks, str)
                or not eks
                or runtime_report.get("executionError")
                or runtime_report.get("apiErrors")
            ):
                raise TdcRuntimeError("腾讯 TDC 自研 VM 输出门禁未通过。")
            return TdcRuntimeResult(
                collect=collect,
                eks=eks,
                opcode_count=int(catalog_data["opcodeCount"]),
                handler_count=int(extended_data["handlerCount"]),
            )
