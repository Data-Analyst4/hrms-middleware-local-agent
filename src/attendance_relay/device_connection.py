from __future__ import annotations

from typing import Any

from attendance_relay.machine_admin import MachineConnectionRequest, ResolvedMachineConnection
from attendance_relay.middleware_repository import MiddlewareRepository
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import Settings


def parse_machine_password(raw: Any) -> int:
    text = str(raw or "").strip()
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        return 0


def resolve_device_connection(
    *,
    middleware_repo: MiddlewareRepository,
    attendance_repo: AttendanceRepository | None,
    settings: Settings,
    device_id: str,
    overrides: MachineConnectionRequest | None = None,
) -> tuple[dict[str, Any], ResolvedMachineConnection]:
    device = middleware_repo.get_device(device_id)
    if not device.get("is_active", True):
        raise ValueError(f"device is inactive: {device_id}")

    machine_number = int(device.get("machine_number") or settings.machine_sync_machine_number or 1)
    if attendance_repo is not None:
        caps = attendance_repo.get_device_capabilities(
            machine_ip=str(device.get("ip") or ""),
            machine_port=int(device.get("port") or 5005),
            device_id=device_id,
        )
        if caps and caps.get("detected_machine_number"):
            machine_number = int(caps["detected_machine_number"])

    resolved = ResolvedMachineConnection(
        machine_ip=str(device.get("ip") or "").strip(),
        machine_port=int(device.get("port") or settings.machine_sync_port),
        machine_password=parse_machine_password(device.get("machine_password")),
        machine_number=machine_number,
        sdk_dll_path=settings.machine_sdk_dll_path,
    )

    if overrides:
        if overrides.machine_ip:
            resolved = ResolvedMachineConnection(
                machine_ip=overrides.machine_ip.strip(),
                machine_port=overrides.machine_port if overrides.machine_port is not None else resolved.machine_port,
                machine_password=(
                    overrides.machine_password
                    if overrides.machine_password is not None
                    else resolved.machine_password
                ),
                machine_number=(
                    overrides.machine_number
                    if overrides.machine_number is not None
                    else resolved.machine_number
                ),
                sdk_dll_path=overrides.sdk_dll_path or resolved.sdk_dll_path,
            )

    if not resolved.machine_ip:
        raise ValueError(f"device {device_id} has no ip configured")
    return device, resolved


def machine_request_from_device(
    device: dict[str, Any],
    resolved: ResolvedMachineConnection,
    *,
    device_id: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "machine_ip": resolved.machine_ip,
        "machine_port": resolved.machine_port,
        "machine_password": resolved.machine_password,
        "machine_number": resolved.machine_number,
        "device_id": device_id or str(device.get("device_id") or ""),
    }
    if extra:
        payload.update(extra)
    return payload
