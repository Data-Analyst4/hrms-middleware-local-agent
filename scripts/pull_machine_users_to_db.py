#!/usr/bin/env python3
"""Pull all users from biometric machine and store in local SQLite DB."""
from __future__ import annotations

import argparse
import json

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Import machine users into middleware database")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--machine-ip", default="192.168.29.44")
    parser.add_argument("--machine-port", type=int, default=5005)
    parser.add_argument("--machine-password", type=int, default=0)
    parser.add_argument("--machine-number", type=int, default=2)
    parser.add_argument("--device-id", default="DEV-LIVE-01")
    parser.add_argument("--limit", type=int, default=50000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    body = {
        "machine_ip": args.machine_ip,
        "machine_port": args.machine_port,
        "machine_password": args.machine_password,
        "machine_number": args.machine_number,
        "device_id": args.device_id,
        "include_user_names": True,
        "limit": args.limit,
        "dry_run": args.dry_run,
        "overwrite_existing_names": True,
    }
    with httpx.Client(base_url=args.base_url, timeout=600.0) as client:
        response = client.post("/api/machine/employees/import-to-db", json=body)
        print(json.dumps(response.json(), indent=2))
        return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
