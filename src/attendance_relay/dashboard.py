from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any


def render_dashboard_html(
    *,
    rows: list[dict[str, Any]],
    total: int,
    employee_code_filter: str | None,
    device_sn_filter: str | None,
    limit: int,
    refreshed_at: str,
) -> str:
    table_rows = _build_rows(rows)
    employee_val = escape(employee_code_filter or "")
    device_val = escape(device_sn_filter or "")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Attendance Dashboard</title>
  <meta http-equiv="refresh" content="20">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
    :root {{
      --bg: #f2f4ef;
      --ink: #10231b;
      --ink-soft: #476457;
      --accent: #0b7a56;
      --accent-2: #d65a00;
      --card: #ffffff;
      --line: #d5ddd7;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Sora", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 18%, #d9f5e9 0%, transparent 28%),
        radial-gradient(circle at 88% 5%, #ffe8cf 0%, transparent 22%),
        var(--bg);
      min-height: 100vh;
    }}
    .wrap {{
      width: min(1200px, 96vw);
      margin: 24px auto 40px;
    }}
    .header {{
      display: flex;
      gap: 14px;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: end;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(1.4rem, 2.2vw, 2rem);
      letter-spacing: 0.4px;
    }}
    .meta {{
      color: var(--ink-soft);
      font-size: 0.92rem;
    }}
    .stats {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }}
    .chip {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 0.9rem;
    }}
    .chip strong {{
      color: var(--accent);
      margin-left: 4px;
    }}
    .panel {{
      margin-top: 14px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 14px 35px rgba(16, 35, 27, 0.06);
    }}
    form {{
      padding: 14px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, #f8fbf9 0%, #ffffff 100%);
    }}
    label {{
      display: block;
      font-size: 0.78rem;
      color: var(--ink-soft);
      margin-bottom: 6px;
    }}
    input {{
      width: 100%;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 10px;
      outline: none;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.85rem;
    }}
    .btns {{
      display: flex;
      gap: 8px;
      align-items: end;
    }}
    button, .link-btn {{
      border: none;
      border-radius: 10px;
      padding: 9px 12px;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      display: inline-block;
      font-size: 0.85rem;
    }}
    button {{
      background: var(--accent);
      color: #fff;
    }}
    .link-btn {{
      background: #ffece0;
      color: var(--accent-2);
    }}
    .table-wrap {{
      overflow: auto;
      max-height: 66vh;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.86rem;
    }}
    th, td {{
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      white-space: nowrap;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #f2f8f4;
      z-index: 1;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.4px;
      color: var(--ink-soft);
    }}
    tr:nth-child(even) td {{
      background: #fbfdfb;
    }}
    .mono {{
      font-family: "IBM Plex Mono", monospace;
    }}
    @media (max-width: 900px) {{
      form {{ grid-template-columns: 1fr 1fr; }}
    }}
    @media (max-width: 620px) {{
      form {{ grid-template-columns: 1fr; }}
      .btns {{ align-items: stretch; }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="header">
      <div>
        <h1>Attendance Dashboard</h1>
        <div class="meta">Auto-refresh every 20 seconds • Last refresh {escape(refreshed_at)}</div>
      </div>
    </section>
    <section class="stats">
      <div class="chip">Total Punches<strong>{total}</strong></div>
      <div class="chip">Rows Loaded<strong>{len(rows)}</strong></div>
      <div class="chip">Limit<strong>{limit}</strong></div>
    </section>
    <section class="panel">
      <form method="get" action="/dashboard">
        <div>
          <label for="employee_code">Employee Code</label>
          <input id="employee_code" name="employee_code" value="{employee_val}" placeholder="E1023">
        </div>
        <div>
          <label for="device_sn">Device Serial</label>
          <input id="device_sn" name="device_sn" value="{device_val}" placeholder="SN-01">
        </div>
        <div>
          <label for="limit">Limit</label>
          <input id="limit" name="limit" value="{limit}" placeholder="200">
        </div>
        <div class="btns">
          <button type="submit">Apply Filter</button>
          <a class="link-btn" href="/dashboard">Reset</a>
        </div>
      </form>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Employee</th>
              <th>Name</th>
              <th>Log DateTime</th>
              <th>Log Time</th>
              <th>Downloaded At</th>
              <th>Device SN</th>
              <th>Source IP</th>
              <th>Created At</th>
            </tr>
          </thead>
          <tbody>
            {table_rows}
          </tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""


def _build_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            '<tr><td colspan="9" style="text-align:center; color:#476457;">'
            "No attendance records found for the selected filters."
            "</td></tr>"
        )

    html_rows: list[str] = []
    for row in rows:
        html_rows.append(
            "<tr>"
            f"<td class='mono'>{escape(_as_text(row.get('id')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('employee_code')))}</td>"
            f"<td>{escape(_as_text(row.get('employee_name')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('log_datetime')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('log_time')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('downloaded_at')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('device_sn')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('source_ip')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('created_at')))}</td>"
            "</tr>"
        )
    return "".join(html_rows)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)
