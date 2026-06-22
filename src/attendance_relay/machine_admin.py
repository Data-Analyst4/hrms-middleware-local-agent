from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from attendance_relay.machine_sdk import (
    BACKUP_NUMBER_CARD,
    MachineSdkError,
    SBXPCClient,
)
from attendance_relay.machine_sync import (
    choose_card_number,
    choose_machine_user_id,
    choose_user_name,
    list_employee_master_rows,
    parse_unsigned_integer,
    sync_rows_to_machine,
)
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import Settings


class MachineConnectionRequest(BaseModel):
    machine_ip: str | None = None
    machine_port: int | None = Field(default=None, ge=1, le=65535)
    machine_password: int | None = None
    machine_number: int | None = Field(default=None, ge=1)
    sdk_dll_path: str | None = None


class MachineSyncRequest(MachineConnectionRequest):
    employee_code: str | None = None
    limit: int = Field(default=2000, ge=1, le=50000)
    dry_run: bool = False
    timezone1: int | None = None
    timezone2: int | None = None
    group_no: int | None = None


class MachineEmployeeUpdateRequest(MachineConnectionRequest):
    user_id: int | None = Field(default=None, ge=0, le=2_147_483_647)
    user_name: str | None = None
    card_no: str | None = None
    timezone1: int | None = None
    timezone2: int | None = None
    group_no: int | None = None
    enable: bool | None = None
    e_machine_number: int | None = Field(default=None, ge=1)
    backup_number: int = Field(default=BACKUP_NUMBER_CARD, ge=0)
    all_slots: bool = False


class MachineEmployeeToggleRequest(MachineConnectionRequest):
    user_id: int | None = Field(default=None, ge=0, le=2_147_483_647)
    e_machine_number: int | None = Field(default=None, ge=1)
    backup_number: int = Field(default=BACKUP_NUMBER_CARD, ge=0)
    all_slots: bool = True


class MachineEmployeeReadRequest(MachineConnectionRequest):
    user_id: int | None = Field(default=None, ge=0, le=2_147_483_647)
    include_user_name: bool = True


class MachineEmployeesReadAllRequest(MachineConnectionRequest):
    include_user_names: bool = False
    limit: int = Field(default=5000, ge=1, le=50000)


class MachineEmployeesImportRequest(MachineEmployeesReadAllRequest):
    device_id: str = ""
    dry_run: bool = False
    overwrite_existing_names: bool = True


class MachineEmployeeDeleteRequest(MachineConnectionRequest):
    user_id: int | None = Field(default=None, ge=0, le=2_147_483_647)
    e_machine_number: int | None = Field(default=None, ge=1)
    backup_number: int = Field(default=BACKUP_NUMBER_CARD, ge=0)
    all_slots: bool = True


class MachineXmlField(BaseModel):
    tag: str
    value: Any = None
    value_type: str = "auto"  # auto|string|int|long|bool


class MachineXmlBinaryField(BaseModel):
    tag: str
    data_base64: str


class MachineXmlParseField(BaseModel):
    tag: str
    value_type: str = "string"  # string|int|long|bool


class MachineXmlBinaryParseField(BaseModel):
    tag: str
    length: int = Field(default=8192, ge=1, le=1024 * 1024)


class MachineXmlExecuteRequest(MachineConnectionRequest):
    request_name: str
    msg_type: str = "request"
    include_machine_id: bool = True
    fields: list[MachineXmlField] = Field(default_factory=list)
    binary_fields: list[MachineXmlBinaryField] = Field(default_factory=list)
    parse_fields: list[MachineXmlParseField] = Field(default_factory=list)
    parse_binary_fields: list[MachineXmlBinaryParseField] = Field(default_factory=list)
    return_request_xml: bool = False
    return_response_xml: bool = True


@dataclass(slots=True)
class ResolvedMachineConnection:
    machine_ip: str
    machine_port: int
    machine_password: int
    machine_number: int
    sdk_dll_path: str


def resolve_machine_connection(
    settings: Settings,
    request: MachineConnectionRequest | None = None,
) -> ResolvedMachineConnection:
    machine_ip = ((request.machine_ip if request else None) or settings.machine_sync_ip).strip()
    if not machine_ip:
        raise ValueError("machine_ip is required. Set config machine_sync_ip or pass machine_ip.")

    return ResolvedMachineConnection(
        machine_ip=machine_ip,
        machine_port=(request.machine_port if request and request.machine_port is not None else settings.machine_sync_port),
        machine_password=(
            request.machine_password if request and request.machine_password is not None else settings.machine_sync_password
        ),
        machine_number=(
            request.machine_number if request and request.machine_number is not None else settings.machine_sync_machine_number
        ),
        sdk_dll_path=(request.sdk_dll_path if request and request.sdk_dll_path else settings.machine_sdk_dll_path),
    )


def build_machine_sync_preview(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    request: MachineSyncRequest,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request)
    rows = list_employee_master_rows(
        repo.engine,
        limit=request.limit,
        employee_code=(request.employee_code or None),
    )
    preview: list[dict[str, Any]] = []
    for row in rows:
        user_id = choose_machine_user_id(row)
        preview.append(
            {
                "employee_code": str(row.get("employee_code") or "").strip(),
                "employee_name": str(row.get("employee_name") or "").strip(),
                "resolved_user_id": user_id,
                "resolved_card_no": (
                    choose_card_number(row, fallback_user_id=(user_id or 0)) if user_id is not None else None
                ),
                "resolved_user_name": choose_user_name(row),
            }
        )
    return {
        "dry_run": True,
        "rows": len(rows),
        "machine": {
            "machine_ip": resolved.machine_ip,
            "machine_port": resolved.machine_port,
            "machine_number": resolved.machine_number,
            "sdk_dll_path": resolved.sdk_dll_path,
        },
        "preview": preview,
    }


def run_machine_sync_from_api(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    request: MachineSyncRequest,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request)
    rows = list_employee_master_rows(
        repo.engine,
        limit=request.limit,
        employee_code=(request.employee_code or None),
    )
    summary = sync_rows_to_machine(
        rows=rows,
        machine_ip=resolved.machine_ip,
        machine_port=resolved.machine_port,
        machine_password=resolved.machine_password,
        machine_number=resolved.machine_number,
        timezone1=(request.timezone1 if request.timezone1 is not None else settings.machine_sync_timezone1),
        timezone2=(request.timezone2 if request.timezone2 is not None else settings.machine_sync_timezone2),
        group_no=(request.group_no if request.group_no is not None else settings.machine_sync_group_no),
        sdk_dll_path=resolved.sdk_dll_path,
    )
    return {
        "dry_run": False,
        "machine": {
            "machine_ip": resolved.machine_ip,
            "machine_port": resolved.machine_port,
            "machine_number": resolved.machine_number,
            "sdk_dll_path": resolved.sdk_dll_path,
        },
        "summary": {
            "scanned": summary.scanned,
            "synced": summary.synced,
            "skipped": summary.skipped,
            "failed": summary.failed,
        },
    }


def _resolve_e_machine_number(resolved: ResolvedMachineConnection, explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    return resolved.machine_number


def _user_enrollment_slots(client: SBXPCClient, machine_number: int, user_id: int) -> list[dict[str, int | bool]]:
    slots = client.list_all_user_ids(machine_number)
    return [entry for entry in slots if int(entry.get("user_id", -1)) == user_id]


def _iter_slot_targets(
    client: SBXPCClient,
    resolved: ResolvedMachineConnection,
    user_id: int,
    *,
    all_slots: bool,
    backup_number: int,
    e_machine_number: int | None,
) -> list[tuple[int, int]]:
    if all_slots:
        user_slots = _user_enrollment_slots(client, resolved.machine_number, user_id)
        if user_slots:
            return [
                (
                    int(entry.get("e_machine_number") or resolved.machine_number),
                    int(entry.get("backup_number", backup_number)),
                )
                for entry in user_slots
            ]
    resolved_e = _resolve_e_machine_number(resolved, e_machine_number)
    return [(resolved_e, backup_number)]


def check_machine_connection(*, settings: Settings, request: MachineConnectionRequest) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request)
    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    profile: dict[str, Any] | None = None
    try:
        device_time = client.get_device_time(resolved.machine_number)
        try:
            from attendance_relay.machine_device_profile import detect_device_profile

            profile = detect_device_profile(client, resolved.machine_number)
        except (MachineSdkError, OSError):
            profile = None
    finally:
        client.disconnect(resolved.machine_number)
    result: dict[str, Any] = {
        "connected": True,
        "machine_ip": resolved.machine_ip,
        "machine_port": resolved.machine_port,
        "machine_number": resolved.machine_number,
        "device_time": device_time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if profile:
        from attendance_relay.machine_device_profile import _public_profile

        result["profile"] = _public_profile(profile)
        result["recommended_machine_number"] = profile.get("detected_machine_number")
        result["adapter_profile"] = profile.get("adapter_profile")
    return result


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _apply_xml_field(client: SBXPCClient, xml: str, field: MachineXmlField) -> str:
    tag = str(field.tag or "").strip()
    if not tag:
        raise ValueError("field.tag is required")
    value_type = str(field.value_type or "auto").strip().lower() or "auto"
    value = field.value

    if value_type in {"auto", "bool"} and isinstance(value, bool):
        return client.xml_add_boolean(xml, tag, value)
    if value_type in {"int", "long"}:
        return client.xml_add_long(xml, tag, int(value or 0))
    if value_type == "bool":
        return client.xml_add_boolean(xml, tag, _to_bool(value))
    if value_type == "auto":
        if isinstance(value, int):
            return client.xml_add_long(xml, tag, value)
        if isinstance(value, float) and value.is_integer():
            return client.xml_add_long(xml, tag, int(value))
    # Fallback: encode as string to keep passthrough permissive.
    return client.xml_add_string(xml, tag, "" if value is None else str(value))


def run_machine_xml_execute(*, settings: Settings, request: MachineXmlExecuteRequest) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request)
    request_name = str(request.request_name or "").strip()
    if not request_name:
        raise ValueError("request_name is required")

    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        request_xml = ""
        request_xml = client.xml_add_string(request_xml, "REQUEST", request_name)
        request_xml = client.xml_add_string(request_xml, "MSGTYPE", str(request.msg_type or "request"))
        if request.include_machine_id:
            request_xml = client.xml_add_long(request_xml, "MachineID", resolved.machine_number)

        for field in request.fields:
            request_xml = _apply_xml_field(client, request_xml, field)

        for field in request.binary_fields:
            tag = str(field.tag or "").strip()
            if not tag:
                raise ValueError("binary_fields.tag is required")
            try:
                payload = base64.b64decode((field.data_base64 or "").encode("ascii"), validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError(f"invalid base64 for binary field tag={tag}") from exc
            request_xml = client.xml_add_binary_byte(request_xml, tag, payload)

        response_xml = client.general_operation_xml(resolved.machine_number, request_xml)

        parsed: dict[str, Any] = {}
        for field in request.parse_fields:
            tag = str(field.tag or "").strip()
            if not tag:
                continue
            value_type = str(field.value_type or "string").strip().lower() or "string"
            try:
                if value_type == "int":
                    parsed[tag] = client.xml_parse_int(response_xml, tag)
                elif value_type == "long":
                    parsed[tag] = client.xml_parse_long(response_xml, tag)
                elif value_type == "bool":
                    parsed[tag] = client.xml_parse_boolean(response_xml, tag)
                else:
                    parsed[tag] = client.xml_parse_string(response_xml, tag)
            except MachineSdkError:
                parsed[tag] = None

        parsed_binary: dict[str, str | None] = {}
        for field in request.parse_binary_fields:
            tag = str(field.tag or "").strip()
            if not tag:
                continue
            try:
                parsed_binary[tag] = client.xml_parse_binary_byte_base64(response_xml, tag, int(field.length))
            except MachineSdkError:
                parsed_binary[tag] = None
    finally:
        client.disconnect(resolved.machine_number)

    result: dict[str, Any] = {
        "executed": True,
        "machine": {
            "machine_ip": resolved.machine_ip,
            "machine_port": resolved.machine_port,
            "machine_number": resolved.machine_number,
            "sdk_dll_path": resolved.sdk_dll_path,
        },
        "request_name": request_name,
        "parsed": parsed,
        "parsed_binary": parsed_binary,
    }
    if request.return_request_xml:
        result["request_xml"] = request_xml
    if request.return_response_xml:
        result["response_xml"] = response_xml
    return result


def _resolve_employee_row_or_fail(repo: AttendanceRepository, employee_code: str) -> dict[str, Any]:
    row = repo.find_employee_master(employee_code)
    if not row:
        raise ValueError(f"employee_code not found in employee_master: {employee_code}")
    return row


def _resolve_user_id(row: dict[str, Any], explicit_user_id: int | None) -> int:
    if explicit_user_id is not None:
        return explicit_user_id
    user_id = choose_machine_user_id(row)
    if user_id is None:
        code = str(row.get("employee_code") or "").strip()
        raise ValueError(f"employee_code cannot map to numeric machine user_id: {code}")
    return user_id


def _resolve_card_number(row: dict[str, Any], explicit_card_no: str | None, fallback_user_id: int) -> int:
    if explicit_card_no is not None and explicit_card_no.strip():
        parsed = parse_unsigned_integer(explicit_card_no.strip(), (1 << 64) - 1)
        if parsed is None:
            raise ValueError("card_no must be a positive integer up to uint64.")
        return parsed
    return choose_card_number(row, fallback_user_id=fallback_user_id)


def update_employee_on_machine(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    employee_code: str,
    request: MachineEmployeeUpdateRequest,
) -> dict[str, Any]:
    row = _resolve_employee_row_or_fail(repo, employee_code)
    resolved = resolve_machine_connection(settings, request)
    user_id = _resolve_user_id(row, request.user_id)
    user_name = (request.user_name or "").strip() or choose_user_name(row)
    card_no = _resolve_card_number(row, request.card_no, fallback_user_id=user_id)
    timezone1 = request.timezone1 if request.timezone1 is not None else settings.machine_sync_timezone1
    timezone2 = request.timezone2 if request.timezone2 is not None else settings.machine_sync_timezone2
    group_no = request.group_no if request.group_no is not None else settings.machine_sync_group_no

    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        client.enable_device(resolved.machine_number, False)
        user_info_applied = False
        slots_touched: list[dict[str, int | bool]] = []
        try:
            client.set_enroll_data_card(resolved.machine_number, user_id, card_no)
            # M60/T501: name must be set after card enroll or GetUserName1 returns empty.
            client.set_user_name(resolved.machine_number, user_id, user_name)
            user_info_applied = client.try_set_user_info(
                resolved.machine_number,
                user_id,
                timezone1,
                timezone2,
                group_no,
            )
            if request.enable is not None:
                slot_targets = _iter_slot_targets(
                    client,
                    resolved,
                    user_id,
                    all_slots=request.all_slots,
                    backup_number=request.backup_number,
                    e_machine_number=request.e_machine_number,
                )
                for e_num, backup in slot_targets:
                    client.enable_user(
                        resolved.machine_number,
                        user_id,
                        e_machine_number=e_num,
                        backup_number=backup,
                        enabled=request.enable,
                    )
                    slots_touched.append(
                        {
                            "e_machine_number": e_num,
                            "backup_number": backup,
                            "enabled": request.enable,
                        }
                    )
        finally:
            client.enable_device(resolved.machine_number, True)
    finally:
        client.disconnect(resolved.machine_number)

    return {
        "employee_code": str(row.get("employee_code") or employee_code),
        "user_id": user_id,
        "user_name": user_name,
        "card_no": card_no,
        "timezone1": timezone1,
        "timezone2": timezone2,
        "group_no": group_no,
        "enabled": request.enable,
        "user_info_applied": user_info_applied,
        "adapter_profile": "m60_native",
        "slots_touched": slots_touched,
        "created_on_machine": True,
    }


def toggle_employee_on_machine(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    employee_code: str,
    enabled: bool,
    request: MachineEmployeeToggleRequest,
) -> dict[str, Any]:
    row = _resolve_employee_row_or_fail(repo, employee_code)
    resolved = resolve_machine_connection(settings, request)
    user_id = _resolve_user_id(row, request.user_id)

    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        client.enable_device(resolved.machine_number, False)
        slots_touched: list[dict[str, int | bool]] = []
        try:
            slot_targets = _iter_slot_targets(
                client,
                resolved,
                user_id,
                all_slots=request.all_slots,
                backup_number=request.backup_number,
                e_machine_number=request.e_machine_number,
            )
            for e_num, backup in slot_targets:
                client.enable_user(
                    resolved.machine_number,
                    user_id,
                    e_machine_number=e_num,
                    backup_number=backup,
                    enabled=enabled,
                )
                slots_touched.append(
                    {
                        "e_machine_number": e_num,
                        "backup_number": backup,
                        "enabled": enabled,
                    }
                )
        finally:
            client.enable_device(resolved.machine_number, True)
    finally:
        client.disconnect(resolved.machine_number)

    return {
        "employee_code": str(row.get("employee_code") or employee_code),
        "user_id": user_id,
        "enabled": enabled,
        "slots_touched": slots_touched,
        "e_machine_number": _resolve_e_machine_number(resolved, request.e_machine_number),
        "backup_number": request.backup_number,
        "all_slots": request.all_slots,
    }


def get_employee_on_machine(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    employee_code: str,
    request: MachineEmployeeReadRequest,
) -> dict[str, Any]:
    row = _resolve_employee_row_or_fail(repo, employee_code)
    resolved = resolve_machine_connection(settings, request)
    user_id = _resolve_user_id(row, request.user_id)

    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        users = client.list_all_user_ids(resolved.machine_number)
        match = next((entry for entry in users if int(entry.get("user_id", -1)) == user_id), None)

        user_name: str | None = None
        if match and request.include_user_name:
            user_name = client.get_user_name(resolved.machine_number, user_id)
    finally:
        client.disconnect(resolved.machine_number)

    return {
        "employee_code": str(row.get("employee_code") or employee_code),
        "user_id": user_id,
        "exists_on_machine": bool(match),
        "user_name": user_name,
        "machine_user_record": match,
        "machine_user_count": len(users),
    }


def list_all_employees_on_machine(
    *,
    settings: Settings,
    request: MachineEmployeesReadAllRequest,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request)

    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        slots = client.list_all_user_ids(resolved.machine_number)
        by_user: dict[int, dict[str, Any]] = {}
        for slot in slots:
            user_id = int(slot.get("user_id", -1))
            if user_id < 0:
                continue
            enabled = bool(slot.get("enabled"))
            current = by_user.get(user_id)
            if current is None:
                by_user[user_id] = {
                    "user_id": user_id,
                    "enabled": enabled,
                    "slot_count": 1,
                }
            else:
                current["slot_count"] = int(current["slot_count"]) + 1
                current["enabled"] = bool(current["enabled"]) or enabled

        rows: list[dict[str, Any]] = []
        for user_id in sorted(by_user):
            entry = dict(by_user[user_id])
            if request.include_user_names:
                try:
                    entry["user_name"] = client.get_user_name(resolved.machine_number, user_id)
                except MachineSdkError:
                    entry["user_name"] = None
            rows.append(entry)
            if len(rows) >= request.limit:
                break

        active = sum(1 for row in rows if row.get("enabled"))
        return {
            "total": len(rows),
            "active": active,
            "inactive": len(rows) - active,
            "machine_user_slots": len(slots),
            "machine": {
                "machine_ip": resolved.machine_ip,
                "machine_port": resolved.machine_port,
                "machine_number": resolved.machine_number,
                "sdk_dll_path": resolved.sdk_dll_path,
            },
            "rows": rows,
        }
    finally:
        client.disconnect(resolved.machine_number)


def compute_available_user_ids(
    used_ids: list[int],
    *,
    limit: int = 40,
    scan_ceiling: int | None = None,
) -> dict[str, Any]:
    used_set = {int(value) for value in used_ids if int(value) >= 0}
    ordered_used = sorted(used_set)
    max_used = ordered_used[-1] if ordered_used else 0
    ceiling = scan_ceiling or max(max_used + limit + 10, limit + 10)

    available: list[int] = []
    for user_id in range(1, ceiling + 1):
        if user_id in used_set:
            continue
        available.append(user_id)
        if len(available) >= limit:
            break

    suggested_next = max_used + 1 if ordered_used else 1
    while suggested_next in used_set:
        suggested_next += 1

    return {
        "used_count": len(used_set),
        "max_used_id": max_used,
        "suggested_next": suggested_next,
        "available_ids": available,
        "used_ids": ordered_used,
    }


def list_available_machine_user_ids(
    *,
    settings: Settings,
    request: MachineConnectionRequest,
    limit: int = 40,
    scan_ceiling: int | None = None,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request)

    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        slots = client.list_all_user_ids(resolved.machine_number)
        used_ids = sorted(
            {
                int(slot.get("user_id", -1))
                for slot in slots
                if int(slot.get("user_id", -1)) >= 0
            }
        )
    finally:
        client.disconnect(resolved.machine_number)

    payload = compute_available_user_ids(used_ids, limit=limit, scan_ceiling=scan_ceiling)
    payload["machine"] = {
        "machine_ip": resolved.machine_ip,
        "machine_port": resolved.machine_port,
        "machine_number": resolved.machine_number,
    }
    return payload


def import_employees_from_machine_to_db(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    request: MachineEmployeesImportRequest,
) -> dict[str, Any]:
    machine_data = list_all_employees_on_machine(settings=settings, request=request)
    if request.dry_run:
        preview_rows = machine_data.get("rows") or []
        return {
            "dry_run": True,
            "total_on_machine": machine_data.get("total", 0),
            "active_on_machine": machine_data.get("active", 0),
            "inactive_on_machine": machine_data.get("inactive", 0),
            "machine_user_slots": machine_data.get("machine_user_slots", 0),
            "machine": machine_data.get("machine"),
            "preview": preview_rows[: min(20, len(preview_rows))],
            "would_import": len(preview_rows),
        }

    stats = repo.import_machine_users_to_db(
        rows=machine_data.get("rows") or [],
        machine_ip=str((machine_data.get("machine") or {}).get("machine_ip") or ""),
        device_id=str(request.device_id or "").strip(),
        machine_number=int((machine_data.get("machine") or {}).get("machine_number") or 1),
        overwrite_existing_names=request.overwrite_existing_names,
    )
    return {
        "dry_run": False,
        "total_on_machine": machine_data.get("total", 0),
        "active_on_machine": machine_data.get("active", 0),
        "inactive_on_machine": machine_data.get("inactive", 0),
        "machine_user_slots": machine_data.get("machine_user_slots", 0),
        "machine": machine_data.get("machine"),
        "device_id": str(request.device_id or "").strip(),
        **stats,
    }


def delete_employee_on_machine(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    employee_code: str,
    request: MachineEmployeeDeleteRequest,
) -> dict[str, Any]:
    row = _resolve_employee_row_or_fail(repo, employee_code)
    resolved = resolve_machine_connection(settings, request)
    user_id = _resolve_user_id(row, request.user_id)

    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        client.enable_device(resolved.machine_number, False)
        deleted_slots: list[dict[str, int]] = []
        delete_errors: list[dict[str, Any]] = []
        try:
            slot_targets = _iter_slot_targets(
                client,
                resolved,
                user_id,
                all_slots=request.all_slots,
                backup_number=request.backup_number,
                e_machine_number=request.e_machine_number,
            )
            for e_num, backup in slot_targets:
                try:
                    client.delete_enroll_data(
                        resolved.machine_number,
                        user_id,
                        e_machine_number=e_num,
                        backup_number=backup,
                    )
                    deleted_slots.append({"e_machine_number": e_num, "backup_number": backup})
                except MachineSdkError as exc:
                    message = str(exc)
                    if "(code=4)" in message or "(code=5)" in message:
                        delete_errors.append(
                            {
                                "e_machine_number": e_num,
                                "backup_number": backup,
                                "error": message,
                                "ignored": True,
                            }
                        )
                        continue
                    raise
        finally:
            client.enable_device(resolved.machine_number, True)
    finally:
        client.disconnect(resolved.machine_number)

    if not deleted_slots and delete_errors:
        raise MachineSdkError(
            f"DeleteEnrollData failed for all slots on user_id={user_id}: {delete_errors[0]['error']}"
        )

    return {
        "employee_code": str(row.get("employee_code") or employee_code),
        "user_id": user_id,
        "deleted": bool(deleted_slots),
        "deleted_slots": deleted_slots,
        "delete_errors": delete_errors,
        "e_machine_number": _resolve_e_machine_number(resolved, request.e_machine_number),
        "backup_number": request.backup_number,
        "all_slots": request.all_slots,
    }


__all__ = [
    "MachineConnectionRequest",
    "MachineEmployeeDeleteRequest",
    "MachineEmployeeReadRequest",
    "MachineEmployeesReadAllRequest",
    "MachineEmployeesImportRequest",
    "MachineEmployeeToggleRequest",
    "MachineEmployeeUpdateRequest",
    "MachineXmlBinaryField",
    "MachineXmlBinaryParseField",
    "MachineXmlExecuteRequest",
    "MachineXmlField",
    "MachineXmlParseField",
    "MachineSdkError",
    "MachineSyncRequest",
    "build_machine_sync_preview",
    "check_machine_connection",
    "delete_employee_on_machine",
    "get_employee_on_machine",
    "import_employees_from_machine_to_db",
    "list_all_employees_on_machine",
    "run_machine_xml_execute",
    "run_machine_sync_from_api",
    "toggle_employee_on_machine",
    "update_employee_on_machine",
]
