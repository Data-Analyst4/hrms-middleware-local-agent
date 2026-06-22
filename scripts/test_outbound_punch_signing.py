#!/usr/bin/env python3
"""Smoke-test K95 punch webhook payload signing (no live HTTP unless --send)."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from attendance_relay.outbound_client import OutboundClient, _build_hmac_signature
from attendance_relay.models import OutboxRecord
from datetime import datetime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="POST to outbound_url from dev.yaml")
    args = parser.parse_args()

    payload = {
        "employee_code_raw": "88001",
        "enroll_no": "88001",
        "employee_code": "88001",
        "log_datetime": "2026-06-13 10:15:30",
        "log_time": "10:15:30",
        "downloaded_at": "2026-06-13 10:15:31",
        "device_sn": "RSS20241196340",
        "branch_code": "V8",
        "device_id": "V8-T501-01",
        "io_time": "20260613101530",
        "raw_payload": {"user_id": "88001", "io_time": "20260613101530"},
    }
    secret = "change-me-v8-webhook-hmac"
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig = _build_hmac_signature(secret, body)
    print("body:", body.decode())
    print("X-Middleware-Signature:", sig)
    print("X-Idempotency-Key:", f"{payload['device_sn']}:{payload['enroll_no']}:{payload['io_time']}")

    if not args.send:
        return 0

    from attendance_relay.settings import load_settings

    settings = load_settings("configs/dev.yaml")
    client = OutboundClient(
        url=settings.outbound_url,
        api_key_header=settings.outbound_api_key_header,
        api_key=settings.outbound_api_key,
        timeout_seconds=settings.outbound_timeout_seconds,
        verify_tls=settings.outbound_verify_tls,
        enforce_https=settings.enforce_https,
        enforce_post=settings.enforce_post,
        method=settings.outbound_method,
        site_code=settings.outbound_site_code,
        device_id=settings.outbound_device_id,
        hmac_secret=settings.outbound_hmac_secret,
    )
    record = OutboxRecord(
        id=1,
        employee_code="88001",
        log_datetime=datetime(2026, 6, 13, 10, 15, 30),
        log_time="10:15:30",
        downloaded_at=datetime(2026, 6, 13, 10, 15, 31),
        device_sn="RSS20241196340",
        attempt_count=0,
        raw_preview=json.dumps(payload["raw_payload"]),
    )
    result = client.send(record, payload_override=payload)
    print("send ok:", result.ok, "status:", result.status_code, "error:", result.error)
    client.close()
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
