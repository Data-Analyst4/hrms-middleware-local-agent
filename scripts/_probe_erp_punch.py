#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from attendance_relay.settings import load_settings


def sig(secret: str, body: bytes) -> str:
    d = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={d}"


def main() -> int:
    s = load_settings("configs/factory.yaml")
    payload = {
        "employee_code_raw": "167",
        "enroll_no": "167",
        "employee_code": "167",
        "log_datetime": "2026-06-22 21:29:21",
        "log_time": "21:29:21",
        "downloaded_at": "2026-06-22 21:30:00",
        "device_sn": "2",
        "branch_code": s.outbound_site_code,
        "device_id": s.outbound_device_id,
        "io_time": "20260622212921",
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    idem = f"{payload['device_sn']}:{payload['enroll_no']}:{payload['io_time']}"
    base = {
        "Content-Type": "application/json",
        "X-Site-Code": s.outbound_site_code,
        "X-Device-Id": s.outbound_device_id,
        "X-Idempotency-Key": idem,
        "X-Middleware-Signature": sig(s.outbound_hmac_secret, body),
    }

    with httpx.Client(timeout=20.0, verify=True) as client:
        for label, headers in [
            ("with x-api-key (current worker)", {**base, s.outbound_api_key_header: s.outbound_api_key}),
            ("HMAC only (no x-api-key)", dict(base)),
            ("wrong HMAC", {**base, s.outbound_api_key_header: s.outbound_api_key, "X-Middleware-Signature": "sha256=bad"}),
        ]:
            r = client.post(s.outbound_url, content=body, headers=headers)
            print(f"\n=== {label} ===")
            print("status:", r.status_code)
            print("body:", r.text[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
