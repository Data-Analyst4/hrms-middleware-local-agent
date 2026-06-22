from __future__ import annotations

from html import escape
from typing import Any


def render_settings_html(*, default_api_key: str, gateway_port: int) -> str:
    api_key = escape(default_api_key)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Middleware Device Settings</title>
  <style>
    body {{ font-family: Segoe UI, sans-serif; margin: 24px; background: #f4f6f8; color: #1a1a1a; }}
    .wrap {{ max-width: 960px; margin: 0 auto; }}
    h1 {{ margin-bottom: 4px; }}
    .sub {{ color: #555; margin-bottom: 20px; }}
    .card {{ background: #fff; border: 1px solid #d9dee3; border-radius: 10px; padding: 16px; margin-bottom: 16px; }}
    label {{ display: block; font-size: 12px; color: #444; margin-top: 8px; }}
    input, select {{ width: 100%; padding: 8px; margin-top: 4px; box-sizing: border-box; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    button {{ margin-top: 12px; padding: 10px 14px; border: 0; border-radius: 8px; cursor: pointer; }}
    .primary {{ background: #0b6b4a; color: #fff; }}
    .secondary {{ background: #e8edf2; color: #1a1a1a; margin-left: 8px; }}
    pre {{ background: #0f1720; color: #d7ffe8; padding: 12px; border-radius: 8px; overflow: auto; max-height: 280px; }}
    .nav a {{ margin-right: 12px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid #e5e9ee; padding: 8px; text-align: left; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="nav"><a href="/dashboard">Attendance</a><a href="/settings"><strong>Devices</strong></a></div>
    <h1>Device & Site Settings</h1>
    <p class="sub">Configure biometric device IP, device_id, and site_id. Changes apply immediately for HRMS API calls.</p>

    <div class="card">
      <label>Middleware API Key</label>
      <input id="apiKey" type="password" value="{api_key}" />
      <div class="grid">
        <div>
          <label>Device ID</label>
          <input id="deviceId" placeholder="SITE-A-T501" />
        </div>
        <div>
          <label>Site ID</label>
          <input id="siteId" placeholder="HQ" />
        </div>
        <div>
          <label>Device Name</label>
          <input id="deviceName" placeholder="Gate T501" />
        </div>
        <div>
          <label>Machine IP</label>
          <input id="deviceIp" placeholder="192.168.29.44" />
        </div>
        <div>
          <label>Port</label>
          <input id="devicePort" type="number" value="5005" />
        </div>
        <div>
          <label>Machine Password</label>
          <input id="machinePassword" value="0" />
        </div>
        <div>
          <label>Machine Number (STN)</label>
          <input id="machineNumber" type="number" value="1" />
        </div>
        <div>
          <label>Cloudflare/Tunnel Public URL (optional)</label>
          <input id="publicUrl" placeholder="https://site-a.example.com" />
        </div>
      </div>
      <button class="primary" onclick="saveDevice()">Save Device</button>
      <button class="secondary" onclick="testConnection()">Test Connection</button>
      <button class="secondary" onclick="detectDevice()">Detect & Auto-STN</button>
      <button class="secondary" onclick="loadDevices()">Refresh List</button>
    </div>

    <div class="card">
      <h3>Registered Devices</h3>
      <table id="deviceTable">
        <thead><tr><th>ID</th><th>Site</th><th>IP</th><th>STN</th><th>Active</th><th>Last Sync</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>

    <div class="card">
      <h3>Output</h3>
      <pre id="output">Ready.</pre>
    </div>
  </div>
  <script>
    const base = window.location.origin;

    function headers() {{
      return {{
        "Content-Type": "application/json",
        "x-api-key": document.getElementById("apiKey").value
      }};
    }}

    function log(obj) {{
      document.getElementById("output").textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
    }}

    async function loadDevices() {{
      const res = await fetch(base + "/api/v1/devices", {{ headers: headers() }});
      const body = await res.json();
      if (!res.ok) return log(body);
      const tbody = document.querySelector("#deviceTable tbody");
      tbody.innerHTML = "";
      for (const row of (body.rows || [])) {{
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${{row.device_id}}</td><td>${{row.site_id || ""}}</td><td>${{row.ip}}:${{row.port}}</td><td>${{row.machine_number || ""}}</td><td>${{row.is_active}}</td><td>${{row.last_sync_at || ""}}</td>`;
        tr.onclick = () => fillForm(row);
        tbody.appendChild(tr);
      }}
      log({{ loaded: (body.rows || []).length }});
    }}

    function fillForm(row) {{
      document.getElementById("deviceId").value = row.device_id || "";
      document.getElementById("siteId").value = row.site_id || "";
      document.getElementById("deviceName").value = row.device_name || "";
      document.getElementById("deviceIp").value = row.ip || "";
      document.getElementById("devicePort").value = row.port || 5005;
      document.getElementById("machinePassword").value = row.machine_password || "0";
      document.getElementById("machineNumber").value = row.machine_number || 1;
      document.getElementById("publicUrl").value = row.middleware_public_url || "";
    }}

    async function saveDevice() {{
      const payload = {{
        device_id: document.getElementById("deviceId").value.trim(),
        site_id: document.getElementById("siteId").value.trim(),
        device_name: document.getElementById("deviceName").value.trim(),
        ip: document.getElementById("deviceIp").value.trim(),
        port: Number(document.getElementById("devicePort").value || 5005),
        machine_password: document.getElementById("machinePassword").value.trim(),
        machine_number: Number(document.getElementById("machineNumber").value || 1),
        middleware_public_url: document.getElementById("publicUrl").value.trim(),
        is_active: true,
        sdk_protocol: "sbxpc_tcp"
      }};
      const res = await fetch(base + "/api/v1/devices", {{ method: "POST", headers: headers(), body: JSON.stringify(payload) }});
      log(await res.json());
      await loadDevices();
    }}

    async function testConnection() {{
      const id = document.getElementById("deviceId").value.trim();
      if (!id) return log("Set device_id first.");
      const res = await fetch(base + "/api/v1/devices/" + encodeURIComponent(id) + "/live/test-connection", {{ method: "POST", headers: headers() }});
      log(await res.json());
    }}

    async function detectDevice() {{
      const id = document.getElementById("deviceId").value.trim();
      if (!id) return log("Set device_id first.");
      const res = await fetch(base + "/api/v1/devices/" + encodeURIComponent(id) + "/live/detect", {{ method: "POST", headers: headers() }});
      const body = await res.json();
      log(body);
      if (body.recommended_machine_number) {{
        document.getElementById("machineNumber").value = body.recommended_machine_number;
      }}
      await loadDevices();
    }}

    loadDevices();
  </script>
</body>
</html>"""
