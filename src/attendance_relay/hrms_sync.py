from __future__ import annotations

from typing import Any

from attendance_relay.middleware_repository import MiddlewareRepository
from attendance_relay.repository import AttendanceRepository


def list_unmapped_machine_users(
    repo: AttendanceRepository,
    *,
    device_id: str | None = None,
    machine_ip: str | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    rows = repo.list_machine_user_registry(
        device_id=device_id or None,
        machine_ip=machine_ip or None,
        limit=limit,
    )
    unmapped: list[dict[str, Any]] = []
    for row in rows:
        user_id = int(row.get("user_id", -1))
        employee_code = str(row.get("employee_code") or "").strip()
        is_auto_code = employee_code == str(user_id)
        if is_auto_code:
            unmapped.append(
                {
                    **row,
                    "mapping_status": "unmapped",
                    "suggested_employee_code": employee_code,
                }
            )
    return unmapped


def build_reconcile_report(
    repo: AttendanceRepository,
    *,
    device_id: str,
    machine_ip: str | None = None,
    limit: int = 5000,
) -> dict[str, Any]:
    registry = repo.list_machine_user_registry(device_id=device_id, machine_ip=machine_ip, limit=limit)
    unmapped = list_unmapped_machine_users(repo, device_id=device_id, machine_ip=machine_ip, limit=limit)
    mapped_count = len(registry) - len(unmapped)
    master_count = repo.count_employee_master()
    return {
        "device_id": device_id,
        "machine_ip": machine_ip,
        "registry_total": len(registry),
        "mapped": mapped_count,
        "unmapped": len(unmapped),
        "employee_master_total": master_count,
        "unmapped_rows": unmapped[: min(50, len(unmapped))],
    }


def build_sync_status(
    *,
    repo: AttendanceRepository,
    middleware_repo: MiddlewareRepository,
) -> dict[str, Any]:
    devices = middleware_repo.list_devices()
    device_summaries: list[dict[str, Any]] = []
    for device in devices:
        device_id = str(device.get("device_id") or "")
        caps = repo.get_device_capabilities(
            machine_ip=str(device.get("ip") or ""),
            machine_port=int(device.get("port") or 5005),
            device_id=device_id,
        )
        registry = repo.list_machine_user_registry(device_id=device_id, limit=50000)
        unmapped = list_unmapped_machine_users(repo, device_id=device_id, limit=50000)
        pending_commands = middleware_repo.count_commands(device_id=device_id, status="PENDING")
        device_summaries.append(
            {
                "device_id": device_id,
                "site_id": device.get("site_id"),
                "ip": device.get("ip"),
                "port": device.get("port"),
                "machine_number": device.get("machine_number"),
                "is_active": device.get("is_active"),
                "last_seen_at": device.get("last_seen_at"),
                "last_sync_at": device.get("last_sync_at"),
                "adapter_profile": (caps or {}).get("adapter_profile"),
                "detected_machine_number": (caps or {}).get("detected_machine_number"),
                "model_name": (caps or {}).get("model_name"),
                "registry_users": len(registry),
                "unmapped_users": len(unmapped),
                "pending_commands": pending_commands,
            }
        )

    return {
        "devices": device_summaries,
        "employee_master_total": repo.count_employee_master(),
        "attendance_events_total": repo.count_attendance_events(),
        "local_punches_total": repo.get_attendance_total(),
        "outbox": repo.get_outbox_counts(),
    }


def apply_employee_mappings(
    repo: AttendanceRepository,
    *,
    device_id: str,
    mappings: list[dict[str, Any]],
    overwrite_names: bool = False,
) -> dict[str, Any]:
    updated = 0
    skipped = 0
    errors: list[dict[str, str]] = []

    for item in mappings:
        try:
            user_id = int(item.get("user_id", -1))
            employee_code = str(item.get("employee_code") or "").strip()
            if user_id < 0 or not employee_code:
                raise ValueError("user_id and employee_code are required")
            user_name = str(item.get("user_name") or item.get("employee_name") or "").strip()
            stats = repo.map_machine_user_to_employee(
                user_id=user_id,
                employee_code=employee_code,
                device_id=device_id,
                user_name=user_name or None,
                overwrite_name=overwrite_names,
            )
            if stats.get("updated"):
                updated += 1
            else:
                skipped += 1
        except ValueError as exc:
            errors.append({"user_id": str(item.get("user_id", "")), "error": str(exc)})

    return {"updated": updated, "skipped": skipped, "errors": errors}


__all__ = [
    "apply_employee_mappings",
    "build_reconcile_report",
    "build_sync_status",
    "list_unmapped_machine_users",
]
