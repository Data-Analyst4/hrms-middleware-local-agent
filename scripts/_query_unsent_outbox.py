#!/usr/bin/env python3
"""List machine punches received locally but not yet sent to ERP."""
import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parents[1] / "attendance.db"
if not db.exists():
    print(f"no database: {db}")
    raise SystemExit(1)

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

print("=== OUTBOX STATUS COUNTS ===")
for row in conn.execute(
    "SELECT status, COUNT(*) AS n FROM attendance_outbox GROUP BY status ORDER BY status"
):
    print(f"  {row['status']}: {row['n']}")

unsent = conn.execute(
    """
    SELECT id, employee_code, log_datetime, log_time, device_sn, status,
           attempt_count, max_retries, last_error, next_attempt_at, created_at, updated_at
    FROM attendance_outbox
    WHERE status IN ('PENDING', 'PROCESSING', 'FAILED')
    ORDER BY id DESC
    """
).fetchall()

print()
if not unsent:
    print("No unsent records — all machine logs have been relayed to ERP (or none pending).")
else:
    print(f"=== NOT SENT TO ERP ({len(unsent)} records) ===")
    for r in unsent:
        print(
            f"id={r['id']} emp={r['employee_code']} "
            f"time={r['log_datetime']} {r['log_time']} device={r['device_sn']} "
            f"status={r['status']} attempts={r['attempt_count']}/{r['max_retries']} "
            f"error={r['last_error'] or '-'} created={r['created_at']}"
        )

# Recent SENT for context
recent_sent = conn.execute(
    """
    SELECT id, employee_code, log_datetime, log_time, device_sn, sent_at
    FROM attendance_outbox
    WHERE status = 'SENT'
    ORDER BY id DESC
    LIMIT 5
    """
).fetchall()
if recent_sent:
    print()
    print("=== LAST 5 SENT (for reference) ===")
    for r in recent_sent:
        print(
            f"id={r['id']} emp={r['employee_code']} "
            f"time={r['log_datetime']} {r['log_time']} sent_at={r['sent_at']}"
        )
