"""配置、批次和领域查询应用服务。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from .collectors.dongchedi import (
    ADAPTER_VERSION,
    CollectorFailure,
    normalize_post_url,
    parse_circle_url,
)
from .errors import DomainError
from .models import (
    Circle,
    CircleTask,
    CommentSnapshot,
    ExportRecord,
    ExtractionRule,
    ExtractionRuleVersion,
    ExtractionRun,
    ExtractionRunRule,
    PlatformConfig,
    PostSnapshot,
    ScheduleConfig,
    ScheduleEvent,
    ScheduleNode,
    ScheduleNodeRule,
    ValidationJob,
    Vehicle,
    utc_now,
)
from .schemas import (
    CircleBatchUpdate,
    CircleRow,
    ExtractionPlanUpdate,
    ManualRunCreate,
    PlatformConfigUpdate,
)

TERMINAL_STATUSES = frozenset({"success", "partial_success", "failed"})
RUN_STATUS_ZH = {
    "queued": "排队中",
    "running": "提取中",
    "waiting_for_auth": "等待平台认证",
    "success": "成功",
    "partial_success": "部分成功",
    "failed": "失败",
}
TRIGGER_ZH = {"manual": "手动触发", "scheduled": "定时提取"}


def related_run_ids(db: Session, run_id: str) -> list[str]:
    """返回同一原始批次及其所有手动补提批次。"""

    current = db.get(ExtractionRun, run_id)
    if not current:
        return []
    while current.related_run_id:
        parent = db.get(ExtractionRun, current.related_run_id)
        if not parent:
            break
        current = parent
    result = [current.id]
    cursor = 0
    while cursor < len(result):
        for child in db.scalars(
            select(ExtractionRun.id)
            .where(ExtractionRun.related_run_id == result[cursor])
            .order_by(ExtractionRun.created_at)
        ):
            if child not in result:
                result.append(child)
        cursor += 1
    return result


def canonical_hash(value: Any) -> str:
    """对规范化 JSON 请求计算幂等哈希。"""

    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def bootstrap_database(db: Session) -> None:
    """写入第一版平台目录和计划配置默认值。"""

    defaults = [
        PlatformConfig(
            code="dongchedi",
            display_name="懂车帝",
            adapter_status="available",
            enabled=True,
            internal_concurrency=2,
            min_quantity=1,
            max_quantity=2000,
            min_concurrency=1,
            max_concurrency=8,
            adapter_version=ADAPTER_VERSION,
        ),
        PlatformConfig(
            code="autohome",
            display_name="汽车之家",
            adapter_status="not_integrated",
            enabled=False,
        ),
        PlatformConfig(
            code="yiche",
            display_name="易车",
            adapter_status="not_integrated",
            enabled=False,
        ),
    ]
    for item in defaults:
        existing = db.get(PlatformConfig, item.code)
        if not existing:
            db.add(item)
        elif item.code == "dongchedi":
            existing.adapter_version = ADAPTER_VERSION
    if not db.get(ScheduleConfig, 1):
        db.add(ScheduleConfig(id=1, timezone_name="Asia/Shanghai", revision=1))


class ConfigService:
    """提取计划、平台和车型圈子配置。"""

    def __init__(self, factory: sessionmaker[Session]):
        self.factory = factory

    def list_platforms(self) -> list[dict[str, Any]]:
        with self.factory() as db:
            return [
                self.platform_dict(item)
                for item in db.scalars(select(PlatformConfig).order_by(PlatformConfig.code))
            ]

    @staticmethod
    def platform_dict(item: PlatformConfig) -> dict[str, Any]:
        return {
            "code": item.code,
            "display_name": item.display_name,
            "adapter_status": item.adapter_status,
            "enabled": item.enabled,
            "internal_concurrency": item.internal_concurrency,
            "quantity_range": {"min": item.min_quantity, "max": item.max_quantity},
            "concurrency_range": {
                "min": item.min_concurrency,
                "max": item.max_concurrency,
            },
            "adapter_version": item.adapter_version,
        }

    def update_platform(self, code: str, value: PlatformConfigUpdate) -> dict[str, Any]:
        with self.factory.begin() as db:
            item = db.get(PlatformConfig, code)
            if not item:
                raise DomainError("PLATFORM_NOT_FOUND", "指定平台不存在。", status_code=404)
            if item.adapter_status != "available" and value.enabled:
                raise DomainError(
                    "PLATFORM_NOT_INTEGRATED",
                    f"{item.display_name}暂未接入，当前不允许启用。",
                    status_code=409,
                )
            actual_concurrency = min(
                max(value.internal_concurrency, item.min_concurrency),
                item.max_concurrency,
            )
            item.enabled = value.enabled
            item.internal_concurrency = actual_concurrency
            db.flush()
            result = self.platform_dict(item)
            notes = []
            if actual_concurrency != value.internal_concurrency:
                notes.append(f"平台内部并发已收敛为安全值 {actual_concurrency}。")
            result["notes"] = notes
            return result

    def get_extraction_plan(self) -> dict[str, Any]:
        with self.factory() as db:
            config = db.get(ScheduleConfig, 1)
            assert config is not None
            rules = list(db.scalars(select(ExtractionRule).order_by(ExtractionRule.created_at)))
            versions = {
                (item.rule_id, item.version): item
                for item in db.scalars(select(ExtractionRuleVersion))
            }
            nodes = list(db.scalars(select(ScheduleNode).order_by(ScheduleNode.created_at)))
            node_rules: dict[str, list[str]] = {}
            for item in db.scalars(
                select(ScheduleNodeRule).order_by(
                    ScheduleNodeRule.schedule_node_id, ScheduleNodeRule.position
                )
            ):
                node_rules.setdefault(item.schedule_node_id, []).append(item.rule_id)

            def rule_dict(rule: ExtractionRule) -> dict[str, Any]:
                version = versions[(rule.id, rule.current_version)]
                return {
                    "id": rule.id,
                    "name": rule.name,
                    "version": rule.current_version,
                    "platform_quantities": version.platform_quantities,
                    "circle_ids": version.selected_circle_ids,
                    "archived": rule.archived,
                    "updated_at": rule.updated_at,
                }

            return {
                "timezone": config.timezone_name,
                "revision": config.revision,
                "rules": [rule_dict(item) for item in rules if not item.archived],
                "archived_rules": [rule_dict(item) for item in rules if item.archived],
                "nodes": [
                    {
                        "id": item.id,
                        "weekdays": item.weekdays,
                        "time": item.time_of_day,
                        "enabled": item.enabled,
                        "rule_ids": node_rules.get(item.id, [item.legacy_rule_id]),
                        "updated_at": item.updated_at,
                    }
                    for item in nodes
                ],
            }

    def update_extraction_plan(self, value: ExtractionPlanUpdate) -> dict[str, Any]:
        with self.factory.begin() as db:
            config = db.get(ScheduleConfig, 1)
            assert config is not None
            if value.revision != config.revision:
                raise DomainError(
                    "EXTRACTION_PLAN_REVISION_CONFLICT",
                    "提取计划已被更新，请刷新后合并当前修改。",
                    status_code=409,
                    details=[{"current_revision": config.revision}],
                )
            names: dict[str, str] = {}
            for draft in value.rules:
                normalized = draft.name.strip()
                key = normalized.casefold()
                if key in names:
                    raise DomainError(
                        "EXTRACTION_RULE_NAME_DUPLICATED",
                        "规则名称需要保持唯一。",
                        details=[{"rule_id": draft.id, "conflicts_with": names[key]}],
                    )
                names[key] = draft.id
            rule_ids = {item.id for item in value.rules}
            node_ids = {item.id for item in value.nodes}
            missing_refs = [
                {
                    "node_id": item.id,
                    "rule_ids": [rule_id for rule_id in item.rule_ids if rule_id not in rule_ids],
                }
                for item in value.nodes
                if any(rule_id not in rule_ids for rule_id in item.rule_ids)
            ]
            if missing_refs:
                raise DomainError(
                    "SCHEDULE_NODE_RULE_MISSING",
                    "计划节点引用了当前计划中不存在的规则。",
                    details=missing_refs,
                )
            conflicts: dict[tuple[int, str], list[str]] = {}
            for node in value.nodes:
                if not node.enabled:
                    continue
                for weekday in node.weekdays:
                    conflicts.setdefault((weekday, node.time), []).append(node.id)
            duplicated = [
                {"weekday": key[0], "time": key[1], "node_ids": ids}
                for key, ids in conflicts.items()
                if len(ids) > 1
            ]
            if duplicated:
                raise DomainError(
                    "SCHEDULE_NODE_TIME_CONFLICT",
                    "启用节点的星期和时间发生冲突。",
                    details=duplicated,
                )
            platforms = list(db.scalars(select(PlatformConfig)))
            integrated = {
                item.code: item for item in platforms if item.adapter_status == "available"
            }
            configured_circles = {
                item.id: item
                for item in db.scalars(select(Circle).where(Circle.source_kind == "configured"))
            }
            rule_quantities: dict[str, dict[str, int]] = {}
            rule_circle_ids: dict[str, list[str]] = {}
            for draft in value.rules:
                circle_ids = sorted(set(draft.circle_ids))
                missing_circles = sorted(set(circle_ids) - set(configured_circles))
                if missing_circles:
                    raise DomainError(
                        "EXTRACTION_RULE_CIRCLE_INVALID",
                        "规则包含不存在或不属于配置来源的圈子。",
                        details=[
                            {"circle_id": item, "rule_id": draft.id} for item in missing_circles
                        ],
                    )
                selected_platforms = {
                    configured_circles[circle_id].platform_code for circle_id in circle_ids
                }
                unavailable = sorted(selected_platforms - set(integrated))
                if unavailable:
                    raise DomainError(
                        "EXTRACTION_RULE_PLATFORM_INVALID",
                        "规则选择了尚未接入的平台圈子。",
                        details=[
                            {"platform_code": code, "rule_id": draft.id} for code in unavailable
                        ],
                    )
                quantity_platforms = set(draft.platform_quantities)
                if quantity_platforms != selected_platforms:
                    raise DomainError(
                        "EXTRACTION_RULE_SCOPE_QUANTITY_MISMATCH",
                        "规则必须为每个已选平台设置且只设置一个每圈目标数。",
                        details=[
                            {
                                "rule_id": draft.id,
                                "missing_platforms": sorted(
                                    selected_platforms - quantity_platforms
                                ),
                                "extra_platforms": sorted(quantity_platforms - selected_platforms),
                            }
                        ],
                    )
                quantities: dict[str, int] = {}
                for code, quantity in draft.platform_quantities.items():
                    platform = integrated[code]
                    if quantity < platform.min_quantity or quantity > platform.max_quantity:
                        raise DomainError(
                            "EXTRACTION_RULE_QUANTITY_INVALID",
                            "规则中的平台数量超出有效范围。",
                            details=[
                                {
                                    "rule_id": draft.id,
                                    "platform_code": code,
                                    "min": platform.min_quantity,
                                    "max": platform.max_quantity,
                                }
                            ],
                        )
                    quantities[code] = quantity
                rule_quantities[draft.id] = quantities
                rule_circle_ids[draft.id] = circle_ids
            invalid_nodes = [
                {"node_id": node.id, "rule_id": rule_id}
                for node in value.nodes
                for rule_id in node.rule_ids
                if node.enabled and not rule_circle_ids[rule_id]
            ]
            if invalid_nodes:
                raise DomainError(
                    "SCHEDULE_NODE_RULE_SCOPE_EMPTY",
                    "启用节点引用的规则至少需要选择一个平台圈子。",
                    details=invalid_nodes,
                )

            existing_rules = {item.id: item for item in db.scalars(select(ExtractionRule))}
            for draft in value.rules:
                rule = existing_rules.get(draft.id)
                quantities = rule_quantities[draft.id]
                circle_ids = rule_circle_ids[draft.id]
                if rule and rule.archived:
                    raise DomainError(
                        "EXTRACTION_RULE_ARCHIVED",
                        "已归档规则需要先恢复后再编辑。",
                        status_code=409,
                        details=[{"rule_id": draft.id}],
                    )
                if not rule:
                    rule = ExtractionRule(id=draft.id, name=draft.name.strip(), current_version=1)
                    db.add(rule)
                    db.add(
                        ExtractionRuleVersion(
                            rule_id=draft.id,
                            version=1,
                            platform_quantities=quantities,
                            selected_circle_ids=circle_ids,
                        )
                    )
                else:
                    current = db.scalar(
                        select(ExtractionRuleVersion).where(
                            ExtractionRuleVersion.rule_id == rule.id,
                            ExtractionRuleVersion.version == rule.current_version,
                        )
                    )
                    changed = rule.name != draft.name.strip() or (
                        current is None
                        or current.platform_quantities != quantities
                        or current.selected_circle_ids != circle_ids
                    )
                    rule.name = draft.name.strip()
                    if changed:
                        rule.current_version += 1
                        db.add(
                            ExtractionRuleVersion(
                                rule_id=rule.id,
                                version=rule.current_version,
                                platform_quantities=quantities,
                                selected_circle_ids=circle_ids,
                            )
                        )

            for node in list(db.scalars(select(ScheduleNode))):
                if node.id not in node_ids:
                    db.delete(node)
            db.flush()
            existing_nodes = {item.id: item for item in db.scalars(select(ScheduleNode))}
            for draft in value.nodes:
                node = existing_nodes.get(draft.id)
                if not node:
                    node = ScheduleNode(id=draft.id)
                    db.add(node)
                node.weekdays = draft.weekdays
                node.time_of_day = draft.time
                node.enabled = draft.enabled
                node.legacy_rule_id = draft.rule_ids[0]
            db.flush()
            for draft in value.nodes:
                db.execute(
                    delete(ScheduleNodeRule).where(
                        ScheduleNodeRule.schedule_node_id == draft.id
                    )
                )
                for position, rule_id in enumerate(draft.rule_ids):
                    db.add(
                        ScheduleNodeRule(
                            schedule_node_id=draft.id,
                            rule_id=rule_id,
                            position=position,
                        )
                    )
            db.flush()

            for rule in existing_rules.values():
                if rule.archived or rule.id in rule_ids:
                    continue
                referenced = db.scalar(
                    select(func.count())
                    .select_from(ScheduleNodeRule)
                    .where(ScheduleNodeRule.rule_id == rule.id)
                )
                if referenced:
                    raise DomainError(
                        "EXTRACTION_RULE_IN_USE",
                        "仍被计划节点引用的规则需要先解除引用。",
                        status_code=409,
                        details=[{"rule_id": rule.id}],
                    )
                used = db.scalar(
                    select(func.count())
                    .select_from(ExtractionRunRule)
                    .where(ExtractionRunRule.rule_id == rule.id)
                )
                if used:
                    rule.archived = True
                else:
                    db.delete(rule)
            config.revision += 1
            db.flush()
        return self.get_extraction_plan()

    def restore_extraction_rule(self, rule_id: str) -> dict[str, Any]:
        with self.factory.begin() as db:
            rule = db.get(ExtractionRule, rule_id)
            if not rule:
                raise DomainError("EXTRACTION_RULE_NOT_FOUND", "指定规则不存在。", status_code=404)
            rule.archived = False
            config = db.get(ScheduleConfig, 1)
            assert config is not None
            config.revision += 1
        return self.get_extraction_plan()

    def list_vehicles(self) -> list[dict[str, Any]]:
        with self.factory() as db:
            vehicles = list(db.scalars(select(Vehicle).order_by(Vehicle.name)))
            circles = list(
                db.scalars(
                    select(Circle)
                    .where(Circle.source_kind == "configured")
                    .order_by(Circle.created_at)
                )
            )
            grouped: dict[str | None, list[dict[str, Any]]] = {}
            for circle in circles:
                grouped.setdefault(circle.vehicle_id, []).append(self.circle_dict(circle))
            return [
                {"id": item.id, "name": item.name, "circles": grouped.get(item.id, [])}
                for item in vehicles
            ]

    @staticmethod
    def circle_dict(item: Circle) -> dict[str, Any]:
        return {
            "id": item.id,
            "platform_code": item.platform_code,
            "external_id": item.external_id,
            "name": item.name,
            "url": item.url,
            "section": item.section,
            "list_order": item.list_order,
            "vehicle_id": item.vehicle_id,
            "source_kind": item.source_kind,
            "auto_enabled": item.auto_enabled,
            "validation_status": item.validation_status,
            "validation_error": item.validation_error,
            "first_validated_at": item.first_validated_at,
            "validated_at": item.validated_at,
            "last_used_at": item.last_used_at,
        }

    def save_circle_batch(self, value: CircleBatchUpdate) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        normalized: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        with self.factory() as read_db:
            platforms = {x.code: x for x in read_db.scalars(select(PlatformConfig))}
            existing_ids = {x.id: x for x in read_db.scalars(select(Circle))}
            vehicle_ids = set(read_db.scalars(select(Vehicle.id)))
            active_rule_versions = list(
                read_db.execute(
                    select(ExtractionRule, ExtractionRuleVersion)
                    .join(
                        ExtractionRuleVersion,
                        ExtractionRuleVersion.rule_id == ExtractionRule.id,
                    )
                    .where(
                        ExtractionRule.archived.is_(False),
                        ExtractionRuleVersion.version == ExtractionRule.current_version,
                    )
                )
            )
        deleted_ids = list(dict.fromkeys(value.deleted_ids))
        for circle_id in deleted_ids:
            circle = existing_ids.get(circle_id)
            if not circle or circle.source_kind != "configured":
                errors.append(
                    {
                        "field": "deleted_ids",
                        "reason": f"要删除的圈子不存在：{circle_id}",
                    }
                )
                continue
            referenced_by = [
                rule.name
                for rule, version in active_rule_versions
                if circle_id in version.selected_circle_ids
            ]
            if referenced_by:
                errors.append(
                    {
                        "field": "deleted_ids",
                        "reason": (
                            f"圈子仍被自动提取规则引用：{'、'.join(sorted(referenced_by))}；"
                            "请先从规则范围中移除。"
                        ),
                    }
                )
        deleted_id_set = set(deleted_ids)
        existing_keys = {
            (x.platform_code, x.external_id, x.section, x.list_order): x.id
            for x in existing_ids.values()
            if x.id not in deleted_id_set
        }
        for index, row in enumerate(value.rows):
            platform = platforms.get(row.platform_code)
            if not platform:
                errors.append({"row": index + 1, "field": "platform_code", "reason": "平台不存在"})
                continue
            if row.section != "dynamic":
                errors.append(
                    {
                        "row": index + 1,
                        "field": "section",
                        "reason": "第一版只支持 dynamic 动态版块",
                    }
                )
            if row.vehicle_id and row.vehicle_id not in vehicle_ids:
                errors.append({"row": index + 1, "field": "vehicle_id", "reason": "来源名称不存在"})
            if not row.vehicle_id and not (row.vehicle_name or "").strip():
                errors.append(
                    {
                        "row": index + 1,
                        "field": "vehicle_name",
                        "reason": "必须选择或填写来源名称",
                    }
                )
            try:
                if row.platform_code == "dongchedi":
                    source = parse_circle_url(row.url)
                    external_id, url, list_order = (
                        source.external_id,
                        source.url,
                        source.list_order,
                    )
                else:
                    match = re.search(r"(\d+)", row.url)
                    if not match:
                        raise CollectorFailure("CIRCLE_URL_INVALID", "圈子链接中缺少圈子 ID。")
                    external_id, url, list_order = match.group(1), row.url.strip(), "latest_reply"
            except CollectorFailure as exc:
                errors.append({"row": index + 1, "field": "url", "reason": exc.message})
                continue
            key = (row.platform_code, external_id, row.section, list_order)
            if key in seen:
                errors.append({"row": index + 1, "field": "url", "reason": "本次提交中圈子来源重复"})
            seen.add(key)
            if row.id and row.id not in existing_ids:
                errors.append({"row": index + 1, "field": "id", "reason": "要修改的圈子不存在"})
            if row.id and row.id in deleted_id_set:
                errors.append(
                    {
                        "row": index + 1,
                        "field": "id",
                        "reason": "同一圈子不可同时保存和删除",
                    }
                )
            owner_id = existing_keys.get(key)
            if owner_id and owner_id != row.id:
                errors.append(
                    {
                        "row": index + 1,
                        "field": "url",
                        "reason": "该平台圈子与列表顺序的来源已存在，请修改原配置",
                    }
                )
            if row.auto_enabled and platform.adapter_status != "available":
                errors.append(
                    {
                        "row": index + 1,
                        "field": "auto_enabled",
                        "reason": f"{platform.display_name}暂未接入，不能启用自动提取",
                    }
                )
            normalized.append(
                {
                    "row": row,
                    "external_id": external_id,
                    "url": url,
                    "list_order": list_order,
                }
            )
        if errors:
            raise DomainError(
                "CIRCLE_BATCH_INVALID",
                "圈子配置存在错误，整批内容均未保存。",
                details=errors,
            )

        with self.factory.begin() as db:
            output = []
            for circle_id in deleted_ids:
                circle = db.get(Circle, circle_id)
                if circle:
                    db.delete(circle)
            if deleted_ids:
                db.flush()
            for item in normalized:
                row = item["row"]
                vehicle_id = row.vehicle_id
                if not vehicle_id:
                    name = row.vehicle_name.strip()
                    vehicle = db.scalar(select(Vehicle).where(Vehicle.name == name))
                    if not vehicle:
                        vehicle = Vehicle(name=name)
                        db.add(vehicle)
                        db.flush()
                    vehicle_id = vehicle.id
                circle = db.get(Circle, row.id) if row.id else None
                changed_identity = bool(
                    circle
                    and (
                        circle.url != item["url"]
                        or circle.platform_code != row.platform_code
                        or circle.section != row.section
                        or circle.list_order != item["list_order"]
                    )
                )
                if not circle:
                    circle = db.scalar(
                        select(Circle).where(
                            Circle.platform_code == row.platform_code,
                            Circle.external_id == item["external_id"],
                            Circle.section == row.section,
                            Circle.list_order == item["list_order"],
                        )
                    )
                if not circle:
                    circle = Circle(
                        platform_code=row.platform_code,
                        external_id=item["external_id"],
                        url=item["url"],
                    )
                    db.add(circle)
                circle.url = item["url"]
                circle.external_id = item["external_id"]
                circle.list_order = item["list_order"]
                circle.vehicle_id = vehicle_id
                circle.source_kind = "configured"
                circle.section = "dynamic"
                if changed_identity:
                    circle.validation_status = "unverified"
                    circle.validation_error = None
                    circle.validated_at = None
                if row.auto_enabled and circle.validation_status != "verified":
                    errors.append(
                        {
                            "row": value.rows.index(row) + 1,
                            "field": "auto_enabled",
                            "reason": "圈子验证通过后才能启用自动提取",
                        }
                    )
                circle.auto_enabled = row.auto_enabled
                output.append(circle)
            if errors:
                raise DomainError(
                    "CIRCLE_BATCH_INVALID",
                    "圈子配置存在错误，整批内容均未保存。",
                    details=errors,
                )
            db.flush()
            response_items = []
            for circle in output:
                vehicle = db.get(Vehicle, circle.vehicle_id) if circle.vehicle_id else None
                response_items.append(
                    dict(self.circle_dict(circle), vehicle_name=vehicle.name if vehicle else None)
                )
            return {
                "items": response_items,
                "saved_count": len(output),
                "deleted_count": len(deleted_ids),
            }

    def list_circles(self) -> list[dict[str, Any]]:
        """返回配置圈子资源列表，并包含前端编辑所需的车型名称。"""

        with self.factory() as db:
            rows = db.execute(
                select(Circle, Vehicle.name)
                .outerjoin(Vehicle, Vehicle.id == Circle.vehicle_id)
                .where(Circle.source_kind == "configured")
                .order_by(Circle.created_at)
            )
            return [
                dict(self.circle_dict(circle), vehicle_name=vehicle_name)
                for circle, vehicle_name in rows
            ]

    def get_circle(self, circle_id: str) -> dict[str, Any]:
        """返回单个配置圈子资源。"""

        with self.factory() as db:
            row = db.execute(
                select(Circle, Vehicle.name)
                .outerjoin(Vehicle, Vehicle.id == Circle.vehicle_id)
                .where(Circle.id == circle_id, Circle.source_kind == "configured")
            ).one_or_none()
            if not row:
                raise DomainError("CIRCLE_NOT_FOUND", "指定圈子不存在。", status_code=404)
            circle, vehicle_name = row
            return dict(self.circle_dict(circle), vehicle_name=vehicle_name)

    def create_circle(self, value: CircleRow) -> dict[str, Any]:
        """创建一个配置圈子，复用批量保存的完整校验。"""

        if value.id:
            raise DomainError("CIRCLE_ID_NOT_ALLOWED", "新增圈子时不应提交圈子 ID。")
        result = self.save_circle_batch(CircleBatchUpdate(rows=[value]))
        return result["items"][0]

    def update_circle(self, circle_id: str, value: CircleRow) -> dict[str, Any]:
        """更新一个配置圈子，复用批量保存的完整校验。"""

        result = self.save_circle_batch(
            CircleBatchUpdate(rows=[value.model_copy(update={"id": circle_id})])
        )
        return result["items"][0]

    def delete_circle(self, circle_id: str) -> dict[str, Any]:
        """删除配置圈子，并保留历史批次内已冻结的圈子信息。"""

        with self.factory() as db:
            circle = db.get(Circle, circle_id)
            if not circle or circle.source_kind != "configured":
                raise DomainError("CIRCLE_NOT_FOUND", "指定圈子不存在。", status_code=404)
            result = self.circle_dict(circle)
        self.save_circle_batch(CircleBatchUpdate(rows=[], deleted_ids=[circle_id]))
        return result

    def list_manual_history(self) -> list[dict[str, Any]]:
        with self.factory() as db:
            items = db.scalars(
                select(Circle)
                .where(Circle.source_kind == "manual_history")
                .order_by(Circle.last_used_at.desc())
            )
            return [self.circle_dict(item) for item in items]

    def delete_manual_history(self, circle_id: str | None = None) -> int:
        with self.factory.begin() as db:
            query = delete(Circle).where(Circle.source_kind == "manual_history")
            if circle_id:
                query = query.where(Circle.id == circle_id)
            result = db.execute(query)
            return result.rowcount or 0

    def create_validation_job(self, circle_id: str) -> dict[str, Any]:
        with self.factory.begin() as db:
            circle = db.get(Circle, circle_id)
            if not circle:
                raise DomainError("CIRCLE_NOT_FOUND", "指定圈子不存在。", status_code=404)
            platform = db.get(PlatformConfig, circle.platform_code)
            if not platform or platform.adapter_status != "available":
                raise DomainError(
                    "PLATFORM_NOT_INTEGRATED",
                    "该平台暂未接入，当前不能验证圈子。",
                    status_code=409,
                )
            existing = db.scalar(
                select(ValidationJob).where(
                    ValidationJob.circle_id == circle_id,
                    ValidationJob.status.in_(["queued", "running", "waiting_for_auth"]),
                )
            )
            job = existing or ValidationJob(circle_id=circle_id)
            db.add(job)
            db.flush()
            return validation_job_dict(job)

    def create_unverified_validation_jobs(self) -> dict[str, Any]:
        """按持久 FIFO 为全部未验证配置圈子创建或复用验证任务。"""

        with self.factory.begin() as db:
            circles = list(
                db.scalars(
                    select(Circle)
                    .where(
                        Circle.source_kind == "configured",
                        Circle.validation_status == "unverified",
                    )
                    .order_by(Circle.created_at, Circle.id)
                )
            )
            jobs: list[ValidationJob] = []
            queued_count = 0
            reused_count = 0
            for circle in circles:
                job = db.scalar(
                    select(ValidationJob).where(
                        ValidationJob.circle_id == circle.id,
                        ValidationJob.status.in_(["queued", "running", "waiting_for_auth"]),
                    )
                )
                if job:
                    reused_count += 1
                else:
                    job = ValidationJob(circle_id=circle.id)
                    db.add(job)
                    queued_count += 1
                jobs.append(job)
            db.flush()
            return {
                "jobs": [validation_job_dict(job) for job in jobs],
                "queued_count": queued_count,
                "reused_count": reused_count,
                "total_count": len(jobs),
            }


def validation_job_dict(job: ValidationJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "circle_id": job.circle_id,
        "status": job.status,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "result": job.result,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


class RunService:
    """手动、定时和手动补提批次服务。"""

    def __init__(self, factory: sessionmaker[Session], timezone_name: str = "Asia/Shanghai"):
        self.factory = factory
        self.timezone = ZoneInfo(timezone_name)

    def _number(self, db: Session) -> str:
        now = datetime.now(self.timezone)
        start_local = now.replace(microsecond=0)
        start_utc = start_local.astimezone(timezone.utc)
        count = (
            db.scalar(
                select(func.count())
                .select_from(ExtractionRun)
                .where(
                    ExtractionRun.created_at >= start_utc,
                    ExtractionRun.created_at < start_utc + timedelta(seconds=1),
                )
            )
            or 0
        )
        return f"{now:%Y%m%d-%H%M%S}-{count + 1:03d}"

    @staticmethod
    def _next_queue_sequence(db: Session) -> int:
        return (
            int(db.scalar(select(func.coalesce(func.max(CircleTask.queue_sequence), 0))) or 0) + 1
        )

    def _idempotent_existing(
        self, db: Session, scope: str, key: str, request_hash: str
    ) -> ExtractionRun | None:
        run = db.scalar(
            select(ExtractionRun).where(
                ExtractionRun.idempotency_scope == scope,
                ExtractionRun.idempotency_key == key,
            )
        )
        if run and run.request_hash != request_hash:
            raise DomainError(
                "IDEMPOTENCY_CONFLICT",
                "该幂等键已经用于不同的提取请求。",
                status_code=409,
            )
        return run

    def create_manual(
        self, value: ManualRunCreate, *, scope: str, header_key: str | None = None
    ) -> dict[str, Any]:
        key = header_key or value.idempotency_key
        if not key:
            raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "提交手动提取时必须提供幂等键。")
        payload = value.model_dump(exclude={"idempotency_key"})
        request_hash = canonical_hash(payload)
        with self.factory.begin() as db:
            existing = self._idempotent_existing(db, scope, key, request_hash)
            if existing:
                result = run_dict(db, existing)
                result["message"] = "该提取任务已提交。"
                result["already_submitted"] = True
                return result
            platform = db.get(PlatformConfig, value.platform_code)
            if not platform:
                raise DomainError("PLATFORM_NOT_FOUND", "指定平台不存在。", status_code=404)
            if platform.adapter_status != "available":
                raise DomainError(
                    "PLATFORM_NOT_INTEGRATED",
                    f"{platform.display_name}暂未接入，当前不能提取。",
                    status_code=409,
                )
            if not platform.enabled:
                raise DomainError(
                    "PLATFORM_DISABLED",
                    f"{platform.display_name}当前已停用，不能创建新的提取任务。",
                    status_code=409,
                )
            quantity = min(max(value.quantity, platform.min_quantity), platform.max_quantity)
            circles: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()
            for circle_id in value.circle_ids:
                circle = db.get(Circle, circle_id)
                if not circle or circle.platform_code != value.platform_code:
                    raise DomainError(
                        "CIRCLE_NOT_FOUND",
                        "手动提取包含不存在或平台不匹配的圈子。",
                        details=[{"circle_id": circle_id}],
                    )
                source_key = (circle.external_id, circle.list_order)
                if source_key in seen:
                    continue
                seen.add(source_key)
                circles.append(
                    {
                        "circle": circle,
                        "external_id": circle.external_id,
                        "url": circle.url,
                        "name": circle.name,
                        "list_order": circle.list_order,
                        "transient": False,
                    }
                )
            for raw_url in value.circle_urls:
                try:
                    if value.platform_code == "dongchedi":
                        source = parse_circle_url(raw_url)
                        external_id, url, list_order = (
                            source.external_id,
                            source.url,
                            source.list_order,
                        )
                    else:
                        external_id, url, list_order = raw_url, raw_url, "latest_reply"
                except CollectorFailure as exc:
                    raise DomainError(exc.code, exc.message) from exc
                source_key = (external_id, list_order)
                if source_key in seen:
                    continue
                seen.add(source_key)
                stored = db.scalar(
                    select(Circle).where(
                        Circle.platform_code == value.platform_code,
                        Circle.external_id == external_id,
                        Circle.section == "dynamic",
                        Circle.list_order == list_order,
                    )
                )
                circles.append(
                    {
                        "circle": stored,
                        "external_id": external_id,
                        "url": url,
                        "name": stored.name if stored else None,
                        "list_order": list_order,
                        "transient": stored is None,
                    }
                )
            normalized_posts: list[str] = []
            for raw_url in value.known_post_urls:
                try:
                    _, normalized = normalize_post_url(raw_url)
                except CollectorFailure as exc:
                    raise DomainError(exc.code, exc.message) from exc
                if normalized not in normalized_posts:
                    normalized_posts.append(normalized)
            if not circles and not normalized_posts:
                raise DomainError(
                    "RUN_INPUT_EMPTY",
                    "至少选择一个圈子、输入一个圈子链接或导入一个帖子链接。",
                )
            run = ExtractionRun(
                number=self._number(db),
                trigger_type="manual",
                input_mode="url_list" if normalized_posts and not circles else "circle_discovery",
                status="queued",
                idempotency_scope=scope,
                idempotency_key=key,
                request_hash=request_hash,
                config_snapshot={
                    "platform_code": value.platform_code,
                    "quantity": quantity,
                    "requested_quantity": value.quantity,
                },
            )
            db.add(run)
            db.flush()
            sequence = self._next_queue_sequence(db)
            for source_position, item in enumerate(circles):
                circle = item["circle"]
                vehicle_name = circle.vehicle.name if circle and circle.vehicle else None
                task = CircleTask(
                    run_id=run.id,
                    circle_id=circle.id if circle else None,
                    platform_code=value.platform_code,
                    external_id=item["external_id"],
                    circle_name=item["name"],
                    circle_url=item["url"],
                    list_order=item["list_order"],
                    target_count=quantity,
                    queue_sequence=sequence,
                    source_position=source_position,
                    config_snapshot={
                        "quantity": quantity,
                        "internal_concurrency": platform.internal_concurrency,
                        "vehicle_name": vehicle_name,
                        "source_name": vehicle_name,
                        "transient": item["transient"],
                    },
                )
                db.add(task)
                sequence += 1
            if normalized_posts:
                db.add(
                    CircleTask(
                        run_id=run.id,
                        platform_code=value.platform_code,
                        external_id="known-url-list",
                        circle_name="导入帖子链接",
                        circle_url="",
                        target_count=len(normalized_posts),
                        queue_sequence=sequence,
                        source_position=len(circles),
                        config_snapshot={
                            "known_post_urls": normalized_posts,
                            "internal_concurrency": platform.internal_concurrency,
                        },
                    )
                )
            run.planned_count = quantity * len(circles) + len(normalized_posts)
            db.flush()
            result = run_dict(db, run)
            result["already_submitted"] = False
            if quantity != value.quantity:
                result["message"] = f"提取数量已自动收敛为平台安全值 {quantity}，任务已提交。"
            else:
                result["message"] = "提取任务已提交。"
            return result

    def create_scheduled(
        self, planned_at: datetime, schedule_node_id: str, schedule_revision: int
    ) -> dict[str, Any] | None:
        key = f"{schedule_node_id}:{planned_at.astimezone(timezone.utc).isoformat()}"
        with self.factory.begin() as db:
            node = db.get(ScheduleNode, schedule_node_id)
            if not node or not node.enabled:
                return None
            rule_refs = list(
                db.scalars(
                    select(ScheduleNodeRule)
                    .where(ScheduleNodeRule.schedule_node_id == schedule_node_id)
                    .order_by(ScheduleNodeRule.position)
                )
            )
            rules_by_id = {
                item.id: item
                for item in db.scalars(
                    select(ExtractionRule).where(
                        ExtractionRule.id.in_([item.rule_id for item in rule_refs])
                    )
                )
            }
            unavailable_rule_ids = [
                item.rule_id
                for item in rule_refs
                if item.rule_id not in rules_by_id or rules_by_id[item.rule_id].archived
            ]
            if not rule_refs or unavailable_rule_ids:
                db.add(
                    ScheduleEvent(
                        planned_at=planned_at,
                        schedule_node_id=schedule_node_id,
                        schedule_revision=schedule_revision,
                        extraction_rule_id=rule_refs[0].rule_id if len(rule_refs) == 1 else None,
                        rule_snapshots=[{"id": item.rule_id} for item in rule_refs],
                        status="blocked",
                        message="计划节点引用的部分提取规则当前不可用，整次触发已阻止。",
                    )
                )
                return None
            ordered_rules = [rules_by_id[item.rule_id] for item in rule_refs]
            current_versions = {
                (item.rule_id, item.version): item
                for item in db.scalars(
                    select(ExtractionRuleVersion).where(
                        ExtractionRuleVersion.rule_id.in_([item.id for item in ordered_rules])
                    )
                )
            }
            if any((rule.id, rule.current_version) not in current_versions for rule in ordered_rules):
                return None
            rule_snapshots = [
                {
                    "id": rule.id,
                    "name": rule.name,
                    "version": rule.current_version,
                    "platform_quantities": current_versions[
                        (rule.id, rule.current_version)
                    ].platform_quantities,
                    "circle_ids": list(
                        dict.fromkeys(
                            current_versions[(rule.id, rule.current_version)].selected_circle_ids
                        )
                    ),
                }
                for rule in ordered_rules
            ]
            request_hash = canonical_hash(
                {
                    "planned_at": planned_at.isoformat(),
                    "schedule_node_id": schedule_node_id,
                    "schedule_revision": schedule_revision,
                    "rules": [
                        {"id": item["id"], "version": item["version"]}
                        for item in rule_snapshots
                    ],
                }
            )
            existing = self._idempotent_existing(db, "scheduler", key, request_hash)
            if existing:
                return run_dict(db, existing)
            platforms = {
                x.code: x
                for x in db.scalars(
                    select(PlatformConfig).where(
                        PlatformConfig.enabled.is_(True),
                        PlatformConfig.adapter_status == "available",
                    )
                )
            }
            selected_circle_ids = list(
                dict.fromkeys(
                    circle_id
                    for snapshot in rule_snapshots
                    for circle_id in snapshot["circle_ids"]
                )
            )
            circles = (
                list(
                    db.scalars(
                        select(Circle)
                        .where(
                            Circle.id.in_(selected_circle_ids),
                            Circle.auto_enabled.is_(True),
                            Circle.validation_status == "verified",
                        )
                        .order_by(Circle.platform_code, Circle.created_at)
                    )
                )
                if selected_circle_ids
                else []
            )
            circles = [item for item in circles if item.platform_code in platforms]
            circles_by_id = {item.id: item for item in circles}
            contributions: dict[str, list[dict[str, Any]]] = {}
            missing: list[dict[str, Any]] = []
            for snapshot in rule_snapshots:
                quantities = snapshot["platform_quantities"]
                for circle_id in snapshot["circle_ids"]:
                    circle = circles_by_id.get(circle_id)
                    if not circle:
                        continue
                    if circle.platform_code not in quantities:
                        missing.append(
                            {"rule_id": snapshot["id"], "platform_code": circle.platform_code}
                        )
                        continue
                    contributions.setdefault(circle_id, []).append(
                        {
                            "rule_id": snapshot["id"],
                            "rule_version": snapshot["version"],
                            "quantity": int(quantities[circle.platform_code]),
                        }
                    )
            if missing:
                db.add(
                    ScheduleEvent(
                        planned_at=planned_at,
                        schedule_node_id=schedule_node_id,
                        schedule_revision=schedule_revision,
                        extraction_rule_id=(
                            rule_snapshots[0]["id"] if len(rule_snapshots) == 1 else None
                        ),
                        extraction_rule_version=(
                            rule_snapshots[0]["version"] if len(rule_snapshots) == 1 else None
                        ),
                        rule_snapshots=rule_snapshots,
                        status="blocked",
                        message="所选规则缺少已选平台数量，整次节点触发已阻止。",
                    )
                )
                return None
            resolved_circles = [item for item in circles if contributions.get(item.id)]
            if not resolved_circles:
                db.add(
                    ScheduleEvent(
                        planned_at=planned_at,
                        schedule_node_id=schedule_node_id,
                        schedule_revision=schedule_revision,
                        extraction_rule_id=(
                            rule_snapshots[0]["id"] if len(rule_snapshots) == 1 else None
                        ),
                        extraction_rule_version=(
                            rule_snapshots[0]["version"] if len(rule_snapshots) == 1 else None
                        ),
                        rule_snapshots=rule_snapshots,
                        status="skipped",
                        message="所选规则当前没有可执行的已验证且全局启用圈子。",
                    )
                )
                return None
            legacy_rule = rule_snapshots[0] if len(rule_snapshots) == 1 else None
            run = ExtractionRun(
                number=self._number(db),
                trigger_type="scheduled",
                input_mode="circle_discovery",
                status="queued",
                idempotency_scope="scheduler",
                idempotency_key=key,
                request_hash=request_hash,
                schedule_node_id=schedule_node_id,
                extraction_rule_id=legacy_rule["id"] if legacy_rule else None,
                extraction_rule_version=legacy_rule["version"] if legacy_rule else None,
                config_snapshot={
                    "planned_at": planned_at.isoformat(),
                    "schedule_node_id": schedule_node_id,
                    "schedule_revision": schedule_revision,
                    "rules": rule_snapshots,
                    "resolved_circles": [
                        {
                            "circle_id": circle.id,
                            "target_count": max(
                                item["quantity"] for item in contributions[circle.id]
                            ),
                            "source_rules": contributions[circle.id],
                        }
                        for circle in resolved_circles
                    ],
                },
            )
            db.add(run)
            db.flush()
            for position, snapshot in enumerate(rule_snapshots):
                db.add(
                    ExtractionRunRule(
                        run_id=run.id,
                        rule_id=snapshot["id"],
                        rule_version=snapshot["version"],
                        position=position,
                    )
                )
            sequence = self._next_queue_sequence(db)
            for source_position, circle in enumerate(resolved_circles):
                platform = platforms[circle.platform_code]
                source_rules = contributions[circle.id]
                quantity = max(item["quantity"] for item in source_rules)
                db.add(
                    CircleTask(
                        run_id=run.id,
                        circle_id=circle.id,
                        platform_code=circle.platform_code,
                        external_id=circle.external_id,
                        circle_name=circle.name,
                        circle_url=circle.url,
                        section=circle.section,
                        list_order=circle.list_order,
                        target_count=quantity,
                        queue_sequence=sequence,
                        source_position=source_position,
                        config_snapshot={
                            "quantity": quantity,
                            "internal_concurrency": platform.internal_concurrency,
                            "vehicle_name": circle.vehicle.name if circle.vehicle else None,
                            "source_name": circle.vehicle.name if circle.vehicle else None,
                            "source_rules": source_rules,
                        },
                    )
                )
                run.planned_count += quantity
                sequence += 1
            db.add(
                ScheduleEvent(
                    planned_at=planned_at,
                    schedule_node_id=schedule_node_id,
                    schedule_revision=schedule_revision,
                    extraction_rule_id=legacy_rule["id"] if legacy_rule else None,
                    extraction_rule_version=legacy_rule["version"] if legacy_rule else None,
                    rule_snapshots=rule_snapshots,
                    status="created",
                    message=f"定时提取批次已按 {len(rule_snapshots)} 条规则合并创建。",
                    run_id=run.id,
                )
            )
            db.flush()
            return run_dict(db, run)

    def retry(self, run_id: str, key: str, scope: str) -> dict[str, Any]:
        with self.factory() as db:
            original = db.get(ExtractionRun, run_id)
            if not original:
                raise DomainError("RUN_NOT_FOUND", "指定提取批次不存在。", status_code=404)
            if original.status not in {"partial_success", "failed"}:
                raise DomainError(
                    "RUN_RETRY_NOT_ALLOWED",
                    "只有部分成功或失败的终态批次可以重新提取。",
                    status_code=409,
                )
            tasks = list(
                db.scalars(
                    select(CircleTask)
                    .where(CircleTask.run_id == run_id)
                    .order_by(CircleTask.queue_sequence)
                )
            )
            selected = [task for task in tasks if task.status != "success"]
            platform_codes = {task.platform_code for task in selected}
            if len(platform_codes) != 1:
                raise DomainError(
                    "RUN_RETRY_PLATFORM_INVALID",
                    "一次手动补提只能包含一个平台。",
                    status_code=409,
                )
            platform_code = next(iter(platform_codes))
            snapshot = []
            for task in selected:
                failed_urls = []
                source_indexes: dict[str, int] = {}
                for failure in (task.checkpoint or {}).get("failed_urls", []):
                    url = failure.get("url") if isinstance(failure, dict) else None
                    if isinstance(url, str) and url and url not in failed_urls:
                        failed_urls.append(url)
                        source_indexes[url] = int(failure.get("source_index", len(source_indexes)))
                if failed_urls:
                    snapshot.append(
                        {
                            "circle_id": task.circle_id,
                            "external_id": task.external_id,
                            "url": task.circle_url,
                            "name": task.circle_name,
                            "list_order": task.list_order,
                            "target_count": len(failed_urls),
                            "source_position": task.source_position,
                            "config_snapshot": {
                                **(task.config_snapshot or {}),
                                "known_post_urls": failed_urls,
                                "source_indexes": source_indexes,
                                "retry_of_task_id": task.id,
                            },
                        }
                    )
            if not snapshot:
                raise DomainError(
                    "RUN_RETRY_URL_EMPTY",
                    "该批次没有可供手动补提的失败 URL。",
                    status_code=409,
                )
        request_hash = canonical_hash({"original_run_id": run_id, "tasks": snapshot})
        with self.factory.begin() as db:
            existing = self._idempotent_existing(db, scope, key, request_hash)
            if existing:
                result = run_dict(db, existing)
                result.update({"already_submitted": True, "message": "该提取任务已提交。"})
                return result
            platform = db.get(PlatformConfig, platform_code)
            if not platform or not platform.enabled:
                raise DomainError(
                    "PLATFORM_DISABLED",
                    "平台重新启用后才能创建手动补提。",
                    status_code=409,
                )
            run = ExtractionRun(
                number=self._number(db),
                trigger_type="manual",
                input_mode="circle_discovery",
                status="queued",
                idempotency_scope=scope,
                idempotency_key=key,
                request_hash=request_hash,
                related_run_id=run_id,
                config_snapshot={"retry_of": run_id},
            )
            db.add(run)
            db.flush()
            sequence = self._next_queue_sequence(db)
            for item in snapshot:
                task = CircleTask(
                    run_id=run.id,
                    circle_id=item["circle_id"],
                    platform_code=platform_code,
                    external_id=item["external_id"],
                    circle_name=item["name"],
                    circle_url=item["url"],
                    list_order=item["list_order"],
                    target_count=item["target_count"],
                    queue_sequence=sequence,
                    source_position=item["source_position"],
                    config_snapshot=item["config_snapshot"],
                )
                db.add(task)
                run.planned_count += task.target_count
                sequence += 1
            db.flush()
            result = run_dict(db, run)
            result.update({"already_submitted": False, "message": "手动补提任务已提交。"})
            return result

    def list_runs(
        self,
        offset: int = 0,
        limit: int = 50,
        *,
        number: str | None = None,
        statuses: list[str] | None = None,
        trigger_type: str | None = None,
        list_order: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> dict[str, Any]:
        with self.factory() as db:
            conditions = []
            if number:
                conditions.append(ExtractionRun.number.ilike(f"%{number.strip()}%"))
            if statuses:
                conditions.append(ExtractionRun.status.in_(statuses))
            if trigger_type:
                conditions.append(ExtractionRun.trigger_type == trigger_type)
            if list_order:
                conditions.extend(
                    [
                        ExtractionRun.input_mode == "circle_discovery",
                        select(CircleTask.id)
                        .where(
                            CircleTask.run_id == ExtractionRun.id,
                            CircleTask.circle_url != "",
                            CircleTask.list_order == list_order,
                        )
                        .exists(),
                    ]
                )
            if created_from:
                conditions.append(ExtractionRun.created_at >= created_from)
            if created_to:
                conditions.append(ExtractionRun.created_at <= created_to)
            total = (
                db.scalar(select(func.count()).select_from(ExtractionRun).where(*conditions)) or 0
            )
            runs = list(
                db.scalars(
                    select(ExtractionRun)
                    .where(*conditions)
                    .order_by(ExtractionRun.created_at.desc(), ExtractionRun.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            run_ids = [item.id for item in runs]
            tasks = (
                list(
                    db.scalars(
                        select(CircleTask)
                        .where(CircleTask.run_id.in_(run_ids))
                        .order_by(CircleTask.queue_sequence)
                    )
                )
                if run_ids
                else []
            )
            grouped: dict[str, list[CircleTask]] = {}
            for task in tasks:
                grouped.setdefault(task.run_id, []).append(task)
            queued = list(
                db.scalars(
                    select(CircleTask)
                    .where(CircleTask.status == "queued")
                    .order_by(CircleTask.platform_code, CircleTask.queue_sequence)
                )
            )
            return {
                "items": [
                    run_dict_from_tasks(item, grouped.get(item.id, []), queued) for item in runs
                ],
                "total": total,
                "offset": offset,
                "limit": limit,
            }

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.factory() as db:
            run = db.get(ExtractionRun, run_id)
            if not run:
                raise DomainError("RUN_NOT_FOUND", "指定提取批次不存在。", status_code=404)
            return run_dict(db, run, include_tasks=True)

    def end_auth_wait(self, run_id: str) -> dict[str, Any]:
        with self.factory.begin() as db:
            run = db.get(ExtractionRun, run_id)
            if not run:
                raise DomainError("RUN_NOT_FOUND", "指定提取批次不存在。", status_code=404)
            if run.status != "waiting_for_auth":
                raise DomainError(
                    "RUN_NOT_WAITING_FOR_AUTH",
                    "该批次当前不处于等待平台认证状态。",
                    status_code=409,
                )
            for task in db.scalars(
                select(CircleTask).where(
                    CircleTask.run_id == run_id, CircleTask.status == "waiting_for_auth"
                )
            ):
                task.status = "partial_success" if task.completed_count else "failed"
                task.error_code = "AUTH_WAIT_ENDED"
                task.error_message = "用户结束了本次等待平台认证的提取。"
                task.finished_at = utc_now()
            aggregate_run(db, run)
            db.flush()
            return run_dict(db, run, include_tasks=True)

    def delete_run(self, run_id: str) -> list[str]:
        with self.factory.begin() as db:
            run = db.get(ExtractionRun, run_id)
            if not run:
                raise DomainError("RUN_NOT_FOUND", "指定提取批次不存在。", status_code=404)
            if run.status not in TERMINAL_STATUSES:
                raise DomainError(
                    "RUN_DELETE_NOT_ALLOWED",
                    "只有成功、部分成功或失败的终态批次可以永久删除。",
                    status_code=409,
                )
            paths = [
                item
                for item in db.scalars(
                    select(ExportRecord.file_path).where(ExportRecord.run_id == run_id)
                )
                if item
            ]
            db.delete(run)
            return paths

    @staticmethod
    def _ranked_posts(
        db: Session,
        run_id: str,
        *,
        title: str | None = None,
        circle: str | None = None,
        visibility: str | None = None,
    ):
        run_ids = related_run_ids(db, run_id)
        conditions = [PostSnapshot.run_id.in_(run_ids)]
        if title:
            conditions.append(PostSnapshot.title.ilike(f"%{title.strip()}%"))
        if circle:
            text = f"%{circle.strip()}%"
            conditions.append(
                or_(CircleTask.circle_name.ilike(text), CircleTask.external_id.ilike(text))
            )
        if visibility:
            conditions.append(PostSnapshot.visibility == visibility)
        return (
            select(
                PostSnapshot.id.label("post_id"),
                PostSnapshot.published_at,
                PostSnapshot.reply_count,
                PostSnapshot.like_count,
                CircleTask.source_position,
                PostSnapshot.order_index,
                func.row_number()
                .over(
                    partition_by=(
                        CircleTask.platform_code,
                        CircleTask.external_id,
                        PostSnapshot.platform_post_id,
                    ),
                    order_by=(
                        CircleTask.source_position,
                        PostSnapshot.order_index,
                        PostSnapshot.created_at,
                    ),
                )
                .label("dedupe_rank"),
            )
            .join(CircleTask, CircleTask.id == PostSnapshot.circle_task_id)
            .where(*conditions)
            .subquery()
        )

    def _filtered_post_ids(
        self,
        db: Session,
        run_id: str,
        *,
        title: str | None = None,
        circle: str | None = None,
        visibility: str | None = None,
        sort_by: str = "source",
        sort_direction: str = "asc",
    ) -> tuple[Any, int]:
        ranked = self._ranked_posts(db, run_id, title=title, circle=circle, visibility=visibility)
        total = (
            db.scalar(select(func.count()).select_from(ranked).where(ranked.c.dedupe_rank == 1))
            or 0
        )
        sort_column = {
            "published_at": ranked.c.published_at,
            "reply_count": ranked.c.reply_count,
            "like_count": ranked.c.like_count,
        }.get(sort_by)
        if sort_column is None:
            direction = "desc" if sort_direction == "desc" else "asc"
            order = tuple(
                getattr(column, direction)()
                for column in (
                    ranked.c.source_position,
                    ranked.c.order_index,
                    ranked.c.post_id,
                )
            )
        else:
            direction = sort_column.desc if sort_direction == "desc" else sort_column.asc
            order = (direction().nulls_last(), ranked.c.source_position, ranked.c.order_index)
        query = select(ranked.c.post_id).where(ranked.c.dedupe_rank == 1).order_by(*order)
        return query, int(total)

    def posts(
        self,
        run_id: str,
        offset: int = 0,
        limit: int = 100,
        *,
        title: str | None = None,
        circle: str | None = None,
        visibility: str | None = None,
        sort_by: str = "source",
        sort_direction: str = "asc",
    ) -> dict[str, Any]:
        with self.factory() as db:
            if not db.get(ExtractionRun, run_id):
                raise DomainError("RUN_NOT_FOUND", "指定提取批次不存在。", status_code=404)
            id_query, total = self._filtered_post_ids(
                db,
                run_id,
                title=title,
                circle=circle,
                visibility=visibility,
                sort_by=sort_by,
                sort_direction=sort_direction,
            )
            post_ids = list(db.scalars(id_query.offset(offset).limit(limit)))
            post_map = {
                item.id: item
                for item in db.scalars(select(PostSnapshot).where(PostSnapshot.id.in_(post_ids)))
            }
            posts = [post_map[item] for item in post_ids if item in post_map]
            task_ids = [item.circle_task_id for item in posts]
            tasks = {
                item.id: item
                for item in db.scalars(select(CircleTask).where(CircleTask.id.in_(task_ids)))
            }
            comments = (
                list(
                    db.scalars(
                        select(CommentSnapshot)
                        .where(CommentSnapshot.post_id.in_([x.id for x in posts]))
                        .order_by(CommentSnapshot.post_id, CommentSnapshot.order_index)
                    )
                )
                if posts
                else []
            )
            grouped: dict[str, list[dict[str, Any]]] = {}
            for item in comments:
                grouped.setdefault(item.post_id, []).append(comment_dict(item))
            return {
                "items": [
                    post_dict(item, grouped.get(item.id, []), tasks.get(item.circle_task_id))
                    for item in posts
                ],
                "total": total,
                "offset": offset,
                "limit": limit,
            }

    def post_detail(self, run_id: str, post_id: str) -> dict[str, Any]:
        with self.factory() as db:
            if not db.get(ExtractionRun, run_id):
                raise DomainError("RUN_NOT_FOUND", "指定提取批次不存在。", status_code=404)
            post = db.get(PostSnapshot, post_id)
            if not post or post.run_id not in related_run_ids(db, run_id):
                raise DomainError("POST_NOT_FOUND", "指定帖子快照不存在。", status_code=404)
            task = db.get(CircleTask, post.circle_task_id)
            comments = [
                comment_dict(item)
                for item in db.scalars(
                    select(CommentSnapshot)
                    .where(CommentSnapshot.post_id == post.id)
                    .order_by(CommentSnapshot.order_index)
                )
            ]
            return post_dict(post, comments, task)

    def post_navigation(self, run_id: str, post_id: str, **filters: Any) -> dict[str, Any]:
        """返回帖子在当前完整筛选和排序结果中的相邻项。"""

        with self.factory() as db:
            if not db.get(ExtractionRun, run_id):
                raise DomainError("RUN_NOT_FOUND", "指定提取批次不存在。", status_code=404)
            id_query, total = self._filtered_post_ids(db, run_id, **filters)
            ids = list(db.scalars(id_query))
            try:
                index = ids.index(post_id)
            except ValueError as error:
                raise DomainError(
                    "POST_NOT_IN_RESULT",
                    "指定帖子不在当前筛选结果中。",
                    status_code=404,
                ) from error
            return {
                "previous_id": ids[index - 1] if index > 0 else None,
                "next_id": ids[index + 1] if index + 1 < len(ids) else None,
                "position": index + 1,
                "total": total,
            }

    def post_urls(self, run_id: str, **filters: Any) -> dict[str, Any]:
        with self.factory() as db:
            if not db.get(ExtractionRun, run_id):
                raise DomainError("RUN_NOT_FOUND", "指定提取批次不存在。", status_code=404)
            id_query, total = self._filtered_post_ids(db, run_id, **filters)
            ids = list(db.scalars(id_query))
            rows = db.execute(
                select(PostSnapshot.id, PostSnapshot.url).where(PostSnapshot.id.in_(ids))
            ).all()
            by_id = {row.id: row.url for row in rows}
            urls: list[str] = []
            seen: set[str] = set()
            for post_id in ids:
                url = by_id.get(post_id)
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
            return {"urls": urls, "total": total}


def run_dict_from_tasks(
    run: ExtractionRun, tasks: list[CircleTask], queued_tasks: list[CircleTask] | None = None
) -> dict[str, Any]:
    """使用已集合加载的任务构造批次摘要，避免列表逐行查询。"""

    queue_position = None
    queued_sequences = [task.queue_sequence for task in tasks if task.status == "queued"]
    if queued_sequences and tasks:
        earliest = min(queued_sequences)
        queue_position = 1 + sum(
            1
            for item in (queued_tasks or [])
            if item.platform_code == tasks[0].platform_code and item.queue_sequence < earliest
        )
    extraction_rules = run.config_snapshot.get("rules", [])
    if not extraction_rules and run.extraction_rule_id and run.extraction_rule_version:
        extraction_rules = [
            {"id": run.extraction_rule_id, "version": run.extraction_rule_version}
        ]
    list_orders = list(
        dict.fromkeys(task.list_order for task in tasks if task.circle_url)
    )
    return {
        "id": run.id,
        "number": run.number,
        "trigger_type": run.trigger_type,
        "trigger_type_name": TRIGGER_ZH.get(run.trigger_type, run.trigger_type),
        "input_mode": run.input_mode,
        "status": run.status,
        "status_name": RUN_STATUS_ZH.get(run.status, run.status),
        "queue_position": queue_position,
        "platform_count": len({task.platform_code for task in tasks}),
        "platform_codes": sorted({task.platform_code for task in tasks}),
        "circle_count": len(tasks),
        "circle_names": [task.circle_name or task.external_id for task in tasks[:3]],
        "source_names": [task_source_name(task) for task in tasks[:3]],
        "list_orders": list_orders,
        "list_order_names": [
            "最新发布" if item == "latest_publish" else "最新回复"
            for item in list_orders
        ],
        "planned_count": run.planned_count,
        "completed_count": run.completed_count,
        "failed_count": run.failed_count,
        "waiting_reason": run.waiting_reason,
        "error_message": run.error_message,
        "related_run_id": run.related_run_id,
        "schedule_node_id": run.schedule_node_id,
        "extraction_rule_id": run.extraction_rule_id,
        "extraction_rule_version": run.extraction_rule_version,
        "extraction_rules": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "version": item.get("version"),
            }
            for item in extraction_rules
            if isinstance(item, dict)
        ],
        "summary_version": run.summary_version,
        "created_at": run.created_at,
        "queued_at": run.queued_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def run_dict(db: Session, run: ExtractionRun, include_tasks: bool = False) -> dict[str, Any]:
    tasks = list(
        db.scalars(
            select(CircleTask)
            .where(CircleTask.run_id == run.id)
            .order_by(CircleTask.queue_sequence)
        )
    )
    queue_position = None
    queued_sequences = [task.queue_sequence for task in tasks if task.status == "queued"]
    if queued_sequences:
        earliest = min(queued_sequences)
        queue_position = (
            db.scalar(
                select(func.count())
                .select_from(CircleTask)
                .where(
                    CircleTask.platform_code == tasks[0].platform_code,
                    CircleTask.status == "queued",
                    CircleTask.queue_sequence < earliest,
                )
            )
            or 0
        ) + 1
    result = run_dict_from_tasks(run, tasks)
    result["queue_position"] = queue_position
    if include_tasks:
        result["tasks"] = [task_dict(task) for task in tasks]
    return result


def task_dict(item: CircleTask) -> dict[str, Any]:
    return {
        "id": item.id,
        "platform_code": item.platform_code,
        "circle_id": item.circle_id,
        "external_id": item.external_id,
        "circle_name": item.circle_name,
        "source_name": task_source_name(item),
        "circle_url": item.circle_url,
        "list_order": item.list_order,
        "list_order_name": "最新发布" if item.list_order == "latest_publish" else "最新回复",
        "status": item.status,
        "status_name": RUN_STATUS_ZH.get(item.status, item.status),
        "target_count": item.target_count,
        "completed_count": item.completed_count,
        "failed_count": item.failed_count,
        "error_code": item.error_code,
        "error_message": item.error_message,
        "stop_reason": item.stop_reason,
        "created_at": item.created_at,
        "started_at": item.started_at,
        "finished_at": item.finished_at,
    }


def post_dict(
    item: PostSnapshot,
    comments: list[dict[str, Any]],
    task: CircleTask | None = None,
) -> dict[str, Any]:
    return {
        "id": item.id,
        "run_id": item.run_id,
        "circle_task_id": item.circle_task_id,
        "platform_code": task.platform_code if task else None,
        "circle_id": task.circle_id if task else None,
        "circle_name": (task.circle_name or task.external_id) if task else None,
        "source_name": task_source_name(task) if task else None,
        "platform_post_id": item.platform_post_id,
        "url": item.url,
        "title": item.title,
        "author": item.author,
        "published_at": item.published_at,
        "content": item.content,
        "image_urls": item.image_urls,
        "video_urls": item.video_urls,
        "reply_count": item.reply_count,
        "like_count": item.like_count,
        "section": item.section,
        "visibility": item.visibility,
        "raw_status": item.raw_status,
        "order_index": item.order_index,
        "comments": comments,
    }


def task_source_name(task: CircleTask) -> str:
    """返回批次创建时冻结的用户来源名称，旧任务使用可辨识回退。"""

    snapshot = task.config_snapshot or {}
    configured = snapshot.get("source_name") or snapshot.get("vehicle_name")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    base = task.circle_name or task.external_id
    order = "最新发布" if task.list_order == "latest_publish" else "最新回复"
    return f"{base} · {order}"


def comment_dict(item: CommentSnapshot) -> dict[str, Any]:
    return {
        "platform_comment_id": item.platform_comment_id,
        "author": item.author,
        "content": item.content,
        "published_at": item.published_at,
        "like_count": item.like_count,
        "order_index": item.order_index,
    }


def aggregate_run(db: Session, run: ExtractionRun) -> None:
    tasks = list(db.scalars(select(CircleTask).where(CircleTask.run_id == run.id)))
    run.completed_count = sum(item.completed_count for item in tasks)
    run.failed_count = sum(item.failed_count for item in tasks)
    statuses = {item.status for item in tasks}
    if "waiting_for_auth" in statuses:
        run.status = "waiting_for_auth"
        run.waiting_reason = next(
            (item.error_message for item in tasks if item.status == "waiting_for_auth"),
            "等待平台认证。",
        )
        return
    if statuses & {"running", "queued"}:
        run.status = "running" if "running" in statuses else "queued"
        return
    if tasks and all(item.status == "success" for item in tasks):
        run.status = "success"
    elif run.completed_count > 0:
        run.status = "partial_success"
    else:
        run.status = "failed"
    run.finished_at = utc_now()
    run.waiting_reason = None
    run.summary_version += 1
