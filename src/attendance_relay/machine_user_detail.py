from __future__ import annotations

import base64
import binascii
import json
import re
from contextlib import contextmanager
from typing import Any, Iterator

from pydantic import BaseModel, Field

from attendance_relay.machine_admin import MachineConnectionRequest, resolve_machine_connection
from attendance_relay.machine_sdk import (
    BACKUP_NUMBER_CARD,
    BACKUP_NUMBER_FACE,
    MachineSdkError,
    SBXPCClient,
)
from attendance_relay.master_data import normalize_employee_code
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import Settings

_CODE_RE = re.compile(r"\(code=(\d+)\)")


class MachineUserProbeRequest(MachineConnectionRequest):
    test_user_id: int = Field(default=1, ge=0, le=2_147_483_647)
    probe_fingerprint_slot: int = Field(default=0, ge=0, le=9)


class MachineUserDetailPullRequest(MachineConnectionRequest):
    user_id: int | None = Field(default=None, ge=0, le=2_147_483_647)
    device_id: str = ""
    store_to_db: bool = True
    include_fingerprint_templates: bool = True
    fingerprint_slots: list[int] = Field(default_factory=lambda: list(range(10)))
    include_card_enrollment: bool = True


def _error_code(message: str | None) -> int | None:
    if not message:
        return None
    match = _CODE_RE.search(message)
    return int(match.group(1)) if match else None


def _combine_card_number(card_low: str | int | None, card_high: str | int | None) -> str | None:
    try:
        low = int(str(card_low or "0").strip() or "0")
        high = int(str(card_high or "0").strip() or "0")
    except ValueError:
        return None
    combined = (high << 32) | low
    return str(combined)


def _is_meaningful_template(template_b64: str | None) -> bool:
    if not template_b64:
        return False
    try:
        raw = base64.b64decode(template_b64, validate=True)
    except (ValueError, binascii.Error):
        return False
    return any(byte != 0 for byte in raw)


@contextmanager
def _machine_session(resolved: Any) -> Iterator[SBXPCClient]:
    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    device_was_enabled = True
    try:
        client.enable_device(resolved.machine_number, False)
        device_was_enabled = False
        yield client
    finally:
        if not device_was_enabled:
            try:
                client.enable_device(resolved.machine_number, True)
            except MachineSdkError:
                pass
        client.disconnect(resolved.machine_number)


def _build_request_xml(
    client: SBXPCClient,
    *,
    machine_number: int,
    request_name: str,
    fields: list[tuple[str, Any, str]],
) -> str:
    xml = client.xml_add_string("", "REQUEST", request_name)
    xml = client.xml_add_string(xml, "MSGTYPE", "request")
    xml = client.xml_add_int(xml, "MachineID", machine_number)
    for tag, value, value_type in fields:
        if value_type == "int":
            xml = client.xml_add_int(xml, tag, int(value))
        elif value_type == "long":
            xml = client.xml_add_long(xml, tag, int(value))
        elif value_type == "bool":
            xml = client.xml_add_boolean(xml, tag, bool(value))
        else:
            xml = client.xml_add_string(xml, tag, "" if value is None else str(value))
    return xml


def _parse_xml_response(
    client: SBXPCClient,
    response_xml: str,
    *,
    string_tags: list[str] | None = None,
    int_tags: list[str] | None = None,
    long_tags: list[str] | None = None,
    bool_tags: list[str] | None = None,
    binary_tags: list[tuple[str, int]] | None = None,
) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for tag in string_tags or []:
        try:
            parsed[tag] = client.xml_parse_string(response_xml, tag)
        except MachineSdkError:
            parsed[tag] = None
    for tag in int_tags or []:
        try:
            parsed[tag] = client.xml_parse_int(response_xml, tag)
        except MachineSdkError:
            parsed[tag] = None
    for tag in long_tags or []:
        try:
            parsed[tag] = client.xml_parse_long(response_xml, tag)
        except MachineSdkError:
            parsed[tag] = None
    for tag in bool_tags or []:
        try:
            parsed[tag] = client.xml_parse_boolean(response_xml, tag)
        except MachineSdkError:
            parsed[tag] = None
    for tag, length in binary_tags or []:
        try:
            parsed[tag] = client.xml_parse_binary_byte_base64(response_xml, tag, length)
        except MachineSdkError:
            parsed[tag] = None
    return parsed


def _try_xml_operation(
    client: SBXPCClient,
    *,
    machine_number: int,
    request_name: str,
    fields: list[tuple[str, Any, str]],
    string_tags: list[str] | None = None,
    int_tags: list[str] | None = None,
    long_tags: list[str] | None = None,
    bool_tags: list[str] | None = None,
    binary_tags: list[tuple[str, int]] | None = None,
) -> dict[str, Any]:
    try:
        request_xml = _build_request_xml(
            client,
            machine_number=machine_number,
            request_name=request_name,
            fields=fields,
        )
        response_xml = client.general_operation_xml(machine_number, request_xml)
        parsed = _parse_xml_response(
            client,
            response_xml,
            string_tags=string_tags,
            int_tags=int_tags,
            long_tags=long_tags,
            bool_tags=bool_tags,
            binary_tags=binary_tags,
        )
        return {
            "request_name": request_name,
            "supported": True,
            "parsed": parsed,
            "error": None,
            "error_code": None,
        }
    except MachineSdkError as exc:
        message = str(exc)
        return {
            "request_name": request_name,
            "supported": False,
            "parsed": {},
            "error": message,
            "error_code": _error_code(message),
        }


def _native_enrollments_from_machine(
    client: SBXPCClient,
    machine_number: int,
    user_id: int,
    *,
    include_fingerprint_templates: bool,
    fingerprint_slots: list[int],
    include_card_enrollment: bool,
    include_face_template: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enrollments: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []

    if include_card_enrollment:
        card = client.try_get_enroll_data1(machine_number, user_id, BACKUP_NUMBER_CARD)
        if card is not None:
            enrollments.append(
                {
                    "credential_type": "CARD",
                    "backup_number": BACKUP_NUMBER_CARD,
                    "fp_number": None,
                    "privilege": card.privilege,
                    "template_base64": card.template_base64,
                    "credential_value": str(card.password_or_card) if card.password_or_card else None,
                }
            )
        else:
            notes.append({"step": "GetEnrollData1(CARD)", "supported": False})

    if include_fingerprint_templates:
        for fp_number in fingerprint_slots:
            if fp_number < 0 or fp_number > 9:
                continue
            fp = client.try_get_enroll_data1(machine_number, user_id, fp_number)
            if fp is None:
                if fp_number == fingerprint_slots[0]:
                    notes.append({"step": f"GetEnrollData1(FP:{fp_number})", "supported": False})
                continue
            if not _is_meaningful_template(fp.template_base64):
                continue
            enrollments.append(
                {
                    "credential_type": "FP",
                    "backup_number": fp_number,
                    "fp_number": fp_number,
                    "privilege": fp.privilege,
                    "template_base64": fp.template_base64,
                    "credential_value": None,
                }
            )

    if include_face_template:
        face = client.try_get_enroll_data1(machine_number, user_id, BACKUP_NUMBER_FACE)
        if face is not None and _is_meaningful_template(face.template_base64):
            enrollments.append(
                {
                    "credential_type": "FACE",
                    "backup_number": BACKUP_NUMBER_FACE,
                    "fp_number": None,
                    "privilege": face.privilege,
                    "template_base64": face.template_base64,
                    "credential_value": None,
                }
            )

    return enrollments, notes


def probe_user_xml_capabilities(*, settings: Settings, request: MachineUserProbeRequest) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request)
    user_id = int(request.test_user_id)
    probes: list[dict[str, Any]] = []

    with _machine_session(resolved) as client:
        probes.append(
            {
                "request_name": "GetUserName1(API)",
                "supported": _probe_get_user_name(client, resolved.machine_number, user_id),
                "parsed": {},
                "error": None,
                "error_code": None,
            }
        )
        probes.append(
            _try_xml_operation(
                client,
                machine_number=resolved.machine_number,
                request_name="GetUserInfo",
                fields=[("UserID", user_id, "int")],
                int_tags=["Timezone1", "Timezone2", "GroupNo", "Privilege"],
                bool_tags=["Enable"],
                string_tags=["CardNo_Low", "CardNo_High"],
            )
        )
        probes.append(
            _try_xml_operation(
                client,
                machine_number=resolved.machine_number,
                request_name="GetUserName",
                fields=[("UserID", user_id, "int")],
                string_tags=["UserName"],
            )
        )
        probes.append(
            _try_xml_operation(
                client,
                machine_number=resolved.machine_number,
                request_name="GetEnrollDataFP",
                fields=[("UserID", str(user_id), "string"), ("FPNumber", request.probe_fingerprint_slot, "long")],
                long_tags=["Privilege"],
                binary_tags=[("Template", 8192)],
            )
        )
        probes.append(
            _try_xml_operation(
                client,
                machine_number=resolved.machine_number,
                request_name="GetEnrollDataCARD",
                fields=[("UserID", str(user_id), "string")],
                long_tags=["Privilege", "CardNum"],
            )
        )

    supported = [row["request_name"] for row in probes if row.get("supported")]
    unsupported = [row["request_name"] for row in probes if not row.get("supported")]
    return {
        "test_user_id": user_id,
        "machine": {
            "machine_ip": resolved.machine_ip,
            "machine_port": resolved.machine_port,
            "machine_number": resolved.machine_number,
            "sdk_dll_path": resolved.sdk_dll_path,
        },
        "supported_requests": supported,
        "unsupported_requests": unsupported,
        "probes": probes,
    }


def _probe_get_user_name(client: SBXPCClient, machine_number: int, user_id: int) -> bool:
    try:
        name = client.get_user_name(machine_number, user_id)
        return bool((name or "").strip())
    except MachineSdkError:
        return False


def pull_user_detail_from_machine(
    *,
    repo: AttendanceRepository | None,
    settings: Settings,
    request: MachineUserDetailPullRequest,
    employee_code: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request)
    user_id = request.user_id
    if user_id is None and employee_code:
        normalized = normalize_employee_code(employee_code)
        if normalized.isdigit():
            user_id = int(normalized)
    if user_id is None:
        raise ValueError("user_id is required, or pass a numeric employee_code")

    profile: dict[str, Any] = {
        "user_id": user_id,
        "employee_code": str(employee_code or user_id),
        "user_name": None,
        "timezone1": None,
        "timezone2": None,
        "group_no": None,
        "privilege": None,
        "enabled": None,
        "card_no_low": None,
        "card_no_high": None,
        "card_no_combined": None,
    }
    enrollments: list[dict[str, Any]] = []
    xml_notes: list[dict[str, Any]] = []

    with _machine_session(resolved) as client:
        try:
            profile["user_name"] = client.get_user_name(resolved.machine_number, user_id)
        except MachineSdkError as exc:
            xml_notes.append({"step": "GetUserName1(API)", "error": str(exc)})

        user_info = _try_xml_operation(
            client,
            machine_number=resolved.machine_number,
            request_name="GetUserInfo",
            fields=[("UserID", user_id, "int")],
            int_tags=["Timezone1", "Timezone2", "GroupNo", "Privilege"],
            bool_tags=["Enable"],
            string_tags=["CardNo_Low", "CardNo_High"],
        )
        xml_notes.append(user_info)
        if user_info.get("supported"):
            parsed = user_info.get("parsed") or {}
            profile["timezone1"] = parsed.get("Timezone1")
            profile["timezone2"] = parsed.get("Timezone2")
            profile["group_no"] = parsed.get("GroupNo")
            profile["privilege"] = parsed.get("Privilege")
            profile["enabled"] = parsed.get("Enable")
            profile["card_no_low"] = parsed.get("CardNo_Low")
            profile["card_no_high"] = parsed.get("CardNo_High")
            profile["card_no_combined"] = _combine_card_number(
                profile["card_no_low"],
                profile["card_no_high"],
            )

        if request.include_card_enrollment:
            card_result = _try_xml_operation(
                client,
                machine_number=resolved.machine_number,
                request_name="GetEnrollDataCARD",
                fields=[("UserID", str(user_id), "string")],
                long_tags=["Privilege", "CardNum"],
            )
            xml_notes.append(card_result)
            if card_result.get("supported"):
                parsed = card_result.get("parsed") or {}
                card_num = parsed.get("CardNum")
                if card_num is not None:
                    enrollments.append(
                        {
                            "credential_type": "CARD",
                            "backup_number": 11,
                            "fp_number": None,
                            "privilege": parsed.get("Privilege"),
                            "template_base64": None,
                            "credential_value": str(card_num),
                        }
                    )
                    if profile["card_no_combined"] is None:
                        profile["card_no_combined"] = str(card_num)

        if request.include_fingerprint_templates:
            for fp_number in request.fingerprint_slots:
                if fp_number < 0 or fp_number > 9:
                    continue
                fp_result = _try_xml_operation(
                    client,
                    machine_number=resolved.machine_number,
                    request_name="GetEnrollDataFP",
                    fields=[("UserID", str(user_id), "string"), ("FPNumber", fp_number, "long")],
                    long_tags=["Privilege"],
                    binary_tags=[("Template", 8192)],
                )
                if not fp_result.get("supported"):
                    if fp_number == request.fingerprint_slots[0]:
                        xml_notes.append(fp_result)
                    continue
                parsed = fp_result.get("parsed") or {}
                template_b64 = parsed.get("Template")
                if not _is_meaningful_template(template_b64):
                    continue
                enrollments.append(
                    {
                        "credential_type": "FP",
                        "backup_number": fp_number,
                        "fp_number": fp_number,
                        "privilege": parsed.get("Privilege"),
                        "template_base64": template_b64,
                        "credential_value": None,
                    }
                )

        needs_native_fp = request.include_fingerprint_templates and not any(
            item.get("credential_type") == "FP" for item in enrollments
        )
        needs_native_card = request.include_card_enrollment and not any(
            item.get("credential_type") == "CARD" for item in enrollments
        )
        if needs_native_fp or needs_native_card:
            native_enrollments, native_notes = _native_enrollments_from_machine(
                client,
                resolved.machine_number,
                user_id,
                include_fingerprint_templates=needs_native_fp,
                fingerprint_slots=request.fingerprint_slots,
                include_card_enrollment=needs_native_card,
            )
            for item in native_enrollments:
                duplicate = any(
                    existing.get("credential_type") == item.get("credential_type")
                    and existing.get("backup_number") == item.get("backup_number")
                    for existing in enrollments
                )
                if not duplicate:
                    enrollments.append(item)
            xml_notes.extend(native_notes)

    device_id = str(request.device_id or "").strip()
    storage: dict[str, Any] | None = None

    if repo is not None:
        registry_rows = repo.list_machine_user_registry(
            machine_ip=resolved.machine_ip,
            device_id=device_id or None,
            limit=50000,
        )
        registry_match = next((row for row in registry_rows if int(row.get("user_id", -1)) == user_id), None)
        if registry_match:
            if profile.get("user_name") in (None, ""):
                profile["user_name"] = registry_match.get("user_name")
            profile["enabled"] = bool(registry_match.get("enabled"))
            profile["registry_slot_count"] = int(registry_match.get("slot_count") or 0)

    if request.store_to_db:
        if repo is None:
            raise ValueError("repository is required when store_to_db=true")
        storage = repo.store_machine_user_detail(
            profile=profile,
            enrollments=enrollments,
            machine_ip=resolved.machine_ip,
            device_id=device_id,
            machine_number=resolved.machine_number,
            profile_json=json.dumps({"xml_notes": xml_notes}, ensure_ascii=False),
        )

    return {
        "user_id": user_id,
        "employee_code": profile["employee_code"],
        "machine": {
            "machine_ip": resolved.machine_ip,
            "machine_port": resolved.machine_port,
            "machine_number": resolved.machine_number,
            "sdk_dll_path": resolved.sdk_dll_path,
        },
        "device_id": device_id,
        "profile": profile,
        "enrollments_loaded": len(enrollments),
        "enrollments": enrollments,
        "xml_notes": xml_notes,
        "storage": storage,
    }


__all__ = [
    "MachineUserDetailPullRequest",
    "MachineUserProbeRequest",
    "probe_user_xml_capabilities",
    "pull_user_detail_from_machine",
]
