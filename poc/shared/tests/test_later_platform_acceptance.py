"""后续平台验收入口的文件合同和 500/500 门禁测试。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

SHARED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHARED))

import later_platform_acceptance as acceptance  # noqa: E402


class FakeProvider:
    """只提供平台中立观察结果，不包含任何真实平台解析逻辑。"""

    platform_code = "autohome"
    adapter_version = "fake-1"

    def __init__(self, candidates: list[dict] | None = None):
        self.candidates = candidates or []

    def discover_sources(self, community_seeds: list[dict], evidence_dir: Path) -> list[dict]:
        records = []
        for seed_index, seed in enumerate(community_seeds):
            for list_order in sorted(acceptance.LIST_ORDERS):
                records.append(
                    {
                        "seed_identity": seed["seed_identity"],
                        "source_identity": f"source-{seed_index}-{list_order}",
                        "community_url": seed["community_url"],
                        "normalized_list_url": (
                            f"https://fixture.invalid/community/{seed_index}/{list_order}"
                        ),
                        "list_order": list_order,
                        "status": "verified",
                        "relation_evidence": {
                            "evidence_type": "fixture_navigation",
                            "confirmed_at": "2026-08-27T00:00:00+00:00",
                        },
                    }
                )
        return records

    def discover_candidates(
        self, sources: list[dict], *, access_mode: str, concurrency: int
    ) -> dict[str, list[dict]]:
        return {
            "candidates": self.candidates,
            "request_events": [
                {
                    "sequence": 1,
                    "stage": "discover",
                    "access_mode": access_mode,
                    "concurrency": concurrency,
                }
            ],
        }

    def run_acceptance(
        self,
        urls: list[str],
        *,
        manifest: dict,
        access_mode: str,
        concurrency: int,
    ) -> dict:
        records = [
            make_result(index, url, manifest["selected"][index]["platform_post_id"])
            for index, url in enumerate(urls)
        ]
        return {
            "results": records,
            "request_events": [
                {
                    "sequence": index + 1,
                    "url_sha256": record["url_sha256"],
                    "stage": "detail",
                    "response_class": "post",
                }
                for index, record in enumerate(records)
            ],
            "environment": {
                "engine": "fixture",
                "access_mode": access_mode,
                "concurrency": concurrency,
            },
        }


def make_sources(path: Path, *, access_mode: str = "anonymous") -> dict:
    document = {
        "schema_version": acceptance.SCHEMA_VERSION,
        "platform_code": "autohome",
        "generated_at": "2026-08-27T00:00:00+00:00",
        "git_commit": acceptance.current_git_commit(),
        "adapter_version": "fake-1",
        "harness_version": acceptance.HARNESS_VERSION,
        "access_mode": access_mode,
        "community_seed_count": 1,
        "relation_attempt_count": 2,
        "verified_source_count": 2,
        "sources": [
            {
                "platform_code": "autohome",
                "source_identity": "source-reply",
                "community_url": "https://fixture.invalid/community/1",
                "normalized_list_url": "https://fixture.invalid/community/1/reply",
                "list_order": "latest_reply",
                "status": "verified",
                "relation_evidence": {"evidence_type": "fixture"},
            },
            {
                "platform_code": "autohome",
                "source_identity": "source-publish",
                "community_url": "https://fixture.invalid/community/1",
                "normalized_list_url": "https://fixture.invalid/community/1/publish",
                "list_order": "latest_publish",
                "status": "verified",
                "relation_evidence": {"evidence_type": "fixture"},
            },
        ],
    }
    acceptance.write_json_new(path, document)
    return document


def make_candidate(index: int, *, source: str | None = None) -> dict:
    identity = source or ("source-reply" if index % 2 == 0 else "source-publish")
    list_order = "latest_reply" if identity == "source-reply" else "latest_publish"
    return {
        "platform_code": "autohome",
        "source_identity": identity,
        "source_memberships": [identity],
        "list_order": list_order,
        "source_position": index,
        "normalized_url": f"https://fixture.invalid/thread/{index:04d}",
        "platform_post_id": f"post-{index:04d}",
        "preflight_valid": True,
        "preflight_class": "post",
        "preflight_observed_post_id": f"post-{index:04d}",
        "adapter_version": "fake-1",
        "access_mode": "anonymous",
        "scenario_tags": [],
        "observed_facts": {"fixture_index": index},
        "evidence_refs": [f"fixture-{index}"],
        "confirmed_at": "2026-08-27T00:00:00+00:00",
    }


def make_candidates(path: Path, count: int, *, tags: bool = False) -> list[dict]:
    candidates = [make_candidate(index) for index in range(count)]
    if tags:
        for index, tag in enumerate(acceptance.SCENARIO_TAGS[:-1]):
            candidates[index]["scenario_tags"] = [tag]
    acceptance.write_jsonl_new(path, candidates)
    return candidates


def make_result(index: int, url: str, post_id: str) -> dict:
    return {
        "input_index": index,
        "url": url,
        "url_sha256": acceptance.sha256_bytes(url.encode()),
        "input_platform_post_id": post_id,
        "observed_platform_post_id": post_id,
        "post_id_matches": True,
        "body": f"正文 {index}",
        "image_urls": [],
        "video_urls": [],
        "comments": [],
        "comment_capture": "first_page",
        "comment_page_end": {"has_more": False, "cursor": None},
        "raw_status": {"fixture_status": "visible"},
        "normalized_status": "visible",
        "response_class": "post",
        "request_count": 2,
        "duration_ms": index + 1,
        "access_channel": "fixture",
        "recovery_count": 0,
        "request_event_refs": [index + 1],
        "contract_errors": [],
        "final_status": "valid",
    }


class SourceAndDiscoveryTests(unittest.TestCase):
    def test_sources_and_discovery_write_platform_neutral_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seeds = root / "seeds.json"
            seeds.write_text(
                json.dumps(
                    {
                        "community_seeds": [
                            {
                                "seed_identity": "seed-1",
                                "community_url": "https://fixture.invalid/c/1",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            sources = root / "sources.json"
            provider = FakeProvider()
            document = acceptance.create_sources(
                provider,
                platform_code="autohome",
                community_seed_file=seeds,
                output=sources,
                evidence_dir=root / "evidence",
                access_mode="anonymous",
            )
            self.assertEqual(2, document["relation_attempt_count"])
            provider.candidates = [
                {
                    **make_candidate(1, source="source-0-latest_publish"),
                    "source_memberships": ["source-0-latest_publish"],
                }
            ]
            report = acceptance.create_discovery(
                provider,
                platform_code="autohome",
                sources_path=sources,
                output=root / "candidates.jsonl",
                events_path=root / "events.jsonl",
                access_mode="anonymous",
                concurrency=1,
            )
            self.assertEqual(1, report["candidate_count"])
            self.assertEqual(1, report["request_event_count"])

    def test_sources_reject_duplicate_seed_order_even_when_total_count_is_two(self) -> None:
        class DuplicateProvider(FakeProvider):
            def discover_sources(
                self, community_seeds: list[dict], evidence_dir: Path
            ) -> list[dict]:
                rows = super().discover_sources(community_seeds, evidence_dir)
                rows[1] = dict(rows[0])
                rows[1]["source_identity"] = "different-identity"
                return rows

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seeds = root / "seeds.json"
            seeds.write_text(
                json.dumps(
                    {
                        "community_seeds": [
                            {
                                "seed_identity": "seed-1",
                                "community_url": "https://fixture.invalid/c/1",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(acceptance.AcceptanceError) as captured:
                acceptance.create_sources(
                    DuplicateProvider(),
                    platform_code="autohome",
                    community_seed_file=seeds,
                    output=root / "sources.json",
                    evidence_dir=root / "evidence",
                    access_mode="anonymous",
                )
            self.assertEqual("SOURCE_RELATION_KEY_INVALID", captured.exception.code)

    def test_missing_registry_has_stable_runtime_error(self) -> None:
        error = ModuleNotFoundError("fixture missing", name="threadsnap.collectors.registry")
        with patch.object(acceptance.importlib, "import_module", side_effect=error):
            with self.assertRaises(acceptance.AcceptanceError) as captured:
                acceptance.load_provider("autohome")
        self.assertEqual("PROVIDER_REGISTRY_UNAVAILABLE", captured.exception.code)


class FreezeAndSampleTests(unittest.TestCase):
    def freeze_fixture(
        self,
        root: Path,
        *,
        candidate_count: int = 501,
        selected_count: int = 500,
        tags: bool = False,
    ) -> tuple[Path, Path, Path, Path, dict]:
        sources = root / "sources.json"
        candidates = root / "candidates.jsonl"
        urls = root / "acceptance-urls.txt"
        manifest = root / "acceptance-manifest.json"
        make_sources(sources)
        make_candidates(candidates, candidate_count, tags=tags)
        document = acceptance.freeze_inputs(
            platform_code="autohome",
            candidates_path=candidates,
            sources_path=sources,
            output=urls,
            manifest_path=manifest,
            count=selected_count,
            seed="fixture-seed",
        )
        return sources, candidates, urls, manifest, document

    def test_freeze_deduplicates_stable_post_ids_and_writes_utf8_lf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = root / "sources.json"
            candidates_path = root / "candidates.jsonl"
            make_sources(sources)
            candidates = [make_candidate(index) for index in range(501)]
            duplicate = dict(candidates[0])
            duplicate["source_identity"] = "source-publish"
            duplicate["source_memberships"] = ["source-publish"]
            duplicate["list_order"] = "latest_publish"
            candidates.append(duplicate)
            acceptance.write_jsonl_new(candidates_path, candidates)
            manifest = acceptance.freeze_inputs(
                platform_code="autohome",
                candidates_path=candidates_path,
                sources_path=sources,
                output=root / "urls.txt",
                manifest_path=root / "manifest.json",
                count=500,
                seed="fixture-seed",
            )
            payload = (root / "urls.txt").read_bytes()
            self.assertNotIn(b"\r", payload)
            self.assertTrue(payload.endswith(b"\n"))
            self.assertEqual(500, len(payload.decode().splitlines()))
            self.assertEqual(501, manifest["eligible_count"])
            self.assertEqual(500, manifest["distinct_post_id_count"])
            self.assertEqual(
                acceptance.sha256_file(root / "urls.txt"),
                manifest["acceptance_urls_sha256"],
            )

    def test_freeze_blocks_when_valid_pool_is_below_500(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = root / "sources.json"
            candidates = root / "candidates.jsonl"
            make_sources(sources)
            make_candidates(candidates, 499)
            with self.assertRaises(acceptance.AcceptanceError) as captured:
                acceptance.freeze_inputs(
                    platform_code="autohome",
                    candidates_path=candidates,
                    sources_path=sources,
                    output=root / "urls.txt",
                    manifest_path=root / "manifest.json",
                    count=500,
                    seed="fixture-seed",
                )
            self.assertEqual("INSUFFICIENT_VALID_POOL", captured.exception.code)

    def test_function_and_cli_do_not_expose_a_smaller_formal_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = root / "sources.json"
            candidates = root / "candidates.jsonl"
            make_sources(sources)
            make_candidates(candidates, 500)
            with self.assertRaises(acceptance.AcceptanceError) as captured:
                acceptance.freeze_inputs(
                    platform_code="autohome",
                    candidates_path=candidates,
                    sources_path=sources,
                    output=root / "urls.txt",
                    manifest_path=root / "manifest.json",
                    count=499,
                    seed="fixture-seed",
                )
            self.assertEqual("FORMAL_COUNT_FIXED", captured.exception.code)
        parser = acceptance.build_parser()
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "freeze",
                    "--platform",
                    "autohome",
                    "--sources",
                    "sources.json",
                    "--candidates",
                    "candidates.jsonl",
                    "--output",
                    "urls.txt",
                    "--manifest",
                    "manifest.json",
                    "--seed",
                    "fixture",
                    "--count",
                    "1",
                ]
            )

    def test_verify_inputs_binds_access_mode_adapter_version_and_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources, _, urls, manifest, document = self.freeze_fixture(root)
            good = acceptance.verify_inputs(
                platform_code="autohome",
                sources_path=sources,
                urls_path=urls,
                manifest_path=manifest,
                expected_count=500,
                current_access_mode="anonymous",
                current_adapter_version="fake-1",
                current_git_commit_value=document["git_commit"],
            )
            self.assertTrue(good["passed"])
            changed = acceptance.verify_inputs(
                platform_code="autohome",
                sources_path=sources,
                urls_path=urls,
                manifest_path=manifest,
                expected_count=500,
                current_access_mode="authenticated",
                current_adapter_version="fake-2",
                current_git_commit_value="different",
            )
            self.assertFalse(changed["passed"])
            self.assertEqual(3, len(changed["errors"]))

    def test_functional_samples_close_all_19_scenarios_with_explicit_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, candidates, _, manifest, _ = self.freeze_fixture(root, tags=True)
            output = root / "functional-samples.jsonl"
            report = acceptance.create_functional_samples(
                platform_code="autohome",
                candidates_path=candidates,
                manifest_path=manifest,
                output=output,
            )
            records = acceptance.load_jsonl(output)
            self.assertEqual(19, report["scenario_count"])
            self.assertEqual(18, report["observed_count"])
            self.assertEqual(1, report["not_observed_count"])
            self.assertEqual(
                set(acceptance.SCENARIO_TAGS), {row["scenario_tag"] for row in records}
            )

    def test_functional_sample_requires_observed_facts_and_evidence_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, candidates, _, manifest, _ = self.freeze_fixture(root, tags=True)
            rows = acceptance.load_jsonl(candidates)
            rows[0]["observed_facts"] = {}
            candidates.unlink()
            acceptance.write_jsonl_new(candidates, rows)
            document = acceptance.load_json(manifest)
            document["candidates_sha256"] = acceptance.sha256_file(candidates)
            manifest.unlink()
            acceptance.write_json_new(manifest, document)
            with self.assertRaises(acceptance.AcceptanceError) as captured:
                acceptance.create_functional_samples(
                    platform_code="autohome",
                    candidates_path=candidates,
                    manifest_path=manifest,
                    output=root / "functional-samples.jsonl",
                )
            self.assertEqual("FUNCTIONAL_SAMPLE_EVIDENCE_MISSING", captured.exception.code)


class ResultContractTests(unittest.TestCase):
    def make_run_fixture(self, root: Path) -> tuple[Path, Path, Path, dict, list[dict]]:
        helper = FreezeAndSampleTests()
        sources, _, urls, manifest_path, manifest = helper.freeze_fixture(root)
        url_values = acceptance.read_urls_strict(urls, 500)
        records = [
            make_result(index, url, manifest["selected"][index]["platform_post_id"])
            for index, url in enumerate(url_values)
        ]
        return sources, urls, manifest_path, manifest, records

    def evaluate(self, root: Path, records: list[dict]) -> dict:
        _, urls, _, manifest, _ = self.make_run_fixture(root)
        return acceptance.evaluate_results(
            platform_code="autohome",
            urls=acceptance.read_urls_strict(urls, 500),
            manifest=manifest,
            records=records,
            request_events=[],
            wall_seconds=10,
        )

    def test_500_unique_terminal_results_accept_media_comments_and_unknown_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, urls, _, manifest, records = self.make_run_fixture(root)
            records[0]["body"] = ""
            records[0]["image_urls"] = ["https://media.fixture.invalid/1.jpg"]
            records[1]["comments"] = [{"comment_id": str(index)} for index in range(10)]
            records[1]["comment_page_end"] = {"has_more": True, "cursor": "next"}
            records[2]["normalized_status"] = "unknown"
            records[2]["raw_status"] = {"evidence": "insufficient"}
            summary = acceptance.evaluate_results(
                platform_code="autohome",
                urls=acceptance.read_urls_strict(urls, 500),
                manifest=manifest,
                records=records,
                request_events=[],
                wall_seconds=10,
            )
            self.assertTrue(summary["passed"])
            self.assertEqual(500, summary["unique_terminal_count"])
            self.assertEqual(500, summary["valid_count"])

    def test_duplicate_result_also_reports_missing_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, urls, _, manifest, records = self.make_run_fixture(root)
            records[-1] = dict(records[0])
            summary = acceptance.evaluate_results(
                platform_code="autohome",
                urls=acceptance.read_urls_strict(urls, 500),
                manifest=manifest,
                records=records,
                request_events=[],
                wall_seconds=10,
            )
            self.assertFalse(summary["passed"])
            self.assertEqual(1, summary["duplicate_result_count"])
            self.assertEqual(1, summary["missing_result_count"])

    def test_comment_termination_does_not_invalidate_post(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, urls, _, manifest, records = self.make_run_fixture(root)
            records[0]["comment_page_end"] = {"has_more": True, "cursor": None}
            summary = acceptance.evaluate_results(
                platform_code="autohome",
                urls=acceptance.read_urls_strict(urls, 500),
                manifest=manifest,
                records=records,
                request_events=[],
                wall_seconds=10,
            )
            self.assertTrue(summary["passed"])
            self.assertEqual(500, summary["valid_count"])

    def test_body_or_media_is_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, urls, _, manifest, records = self.make_run_fixture(root)
            records[0]["body"] = ""
            records[0]["final_status"] = "invalid"
            summary = acceptance.evaluate_results(
                platform_code="autohome",
                urls=acceptance.read_urls_strict(urls, 500),
                manifest=manifest,
                records=records,
                request_events=[],
                wall_seconds=10,
            )
            self.assertFalse(summary["passed"])
            self.assertEqual(1, summary["failure_category_counts"]["content_missing"])

    def test_control_response_is_invalid_and_counted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, urls, _, manifest, records = self.make_run_fixture(root)
            records[0]["response_class"] = "captcha"
            records[0]["final_status"] = "invalid"
            summary = acceptance.evaluate_results(
                platform_code="autohome",
                urls=acceptance.read_urls_strict(urls, 500),
                manifest=manifest,
                records=records,
                request_events=[],
                wall_seconds=10,
            )
            self.assertFalse(summary["passed"])
            self.assertEqual(1, summary["unrecovered_control_count"])
            self.assertEqual(1, summary["response_class_counts"]["captcha"])


class RunArtifactTests(unittest.TestCase):
    def test_fake_provider_run_and_read_only_verifier_pass_500(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources, candidates, urls, manifest_path, _ = FreezeAndSampleTests().freeze_fixture(
                root, tags=True
            )
            samples = root / "functional-samples.jsonl"
            acceptance.create_functional_samples(
                platform_code="autohome",
                candidates_path=candidates,
                manifest_path=manifest_path,
                output=samples,
            )
            result_dir = root / "result"
            summary = acceptance.create_run(
                FakeProvider(),
                platform_code="autohome",
                sources_path=sources,
                urls_path=urls,
                manifest_path=manifest_path,
                functional_samples_path=samples,
                output_dir=result_dir,
                concurrency=2,
            )
            self.assertTrue(summary["passed"])
            report = acceptance.verify_run(
                platform_code="autohome",
                sources_path=sources,
                urls_path=urls,
                manifest_path=manifest_path,
                functional_samples_path=samples,
                result_dir=result_dir,
                expected_count=500,
                current_access_mode="anonymous",
                current_adapter_version="fake-1",
                current_git_commit_value=acceptance.current_git_commit(),
            )
            self.assertTrue(report["passed"], report["errors"][:5])
            self.assertEqual(500, report["valid_count"])

    def test_sha256sums_tampering_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources, candidates, urls, manifest_path, _ = FreezeAndSampleTests().freeze_fixture(
                root, tags=True
            )
            samples = root / "functional-samples.jsonl"
            acceptance.create_functional_samples(
                platform_code="autohome",
                candidates_path=candidates,
                manifest_path=manifest_path,
                output=samples,
            )
            result_dir = root / "result"
            acceptance.create_run(
                FakeProvider(),
                platform_code="autohome",
                sources_path=sources,
                urls_path=urls,
                manifest_path=manifest_path,
                functional_samples_path=samples,
                output_dir=result_dir,
                concurrency=1,
            )
            with (result_dir / "run.log").open("a", encoding="utf-8") as stream:
                stream.write("tampered=true\n")
            report = acceptance.verify_run(
                platform_code="autohome",
                sources_path=sources,
                urls_path=urls,
                manifest_path=manifest_path,
                functional_samples_path=samples,
                result_dir=result_dir,
                expected_count=500,
            )
            self.assertFalse(report["passed"])
            self.assertIn("checksum_mismatch:run.log", report["errors"])


if __name__ == "__main__":
    unittest.main()
