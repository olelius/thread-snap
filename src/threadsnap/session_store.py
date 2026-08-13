"""平台 Session 的加密持久化。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .errors import DomainError
from .models import PlatformSession, utc_now


class SessionStore:
    """加密保存浏览器 storage state，接口永远不返回原值。"""

    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]):
        self.settings = settings
        self.session_factory = session_factory
        self.fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        if self.settings.session_fernet_key:
            return self.settings.session_fernet_key.encode("ascii")
        key_path = self.settings.data_dir / "session.key"
        if key_path.exists():
            return key_path.read_bytes().strip()
        key = Fernet.generate_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(key + b"\n")
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
        return key

    @staticmethod
    def validate_state(state: dict[str, Any]) -> None:
        cookies = state.get("cookies")
        if not isinstance(cookies, list) or not cookies:
            raise DomainError(
                "SESSION_INVALID",
                "平台会话文件缺少有效 Cookie。",
                details=[{"field": "cookies", "reason": "必须是非空数组"}],
            )
        for index, item in enumerate(cookies):
            if not isinstance(item, dict) or not all(
                item.get(key) for key in ("name", "value", "domain", "path")
            ):
                raise DomainError(
                    "SESSION_INVALID",
                    "平台会话文件包含无效 Cookie。",
                    details=[
                        {
                            "field": f"cookies[{index}]",
                            "reason": "缺少 name、value、domain 或 path",
                        }
                    ],
                )

    def import_state(self, platform_code: str, state: dict[str, Any]) -> None:
        self.validate_state(state)
        payload = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encrypted = self.fernet.encrypt(payload)
        with self.session_factory.begin() as db:
            record = db.get(PlatformSession, platform_code) or PlatformSession(
                platform_code=platform_code
            )
            record.encrypted_state = encrypted
            record.status = "available"
            record.last_verified_at = utc_now()
            record.error_message = None
            db.add(record)

    def import_file(self, platform_code: str, path: Path) -> None:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise DomainError("SESSION_INVALID", "平台会话文件必须是 JSON 对象。")
        self.import_state(platform_code, state)

    def get_state(self, platform_code: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            record = db.get(PlatformSession, platform_code)
            encrypted = record.encrypted_state if record else None
        if not encrypted:
            return None
        try:
            result = json.loads(self.fernet.decrypt(encrypted))
        except (InvalidToken, json.JSONDecodeError) as exc:
            raise DomainError(
                "SESSION_DECRYPT_FAILED",
                "平台会话状态读取失败，请重新完成平台认证。",
                status_code=500,
            ) from exc
        return result if isinstance(result, dict) else None

    def status(self, platform_code: str) -> dict[str, Any]:
        with self.session_factory() as db:
            record = db.get(PlatformSession, platform_code)
            if not record:
                return {
                    "platform_code": platform_code,
                    "status": "missing",
                    "last_verified_at": None,
                    "error_message": None,
                }
            return {
                "platform_code": platform_code,
                "status": record.status,
                "last_verified_at": record.last_verified_at,
                "error_message": record.error_message,
            }

    def clear(self, platform_code: str) -> None:
        with self.session_factory.begin() as db:
            record = db.get(PlatformSession, platform_code)
            if record:
                record.encrypted_state = None
                record.status = "missing"
                record.last_verified_at = None
                record.error_message = None
