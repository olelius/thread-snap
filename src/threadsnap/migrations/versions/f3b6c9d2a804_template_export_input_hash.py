"""导出缓存包含新增舆情字段和截图版本，既有导出记录原样保留。"""

import sqlalchemy as sa
from alembic import op

revision = "f3b6c9d2a804"
down_revision = "e7a4c8d2b601"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """旧记录使用空指纹，只有采用新增字段的模板保存新输入指纹。"""
    with op.batch_alter_table("export_records") as batch:
        batch.add_column(sa.Column("input_sha256", sa.String(64), nullable=False, server_default=""))
        batch.drop_constraint("uq_export_version", type_="unique")
        batch.create_unique_constraint("uq_export_version", ["run_id", "summary_version", "template_version_id", "input_sha256"])


def downgrade() -> None:
    """已有同批次多输入版本时停止回退，避免丢弃历史导出。"""
    duplicate = op.get_bind().execute(sa.text(
        "SELECT 1 FROM export_records GROUP BY run_id, summary_version, template_version_id HAVING count(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError("已有多输入版本导出，请保留当前数据库结构并仅回退代码。")
    with op.batch_alter_table("export_records") as batch:
        batch.drop_constraint("uq_export_version", type_="unique")
        batch.drop_column("input_sha256")
        batch.create_unique_constraint("uq_export_version", ["run_id", "summary_version", "template_version_id"])
