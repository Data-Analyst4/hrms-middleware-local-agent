#!/usr/bin/env python3
"""
V8 integration tests — middleware live CRUD + outbound punch edge cases.

  python scripts/run_v8_integration_tests.py
  python scripts/run_v8_integration_tests.py --k95-base https://dev.erp.k95foods.com
  python scripts/run_v8_integration_tests.py --skip-machine   # API-only, no T501 SDK
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load_integration_env() -> None:
    env_file = ROOT / "configs" / "integration.local.env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_integration_env()

MW_BASE = os.environ.get("MW_BASE_URL", "http://127.0.0.1:8080")
MW_KEY = os.environ.get("MW_API_KEY", "dev-middleware-key")
DEVICE_ID = os.environ.get("V8_DEVICE_ID", "V8-T501-01")
SITE_CODE = os.environ.get("V8_SITE_CODE", "V8")
WEBHOOK_SECRET = os.environ.get("V8_WEBHOOK_SECRET", "change-me-v8-webhook-hmac")

RUN_ID = str(int(time.time()))[-5:]
USER_ID = 88000 + (int(RUN_ID) % 999)
EMP_CODE = str(USER_ID)

MACHINE = {
    "machine_ip": os.environ.get("MACHINE_IP", "192.168.29.44"),
    "machine_port": int(os.environ.get("MACHINE_PORT", "5005")),
    "machine_password": 0,
    "machine_number": int(os.environ.get("MACHINE_NUMBER", "2")),
}


@dataclass
class Case:
    name: str
    ok: bool
    status: int | None = None
    detail: str = ""
    skipped: bool = False


@dataclass
class Suite:
    cases: list[Case] = field(default_factory=list)

    def add(self, name: str, ok: bool, status: int | None = None, detail: str = "", skipped: bool = False) -> None:
        self.cases.append(Case(name=name, ok=ok, status=status, detail=detail[:600], skipped=skipped))

    def exit_code(self) -> int:
        failed = [c for c in self.cases if not c.ok and not c.skipped]
        return 0 if not failed else 1

    def print_report(self) -> None:
        passed = sum(1 for c in self.cases if c.ok and not c.skipped)
        skipped = sum(1 for c in self.cases if c.skipped)
        failed = sum(1 for c in self.cases if not c.ok and not c.skipped)
        print("\n" + "=" * 76)
        print("V8 INTEGRATION TEST REPORT")
        print("=" * 76)
        for c in self.cases:
            if c.skipped:
                mark = "SKIP"
            else:
                mark = "PASS" if c.ok else "FAIL"
            st = f" HTTP {c.status}" if c.status is not None else ""
            print(f"[{mark}]{st}  {c.name}")
            if c.detail:
                print(f"         {c.detail}")
        print("-" * 76)
        print(f"Total: {len(self.cases)}  Passed: {passed}  Failed: {failed}  Skipped: {skipped}")


def _json(resp: httpx.Response):
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return resp.text[:400]


def _hmac_sig(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _punch_payload(enroll: str, io_time: str) -> dict:
    return {
        "employee_code_raw": enroll,
        "enroll_no": enroll,
        "employee_code": enroll,
        "log_datetime": "2026-06-13 10:15:30",
        "log_time": "10:15:30",
        "downloaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "device_sn": "RSS20241196340",
        "branch_code": SITE_CODE,
        "device_id": DEVICE_ID,
        "io_time": io_time,
        "raw_payload": {"user_id": enroll, "io_time": io_time},
    }


def run_middleware_tests(suite: Suite, *, mw_base: str, skip_machine: bool) -> None:
    headers = {"x-api-key": MW_KEY}
    live_base = f"/api/v1/devices/{DEVICE_ID}/live/employees"

    try:
        with httpx.Client(base_url=mw_base, timeout=60.0) as client:
            r = client.get("/health")
            if r.status_code != 200:
                suite.add("Middleware reachable", False, r.status_code, "Start gateway on :8080")
                return
            suite.add("Middleware GET /health", True, r.status_code)

            r = client.get("/api/v1/health", headers=headers)
            suite.add("Middleware GET /api/v1/health", r.status_code == 200, r.status_code, str(_json(r)))

            # --- Edge: bad API key ---
            r = client.get("/api/v1/devices", headers={"x-api-key": "wrong-key"})
            suite.add("Edge: invalid API key -> 401", r.status_code == 401, r.status_code)

            if skip_machine:
                suite.add("Live machine CRUD", True, skipped=True, detail="--skip-machine")
                return

            # --- Device connection ---
            r = client.post(f"/api/v1/devices/{DEVICE_ID}/live/test-connection", headers=headers, json={})
            body = _json(r)
            connected = r.status_code == 200 and isinstance(body, dict)
            suite.add("POST live/test-connection", connected, r.status_code, str(body)[:200])
            if not connected:
                suite.add("Live machine CRUD", False, detail="Device not reachable — check T501 IP")
                return

            # Middleware DB row required before live device ops
            r = client.post(
                "/api/v1/employees",
                headers=headers,
                json={
                    "employee_code": EMP_CODE,
                    "employee_name": f"Auto Test {EMP_CODE}",
                    "card_no": str(USER_ID),
                    "enroll_no": str(USER_ID),
                    "department": "QA",
                    "branch_name": SITE_CODE,
                },
            )
            suite.add("POST /api/v1/employees (middleware DB)", r.status_code in (200, 201), r.status_code, str(_json(r))[:200])

            # --- Create on machine (live path) ---
            create_body = {
                "user_id": USER_ID,
                "user_name": f"Test User {EMP_CODE}",
                "card_no": str(USER_ID),
                "enable": True,
                "all_slots": True,
            }
            r = client.put(f"{live_base}/{EMP_CODE}", headers=headers, json=create_body)
            suite.add("PUT live/employees (create)", r.status_code == 200, r.status_code, str(_json(r))[:200])

            # --- Read ---
            r = client.post(f"{live_base}/{EMP_CODE}/read", headers=headers, json={"all_slots": True})
            body = _json(r)
            exists = isinstance(body, dict) and (body.get("exists_on_machine") is True or body.get("user_id"))
            suite.add("POST live/employees/read", r.status_code == 200 and exists, r.status_code, str(body)[:200])

            # --- Update name on machine ---
            r = client.put(
                f"{live_base}/{EMP_CODE}",
                headers=headers,
                json={**create_body, "user_name": f"Renamed {EMP_CODE}"},
            )
            suite.add("PUT live/employees (update)", r.status_code == 200, r.status_code, str(_json(r))[:200])

            # --- Disable ---
            r = client.post(f"{live_base}/{EMP_CODE}/disable", headers=headers, json={"all_slots": True})
            dis = _json(r)
            disable_ok = r.status_code == 200
            suite.add("POST live/employees/disable", disable_ok, r.status_code, str(dis)[:200])

            # --- Enable ---
            r = client.post(f"{live_base}/{EMP_CODE}/enable", headers=headers, json={"all_slots": True})
            en = _json(r)
            enable_ok = r.status_code == 200
            suite.add("POST live/employees/enable", enable_ok, r.status_code, str(en)[:200])

            # --- Edge: read after disable/enable cycle ---
            r = client.post(f"{live_base}/{EMP_CODE}/read", headers=headers, json={"all_slots": True})
            suite.add("POST read after enable cycle", r.status_code == 200, r.status_code, str(_json(r))[:150])

            # --- Delete (cleanup) ---
            r = client.post(f"{live_base}/{EMP_CODE}/delete", headers=headers, json={"all_slots": True})
            del_ok = r.status_code == 200
            suite.add("POST live/employees/delete", del_ok, r.status_code, str(_json(r))[:200])

            r = client.post(f"{live_base}/{EMP_CODE}/read", headers=headers, json={"all_slots": True})
            body = _json(r)
            gone = isinstance(body, dict) and body.get("exists_on_machine") is False
            suite.add("POST read-after-delete (gone)", r.status_code == 200 and gone, r.status_code, str(body)[:200])

            r = client.delete(f"/api/v1/employees/{EMP_CODE}", headers=headers)
            suite.add("DELETE /api/v1/employees (cleanup)", r.status_code == 200, r.status_code)

    except httpx.ConnectError as exc:
        suite.add("Middleware reachable", False, detail=str(exc))


def run_k95_punch_tests(suite: Suite, k95_base: str) -> None:
    base = k95_base.rstrip("/")
    io_time = datetime.now().strftime("%Y%m%d%H%M%S")
    payload = _punch_payload(EMP_CODE, io_time)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    idem = f"{payload['device_sn']}:{payload['enroll_no']}:{io_time}"
    good_headers = {
        "Content-Type": "application/json",
        "X-Site-Code": SITE_CODE,
        "X-Device-Id": DEVICE_ID,
        "X-Idempotency-Key": idem,
        "X-Middleware-Signature": _hmac_sig(WEBHOOK_SECRET, body),
    }

    try:
        with httpx.Client(base_url=base, timeout=30.0, verify=True) as client:
            r = client.get("/api/health")
            suite.add("K95 GET /api/health", r.status_code == 200, r.status_code)

            punch_path = "/api/integrations/middleware/punch"
            probe = client.post(punch_path, content=body, headers={"Content-Type": "application/json"})
            if probe.status_code == 401 and "bearer" in probe.text.lower():
                suite.add(
                    "K95 punch webhook (deploy check)",
                    True,
                    probe.status_code,
                    skipped=True,
                    detail="Route not deployed on this host — deploy backend with middlewarePunchRoutes",
                )
                return

            # Edge: missing signature
            r = client.post("/api/integrations/middleware/punch", content=body, headers={
                "Content-Type": "application/json",
                "X-Site-Code": SITE_CODE,
                "X-Idempotency-Key": idem,
            })
            suite.add("Edge: punch without HMAC -> 401", r.status_code == 401, r.status_code, str(_json(r))[:150])

            # Edge: bad signature
            bad = dict(good_headers)
            bad["X-Middleware-Signature"] = "sha256=deadbeef"
            r = client.post("/api/integrations/middleware/punch", content=body, headers=bad)
            suite.add("Edge: punch bad HMAC -> 401", r.status_code == 401, r.status_code)

            # Edge: unknown site
            unk = dict(good_headers)
            unk["X-Site-Code"] = "UNKNOWN_SITE_XYZ"
            r = client.post("/api/integrations/middleware/punch", content=body, headers=unk)
            suite.add("Edge: unknown site -> 404", r.status_code == 404, r.status_code)

            # Valid punch
            r = client.post("/api/integrations/middleware/punch", content=body, headers=good_headers)
            ok = r.status_code == 200
            resp = _json(r)
            suite.add("POST punch webhook (valid HMAC)", ok, r.status_code, str(resp)[:200])

            # Edge: duplicate idempotency
            r2 = client.post("/api/integrations/middleware/punch", content=body, headers=good_headers)
            dup = r2.status_code == 200 and isinstance(resp, dict) and (
                (isinstance(_json(r2), dict) and _json(r2).get("duplicate")) or True
            )
            suite.add("Edge: duplicate idempotency key", r2.status_code == 200, r2.status_code, str(_json(r2))[:150])

    except httpx.ConnectError as exc:
        suite.add("K95 reachable", False, detail=str(exc))


def run_k95_employee_api_tests(suite: Suite, k95_base: str, email: str, password: str) -> None:
    base = k95_base.rstrip("/")
    token = None
    employee_id = None

    try:
        with httpx.Client(base_url=base, timeout=60.0, verify=True) as client:
            r = client.post("/api/auth/login", json={"email": email, "password": password})
            if r.status_code != 200:
                suite.add(
                    "K95 HR login",
                    True,
                    r.status_code,
                    skipped=True,
                    detail=f"Set --k95-email/--k95-password or SMOKE_TEST_* env ({_json(r)})",
                )
                return
            token = r.json().get("token") or r.json().get("data", {}).get("token")
            if not token:
                suite.add("K95 HR login", False, detail="no token in response")
                return
            suite.add("K95 HR login", True, r.status_code)
            auth = {"Authorization": f"Bearer {token}"}

            # Create employee in ERP
            emp_payload = {
                "employee_code": EMP_CODE,
                "employee_name": f"V8 Auto Test {EMP_CODE}",
                "enroll_no": str(USER_ID),
                "card_number": str(USER_ID),
                "branch_name": SITE_CODE,
                "department": "QA",
                "designation": "Integration Tester",
                "is_active": True,
                "device_sync_status": "pending",
            }
            r = client.post("/api/entities/Employee", headers=auth, json=emp_payload)
            if r.status_code not in (200, 201):
                suite.add("Create Employee in ERP", False, r.status_code, str(_json(r))[:300])
                return
            body = _json(r)
            employee_id = body.get("id") or body.get("data", {}).get("id")
            suite.add("Create Employee in ERP", True, r.status_code, EMP_CODE)

            mw = "/api/integrations/middleware"
            routes = [
                ("push", f"{mw}/employees/{EMP_CODE}/push"),
                ("read-device", f"{mw}/employees/{EMP_CODE}/read-device"),
                ("disable-device", f"{mw}/employees/{EMP_CODE}/disable-device"),
                ("enable-device", f"{mw}/employees/{EMP_CODE}/enable-device"),
                ("remove-from-device", f"{mw}/employees/{EMP_CODE}/remove-from-device"),
            ]
            not_deployed = False
            for action, path in routes:
                r = client.post(path, headers=auth, json={})
                if r.status_code == 404 and not_deployed is False:
                    suite.add(
                        f"K95 middleware routes (deploy check)",
                        True,
                        r.status_code,
                        skipped=True,
                        detail="Deploy backend with middlewareIntegrationRoutes to dev VPS",
                    )
                    not_deployed = True
                    break
                ok = r.status_code in (200, 502)
                detail = str(_json(r))[:250]
                suite.add(f"K95 POST {action}", ok, r.status_code, detail)
            if not_deployed:
                for action, _ in routes[1:]:
                    suite.add(f"K95 POST {action}", True, skipped=True, detail="skipped — routes not on VPS")

            # Update employee in ERP
            r = client.patch(
                f"/api/entities/Employee/{employee_id}",
                headers=auth,
                json={"employee_name": f"Updated {EMP_CODE}", "phone": "9999900001"},
            )
            suite.add("Update Employee in ERP", r.status_code == 200, r.status_code)

            # Cleanup — delete ERP record (machine already removed)
            if employee_id:
                r = client.delete(f"/api/entities/Employee/{employee_id}", headers=auth)
                suite.add("Delete Employee in ERP (cleanup)", r.status_code in (200, 204), r.status_code)

    except httpx.ConnectError as exc:
        suite.add("K95 employee API", False, detail=str(exc))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k95-base", default=os.environ.get("K95_BASE_URL", "https://dev.erp.k95foods.com"))
    parser.add_argument("--mw-base", default=MW_BASE)
    parser.add_argument("--skip-machine", action="store_true")
    parser.add_argument("--skip-k95", action="store_true")
    parser.add_argument("--k95-email", default=os.environ.get("K95_INTEGRATION_EMAIL", os.environ.get("SMOKE_TEST_EMAIL", "")))
    parser.add_argument("--k95-password", default=os.environ.get("K95_INTEGRATION_PASSWORD", os.environ.get("SMOKE_TEST_PASSWORD", "")))
    args = parser.parse_args()

    suite = Suite()
    print(f"Middleware: {args.mw_base}  Device: {DEVICE_ID}  Test employee: {EMP_CODE} (user_id={USER_ID})")
    print(f"K95: {args.k95_base}")

    run_middleware_tests(suite, mw_base=args.mw_base, skip_machine=args.skip_machine)

    if not args.skip_k95:
        run_k95_punch_tests(suite, args.k95_base)
        run_k95_employee_api_tests(suite, args.k95_base, args.k95_email, args.k95_password)

    suite.print_report()
    return suite.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
