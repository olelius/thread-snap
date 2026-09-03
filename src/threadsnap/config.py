"""运行配置。所有可变运行参数从环境读取，业务配置保存在数据库。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """ThreadSnap 进程级配置。"""

    model_config = SettingsConfigDict(env_prefix="THREADSNAP_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/threadsnap.db"
    data_dir: Path = Path("data")
    timezone: str = "Asia/Shanghai"
    scheduler_poll_seconds: float = Field(default=15.0, gt=0)
    worker_poll_seconds: float = Field(default=1.0, gt=0)
    local_sentiment_num_threads: int = Field(default=2, ge=1, le=4)
    start_background_services: bool = True
    # 三个平台各自占用一个执行通道；平台内部并发仍由平台配置单独控制。
    platform_level_concurrency: int = Field(default=3, ge=1, le=3)
    dongchedi_storage_state: Path | None = None
    session_fernet_key: str | None = None
    # 懂车帝当前会对无头浏览器返回 HTTP 200 零字节文档；认证浏览器默认使用
    # 完整 Chromium 的有头模式，Linux 由 Weston 提供无头 Wayland 显示。
    auth_browser_headless: bool = False
    runtime_mode: str = "production"
    enable_reputation_synthetic_runs: bool = False
    reputation_test_database: bool = False

    @property
    def template_dir(self) -> Path:
        return self.data_dir / "templates"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def auth_profile_dir(self) -> Path:
        """平台交互会话浏览器的隔离 Profile 根目录。"""

        return self.data_dir / "auth-profiles"

    @property
    def screenshot_dir(self) -> Path:
        """圈子页面原始证据与派生成果的持久目录。"""

        return self.data_dir / "screenshots"

    @property
    def screenshot_evidence_dir(self) -> Path:
        return self.screenshot_dir / "evidence"

    @property
    def screenshot_artifact_dir(self) -> Path:
        return self.screenshot_dir / "artifacts"

    @property
    def reputation_dir(self) -> Path:
        """口碑巡检证据与交付文件根目录。"""

        return self.data_dir / "reputation"

    @property
    def paddlenlp_home(self) -> Path:
        """本地轻量文字模型与静态推理文件的持久目录。"""

        return self.data_dir / "paddlenlp"

    def ensure_directories(self) -> None:
        """创建后端持久文件目录。"""

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.template_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.auth_profile_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_evidence_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_artifact_dir.mkdir(parents=True, exist_ok=True)
        self.reputation_dir.mkdir(parents=True, exist_ok=True)
        self.paddlenlp_home.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程级配置单例。"""

    return Settings()
