"""为命名AI账户及规则、分析任务增加账户身份，旧记录保留默认账户1。"""

import sqlalchemy as sa
from alembic import op

revision = "e7a4c8d2b601"
down_revision = "c3f7a1d9e402"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """只增加列及索引，不复制或解密现有凭据，不重建历史任务。"""
    op.add_column("sentiment_configs", sa.Column("name", sa.String(120), nullable=False, server_default="默认账户"))
    op.create_index("uq_sentiment_configs_name", "sentiment_configs", ["name"], unique=True)
    op.add_column("extraction_rule_versions", sa.Column("ai_account_id", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("sentiment_analyses", sa.Column("account_id", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("sentiment_analyses", sa.Column("account_name", sa.String(120), nullable=False, server_default="默认账户"))
    op.create_index("ix_sentiment_analysis_account_queue", "sentiment_analyses", ["account_id", "status", "created_at"])


def downgrade() -> None:
    """出现多账户数据后禁止自动丢弃其身份，保留人工回退边界。"""
    db = op.get_bind()
    for statement in (
        "SELECT 1 FROM sentiment_configs WHERE id <> 1 LIMIT 1",
        "SELECT 1 FROM sentiment_analyses WHERE account_id <> 1 LIMIT 1",
        "SELECT 1 FROM extraction_rule_versions WHERE ai_account_id <> 1 LIMIT 1",
    ):
        if db.execute(sa.text(statement)).first():
            raise RuntimeError("已有多账户配置或历史关联，请保留当前数据库并人工安排回退。")
    op.drop_index("ix_sentiment_analysis_account_queue", table_name="sentiment_analyses")
    op.drop_column("sentiment_analyses", "account_name")
    op.drop_column("sentiment_analyses", "account_id")
    op.drop_column("extraction_rule_versions", "ai_account_id")
    op.drop_index("uq_sentiment_configs_name", table_name="sentiment_configs")
    op.drop_column("sentiment_configs", "name")
