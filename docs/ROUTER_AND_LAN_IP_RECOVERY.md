# Router / ISP IP Change — Reconnect App to Attendance Machine

Use this guide when:

- The factory **router was replaced or reset**
- The **ISP changed the router’s public (WAN) IP**
- The **PC or biometric machine lost connection** after a power cut or network change
- `Test-NetConnection` to the machine on port **5005** fails

**Project folder on factory PC:** `C:\hrms-middleware-local-agent` (or wherever you installed).

---

## Understand two different IPs

| IP type | Example | Changes when ISP renews? | What breaks if wrong? |
|---------|---------|--------------------------|------------------------|
| **Public (WAN)** | `103.x.x.x` on router | Often **yes** | Nothing — Cloudflare tunnel handles ERP access |
| **LAN (private)** | `192.168.1.50` (PC), `192.168.1.100` (machine) | **No** (unless router reset) | SDK + live punch push |

**Rule:** PC LAN IP and machine LAN IP must be **different** but on the **same subnet** (e.g. both `192.168.1.x`, mask `255.255.255.0`).

---

## Quick recovery (factory PC)

Run in order:

| Step | Command | Admin? |
|------|---------|--------|
| 1 | `RECOVER_AFTER_NETWORK_CHANGE.cmd` | No (checks only) |
| 2 | Edit `configs\site.local.yaml` if machine IP changed | No |
| 3 | `4-CONFIGURE_LAN_IP.cmd` | **Yes** — lock PC LAN IP |
| 4 | `3-CONFIGURE_DEVICE.cmd` | **Yes** — firewall + live-push to machine |
| 5 | `RESTART_STACK.cmd` | No |
| 6 | `CHECK_STATUS.cmd` | No |

---

## Step-by-step (full procedure)

### Step 0 — One-click health check

Open PowerShell in the project folder:

```powershell
cd C:\hrms-middleware-local-agent
.\RECOVER_AFTER_NETWORK_CHANGE.cmd
```

Read the output. It shows PC IP, machine IP from config, ping, port 5005, and local/public health.

To auto-fix live-push drift (needs machine reachable on LAN):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\recover_after_network_change.ps1 -FixLivePush
```

---

### Step 1 — Check PC network (after router change)

```powershell
ipconfig
```

Note:

- **IPv4 Address** on Wi‑Fi or Ethernet (e.g. `192.168.1.50`)
- **Default Gateway** (usually `192.168.1.1`)

If the router was reset, the subnet might still be `192.168.1.x` or might become `192.168.0.x`. PC and machine must use the **same** subnet as the gateway.

---

### Step 2 — Pick IPs (no duplicates)

Example for a typical home/factory router at `192.168.1.1`:

| Device | Suggested IP | DHCP |
|--------|--------------|------|
| Router | `192.168.1.1` | — |
| **Middleware PC** | `192.168.1.50` | Static (recommended) |
| **T501 attendance machine** | `192.168.1.100` | Static (**DHCP OFF** on device) |

**Never** set the machine to the same IP as the PC.

If `SourceAddress` and `RemoteAddress` are the same in `Test-NetConnection`, you have an **IP conflict** — change one device IP.

---

### Step 3 — Set static IP on the attendance machine

On the T501 **Network / Communication** menu:

1. **DHCP = OFF**
2. **IP Address** = machine IP (e.g. `192.168.1.100`) — **not** the PC IP
3. **Subnet Mask** = `255.255.255.0`
4. **Gateway** = router IP (e.g. `192.168.1.1`)
5. **Port** = `5005`
6. **STN** = your site number (e.g. `1`)
7. **Password** = `0` if disabled, or your device password
8. **Save** and **reboot** the machine

Close any vendor desktop software connected to the machine (only one SDK client at a time).

---

### Step 4 — Update `configs\site.local.yaml` on the PC

Edit:

`C:\hrms-middleware-local-agent\configs\site.local.yaml`

Update these keys to match the **machine** (not the PC):

```yaml
machine_sync_ip: "192.168.1.100"
machine_sync_port: 5005
machine_sync_password: 0
machine_sync_machine_number: 1
device_lan_ip_for_firewall: "192.168.1.100"

pc_lan_ip: "192.168.1.50"
pc_lan_static_enabled: true
```

| Key | Set to |
|-----|--------|
| `machine_sync_ip` | Biometric device IP only |
| `device_lan_ip_for_firewall` | Same as `machine_sync_ip` |
| `pc_lan_ip` | This middleware PC’s LAN IP |
| `pc_lan_static_enabled` | `true` to lock PC IP during step 5–6 |

**Do not change** Cloudflare or ERP keys unless DevOps gave you new values.

---

### Step 5 — Lock PC LAN IP (Windows static)

Right-click **Run as Administrator**:

```text
4-CONFIGURE_LAN_IP.cmd
```

This sets Windows static IP to `pc_lan_ip` and saves `var\lan_setup\router_dhcp_reservation.txt` (MAC + IP for router admin).

**Optional (router web UI):** Open `http://192.168.1.1` → DHCP Reservation → bind PC MAC to `pc_lan_ip`.

---

### Step 6 — Firewall + point machine punches to this PC

Right-click **Run as Administrator**:

```text
3-CONFIGURE_DEVICE.cmd
```

This:

1. Confirms PC static IP (if enabled)
2. Opens firewall port **8081** for live punch push
3. Configures the device to push attendance to this PC

---

### Step 7 — Restart middleware

```text
RESTART_STACK.cmd
```

Wait ~30 seconds, then:

```text
CHECK_STATUS.cmd
```

---

### Step 8 — Verify LAN connection to machine

```powershell
ping 192.168.1.100
Test-NetConnection -ComputerName 192.168.1.100 -Port 5005
```

**Expected:**

- `PingSucceeded : True`
- `SourceAddress` = PC IP (e.g. `192.168.1.50`)
- `RemoteAddress` = machine IP (e.g. `192.168.1.100`) — **must differ**
- `TcpTestSucceeded : True`

---

### Step 9 — Verify app SDK connection

```powershell
$body = @{
  machine_ip = "192.168.1.100"
  machine_port = 5005
  machine_password = 0
  machine_number = 1
  sdk_dll_path = "C:\hrms-middleware-local-agent\sdk_extracted\20211204-SBXPC-1\bin\SBXPCDLL64.dll"
} | ConvertTo-Json

Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8080/api/machine/test-connection" `
  -ContentType "application/json" -Body $body
```

**Success:** `"connected": true`

Or open `http://127.0.0.1:8080/docs` → **POST /api/machine/test-connection**.

---

### Step 10 — Verify public URL (ISP WAN change)

ISP public IP changes **do not** require config edits if Cloudflare tunnel is running.

```powershell
curl.exe https://1299-mw.k95foods.com/health
```

Replace hostname with your `cloudflare_public_hostname` from `site.local.yaml`.

If this fails but local health works:

```text
REPAIR_CLOUDFLARE.cmd
```

---

### Step 11 — Test live punch

1. Open `http://127.0.0.1:8080/dashboard`
2. Scan finger on the machine
3. A new punch row should appear within seconds

If punches are missing:

```powershell
.\.venv\Scripts\python.exe scripts\ensure_device_live_push.py --config configs\factory.yaml --fix
```

The stack also auto-heals live-push every **15 minutes** when running.

---

## When ISP changes public IP only

| Check | Action |
|-------|--------|
| `http://127.0.0.1:8080/health` | Should work — no change |
| `https://YOUR-SITE-mw.k95foods.com/health` | Should work — tunnel is outbound |
| Machine connection | Unchanged — LAN IPs are independent of ISP WAN |

**No edits** to `site.local.yaml` or machine menu needed for ISP WAN-only changes.

---

## When router is replaced or factory-reset

| Task | Required? |
|------|-----------|
| Re-assign static LAN IPs (PC + machine) | **Yes** |
| Update `machine_sync_ip` in yaml | **Yes** if machine IP changed |
| Run `4-CONFIGURE_LAN_IP.cmd` + `3-CONFIGURE_DEVICE.cmd` | **Yes** |
| Re-run Cloudflare login | **No** (unless PC was reimaged) |
| Update ERP VPS keys | **No** |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Ping OK, port 5005 fails, same Source/Remote IP | IP conflict | Different IPs for PC vs machine |
| Ping fails | Wrong subnet, cable, Wi‑Fi | Fix LAN; same router network |
| `connected: false` in test-connection | Wrong STN/password; vendor app open | Fix device menu; close vendor software |
| Punches on dashboard, not ERP | ERP/outbox issue | `CHECK_STATUS.cmd`; check `outbound_*` keys |
| ERP cannot sync employees | Tunnel down | `REPAIR_CLOUDFLARE.cmd`; local `/health` |
| Live push drift after PC IP change | Device still pushes to old IP | `3-CONFIGURE_DEVICE.cmd` or `ensure_device_live_push.py --fix` |

---

## Checklist (printable)

```
[ ] ipconfig — note PC IP and gateway
[ ] Machine static IP set (DHCP OFF), different from PC
[ ] site.local.yaml — machine_sync_ip + pc_lan_ip updated
[ ] 4-CONFIGURE_LAN_IP.cmd (Admin)
[ ] 3-CONFIGURE_DEVICE.cmd (Admin)
[ ] RESTART_STACK.cmd
[ ] Test-NetConnection machine:5005 → TcpTestSucceeded True
[ ] POST /api/machine/test-connection → connected true
[ ] https://SITE-mw.k95foods.com/health OK
[ ] Test finger punch on dashboard
```

---

## Related docs

- [SITE_PC_SETUP.md](SITE_PC_SETUP.md) — first-time install
- [PRODUCTION_RESILIENCE.md](PRODUCTION_RESILIENCE.md) — auto-heal and failure modes
- [MACHINE_SETUP_AND_TESTING_GUIDE.md](MACHINE_SETUP_AND_TESTING_GUIDE.md) — full API tests
