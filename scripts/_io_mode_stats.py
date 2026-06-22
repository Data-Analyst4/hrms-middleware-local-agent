#!/usr/bin/env python3
import json
import sqlite3
from collections import Counter

conn = sqlite3.connect("attendance.db")
rows = conn.execute(
    "SELECT id, log_datetime, raw_preview FROM tbl_realtime_glog WHERE raw_preview LIKE '%io_mode%' ORDER BY id"
).fetchall()

io_vals: Counter[int | str] = Counter()
verify_vals: Counter[int | str] = Counter()
for row_id, dt, raw in rows:
    snippet = raw[raw.find("{") : raw.rfind("}") + 1]
    try:
        payload = json.loads(snippet)
    except json.JSONDecodeError:
        continue
    io_vals[payload.get("io_mode", "?")] += 1
    verify_vals[payload.get("verify_mode", "?")] += 1

print(f"Rows with io_mode in raw_preview: {len(rows)}")
print("io_mode distribution:", dict(sorted(io_vals.items(), key=lambda x: str(x[0]))))
print("verify_mode distribution:", dict(sorted(verify_vals.items(), key=lambda x: str(x[0]))))
print()
print("Last 10:")
for row_id, dt, raw in rows[-10:]:
    payload = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    print(
        f"  id={row_id}  {dt}  io_mode={payload.get('io_mode')}  verify_mode={payload.get('verify_mode')}"
    )
