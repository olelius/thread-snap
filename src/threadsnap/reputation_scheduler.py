"""固定口碑日程、正式执行和10:30产物的单进程协调器。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from .reputation import ReputationService

LOGGER = logging.getLogger(__name__)


class ReputationCoordinator:
    """串行协调批次，页面内部并发由批次冻结的平台并发控制。"""

    def __init__(self, service: ReputationService, poll_seconds: float = 15.0) -> None:
        self.service = service
        self.poll_seconds = poll_seconds
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.service.recover_interrupted()
        self.stop_event.clear()
        self.wake_event.set()
        self.thread = threading.Thread(
            target=self._loop,
            name="threadsnap-reputation-coordinator",
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def wake(self) -> None:
        self.wake_event.set()

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:
                LOGGER.exception("口碑巡检协调器轮询失败")
            self.wake_event.wait(self.poll_seconds)
            self.wake_event.clear()

    def tick(self, now: datetime | None = None) -> dict:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        outcome = self.service.check_schedule(current)
        for run_id in outcome["queued_run_ids"]:
            if self.stop_event.is_set():
                break
            if not self.service.can_execute_official(run_id):
                continue
            run = self.service.execute_run(run_id)
            report_planned = run.get("report_planned_at")
            if (
                run.get("source_type") == "scheduled"
                and report_planned
                and current >= datetime.fromisoformat(report_planned).astimezone(timezone.utc)
            ):
                self.service.generate_report(run_id, datetime.now(timezone.utc))
        current = datetime.now(timezone.utc) if now is None else current
        refreshed = self.service.check_schedule(current)
        for run_id in refreshed["report_run_ids"]:
            if self.stop_event.is_set():
                break
            self.service.generate_report(run_id, current)
        outcome["report_run_ids"] = refreshed["report_run_ids"]
        return outcome
