#!/usr/bin/env python3
"""Live CRUD smoke test against gateway + machine."""
from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass, field

import httpx

BASE = "http://127.0.0.1:8080"
MW_KEY = "dev-middleware-key"
AGENT_KEY = "dev-agent-key"
AGENT_JWT = "dev-agent-jwt"

DEVICE_ID = "CRUD_TEST_DEV"
EMP_CODE = "99091"
USER_ID = 99091

MACHINE = {
    "machine_ip": "192.168.29.44",
    "machine_port": 5005,
    "machine_password": 0,
    "machine_number": 2,
    "device_id": DEVICE_ID,
}


@dataclass
class Result:
    name: str
    ok: bool
    status: int | None = None
    detail: str = ""


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    def add(self, name: str, ok: bool, status: int | None = None, detail: str = "") -> None:
        self.results.append(Result(name=name, ok=ok, status=status, detail=detail[:500]))

    def print_summary(self) -> int:
        passed = sum(1 for r in self.results if r.ok)
        failed = len(self.results) - passed
        print("\n" + "=" * 72)
        print("CRUD SMOKE TEST SUMMARY")
        print("=" * 72)
        for r in self.results:
            mark = "PASS" if r.ok else "FAIL"
            st = f" HTTP {r.status}" if r.status is not None else ""
            print(f"[{mark}]{st}  {r.name}")
            if r.detail:
                print(f"         {r.detail}")
        print("-" * 72)
        print(f"Total: {len(self.results)}  Passed: {passed}  Failed: {failed}")
        return 0 if failed == 0 else 1


def _json(resp: httpx.Response) -> dict | list | str:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return resp.text[:300]


def main() -> int:
    report = Report()
    headers = {"x-api-key": MW_KEY}
    agent_headers = {"x-api-key": AGENT_KEY, "Authorization": f"Bearer {AGENT_JWT}"}
    machine_body = {**MACHINE}

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        # --- Infrastructure ---
        r = client.get("/health")
        report.add("GET /health", r.status_code == 200, r.status_code, str(_json(r)))

        r = client.get("/api/v1/health")
        report.add("GET /api/v1/health", r.status_code == 200, r.status_code, str(_json(r)))

        r = client.post("/api/machine/test-connection", json=machine_body)
        body = _json(r)
        connected = isinstance(body, dict) and body.get("connected") is True
        report.add("POST /api/machine/test-connection (SDK)", connected, r.status_code, str(body))

        # --- Device CRUD ---
        r = client.post(
            "/api/v1/devices",
            headers=headers,
            json={
                "device_id": DEVICE_ID,
                "device_name": "CRUD Test Device",
                "site_id": "TEST-SITE",
                "ip": MACHINE["machine_ip"],
                "port": MACHINE["machine_port"],
                "machine_password": "0",
            },
        )
        report.add("POST /api/v1/devices (Create/Upsert)", r.status_code in (200, 201), r.status_code, str(_json(r)))

        r = client.get("/api/v1/devices", headers=headers)
        dev_ok = r.status_code == 200 and any(
            row.get("device_id") == DEVICE_ID for row in (_json(r) or {}).get("rows", [])
        )
        report.add("GET /api/v1/devices (Read list)", dev_ok, r.status_code, f"found={dev_ok}")

        r = client.patch(
            f"/api/v1/devices/{DEVICE_ID}",
            headers=headers,
            json={"device_name": "CRUD Test Device Updated"},
        )
        report.add("PATCH /api/v1/devices/{id} (Update)", r.status_code == 200, r.status_code, str(_json(r)))

        # --- Employee middleware CRUD (cloud DB) ---
        r = client.post(
            "/api/v1/employees",
            headers=headers,
            json={
                "employee_code": EMP_CODE,
                "employee_name": "CRUD Smoke User",
                "card_no": str(USER_ID),
                "department": "QA",
                "designation": "Tester",
            },
        )
        report.add(
            "POST /api/v1/employees (Create DB only)",
            r.status_code in (200, 201),
            r.status_code,
            str(_json(r)),
        )

        r = client.get("/api/v1/employees", headers=headers)
        get_list_ok = r.status_code == 200
        report.add("GET /api/v1/employees (Read list)", get_list_ok, r.status_code, f"status={r.status_code}")

        r = client.get(f"/api/v1/employees/{EMP_CODE}", headers=headers)
        get_one_ok = r.status_code == 200
        report.add("GET /api/v1/employees/{code} (Read one)", get_one_ok, r.status_code, f"status={r.status_code}")

        r = client.patch(
            f"/api/v1/employees/{EMP_CODE}",
            headers=headers,
            json={"employee_name": "CRUD Smoke User Updated", "phone_no": "9999900001"},
        )
        report.add("PATCH /api/v1/employees/{code} (Update DB)", r.status_code == 200, r.status_code, str(_json(r)))

        # --- Machine employee CRUD ---
        create_machine = {
            **machine_body,
            "user_id": USER_ID,
            "user_name": "CRUD Smoke User",
            "card_no": str(USER_ID),
            "enable": True,
        }
        r = client.put(f"/api/machine/employees/{EMP_CODE}", json=create_machine)
        body = _json(r)
        machine_create_ok = r.status_code == 200
        report.add(
            "PUT /api/machine/employees/{code} (Create on machine)",
            machine_create_ok,
            r.status_code,
            str(body),
        )

        r = client.post(f"/api/machine/employees/{EMP_CODE}/read", json={**machine_body, "user_id": USER_ID})
        body = _json(r)
        exists = isinstance(body, dict) and body.get("exists_on_machine") is True
        report.add(
            "POST /api/machine/employees/{code}/read (Read from machine)",
            r.status_code == 200 and exists,
            r.status_code,
            str(body),
        )

        r = client.put(
            f"/api/machine/employees/{EMP_CODE}",
            json={**create_machine, "user_name": "CRUD Renamed On Machine"},
        )
        report.add(
            "PUT /api/machine/employees/{code} (Update on machine)",
            r.status_code == 200,
            r.status_code,
            str(_json(r)),
        )

        r = client.post(f"/api/machine/employees/{EMP_CODE}/disable", json={**machine_body, "user_id": USER_ID})
        dis_body = _json(r)
        disable_ok = r.status_code == 200 and isinstance(dis_body, dict) and dis_body.get("enabled") is False
        report.add(
            "POST /api/machine/employees/{code}/disable",
            disable_ok,
            r.status_code,
            str(dis_body),
        )

        r = client.post(f"/api/machine/employees/{EMP_CODE}/enable", json={**machine_body, "user_id": USER_ID})
        en_body = _json(r)
        enable_ok = r.status_code == 200 and isinstance(en_body, dict) and en_body.get("enabled") is True
        report.add(
            "POST /api/machine/employees/{code}/enable",
            enable_ok,
            r.status_code,
            str(en_body),
        )

        r = client.post(
            "/api/machine/employees/sync",
            json={**machine_body, "dry_run": True, "employee_code": EMP_CODE, "limit": 5},
        )
        report.add(
            "POST /api/machine/employees/sync (dry_run preview)",
            r.status_code == 200,
            r.status_code,
            str(_json(r))[:200],
        )

        # --- Command queue (async path) ---
        req_id = str(uuid.uuid4())
        r = client.post(
            f"/api/v1/devices/{DEVICE_ID}/employees/{EMP_CODE}/disable",
            headers=headers,
            json={"request_id": req_id, "payload": {"user_id": USER_ID}, "priority": 100},
        )
        report.add(
            "POST /api/v1/devices/{id}/employees/{code}/disable (queue)",
            r.status_code == 202,
            r.status_code,
            str(_json(r)),
        )

        r = client.get("/api/v1/commands", headers=headers, params={"device_id": DEVICE_ID, "limit": 5})
        report.add("GET /api/v1/commands (Read queue)", r.status_code == 200, r.status_code, str(_json(r))[:200])

        # --- Agent heartbeat ---
        r = client.post(
            "/api/v1/agent/heartbeat",
            headers=agent_headers,
            json={"agent_id": "CRUD_AGENT", "site_id": "TEST-SITE", "host_name": "PC-TEST"},
        )
        report.add("POST /api/v1/agent/heartbeat", r.status_code == 200, r.status_code, str(_json(r)))

        # --- Attendance ingest simulate ---
        punch = f"user_id={USER_ID}\tio_time=20260614093000\tdev_id=CRUD-SN-01\n".encode("ascii")
        r = client.post(
            "/machine/realtime_glog",
            headers={"request_code": "realtime_glog"},
            content=punch,
        )
        ingest_ok = r.status_code == 200 and "response_code=OK" in r.text
        report.add("POST /machine/realtime_glog (punch ingest)", ingest_ok, r.status_code, r.text[:100])

        r = client.get("/api/v1/attendance", headers=headers, params={"employee_code": EMP_CODE, "limit": 5})
        report.add("GET /api/v1/attendance", r.status_code == 200, r.status_code, str(_json(r))[:200])

        r = client.get("/api/attendances", params={"employee_code": EMP_CODE, "limit": 5})
        report.add("GET /api/attendances (dashboard API)", r.status_code == 200, r.status_code, str(_json(r))[:200])

        # --- Machine delete (cleanup) ---
        r = client.request(
            "DELETE",
            f"/api/machine/employees/{EMP_CODE}",
            json={**machine_body, "user_id": USER_ID, "all_slots": True},
        )
        del_body = _json(r)
        delete_ok = r.status_code == 200 and isinstance(del_body, dict) and del_body.get("deleted") is True
        report.add(
            "DELETE /api/machine/employees/{code} (Delete from machine)",
            delete_ok,
            r.status_code,
            str(del_body),
        )

        r = client.post(f"/api/machine/employees/{EMP_CODE}/read", json={**machine_body, "user_id": USER_ID})
        body = _json(r)
        gone = isinstance(body, dict) and body.get("exists_on_machine") is False
        report.add(
            "POST read-after-delete (verify removed)",
            r.status_code == 200 and gone,
            r.status_code,
            str(body),
        )

        # --- Employee DB delete (cleanup) ---
        r = client.delete(f"/api/v1/employees/{EMP_CODE}", headers=headers)
        report.add(
            "DELETE /api/v1/employees/{code} (Delete DB only)",
            r.status_code == 200,
            r.status_code,
            str(_json(r)),
        )

    return report.print_summary()


if __name__ == "__main__":
    sys.exit(main())
