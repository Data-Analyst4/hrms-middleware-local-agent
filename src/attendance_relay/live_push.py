from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from attendance_relay.machine_admin import MachineConnectionRequest, MachineSdkError, resolve_machine_connection
from attendance_relay.machine_sdk import SBXPCClient
from attendance_relay.net_utils import guess_site_lan_ip
from attendance_relay.settings import Settings

# M50/T501 EventSendMode: 0=None, 1=Network, 2=RS485
EVENT_SEND_NETWORK = 1


@dataclass(slots=True)
class LivePushStatus:
    ok: bool
    device_ip: str
    expected_server_ip: str
    expected_server_port: int
    configured_server_ip: str | None
    configured_server_port: int | None
    event_send_mode: int | None
    drift: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "device_ip": self.device_ip,
            "expected_server_ip": self.expected_server_ip,
            "expected_server_port": self.expected_server_port,
            "configured_server_ip": self.configured_server_ip,
            "configured_server_port": self.configured_server_port,
            "event_send_mode": self.event_send_mode,
            "drift": self.drift,
            "error": self.error,
        }


def _xml_get_log_server(client: SBXPCClient, machine_number: int) -> dict[str, str | int | None]:
    request_xml = client.xml_add_string("", "REQUEST", "GetLogServerSetting")
    request_xml = client.xml_add_string(request_xml, "MSGTYPE", "request")
    request_xml = client.xml_add_long(request_xml, "MachineID", machine_number)
    response_xml = client.general_operation_xml(machine_number, request_xml)
    mode = client.xml_parse_long(response_xml, "EventSendMode")
    port = client.xml_parse_long(response_xml, "ManagerPCPort")
    try:
        domain = client.xml_parse_string(response_xml, "ManagerPCDomainName")
    except MachineSdkError:
        domain = None
    return {
        "ManagerPCDomainName": domain,
        "ManagerPCPort": port,
        "EventSendMode": mode,
    }


def _xml_set_log_server(
    client: SBXPCClient,
    machine_number: int,
    *,
    server_ip: str,
    server_port: int,
    event_mode: int,
) -> str:
    request_xml = client.xml_add_string("", "REQUEST", "SetLogServerSetting")
    request_xml = client.xml_add_string(request_xml, "MSGTYPE", "request")
    request_xml = client.xml_add_long(request_xml, "MachineID", machine_number)
    request_xml = client.xml_add_string(request_xml, "ManagerPCDomainName", server_ip)
    request_xml = client.xml_add_long(request_xml, "ManagerPCPort", int(server_port))
    request_xml = client.xml_add_long(request_xml, "EventSendMode", int(event_mode))
    return client.general_operation_xml(machine_number, request_xml)


def resolve_live_push_targets(
    settings: Settings,
    *,
    server_ip: str | None = None,
    server_port: int | None = None,
    connection: MachineConnectionRequest | None = None,
) -> tuple[str, int, Any]:
    expected_ip = (server_ip or "").strip() or guess_site_lan_ip()
    expected_port = int(server_port or settings.fk_web_listener_port or 8081)
    conn = connection or MachineConnectionRequest(
        machine_ip=settings.machine_sync_ip,
        machine_port=settings.machine_sync_port,
        machine_password=settings.machine_sync_password,
        machine_number=settings.machine_sync_machine_number,
    )
    resolved = resolve_machine_connection(settings, conn)
    return expected_ip, expected_port, resolved


def check_live_push(
    settings: Settings,
    *,
    server_ip: str | None = None,
    server_port: int | None = None,
    connection: MachineConnectionRequest | None = None,
) -> LivePushStatus:
    expected_ip, expected_port, resolved = resolve_live_push_targets(
        settings,
        server_ip=server_ip,
        server_port=server_port,
        connection=connection,
    )
    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    try:
        client.connect_tcpip(
            machine_number=resolved.machine_number,
            ip_address=resolved.machine_ip,
            port=resolved.machine_port,
            password=resolved.machine_password,
        )
        current = _xml_get_log_server(client, resolved.machine_number)
    except Exception as exc:  # noqa: BLE001
        return LivePushStatus(
            ok=False,
            device_ip=resolved.machine_ip,
            expected_server_ip=expected_ip,
            expected_server_port=expected_port,
            configured_server_ip=None,
            configured_server_port=None,
            event_send_mode=None,
            drift=True,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        try:
            client.disconnect(resolved.machine_number)
        except MachineSdkError:
            pass

    configured_ip = str(current.get("ManagerPCDomainName") or "").strip() or None
    configured_port_raw = current.get("ManagerPCPort")
    configured_port = int(configured_port_raw) if configured_port_raw is not None else None
    event_mode_raw = current.get("EventSendMode")
    event_mode = int(event_mode_raw) if event_mode_raw is not None else None

    drift = (
        configured_ip != expected_ip
        or configured_port != expected_port
        or event_mode != EVENT_SEND_NETWORK
    )
    return LivePushStatus(
        ok=not drift,
        device_ip=resolved.machine_ip,
        expected_server_ip=expected_ip,
        expected_server_port=expected_port,
        configured_server_ip=configured_ip,
        configured_server_port=configured_port,
        event_send_mode=event_mode,
        drift=drift,
    )


def ensure_live_push(
    settings: Settings,
    *,
    server_ip: str | None = None,
    server_port: int | None = None,
    connection: MachineConnectionRequest | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    expected_ip, expected_port, resolved = resolve_live_push_targets(
        settings,
        server_ip=server_ip,
        server_port=server_port,
        connection=connection,
    )
    summary: dict[str, Any] = {
        "device_ip": resolved.machine_ip,
        "target_server_ip": expected_ip,
        "target_server_port": expected_port,
        "event_send_mode": EVENT_SEND_NETWORK,
    }

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
        before_log = _xml_get_log_server(client, resolved.machine_number)
        summary["before_log_server"] = before_log

        if dry_run:
            summary["dry_run"] = True
            return summary

        _xml_set_log_server(
            client,
            resolved.machine_number,
            server_ip=expected_ip,
            server_port=expected_port,
            event_mode=EVENT_SEND_NETWORK,
        )
        after_log = _xml_get_log_server(client, resolved.machine_number)
        summary["after_log_server"] = after_log
        summary["ok"] = True
    finally:
        try:
            client.enable_device(resolved.machine_number, True)
        except MachineSdkError:
            pass
        client.disconnect(resolved.machine_number)

    return summary
