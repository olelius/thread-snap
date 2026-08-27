"""每周与循环计划节点的全局调度器。"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .models import ScheduleConfig, ScheduleEvent, ScheduleNode
from .schedule_times import schedule_node_trigger_times
from .services import RunService


class SchedulerService:
    """按实际星期与秒级触发点执行节点，进程停机期间不补跑。"""

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
        due: list[tuple[datetime, str, str, int, bool]] = []
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
            node_trigger_times = {
                node.id: schedule_node_trigger_times(
                    node.node_type,
                    node.time_of_day,
                    node.end_time_of_day,
                    node.interval_minutes,
                )
                for node in nodes
            }
            trigger_owners: dict[tuple[str, int, str], list[str]] = {}
            for node in nodes:
                for weekday in node.weekdays:
                    for trigger_time in node_trigger_times[node.id]:
                        trigger_owners.setdefault(
                            (node.node_type, weekday, trigger_time), []
                        ).append(node.id)
            for node in nodes:
                trigger_times = node_trigger_times[node.id]
                for trigger_time in trigger_times:
                    hour, minute, second = (int(part) for part in trigger_time.split(":"))
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
                            conflict = (
                                len(trigger_owners[(node.node_type, day.weekday(), trigger_time)])
                                > 1
                            )
                            due.append(
                                (
                                    planned_at,
                                    node.node_type,
                                    node.id,
                                    config.revision,
                                    conflict,
                                )
                            )
        latest: dict | None = None
        type_order = {"weekly": 0, "recurring": 1}
        ordered_due = sorted(
            due,
            key=lambda item: (
                item[0],
                type_order.get(item[1], 99),
                item[2],
            ),
        )
        for planned_at, node_type, node_id, revision, conflict in ordered_due:
            if conflict:
                self._record_same_type_conflict(planned_at, node_type, node_id, revision)
                continue
            latest = self.run_service.create_scheduled(planned_at, node_id, revision)
            if latest and self.event_publisher:
                self.event_publisher(
                    "run.changed",
                    latest["id"],
                    summary_version=latest["summary_version"],
                    status=latest["status"],
                )
        return latest

    def _record_same_type_conflict(
        self,
        planned_at: datetime,
        node_type: str,
        node_id: str,
        revision: int,
    ) -> None:
        """为异常持久数据记录阻止事件，不任意选择同类型节点继续触发。"""

        type_name = "循环计划" if node_type == "recurring" else "每周计划"
        with self.factory.begin() as db:
            existing = db.scalar(
                select(ScheduleEvent).where(
                    ScheduleEvent.planned_at == planned_at,
                    ScheduleEvent.schedule_node_id == node_id,
                )
            )
            if existing:
                return
            db.add(
                ScheduleEvent(
                    planned_at=planned_at,
                    schedule_node_id=node_id,
                    schedule_revision=revision,
                    status="blocked",
                    message=f"{type_name}存在同秒启用节点，整次节点触发已阻止。",
                )
            )
