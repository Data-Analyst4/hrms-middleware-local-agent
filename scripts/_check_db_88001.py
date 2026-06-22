#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect("attendance.db")
conn.row_factory = sqlite3.Row

print("=== employee_master (88001 / 167) ===")
for row in conn.execute(
    """
    SELECT employee_code, employee_name, card_no
    FROM employee_master
    WHERE employee_code IN ('88001', '167', '00000167')
       OR employee_code_normalized IN ('88001', '167')
    ORDER BY employee_code
    """
):
    print(dict(row))

print("\n=== employee_master total ===")
print(conn.execute("SELECT COUNT(*) AS n FROM employee_master").fetchone()["n"])

print("\n=== machine_user_registry (88001) ===")
try:
    rows = conn.execute(
        """
        SELECT user_id, employee_code, user_name, machine_ip, device_id, enabled
        FROM machine_user_registry
        WHERE user_id = 88001 OR employee_code = '88001'
        LIMIT 5
        """
    ).fetchall()
    print(len(rows), "rows")
    for row in rows:
        print(dict(row))
except sqlite3.OperationalError as exc:
    print("table query error:", exc)

print("\n=== punches for 88001 ===")
for row in conn.execute(
    """
    SELECT id, employee_code, log_datetime, device_sn
    FROM tbl_realtime_glog
    WHERE employee_code LIKE '%88001%'
    ORDER BY id DESC
    LIMIT 5
    """
):
    print(dict(row))

conn.close()
