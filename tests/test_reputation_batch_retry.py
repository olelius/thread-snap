"""正式巡检统一轮次的最小数据库/协调器组合验证，不访问真实平台。"""
import json
import unittest
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select

from tests.test_reputation import OfficialFakeAdapter, OfficialReputationLifecycleTest
from threadsnap.models import (
    PlatformConfig,
    ReputationResult,
    ReputationRun,
    ReputationScopeDraft,
    ReputationScopeVersion,
)
from threadsnap.reputation_adapter import ReputationAdapterError
from threadsnap.reputation_scheduler import ReputationCoordinator


class ReputationBatchRetryTest(unittest.TestCase):
    """复用既有隔离SQLite/FastAPI夹具，只运行当前重试路径。"""

    def setUp(self):
        self.fixture = OfficialReputationLifecycleTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.service = self.fixture.service

    def queue(self):
        """经正式日程生成真实领域对象，不直接伪造批次。"""
        outcome = self.service.check_schedule(self.fixture._at('2030-01-02', '10:00'))
        return outcome['queued_run_ids'][0]

    def test_cross_platform_waves_cover_all_recoverable_errors_and_preserve_success(self):
        """全平台首轮屏障、广义错误、缺证据、最多四次及终态汇报一起验证。"""
        service = self.service
        with service.sessions.begin() as db:
            draft = db.get(ReputationScopeDraft, 'current')
            version = db.get(ReputationScopeVersion, draft.published_version_id)
            snapshot = json.loads(json.dumps(version.snapshot))
            snapshot['vehicles'] = snapshot['vehicles'][:8]
            for i, vehicle in enumerate(snapshot['vehicles']):
                code = ('dongchedi', 'autohome', 'yiche')[i % 3]
                mapping = vehicle['mappings']['dongchedi']
                mapping['platform_url'] = (f'https://k.autohome.com.cn/{30000+i}/' if code == 'autohome'
                                          else f'https://dianping.yiche.com/fixture{i}/koubei/' if code == 'yiche'
                                          else mapping['platform_url'])
                vehicle['mappings'] = {code: mapping}
            version.snapshot = snapshot
            for code in ('dongchedi', 'autohome', 'yiche'):
                db.get(PlatformConfig, code).enabled = True
        counts = Counter()
        calls = []
        factory_options = []
        observed = []
        ids = [v['id'] for v in snapshot['vehicles']]
        run_id = self.queue()
        blocked = ids[6]

        class Adapter(OfficialFakeAdapter):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                factory_options.append(kwargs)

            def validate_sync(self, targets, output_dir, on_result=None):
                results = super().validate_sync(targets, output_dir)
                for i, target in enumerate(targets):
                    key = target.vehicle_id
                    counts[key] += 1
                    attempt = counts[key]
                    calls.append((key, attempt))
                    if attempt > 1:
                        # 所有平台的首轮已被处理，不是某平台提前重试。
                        if not all(counts[k] >= 1 for k in ids):
                            raise AssertionError('cross-platform first wave not completed')
                    if key == ids[1] and attempt == 1:
                        results[i] = TimeoutError('page operation timed out')
                    elif key == ids[2] and attempt < 3:
                        results[i] = ValueError('temporary malformed response')
                    elif key == ids[3] and attempt < 4:
                        results[i] = ReputationAdapterError('REPUTATION_METRIC_CONTRACT', '暂时缺字段')
                    elif key == ids[4] and attempt == 1:
                        results[i] = replace(results[i], metric_region_path=None)
                    elif key == ids[5]:
                        results[i] = RuntimeError('unknown transient error')
                    elif key == blocked:
                        results[i] = ReputationAdapterError('AUTH_REQUIRED', '需更新会话')
                    if on_result:
                        on_result(i, target, results[i])
                    current = service.get_run(run_id)
                    observed.append((current['status'], current['report_status'], current['completed_count']))
                return results

        service.adapter_factory = Adapter
        service.adapter_factories.update(autohome=Adapter, yiche=Adapter)
        container = self.fixture.client.app.state.container
        for code in ('autohome', 'yiche'):
            container.session_store.import_state(code, {'cookies': [{'name':'fixture','value':'state','domain':'.example.com','path':'/'}]})
        # 平台启用是正式调度的前置；queue之前的版本包括既有默认平台配置。
        ReputationCoordinator(service).tick(self.fixture._at('2030-01-02', '10:00'))
        # 实际协调器完成采集及汇报，再从既有HTTP API核对分母与终态。
        response = self.fixture.client.get(f'/api/v1/reputation/runs/{run_id}')
        self.assertEqual(200, response.status_code)
        finished = response.json()
        self.assertEqual([1, 2, 3, 4, 2, 4, 1, 1], [counts[k] for k in ids])
        self.assertEqual(('partial_success', 6, 2), (finished['status'], finished['completed_count'], finished['failed_count']))
        self.assertTrue(all(status == 'running' and report == 'waiting' for status, report, _ in observed))
        self.assertTrue(all(o['timeout_seconds'] == 30 and o['concurrency'] == 2 for o in factory_options))
        self.assertEqual(1, len({id(o['global_limiter']) for o in factory_options}))
        before = json.dumps(finished['results'], sort_keys=True)
        self.assertEqual(before, json.dumps(service.execute_run(run_id)['results'], sort_keys=True))
        report = service.generate_report(run_id)
        self.assertEqual('success', report['report_status'])
        self.assertTrue(report['downloads']['xlsx'])
        artifact = Path('artifacts/runtime/reputation-retry/combined-result.json')
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps({
            'entry': 'ReputationCoordinator.tick -> execute_run -> GET run -> report',
            'scope': 'isolated SQLite; no production platform or AI calls',
            'expected_attempts': [1, 2, 3, 4, 2, 4, 1, 1],
            'actual_attempts': [counts[k] for k in ids],
            'completed': finished['completed_count'], 'failed': finished['failed_count'],
            'report_status': report['report_status'], 'terminal_reentry_unchanged': True,
            'calls': calls,
        }, ensure_ascii=False, indent=2), encoding='utf-8')

    def test_restart_reuses_committed_success_attempt_counts_and_original_budget(self):
        """中断恢复不重采成功项，已完成失败尝试不清零，耗尽后无需第五次。"""
        run_id = self.queue()
        OfficialFakeAdapter.failures = {'official-01'}
        original = self.service._persist_official_result
        stopped = False
        def stop_after_first(*args, **kwargs):
            nonlocal stopped
            result = original(*args, **kwargs)
            if not kwargs.get('pending_retry') and not stopped:
                stopped = True
                raise KeyboardInterrupt('simulate process interruption')
            return result
        with patch.object(self.service, '_persist_official_result', side_effect=stop_after_first):
            with self.assertRaises(KeyboardInterrupt):
                self.service.execute_run(run_id)
        with self.service.sessions() as db:
            committed = {r.vehicle_id: r.id for r in db.scalars(select(ReputationResult).where(ReputationResult.run_id == run_id, ReputationResult.status == 'success'))}
        self.assertTrue(committed)
        self.service.recover_interrupted()
        called = []
        class CountingAdapter(OfficialFakeAdapter):
            def validate_sync(self, targets, output_dir, on_result=None):
                called.extend(t.vehicle_id for t in targets)
                return super().validate_sync(targets, output_dir, on_result)
        self.service.adapter_factory = CountingAdapter
        finished = self.service.execute_run(run_id)
        self.assertTrue(set(committed).isdisjoint(called))
        failed = next(r for r in finished['results'] if r['vehicle_id'] == 'official-01')
        self.assertEqual(4, failed['attempt_count'])
        self.assertEqual(3, called.count('official-01'))

    def test_expired_batch_never_starts_new_attempt(self):
        """恢复已经超出45分钟预算的批次时不发起新平台访问。"""
        run_id = self.queue()
        from datetime import datetime, timezone
        with self.service.sessions.begin() as db:
            run = db.get(ReputationRun, run_id)
            run.started_at = datetime.now(timezone.utc) - timedelta(minutes=46)
        with patch.object(self.service, 'adapter_factory') as factory:
            finished = self.service.execute_run(run_id)
        factory.assert_not_called()
        self.assertEqual('failed', finished['status'])
        self.assertEqual(27, finished['failed_count'])
        self.assertEqual({'REPUTATION_BATCH_TIMEOUT'}, {r['error_code'] for r in finished['results']})


if __name__ == '__main__':
    unittest.main()
