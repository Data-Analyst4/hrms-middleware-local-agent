#!/usr/bin/env python3
"""Pull general attendance logs from biometric device into local SQLite."""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
from datetime import datetime
from pathlib import Path

from attendance_relay.settings import load_settings
from attendance_relay.db import create_db_engine, init_local_schema
from attendance_relay.hashing import build_event_hash
from attendance_relay.models import MachinePunch
from attendance_relay.repository import AttendanceRepository
from attendance_relay.machine_sdk import SBXPCClient, MachineSdkError
from attendance_relay.time_utils import format_datetime, format_time, now_local


def _read_general_logs(
    *,
    dll_path: Path,
    machine_ip: str,
    machine_port: int,
    machine_password: int,
    machine_number: int,
    read_mark: bool = False,
) -> list[dict[str, str | int]]:
    client = SBXPCClient(dll_path)
    dll = client._dll
    long_t = client._long_t
    bool_t = client._bool_t

    dll._ReadGeneralLogData.argtypes = [long_t, bool_t]
    dll._ReadGeneralLogData.restype = bool_t
    dll._GetGeneralLogData.argtypes = [
        long_t,
        ctypes.POINTER(long_t),
        ctypes.POINTER(long_t),
        ctypes.POINTER(long_t),
        ctypes.POINTER(long_t),
        ctypes.POINTER(long_t),
        ctypes.POINTER(long_t),
        ctypes.POINTER(long_t),
        ctypes.POINTER(long_t),
        ctypes.POINTER(long_t),
        ctypes.POINTER(long_t),
    ]
    dll._GetGeneralLogData.restype = bool_t

    client.dotnet()
    client.connect_tcpip(
        machine_number=machine_number,
        ip_address=machine_ip,
        port=machine_port,
        password=machine_password,
    )
    rows: list[dict[str, str | int]] = []
    try:
        client.enable_device(machine_number, False)
        if not bool(dll._ReadGeneralLogData(machine_number, read_mark)):
            raise MachineSdkError("ReadGeneralLogData failed")

        while True:
            t_machine = long_t(0)
            enroll = long_t(0)
            e_machine = long_t(0)
            verify = long_t(0)
            year = long_t(0)
            month = long_t(0)
            day = long_t(0)
            hour = long_t(0)
            minute = long_t(0)
            second = long_t(0)
            has = bool(
                dll._GetGeneralLogData(
                    machine_number,
                    ctypes.byref(t_machine),
                    ctypes.byref(enroll),
                    ctypes.byref(e_machine),
                    ctypes.byref(verify),
                    ctypes.byref(year),
                    ctypes.byref(month),
                    ctypes.byref(day),
                    ctypes.byref(hour),
                    ctypes.byref(minute),
                    ctypes.byref(second),
                )
            )
            if not has:
                break

            user_id = int(enroll.value)
            log_dt = datetime(
                int(year.value),
                int(month.value),
                int(day.value),
                int(hour.value),
                int(minute.value),
                int(second.value),
            )
            raw_io_time = log_dt.strftime("%Y%m%d%H%M%S")
            user_name = ""
            try:
                user_name = client.get_user_name(machine_number, user_id)
            except MachineSdkError:
                pass
            rows.append(
                {
                    "user_id": user_id,
                    "user_name": user_name,
                    "log_datetime": format_datetime(log_dt),
                    "log_time": format_time(log_dt),
                    "raw_io_time": raw_io_time,
                    "verify_mode": int(verify.value),
                }
            )
    finally:
        try:
            client.enable_device(machine_number, True)
        except MachineSdkError:
            pass
        client.disconnect(machine_number)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull device GLog rows into tbl_realtime_glog.")
    parser.add_argument("--config", default="configs/dev.yaml")
    parser.add_argument("--since", default="", help="Import logs on/after this date (YYYY-MM-DD).")
    parser.add_argument("--device-sn", default="2", help="device_sn stored in tbl_realtime_glog.")
    parser.add_argument("--device-id", default="V8-T501-01")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Read only new device logs since last SDK read (ReadMark=true). Fast for polling.",
    )
    args = parser.parse_args()

    settings = load_settings(args.config)
    since = (args.since or "").strip()
    if not since:
        since = now_local(settings.tz_name).strftime("%Y-%m-%d")

    engine = create_db_engine(settings)
    if engine.dialect.name == "sqlite":
        init_local_schema(engine)
    repo = AttendanceRepository(engine)

    existing = repo.list_attendance(limit=10000, since=since)
    existing_keys = {
        (str(row.get("employee_code") or ""), str(row.get("log_datetime") or ""), str(row.get("device_sn") or ""))
        for row in existing
    }

    dll_path = Path(settings.machine_sdk_dll_path)
    logs = _read_general_logs(
        dll_path=dll_path,
        machine_ip=settings.machine_sync_ip,
        machine_port=settings.machine_sync_port,
        machine_password=settings.machine_sync_password,
        machine_number=settings.machine_sync_machine_number,
        read_mark=bool(args.incremental),
    )

    downloaded_at = now_local(settings.tz_name)
    imported = 0
    skipped = 0
    latest: dict[str, str | int] | None = None

    for row in logs:
        if row["log_datetime"][:10] < since:
            continue
        employee_code = str(row["user_id"])
        device_sn = str(args.device_sn)
        key = (employee_code, str(row["log_datetime"]), device_sn)
        if key in existing_keys:
            skipped += 1
            continue

        punch = MachinePunch(
            employee_code=employee_code,
            log_datetime=datetime.strptime(str(row["log_datetime"]), "%Y-%m-%d %H:%M:%S"),
            log_time=str(row["log_time"]),
            downloaded_at=downloaded_at,
            device_sn=device_sn,
            raw_user_id=employee_code,
            raw_io_time=str(row["raw_io_time"]),
            source_ip=settings.machine_sync_ip,
            raw_preview=json.dumps(
                {
                    "source": "sdk_pull",
                    "device_id": args.device_id,
                    "user_name": row.get("user_name"),
                    "verify_mode": row.get("verify_mode"),
                },
                ensure_ascii=False,
            )[:2000],
        )
        event_hash = build_event_hash(
            employee_code=punch.employee_code,
            log_datetime=format_datetime(punch.log_datetime),
            log_time=punch.log_time,
            device_sn=punch.device_sn,
        )
        repo.persist_punch(
            punch=punch,
            event_hash=event_hash,
            max_retries=settings.max_retries,
            enqueue_outbound=settings.outbound_relay_enabled,
        )
        existing_keys.add(key)
        imported += 1
        latest = row
        if imported >= args.limit:
            break

    summary = {
        "since": since,
        "incremental": bool(args.incremental),
        "device_ip": settings.machine_sync_ip,
        "device_sn": args.device_sn,
        "read_from_device": len(logs),
        "imported": imported,
        "skipped_duplicates": skipped,
        "latest_imported": latest,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
