#!/usr/bin/env python3
"""Probe and pull detailed machine user data for Phase 1 testing."""
from __future__ import annotations

import argparse
import json

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe/pull machine user detail")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--machine-ip", default="192.168.29.44")
    parser.add_argument("--machine-port", type=int, default=5005)
    parser.add_argument("--machine-password", type=int, default=0)
    parser.add_argument("--machine-number", type=int, default=2)
    parser.add_argument("--device-id", default="DEV-LIVE-01")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()

    machine = {
        "machine_ip": args.machine_ip,
        "machine_port": args.machine_port,
        "machine_password": args.machine_password,
        "machine_number": args.machine_number,
    }

    with httpx.Client(base_url=args.base_url, timeout=300.0) as client:
        probe_body = {**machine, "test_user_id": args.user_id, "probe_fingerprint_slot": 0}
        probe = client.post("/api/machine/capabilities/probe-user", json=probe_body)
        print("PROBE", probe.status_code)
        print(json.dumps(probe.json(), indent=2))
        if probe.status_code != 200:
            return 1
        if args.probe_only:
            return 0

        pull_body = {
            **machine,
            "user_id": args.user_id,
            "device_id": args.device_id,
            "store_to_db": True,
            "include_fingerprint_templates": True,
            "include_card_enrollment": True,
        }
        pull = client.post(f"/api/machine/employees/{args.user_id}/pull-detail", json=pull_body)
        print("PULL", pull.status_code)
        body = pull.json()
        if isinstance(body, dict) and "enrollments" in body:
            slim = dict(body)
            slim["enrollments"] = [
                {
                    **row,
                    "template_base64": (
                        f"<{len(row.get('template_base64') or '')} chars>"
                        if row.get("template_base64")
                        else None
                    ),
                }
                for row in body.get("enrollments") or []
            ]
            print(json.dumps(slim, indent=2))
        else:
            print(json.dumps(body, indent=2))
        if pull.status_code != 200:
            return 1

        detail = client.get(
            f"/api/v1/machine-users/{args.user_id}/detail",
            headers={"x-api-key": "dev-middleware-key"},
            params={"machine_ip": args.machine_ip, "device_id": args.device_id},
        )
        print("DETAIL", detail.status_code)
        detail_body = detail.json()
        if isinstance(detail_body, dict) and "enrollments" in detail_body:
            slim_detail = dict(detail_body)
            slim_detail["enrollments"] = [
                {
                    **row,
                    "template_base64": (
                        f"<{len(row.get('template_base64') or '')} chars>"
                        if row.get("template_base64")
                        else None
                    ),
                }
                for row in detail_body.get("enrollments") or []
            ]
            print(json.dumps(slim_detail, indent=2))
        else:
            print(json.dumps(detail_body, indent=2))
        return 0 if detail.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
