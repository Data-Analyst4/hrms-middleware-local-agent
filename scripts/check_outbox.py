#!/usr/bin/env python3
import sqlite3
from pathlib import Path

db = Path("attendance.db")
if not db.exists():
    print("no attendance.db")
    raise SystemExit(1)
c = sqlite3.connect(db)
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("tables:", tables)
for t in tables:
    if "outbox" in t.lower() or t == "attendance_events":
        try:
            n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"{t}: {n} rows")
            if n:
                cols = [d[0] for d in c.execute(f"PRAGMA table_info({t})").fetchall()]
                print("  cols:", cols[:12])
                row = c.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 3").fetchall()
                for r in row:
                    print("  ", r)
        except Exception as e:
            print(t, e)
