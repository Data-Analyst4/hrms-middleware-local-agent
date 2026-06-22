from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from attendance_relay.db import create_db_engine, init_local_schema
from attendance_relay.decoder import DecodeError, decode_machine_payload
from attendance_relay.hashing import build_event_hash
from attendance_relay.logging_utils import configure_logging, log_event
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import Settings
from attendance_relay.time_utils import format_datetime, now_local

LOGGER = logging.getLogger("attendance_relay.fk_web_listener")


def _write_fk_health(settings: Settings, *, event: str, source_ip: str | None = None) -> None:
    health_path = Path(settings.fk_health_file)
    health_path.parent.mkdir(parents=True, exist_ok=True)
    now = format_datetime(now_local(settings.tz_name))
    payload = {
        "updated_at": now,
        "last_event": event,
        "last_source_ip": source_ip,
        "port": settings.fk_web_listener_port,
    }
    if health_path.exists():
        try:
            payload.update(json.loads(health_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    payload["updated_at"] = now
    payload["last_event"] = event
    if source_ip:
        payload["last_source_ip"] = source_ip
    if event == "fk_punch_ingested":
        payload["last_punch_at"] = now
    health_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


def _parse_headers(raw: bytes) -> tuple[str, dict[str, str], bytes]:
    header_end = raw.find(b"\r\n\r\n")
    sep_len = 4
    if header_end < 0:
        header_end = raw.find(b"\n\n")
        sep_len = 2
    if header_end < 0:
        raise ValueError("missing HTTP header terminator")

    header_block = raw[:header_end].decode("latin-1", errors="ignore")
    body = raw[header_end + sep_len :]
    lines = header_block.replace("\r", "").split("\n")
    request_line = lines[0] if lines else ""
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return request_line, headers, body


def _read_content_length(headers: dict[str, str], body: bytes) -> bytes:
    raw_len = headers.get("content-length", "").strip()
    if not raw_len.isdigit():
        return body
    expected = int(raw_len)
    if len(body) >= expected:
        return body[:expected]
    return body


def _fk_response(body: str = "", ok_code: str = "OK") -> bytes:
    payload = body.encode("ascii", errors="ignore")
    header = (
        "HTTP/1.0 200 OK\r\n"
        f"response_code: {ok_code}\r\n"
        "Connection: close\r\n"
        "Content-Type: application/octet-stream\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "\r\n"
    )
    return header.encode("ascii") + payload


async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    settings: Settings,
    repo: AttendanceRepository,
) -> None:
    peer = writer.get_extra_info("peername")
    source_ip = peer[0] if peer else None
    try:
        raw = await asyncio.wait_for(reader.read(65536), timeout=30.0)
        if not raw:
            return

        request_line, headers, body = _parse_headers(raw)
        body = _read_content_length(headers, body)
        request_code = headers.get("request_code", "")
        dev_id = headers.get("dev_id", "")

        if request_code == "receive_cmd":
            log_event(LOGGER, "info", "fk_receive_cmd", dev_id=dev_id, source_ip=source_ip)
            _write_fk_health(settings, event="fk_receive_cmd", source_ip=source_ip)
            writer.write(_fk_response(""))
            await writer.drain()
            return

        if request_code != settings.expected_request_code:
            log_event(
                LOGGER,
                "warning",
                "fk_invalid_request_code",
                request_code=request_code,
                source_ip=source_ip,
            )
            writer.write(_fk_response("", ok_code="ERROR"))
            await writer.drain()
            return

        downloaded_at = now_local(settings.tz_name)
        try:
            punch = decode_machine_payload(
                raw_body=body,
                downloaded_at=downloaded_at,
                source_ip=source_ip,
                device_sn_override=dev_id or None,
            )
        except DecodeError as exc:
            log_event(
                LOGGER,
                "error",
                "fk_decode_failed",
                error=str(exc),
                source_ip=source_ip,
                dev_id=dev_id,
            )
            writer.write(_fk_response("", ok_code="ERROR"))
            await writer.drain()
            return

        event_hash = build_event_hash(
            employee_code=punch.employee_code,
            log_datetime=format_datetime(punch.log_datetime),
            log_time=punch.log_time,
            device_sn=punch.device_sn,
        )
        _, deduped = repo.persist_punch(
            punch=punch,
            event_hash=event_hash,
            max_retries=settings.max_retries,
            enqueue_outbound=settings.outbound_relay_enabled,
        )
        log_event(
            LOGGER,
            "info",
            "fk_punch_ingested",
            employee_code=punch.employee_code,
            device_sn=punch.device_sn,
            log_datetime=format_datetime(punch.log_datetime),
            deduped=deduped,
            source_ip=source_ip,
        )
        _write_fk_health(settings, event="fk_punch_ingested", source_ip=source_ip)
        writer.write(_fk_response(f"response_code={settings.machine_ok_response_code}"))
        await writer.drain()
    except Exception as exc:  # noqa: BLE001
        log_event(LOGGER, "error", "fk_connection_error", error=str(exc), source_ip=source_ip)
        try:
            writer.write(_fk_response("", ok_code="ERROR"))
            await writer.drain()
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass


async def run_fk_web_listener(settings: Settings) -> None:
    configure_logging(settings.log_level)
    engine = create_db_engine(settings)
    if engine.dialect.name == "sqlite":
        init_local_schema(engine)
    repo = AttendanceRepository(engine)

    host = settings.fk_web_listener_host
    port = settings.fk_web_listener_port

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _handle_connection(reader, writer, settings=settings, repo=repo)

    server = await asyncio.start_server(handler, host=host, port=port)
    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    log_event(LOGGER, "info", "fk_web_listener_started", host=host, port=port, bind=sockets)
    _write_fk_health(settings, event="fk_web_listener_started")
    async with server:
        await server.serve_forever()
