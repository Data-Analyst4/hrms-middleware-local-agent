#!/usr/bin/env python3
"""Capture full K95 punch webhook investigation report for ERP team."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from attendance_relay.outbound_client import _build_hmac_signature
from attendance_relay.settings import load_settings

settings = load_settings("configs/dev.yaml")
URL = settings.outbound_url


def post_case(name: str, payload: dict, headers_extra: dict | None = None, skip_hmac: bool = False) -> dict:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    enroll = str(payload.get("enroll_no") or payload.get("employee_code"))
    io_time = str(payload.get("io_time") or "")
    if not io_time and payload.get("log_datetime"):
        io_time = str(payload["log_datetime"]).replace("-", "").replace(":", "").replace(" ", "")[:14]
    headers = {
        "Content-Type": "application/json",
        settings.outbound_api_key_header: settings.outbound_api_key,
        "X-Site-Code": settings.outbound_site_code,
        "X-Device-Id": settings.outbound_device_id,
        "X-Idempotency-Key": f"{payload.get('device_sn', 'SN')}:{enroll}:{io_time}",
    }
    if not skip_hmac:
        headers["X-Middleware-Signature"] = _build_hmac_signature(settings.outbound_hmac_secret, body)
    if headers_extra:
        headers.update(headers_extra)
    try:
        r = httpx.post(URL, content=body, headers=headers, timeout=30.0, verify=settings.outbound_verify_tls)
        return {
            "case": name,
            "http_status": r.status_code,
            "response": r.text[:800],
            "request_headers": {k: ("***" if "key" in k.lower() or "signature" in k.lower() else v) for k, v in headers.items()},
            "request_body": json.loads(body.decode()),
        }
    except Exception as exc:
        return {"case": name, "error": f"{type(exc).__name__}: {exc}"}


def outbox_summary() -> dict:
    c = sqlite3.connect("attendance.db")
    counts = dict(c.execute("SELECT status, COUNT(*) FROM attendance_outbox GROUP BY status").fetchall())
    last_sent = c.execute(
        "SELECT id, employee_code, log_datetime, sent_at FROM attendance_outbox WHERE status='SENT' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    first_fail = c.execute(
        "SELECT id, employee_code, log_datetime, created_at FROM attendance_outbox WHERE status='FAILED' ORDER BY id ASC LIMIT 1"
    ).fetchone()
    last_fail = c.execute(
        "SELECT id, employee_code, log_datetime, last_error, created_at FROM attendance_outbox WHERE status='FAILED' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "outbox_counts": counts,
        "last_successful_punch": last_sent,
        "first_failed_punch_after_success": first_fail,
        "latest_failed_punch": last_fail,
    }


def main() -> int:
    io_time = datetime.now().strftime("%Y%m%d%H%M%S")
    payload = {
        "employee_code_raw": "88001",
        "enroll_no": "88001",
        "employee_code": "88001",
        "log_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "log_time": datetime.now().strftime("%H:%M:%S"),
        "downloaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "device_sn": "2",
        "branch_code": settings.outbound_site_code,
        "device_id": settings.outbound_device_id,
        "io_time": io_time,
        "raw_payload": {"user_id": "88001", "io_time": io_time},
        "employee_name": "Test User",
    }

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": (
            "K95 ERP returns HTTP 500 with JavaScript error 'code is not defined' on valid signed punch requests. "
            "Auth and site validation work (401/404). Issue is inside middlewarePunchRoutes handler after validation."
        ),
        "endpoint": URL,
        "middleware_config": {
            "site_code": settings.outbound_site_code,
            "device_id": settings.outbound_device_id,
            "api_key_header": settings.outbound_api_key_header,
            "hmac_header": "X-Middleware-Signature",
            "idempotency_header": "X-Idempotency-Key",
        },
        "local_outbox": outbox_summary(),
        "live_tests": [
            post_case("health_check_get_api_health", {}, headers_extra={}, skip_hmac=True),
            post_case("no_hmac_signature", payload, skip_hmac=True),
            post_case("bad_hmac_signature", payload, headers_extra={"X-Middleware-Signature": "sha256=deadbeef"}),
            post_case("unknown_site_code", payload, headers_extra={"X-Site-Code": "UNKNOWN_SITE_XYZ"}),
            post_case("valid_signed_punch_88001", payload),
            post_case(
                "valid_signed_punch_167",
                {
                    **payload,
                    "employee_code_raw": "167",
                    "enroll_no": "167",
                    "employee_code": "167",
                    "raw_payload": {"user_id": "167", "io_time": io_time},
                },
            ),
        ],
        "erp_team_checklist": [
            "Search backend logs for POST /api/integrations/middleware/punch around first failure time in local_outbox",
            "Find middlewarePunchRoutes (or equivalent) and locate ReferenceError: code is not defined",
            "Check recent deploys to dev.erp.k95foods.com between last SENT and first FAILED punch timestamps",
            "Verify handler uses correct variable names after employee/site lookup (e.g. branch_code vs code)",
            "Confirm V8 site exists in ERP branch/site table and employee enroll_no maps to HR employee record",
            "After fix: re-run python scripts/run_v8_integration_tests.py --skip-machine",
        ],
    }

    # fix health check - use GET on base URL
    try:
        base = URL.rsplit("/api/", 1)[0]
        r = httpx.get(f"{base}/api/health", timeout=15.0)
        report["live_tests"][0] = {
            "case": "GET /api/health",
            "http_status": r.status_code,
            "response": r.text[:300],
        }
    except Exception as exc:
        report["live_tests"][0] = {"case": "GET /api/health", "error": str(exc)}

    out = ROOT / "var" / "logs" / "k95_erp_investigation_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
