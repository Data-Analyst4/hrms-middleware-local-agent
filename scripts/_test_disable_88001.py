#!/usr/bin/env python3
"""Read, disable, and verify employee 88001 on the biometric machine."""
from __future__ import annotations

import json
import sys

import httpx

BASE = "http://127.0.0.1:8080"
EMP = "88001"


def post(path: str, body: dict | None = None) -> tuple[int, dict]:
    payload = body or {}
    r = httpx.post(f"{BASE}{path}", json=payload, timeout=60.0)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return r.status_code, data


def main() -> int:
    print("=== 1) Read employee on machine (before) ===")
    status, data = post(f"/api/machine/employees/{EMP}/read", {})
    print(status, json.dumps(data, indent=2, ensure_ascii=False))
    if status != 200:
        print("\nNote: employee must exist in employee_master DB for machine APIs.")
        print("Trying read-all to see if user 88001 is on device anyway...")
        status2, data2 = post("/api/machine/employees/read-all", {"include_user_names": True, "limit": 200})
        print(status2, "loaded", data2.get("loaded"))
        for row in data2.get("rows", []):
            if str(row.get("user_id")) in ("88001", "88001") or "88001" in str(row.get("user_name", "")):
                print("  found on machine:", row)
        return 1

    print("\n=== 2) Disable employee ===")
    status, data = post(
        f"/api/machine/employees/{EMP}/disable",
        {"all_slots": True},
    )
    print(status, json.dumps(data, indent=2, ensure_ascii=False))
    if status != 200:
        return 1

    print("\n=== 3) Read employee on machine (after disable) ===")
    status, data = post(f"/api/machine/employees/{EMP}/read", {})
    print(status, json.dumps(data, indent=2, ensure_ascii=False))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
