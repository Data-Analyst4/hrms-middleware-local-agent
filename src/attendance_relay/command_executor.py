from __future__ import annotations

import logging
from typing import Any

from attendance_relay.device_connection import resolve_device_connection
from attendance_relay.machine_admin import (
    MachineEmployeeDeleteRequest,
    MachineEmployeeToggleRequest,
    MachineEmployeeUpdateRequest,
    MachineEmployeesImportRequest,
    MachineConnectionRequest,
    MachineSdkError,
    check_machine_connection,
    delete_employee_on_machine,
    import_employees_from_machine_to_db,
    toggle_employee_on_machine,
    update_employee_on_machine,
)
from attendance_relay.middleware_repository import MiddlewareRepository
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import Settings

LOGGER = logging.getLogger("attendance_relay.command_executor")


def execute_command(
    *,
    command: dict[str, Any],
    repo: AttendanceRepository,
    middleware_repo: MiddlewareRepository,
    settings: Settings,
) -> dict[str, Any]:
    device_id = str(command.get("device_id") or "").strip()
    command_type = str(command.get("command_type") or "").strip()
    payload = dict(command.get("payload") or {})

    if not device_id:
        raise ValueError("command.device_id is required")

    _device, resolved = resolve_device_connection(
        middleware_repo=middleware_repo,
        attendance_repo=repo,
        settings=settings,
        device_id=device_id,
    )
    employee_code = str(payload.get("employee_code") or "").strip()

    if command_type == "device.test_connection":
        return check_machine_connection(
            settings=settings,
            request=MachineConnectionRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
            ),
        )

    if command_type in {"employee.sync_bulk", "device.sync_employees"}:
        result = import_employees_from_machine_to_db(
            repo=repo,
            settings=settings,
            request=MachineEmployeesImportRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
                device_id=device_id,
                include_user_names=True,
                overwrite_existing_names=True,
                dry_run=bool(payload.get("dry_run")),
                limit=int(payload.get("limit") or 5000),
            ),
        )
        middleware_repo.mark_device_sync(device_id)
        return result

    if not employee_code:
        raise ValueError("payload.employee_code is required for employee commands")

    if command_type in {"employee.sync_one", "employee.update", "employee.create"}:
        result = update_employee_on_machine(
            repo=repo,
            settings=settings,
            employee_code=employee_code,
            request=MachineEmployeeUpdateRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
                user_id=payload.get("user_id"),
                user_name=payload.get("user_name"),
                card_no=payload.get("card_no"),
                timezone1=payload.get("timezone1"),
                timezone2=payload.get("timezone2"),
                group_no=payload.get("group_no"),
                enable=payload.get("enable", True),
                all_slots=bool(payload.get("all_slots", True)),
            ),
        )
        middleware_repo.mark_device_sync(device_id)
        return result

    if command_type == "employee.enable":
        return toggle_employee_on_machine(
            repo=repo,
            settings=settings,
            employee_code=employee_code,
            enabled=True,
            request=MachineEmployeeToggleRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
                user_id=payload.get("user_id"),
                all_slots=bool(payload.get("all_slots", True)),
            ),
        )

    if command_type == "employee.disable":
        return toggle_employee_on_machine(
            repo=repo,
            settings=settings,
            employee_code=employee_code,
            enabled=False,
            request=MachineEmployeeToggleRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
                user_id=payload.get("user_id"),
                all_slots=bool(payload.get("all_slots", True)),
            ),
        )

    if command_type == "employee.delete":
        return delete_employee_on_machine(
            repo=repo,
            settings=settings,
            employee_code=employee_code,
            request=MachineEmployeeDeleteRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
                user_id=payload.get("user_id"),
                all_slots=bool(payload.get("all_slots", True)),
            ),
        )

    raise ValueError(f"unsupported command_type: {command_type}")


def execute_command_safe(
    *,
    command: dict[str, Any],
    repo: AttendanceRepository,
    middleware_repo: MiddlewareRepository,
    settings: Settings,
) -> tuple[bool, dict[str, Any], str | None]:
    try:
        result = execute_command(
            command=command,
            repo=repo,
            middleware_repo=middleware_repo,
            settings=settings,
        )
        return True, result, None
    except (ValueError, MachineSdkError) as exc:
        LOGGER.warning("command_failed type=%s error=%s", command.get("command_type"), exc)
        return False, {}, str(exc)
