"""为真实批量保留删除补齐六个高量外键检索索引，不改变业务数据。"""

import sqlalchemy as sa
from alembic import context, op

revision = "d9e4b7a2c601"
down_revision = "f3b6c9d2a804"
branch_labels = None
depends_on = None

# 仅覆盖此次真实删除基准确认的逐帖子/分析/修订引用及批次帖子定位。
INDEXES = (
    ("ix_comment_snapshots_post", "comment_snapshots", "post_id"),
    ("ix_sentiment_analysis_reused_from", "sentiment_analyses", "reused_from_analysis_id"),
    (
        "ix_manual_sentiment_inherited_from",
        "manual_sentiment_revisions",
        "inherited_from_revision_id",
    ),
    ("ix_evidence_item_post_snapshot", "circle_page_evidence_items", "post_snapshot_id"),
    ("ix_artifact_item_post_snapshot", "screenshot_artifact_items", "post_snapshot_id"),
    ("ix_post_snapshots_run", "post_snapshots", "run_id"),
)


def _exists_with_expected_definition(name: str, table: str, column: str) -> bool:
    """在线重试允许之前已提交的正确索引；同名但不同定义不能被悄悄跳过。"""
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        owner = connection.execute(
            sa.text("SELECT tbl_name FROM sqlite_master WHERE type='index' AND name=:name"),
            {"name": name},
        ).scalar_one_or_none()
        if owner is not None and owner != table:
            raise RuntimeError(f"保留索引定义冲突：{name} 属于 {owner} 而非 {table}")
    indexes = sa.inspect(connection).get_indexes(table)
    existing = next((index for index in indexes if index["name"] == name), None)
    if existing is None:
        return False
    if (
        existing["column_names"] != [column]
        or existing["unique"]
        or any(
            key.endswith("_where") and value is not None
            for key, value in existing.get("dialect_options", {}).items()
        )
    ):
        raise RuntimeError(f"保留索引定义冲突：{name} 必须是 {table}({column}) 的非唯一完整索引")
    return True


def upgrade() -> None:
    """只增加非唯一单列索引，已有表、列、外键与每一行业务快照保持不变。"""
    for name, table, column in INDEXES:
        # 生产走在线迁移。离线SQL仅输出标准DDL，不承诺未知数据库的半途恢复。
        if context.is_offline_mode() or not _exists_with_expected_definition(name, table, column):
            op.create_index(name, table, [column], unique=False)


def downgrade() -> None:
    """精确撤销本次六项索引，允许旧迁移器继续识别基线版本，不回写旧业务数据。"""
    for name, table, column in reversed(INDEXES):
        if context.is_offline_mode() or _exists_with_expected_definition(name, table, column):
            op.drop_index(name, table_name=table)
