"""SQLAlchemy 数据库入口。"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

SQLITE_BUSY_TIMEOUT_MILLISECONDS = 15_000


class Base(DeclarativeBase):
    """所有持久化模型的基类。"""


class UTCDateTime(TypeDecorator[datetime]):
    """统一持久化 UTC，并为 SQLite 读出的无时区时间恢复 UTC 标识。"""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        if dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, _dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def migrate_database(database_url: str) -> None:
    """使用版本化 Alembic 迁移将数据库升级到最新结构。"""

    migrations_dir = Path(__file__).resolve().parent / "migrations"
    if not (migrations_dir / "env.py").is_file():
        raise RuntimeError(f"未找到数据库迁移资源：{migrations_dir}")
    config = Config()
    config.set_main_option("script_location", str(migrations_dir))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


def build_engine(database_url: str) -> Engine:
    """创建数据库引擎，并为 SQLite 启用外键和 WAL。"""

    connect_args = (
        {
            "check_same_thread": False,
            "timeout": SQLITE_BUSY_TIMEOUT_MILLISECONDS / 1000,
        }
        if database_url.startswith("sqlite")
        else {}
    )
    engine = create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MILLISECONDS}")
            cursor.close()

    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """创建不在提交后失效对象的 Session 工厂。"""

    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False)


def session_dependency(
    factory: sessionmaker[Session],
) -> Generator[Session, None, None]:
    """FastAPI 数据库依赖。"""

    with factory() as session:
        yield session
