#!/usr/bin/env python3
"""Enqueue recent tbl_realtime_glog punches into attendance_outbox for outbound worker."""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "attendance.db"


def event_hash(employee_code: str, log_datetime: str, log_time: str, device_sn: str) -> str:
    canonical = "|".join([employee_code.strip(), log_datetime.strip(), log_time.strip(), device_sn.strip()])
    return hashlib.sha256(canonical.encode()).hexdigest()


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    if not DB.exists():
        print("attendance.db not found")
        return 1
    c = sqlite3.connect(DB)
    rows = c.execute(
        """
        SELECT employee_code, log_datetime, log_time, downloaded_at, device_sn
        FROM tbl_realtime_glog
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    added = 0
    skipped = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for emp, log_dt, log_time, downloaded_at, device_sn in rows:
        eh = event_hash(emp, log_dt, log_time, device_sn)
        exists = c.execute("SELECT 1 FROM attendance_outbox WHERE event_hash = ?", (eh,)).fetchone()
        if exists:
            skipped += 1
            continue
        try:
            c.execute(
                """
                INSERT INTO attendance_outbox (
                  event_hash, employee_code, log_datetime, log_time, downloaded_at, device_sn,
                  status, attempt_count, max_retries, next_attempt_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', 0, 5, ?, ?, ?)
                """,
                (eh, emp, log_dt, log_time, downloaded_at, device_sn, now, now, now),
            )
            added += 1
        except sqlite3.IntegrityError:
            skipped += 1
    c.commit()
    print(f"backfill: added={added} skipped={skipped} (from last {len(rows)} glog rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
