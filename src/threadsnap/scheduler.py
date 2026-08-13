"""单一全局定时协调器。"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .models import GlobalSchedule, ScheduleEvent
from .services import RunService


class SchedulerService:
    """只处理当前分钟，停机期间错过的节点不补跑。"""

    def __init__(
        self,
        factory: sessionmaker[Session],
        run_service: RunService,
        poll_seconds: float = 15.0,
    ):
        self.factory = factory
        self.run_service = run_service
        self.poll_seconds = poll_seconds
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="threadsnap-scheduler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:
                pass
            self.stop_event.wait(self.poll_seconds)

    def tick(self, now: datetime | None = None) -> dict | None:
        with self.factory() as db:
            schedule = db.get(GlobalSchedule, 1)
            if not schedule or not schedule.times:
                return None
            zone = ZoneInfo(schedule.timezone_name)
            local_now = (now or datetime.now(timezone.utc)).astimezone(zone)
            minute = local_now.replace(second=0, microsecond=0)
            if minute.strftime("%H:%M") not in schedule.times:
                return None
            planned_at = minute.astimezone(timezone.utc)
            existing = db.scalar(
                select(ScheduleEvent).where(
                    ScheduleEvent.planned_at == planned_at,
                    ScheduleEvent.schedule_version == schedule.version,
                )
            )
            if existing:
                return {
                    "status": existing.status,
                    "message": existing.message,
                    "run_id": existing.run_id,
                }
            version = schedule.version
        return self.run_service.create_scheduled(planned_at, version)
