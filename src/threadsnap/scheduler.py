"""每周计划节点调度器。"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .models import ScheduleConfig, ScheduleEvent, ScheduleNode
from .services import RunService


class SchedulerService:
    """按星期与秒级时间触发节点，进程停机期间的节点不补跑。"""

    def __init__(
        self,
        factory: sessionmaker[Session],
        run_service: RunService,
        poll_seconds: float = 15.0,
        event_publisher: Callable[..., Any] | None = None,
    ):
        self.factory = factory
        self.run_service = run_service
        self.poll_seconds = poll_seconds
        self.event_publisher = event_publisher
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_tick_at: datetime | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.last_tick_at = None
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
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        window_start = self.last_tick_at or current - timedelta(seconds=max(self.poll_seconds, 1.0))
        if window_start > current:
            window_start = current - timedelta(seconds=max(self.poll_seconds, 1.0))
        self.last_tick_at = current
        due: list[tuple[datetime, str, int]] = []
        with self.factory() as db:
            config = db.get(ScheduleConfig, 1)
            if not config:
                return None
            zone = ZoneInfo(config.timezone_name)
            local_now = current.astimezone(zone)
            nodes = list(
                db.scalars(
                    select(ScheduleNode)
                    .where(ScheduleNode.enabled.is_(True))
                    .order_by(ScheduleNode.time_of_day, ScheduleNode.id)
                )
            )
            for node in nodes:
                hour, minute, second = (int(part) for part in node.time_of_day.split(":"))
                for day_offset in (1, 0):
                    day = (local_now - timedelta(days=day_offset)).date()
                    if day.weekday() not in node.weekdays:
                        continue
                    planned_local = datetime(
                        day.year,
                        day.month,
                        day.day,
                        hour,
                        minute,
                        second,
                        tzinfo=zone,
                    )
                    planned_at = planned_local.astimezone(timezone.utc)
                    if not window_start < planned_at <= current:
                        continue
                    existing = db.scalar(
                        select(ScheduleEvent).where(
                            ScheduleEvent.planned_at == planned_at,
                            ScheduleEvent.schedule_node_id == node.id,
                        )
                    )
                    if not existing:
                        due.append((planned_at, node.id, config.revision))
        latest: dict | None = None
        for planned_at, node_id, revision in due:
            latest = self.run_service.create_scheduled(planned_at, node_id, revision)
            if latest and self.event_publisher:
                self.event_publisher(
                    "run.changed",
                    latest["id"],
                    summary_version=latest["summary_version"],
                    status=latest["status"],
                )
        return latest
