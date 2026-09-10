"""整篇倾向提示词、输出协议和跨版本缓存隔离回归；不冒充模型准确率验收。"""

import unittest

from sqlalchemy import select

from tests.test_backend import AppCase
from threadsnap.models import PostSnapshot, SentimentAnalysis, SentimentConfig, utc_now
from threadsnap.sentiment import (
    DEEPSEEK_MODEL_CODE,
    HOSTED_MODEL_CODE,
    LOCAL_MODEL_CODE,
    OVERALL_SENTIMENT_POLICY,
    analysis_version,
    build_output_correction_request,
    build_request,
)


class OverallTonePromptTests(unittest.TestCase):
    """核对两条云端路径使用同一判定口径且保留各自传输合同。"""

    def test_cloud_prompts_share_policy_and_keep_input(self):
        post = PostSnapshot(
            title="整体满意", content="车机偶尔慢一点，还是推荐。", image_urls=[], video_urls=[]
        )
        for model in (HOSTED_MODEL_CODE, DEEPSEEK_MODEL_CODE):
            with self.subTest(model=model):
                config = SentimentConfig(
                    model_code=model, brand="测试品牌", products=[], supplement=""
                )
                body = build_request(post, config)
                content = body["messages"][0]["content"]
                prompt = content if isinstance(content, str) else content[-1]["text"]
                self.assertEqual(1, prompt.count(OVERALL_SENTIMENT_POLICY))
                self.assertIn("标题：整体满意", prompt)
                self.assertIn("正文：车机偶尔慢一点，还是推荐。", prompt)
                self.assertNotIn("对判定对象不利为 negative", prompt)
                if model == DEEPSEEK_MODEL_CODE:
                    self.assertTrue(body["tools"][0]["function"]["strict"])
                    self.assertNotIn("response_format", body)
                else:
                    self.assertEqual({"type": "json_object"}, body["response_format"])
                corrected = build_output_correction_request(
                    body,
                    "invalid",
                    ValueError("contract"),
                    input_mode="text_only" if model == DEEPSEEK_MODEL_CODE else "multimodal",
                )
                self.assertEqual(body["messages"][0], corrected["messages"][0])

    def test_versions_change_only_cloud_paths(self):
        self.assertEqual("v5-overall-tone", analysis_version(HOSTED_MODEL_CODE))
        self.assertEqual("deepseek-text-v6-overall-tone", analysis_version(DEEPSEEK_MODEL_CODE))
        self.assertEqual("local-v1", analysis_version(LOCAL_MODEL_CODE))

    def test_policy_covers_mixed_praise_complaints_and_context(self):
        for boundary in (
            "轻微不足",
            "个人偏好",
            "改进建议",
            "主要负面态度",
            "严重故障",
            "反讽",
            "转述",
            "否认",
            "不按正负词句数量",
            "先确定整篇倾向",
            "primary_category=null",
            "secondary_categories=[]",
        ):
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, OVERALL_SENTIMENT_POLICY)


class OverallToneCacheTests(AppCase):
    """使用隔离 SQLite 验证真实入队服务，而非仅检查版本常量。"""

    def test_old_ai_result_is_not_reused_but_current_result_is(self):
        source_id, source_post_id = self.queue_deepseek_sentiment("tone-source")
        with self.container.sessions.begin() as db:
            source = db.get(SentimentAnalysis, source_id)
            source.status = "analysis_completed"
            source.prompt_version = "deepseek-text-v5-strict-tool"
            source.result = "negative"
            source.primary_category = "product_criticism"
            source.finished_at = utc_now()
            original_post = db.get(PostSnapshot, source_post_id)
            original_post.sentiment_result = "negative"
            original_post.analysis_status = "analysis_completed"
            identity = (original_post.platform_post_id, original_post.title, original_post.content)
        for suffix, reuse in (("old", False), ("new", True)):
            analysis_id, post_id = self.queue_deepseek_sentiment(
                "tone-" + suffix, source_name="车型-" + suffix
            )
            with self.container.sessions.begin() as db:
                if reuse:
                    # 模拟同版本完整 AI 结果，验证缓存仍可精确复用。
                    source = db.get(SentimentAnalysis, source_id)
                    source.prompt_version = analysis_version(DEEPSEEK_MODEL_CODE)
                db.delete(db.get(SentimentAnalysis, analysis_id))
                db.flush()
                post = db.get(PostSnapshot, post_id)
                post.platform_post_id, post.title, post.content = identity
                self.container.sentiment.enqueue_for_post(db, post, platform_code="dongchedi")
                queued = db.scalar(
                    select(SentimentAnalysis).where(SentimentAnalysis.post_id == post_id)
                )
                self.assertEqual(analysis_version(DEEPSEEK_MODEL_CODE), queued.prompt_version)
                self.assertEqual(source_id if reuse else None, queued.reused_from_analysis_id)
                self.assertEqual(
                    "analysis_completed" if reuse else "analysis_queued", queued.status
                )
                if not reuse:
                    self.assertIsNone(post.sentiment_result)
                    self.assertEqual(
                        "negative", db.get(PostSnapshot, source_post_id).sentiment_result
                    )
                    self.assertEqual(
                        "deepseek-text-v5-strict-tool",
                        db.get(SentimentAnalysis, source_id).prompt_version,
                    )
