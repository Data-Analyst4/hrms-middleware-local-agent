from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from attendance_relay.machine_admin import MachineConnectionRequest, resolve_machine_connection
from attendance_relay.machine_sdk import MachineSdkError, SBXPCClient
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import Settings


class MachineDeviceDetectRequest(MachineConnectionRequest):
    device_id: str = ""
    store_to_db: bool = True


def infer_adapter_profile(
    *,
    model_name: str | None,
    firmware: str | None,
    machine_type: int | None = None,
) -> str:
    model = str(model_name or "").upper()
    fw = str(firmware or "").upper()
    if "S300" in model or "SB3600" in model or "SB100" in model:
        return "s300_xml"
    if "M60" in fw or "T501" in model or "M50" in model or "REALTIME" in model:
        return "m60_native"
    if machine_type is not None and machine_type in {50, 60}:
        return "m60_native"
    return "m60_native"


def _public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(profile)
    cleaned.pop("response_xml", None)
    return cleaned


def detect_device_profile(client: SBXPCClient, machine_number: int) -> dict[str, Any]:
    details = client.get_device_details(machine_number)
    parsed = dict(details.get("parsed") or {})
    model_info: dict[str, Any] | None = None
    try:
        native_model = client.get_device_model(machine_number)
        model_info = {
            "is_big_user_id": native_model.is_big_user_id,
            "company_type": native_model.company_type,
            "machine_type": native_model.machine_type,
            "machine_version": native_model.machine_version,
        }
    except MachineSdkError as exc:
        model_info = {"error": str(exc)}

    detected_machine_number = int(parsed.get("STN") or machine_number)
    adapter_profile = infer_adapter_profile(
        model_name=parsed.get("PdName"),
        firmware=parsed.get("FW"),
        machine_type=(model_info or {}).get("machine_type"),
    )
    xml_user_info = adapter_profile == "s300_xml"

    return {
        "connection_machine_number": machine_number,
        "detected_machine_number": detected_machine_number,
        "machine_number_mismatch": detected_machine_number != machine_number,
        "model_name": parsed.get("PdName"),
        "manufacturer": parsed.get("Manuf"),
        "firmware": parsed.get("FW"),
        "serial_no": parsed.get("SerialNo"),
        "user_count": parsed.get("UserCnt"),
        "fp_count": parsed.get("FpCnt"),
        "face_count": parsed.get("FaceCnt"),
        "log_count": parsed.get("LogCnt"),
        "enroll_slots": parsed.get("EnrollSlot"),
        "adapter_profile": adapter_profile,
        "capabilities": {
            "native_get_user_name": True,
            "native_get_enroll_data1": True,
            "native_set_user_name": True,
            "native_set_enroll_data1": True,
            "native_enable_user": True,
            "native_delete_enroll_data": True,
            "xml_get_device_details": True,
            "xml_get_user_info": xml_user_info,
            "xml_set_user_info": xml_user_info,
            "xml_get_enroll_fp": xml_user_info,
            "xml_get_enroll_card": xml_user_info,
        },
        "device_details": parsed,
        "device_model": model_info,
        "response_xml": details.get("response_xml"),
    }


def detect_device_on_machine(
    *,
    repo: AttendanceRepository | None,
    settings: Settings,
    request: MachineDeviceDetectRequest,
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
        device_time = client.get_device_time(resolved.machine_number)
        profile = detect_device_profile(client, resolved.machine_number)
    finally:
        client.disconnect(resolved.machine_number)

    device_id = str(request.device_id or "").strip()
    storage: dict[str, Any] | None = None
    if request.store_to_db:
        if repo is None:
            raise ValueError("repository is required when store_to_db=true")
        storage = repo.upsert_device_capabilities(
            machine_ip=resolved.machine_ip,
            machine_port=resolved.machine_port,
            device_id=device_id,
            profile=profile,
        )

    return {
        "connected": True,
        "machine_ip": resolved.machine_ip,
        "machine_port": resolved.machine_port,
        "machine_number": resolved.machine_number,
        "device_time": device_time.strftime("%Y-%m-%d %H:%M:%S"),
        "profile": _public_profile(profile),
        "recommended_machine_number": profile.get("detected_machine_number"),
        "device_id": device_id,
        "storage": storage,
    }


__all__ = [
    "MachineDeviceDetectRequest",
    "detect_device_on_machine",
    "detect_device_profile",
    "infer_adapter_profile",
]
