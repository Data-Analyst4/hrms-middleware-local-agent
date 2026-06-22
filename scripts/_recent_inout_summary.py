#!/usr/bin/env python3
"""Summarize recent IN/OUT punches from attendance.db."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime

IO = {0: "IN", 1: "OUT", "0": "IN", "1": "OUT"}
VERIFY = {0: "Multi", 1: "Fingerprint", 2: "Card", 3: "Pwd+Card", 7: "Face"}


def parse_json(raw: str | None) -> dict:
    if not raw or "{" not in raw:
        return {}
    snippet = raw[raw.find("{") : raw.rfind("}") + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return {}


def io_label(raw: dict) -> str:
    value = raw.get("io_mode")
    if value is None:
        return "?"
    return IO.get(value, IO.get(str(value), "?"))


def verify_label(raw: dict) -> str:
    value = raw.get("verify_mode")
    if value is None:
        return "?"
    return VERIFY.get(value, VERIFY.get(str(value), str(value)))


def source_label(row: sqlite3.Row, raw: dict) -> str:
    if raw.get("source") == "sdk_pull":
        return "sdk_pull"
    ip = row["source_ip"] or ""
    if ip.startswith("192.168.29.44"):
        return "live_device"
    if ip and ip not in ("127.0.0.1", "::1"):
        return f"live({ip})"
    return "test/other"


def main() -> None:
    conn = sqlite3.connect("attendance.db")
    conn.row_factory = sqlite3.Row
    today = datetime.now().strftime("%Y-%m-%d")

    rows = conn.execute(
        """
        SELECT g.*, em.employee_name
        FROM tbl_realtime_glog g
        LEFT JOIN employee_master em
          ON em.employee_code = g.employee_code
          OR em.employee_code = CAST(CAST(g.employee_code AS INTEGER) AS TEXT)
        WHERE g.id >= 52
        ORDER BY g.log_datetime ASC, g.id ASC
        """,
    ).fetchall()

    live_io_rows = []
    for row in rows:
        raw = parse_json(row["raw_preview"])
        if "io_mode" not in raw or raw.get("source") == "sdk_pull":
            continue
        live_io_rows.append((row, raw))

    print(f"TEST SESSION: punches from id 52 onward (since ~00:09)")
    print(f"Rows in session: {len(rows)}")
    print(f"Live FkWEb rows with io_mode: {len(live_io_rows)}")
    print()

    by_io: dict[str, int] = defaultdict(int)
    by_emp: dict[str, list[tuple]] = defaultdict(list)
    seen_ids: set[int] = set()
    for row, raw in live_io_rows:
        if row["id"] in seen_ids:
            continue
        seen_ids.add(row["id"])
        label = io_label(raw)
        by_io[label] += 1
        code = str(row["employee_code"]).lstrip("0") or str(row["employee_code"])
        name = row["employee_name"] or code
        by_emp[f"{code} ({name})"].append(
            (row["log_datetime"], label, verify_label(raw), row["id"])
        )

    print("IN/OUT counts (live only):")
    for key in ("IN", "OUT", "?"):
        if by_io[key]:
            print(f"  {key}: {by_io[key]}")
    print()

    print("Per employee (live IN/OUT sequence):")
    for emp, events in sorted(by_emp.items()):
        print(f"  {emp} — {len(events)} punch(es)")
        for dt, io, verify, pid in events[-10:]:
            print(f"    {dt}  {io:>3}  {verify}  id={pid}")
    print()

    print("All session punches (chronological):")
    printed: set[int] = set()
    for row, raw in live_io_rows:
        if row["id"] in printed:
            continue
        printed.add(row["id"])
        code = str(row["employee_code"]).lstrip("0") or str(row["employee_code"])
        name = (row["employee_name"] or "-")[:18]
        print(
            f"  id={row['id']:>3}  {row['log_datetime']}  "
            f"emp={code:>6}  {name:18}  {io_label(raw):>3}  {verify_label(raw):>11}  "
            f"io_mode={raw.get('io_mode')}  verify_mode={raw.get('verify_mode')}"
        )

    conn.close()


if __name__ == "__main__":
    main()
