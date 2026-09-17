"""局部布局失败保留可靠指标，同时映射验证继续要求完整证据。"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.test_reputation import OfficialReputationLifecycleTest
from threadsnap.reputation_adapter import ReputationAdapterError, ReputationMappingTarget
from threadsnap.reputation_autohome import AutohomeReputationAdapter
from threadsnap.reputation_registry import REPUTATION_PLATFORMS


class LayoutEvidenceContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_layout_only_failure_preserves_metrics_but_not_verified_mapping(self):
        """真实适配器返回部分结果→巡检持久化保留指标→映射验证仍失败。"""
        fixture=OfficialReputationLifecycleTest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        service=fixture.service
        run_id=service.check_schedule(fixture._at('2030-01-02','10:00'))['queued_run_ids'][0]
        vehicle=service.get_scope()['vehicles'][0]
        target=ReputationMappingTarget(vehicle['id'],'7711','https://k.autohome.com.cn/7711/','页面车型','a'*64)
        page=SimpleNamespace(url=target.platform_url,set_default_timeout=lambda _:None,
                             goto=AsyncMock(return_value=SimpleNamespace(status=200)),wait_for_selector=AsyncMock())
        context=SimpleNamespace(new_page=AsyncMock(return_value=page),close=AsyncMock(),request=SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(ok=True,status=200,json=AsyncMock(return_value={
                'result':{'seriesid':'7711','seriesname':'页面车型','average':'4.25','averagenum':16,'rowcount':20}
            })))
        ))
        browser=SimpleNamespace(new_context=AsyncMock(return_value=context))
        measurement={'actual_name':'页面车型','score':'4.25','rank':None,'volume':None,'rect':{'x':0,'y':0,'width':200,'height':100}}
        error=ReputationAdapterError('REPUTATION_PAGE_UNSTABLE','截图边界持续变化。',retryable=True)
        error.measurements=[measurement]*3
        error.metrics_stable=True
        root=fixture.root/'layout'
        root.mkdir()
        with patch('threadsnap.reputation_autohome.stable_measure',AsyncMock(side_effect=error)):
            result=await AutohomeReputationAdapter(None)._visit(browser,target,root)
        self.assertEqual('4.25',result.score_raw)
        self.assertEqual('16',result.volume_raw)
        self.assertIsNone(result.metric_region_path)
        self.assertEqual('REPUTATION_PAGE_UNSTABLE',result.evidence_error_code)
        service._persist_official_result(run_id,'autohome',target,vehicle,None,result,4,1)
        row=next(r for r in service.get_run(run_id)['results'] if r['platform_code']=='autohome')
        self.assertEqual('partial_success',row['status'])
        self.assertEqual('4.25',row['metrics']['score']['value'])
        self.assertEqual('REPUTATION_PAGE_UNSTABLE',row['error_code'])
        from datetime import datetime, timezone
        attempt=service._validation_attempt_record('sample',target,1,result,datetime.now(timezone.utc),REPUTATION_PLATFORMS['autohome'])
        self.assertEqual('failed',attempt.status)
        self.assertEqual('passed',attempt.gate_results['metrics'])
        self.assertEqual('failed',attempt.gate_results['evidence'])
        # 不稳定内容不是布局-only：仍需失败，不允许凭API值掩盖身份/内容不一致。
        error.metrics_stable=False
        with patch('threadsnap.reputation_autohome.stable_measure',AsyncMock(side_effect=error)):
            with self.assertRaises(ReputationAdapterError):
                await AutohomeReputationAdapter(None)._visit(browser,target,root)
        # 稳定页面但写PNG失败，同样保存可靠指标，不伪造文件。
        with patch('threadsnap.reputation_autohome.stable_measure',AsyncMock(return_value=(measurement,[measurement]*3))), patch('threadsnap.reputation_autohome.capture_region',AsyncMock(side_effect=OSError('capture failed'))):
            result=await AutohomeReputationAdapter(None)._visit(browser,target,root)
        self.assertEqual('4.25',result.score_raw)
        self.assertIsNone(result.metric_region_path)
        self.assertEqual('REPUTATION_EVIDENCE_WRITE_FAILED',result.evidence_error_code)

if __name__=='__main__':
    unittest.main()
