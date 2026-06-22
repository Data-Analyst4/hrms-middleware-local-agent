#!/usr/bin/env python3
"""Smoke test HRMS phase APIs (no live machine required for most checks)."""
from __future__ import annotations

import sys
import uuid

import httpx

BASE = "http://127.0.0.1:8080"
MW_KEY = "dev-middleware-key"
DEVICE_ID = "PHASE_TEST_DEV"


def main() -> int:
    headers = {"x-api-key": MW_KEY}
    failed = 0

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        checks = [
            ("GET /health", lambda: client.get("/health")),
            (
                "POST /api/v1/devices",
                lambda: client.post(
                    "/api/v1/devices",
                    headers=headers,
                    json={
                        "device_id": DEVICE_ID,
                        "site_id": "TEST-SITE",
                        "device_name": "Phase Test",
                        "ip": "192.168.29.44",
                        "port": 5005,
                        "machine_number": 2,
                        "machine_password": "0",
                    },
                ),
            ),
            ("GET /api/v1/employees", lambda: client.get("/api/v1/employees", headers=headers)),
            ("GET /api/v1/sync-status", lambda: client.get("/api/v1/sync-status", headers=headers)),
            (
                "GET /api/v1/mappings/unmapped",
                lambda: client.get("/api/v1/mappings/unmapped", headers=headers, params={"device_id": DEVICE_ID}),
            ),
            ("GET /settings page", lambda: client.get("/settings")),
            (
                "POST sync-queue command",
                lambda: client.post(
                    f"/api/v1/devices/{DEVICE_ID}/employees/99091/sync-queue",
                    headers=headers,
                    json={"request_id": str(uuid.uuid4()), "payload": {}, "priority": 100},
                ),
            ),
            (
                "GET local punches",
                lambda: client.get("/api/v1/attendance/local-punches", headers=headers, params={"limit": 5}),
            ),
        ]

        for name, fn in checks:
            try:
                resp = fn()
                ok = resp.status_code in (200, 201, 202)
                mark = "PASS" if ok else "FAIL"
                print(f"[{mark}] {name} HTTP {resp.status_code}")
                if not ok:
                    failed += 1
                    print(f"       {resp.text[:200]}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"[FAIL] {name} error={exc}")

    print(f"\nFailed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
