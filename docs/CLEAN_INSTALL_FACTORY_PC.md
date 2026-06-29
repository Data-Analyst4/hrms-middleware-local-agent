# Clean Install on Any Factory PC (V8, V9, 1299, …)

Use this guide when installing the HR middleware on a **new** factory PC or **reinstalling** on an existing PC.

**Repo:** https://github.com/Data-Analyst4/hrms-middleware-local-agent  
**Branch:** `main` only

---

## V8 example (one PC = one site)

| Item | V8 value |
|------|----------|
| Site code | `V8` |
| Device ID | `V8-T501-01` (auto) |
| Tunnel hostname | `v8-mw.k95foods.com` |
| Tunnel name | `v8-middleware` |
| Machine IP (example) | `192.168.29.44` — **use your real LAN IP** |
| Machine port | `5005` |
| Machine STN | `1` or `2` (read from device menu) |

Each site gets **unique** `middleware_api_key` and `outbound_hmac_secret`. Never copy keys from site 1299 onto V8.

---

## Mistakes we hit before (read first)

| # | Mistake | How to avoid |
|---|---------|--------------|
| 1 | File named `site.local.yml` | Must be **`site.local.yaml`** (with `a`) |
| 2 | Expecting config from GitHub | `site.local.yaml` is **gitignored** — run `1-CONFIGURE_SITE.cmd` or `DEPLOY_NEW_SITE.cmd` |
| 3 | Old `deploy_new_site.ps1` parser crash | `git pull origin main` before install (fix in commit `a03e2bb+`) |
| 4 | Windows Store fake `python` | Settings → App execution aliases → **OFF** `python.exe` / `python3.exe` |
| 5 | Python installed but script fails | **Close cmd**, open **new Administrator cmd**, then install |
| 6 | `.venv` access denied | Run `scripts\stop_stack.ps1` first; close other Python windows |
| 7 | Empty `outbound_api_key: ""` in yaml | Leave key out or set real ERP punch API key — empty string can crash gateway |
| 8 | Port 8080 already in use | Only one gateway: run `stop_stack.ps1`, use supervisor only (no manual `run_gateway.py`) |
| 9 | Ran `cloudflared tunnel create` many times | **Once per site** — duplicates break config; delete extras in Cloudflare dashboard |
| 10 | `REPAIR_CLOUDFLARE` used wrong site | Scripts read `site.local.yaml` — set `cloudflare_tunnel_name` / hostname for **this** site |
| 11 | PC IP = machine IP (e.g. both `.66`) | **Different IPs** on same subnet — see [ROUTER_AND_LAN_IP_RECOVERY.md](ROUTER_AND_LAN_IP_RECOVERY.md) |
| 12 | Copied 1299 `site.local.yaml` onto V8 PC | Each site needs its **own** site code, keys, tunnel hostname |
| 13 | Wrong git branch | Use **`main`**, not `codex/hrms-docs-and-xml-updates` |
| 14 | Vendor app open on machine | Close desktop biometric software — only one SDK client at a time |
| 15 | Skipped `3-CONFIGURE_DEVICE.cmd` | Required for firewall :8081 + live punch push to PC |

---

## Before you start — collect these

| Item | Where to get it |
|------|-----------------|
| Site code | ERP branch: `V8`, `V9`, `1299`, … |
| Machine LAN IP | T501 network menu (DHCP **OFF**, static IP) |
| Machine STN | Device communication menu |
| Machine password | `0` if disabled |
| PC will sit on same LAN | Same subnet as machine (e.g. `192.168.29.x`) |
| K95 `outbound_api_key` | Ask DevOps (global ERP punch API key) |

**IP plan (example for `192.168.29.x` network):**

| Device | Suggested IP |
|--------|----------------|
| Router | `192.168.29.1` |
| Middleware PC | `192.168.29.124` |
| T501 machine | `192.168.29.44` |

PC IP and machine IP **must differ**.

---

## Path A — Brand-new factory PC (recommended)

### Step 0 — One-time Windows prep

1. **Administrator** account available for install CMDs.
2. **Disable** Windows Store Python aliases (see mistake #4 above).
3. Install **Git** (optional but best for updates): https://git-scm.com/download/win

### Step 1 — Get the code

```powershell
cd C:\
git clone -b main https://github.com/Data-Analyst4/hrms-middleware-local-agent.git
cd hrms-middleware-local-agent
```

Or extract GitHub ZIP from branch **`main`**.

Verify SDK exists:

```powershell
dir sdk_extracted\20211204-SBXPC-1\bin\SBXPCDLL64.dll
```

### Step 2 — Configure site (creates keys + yaml)

Double-click:

```text
1-CONFIGURE_SITE.cmd
```

When prompted for **V8**:

| Prompt | Enter |
|--------|--------|
| ERP branch / site code | `V8` |
| PC label | `V8 Factory Gate PC` |
| Biometric machine LAN IP | e.g. `192.168.29.44` |
| Machine STN | e.g. `1` |
| K95 ERP base URL | `https://dev.erp.k95foods.com` |

This creates **`configs\site.local.yaml`** and **`configs\k95-vps-snippet.env`**.

**Verify filename:** `configs\site.local.yaml` — not `.yml`.

**Verify V8 auto-fields:**

```yaml
outbound_site_code: "V8"
outbound_device_id: "V8-T501-01"
cloudflare_public_hostname: "v8-mw.k95foods.com"
cloudflare_tunnel_name: "v8-middleware"
```

If `outbound_api_key` is empty, ask DevOps and add the real key before starting the stack.

### Step 3 — Send keys to DevOps (VPS)

Email/chat **`configs\k95-vps-snippet.env`** to DevOps.

They add to K95 VPS `.env` (example):

```env
V8_MIDDLEWARE_API_KEY=<same as middleware_api_key on V8 PC>
V8_WEBHOOK_SECRET=<same as outbound_hmac_secret on V8 PC>
V8_TUNNEL_URL=https://v8-mw.k95foods.com
V8_DEVICE_ID=V8-T501-01
```

Then restart K95 backend on VPS.

### Step 4 — Install middleware (Administrator)

Right-click → **Run as administrator**:

```text
2-INSTALL_FACTORY.cmd
```

Or all-in-one (configure + install in one go):

```text
DEPLOY_NEW_SITE.cmd
```

If Python/venv fails: close window → new Admin cmd → `git pull` → delete broken `.venv` if needed → retry.

### Step 5 — Cloudflare tunnel (one-time per V8 PC)

If tunnel not set up during install:

```powershell
cloudflared tunnel login
```

Select **k95foods.com** in browser.

Then:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_cloudflare_tunnel.ps1 `
  -TunnelName "v8-middleware" `
  -PublicHostname "v8-mw.k95foods.com" `
  -LocalPort 8080
```

```text
SETUP_FACTORY_AUTOSTART.cmd
```

**Run tunnel create only once.** If you ran it multiple times, open Cloudflare Zero Trust → delete duplicate `v8-middleware` tunnels; keep one UUID in `%USERPROFILE%\.cloudflared\config-v8-middleware.yml`.

### Step 6 — LAN + machine connection (Administrator)

Right-click → **Run as administrator**:

```text
3-CONFIGURE_DEVICE.cmd
```

This:

1. Locks PC LAN IP (`pc_lan_ip` in yaml)
2. Opens firewall port **8081**
3. Points device live-push at this PC

### Step 7 — Network check (machine)

```powershell
ping 192.168.29.44
Test-NetConnection -ComputerName 192.168.29.44 -Port 5005
```

Expected: `TcpTestSucceeded : True`, **SourceAddress ≠ RemoteAddress**.

### Step 8 — Restart and verify

```text
RESTART_STACK.cmd
CHECK_STATUS.cmd
```

```powershell
curl.exe http://127.0.0.1:8080/health
curl.exe https://v8-mw.k95foods.com/health
```

SDK test:

```powershell
$body = @{
  machine_ip = "192.168.29.44"
  machine_port = 5005
  machine_password = 0
  machine_number = 1
  sdk_dll_path = "C:\hrms-middleware-local-agent\sdk_extracted\20211204-SBXPC-1\bin\SBXPCDLL64.dll"
} | ConvertTo-Json

Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8080/api/machine/test-connection" `
  -ContentType "application/json" -Body $body
```

Expected: `"connected": true`

Punch test:

```powershell
.\.venv\Scripts\python.exe scripts\_probe_erp_punch.py
```

Finger scan → check `http://127.0.0.1:8080/dashboard`

---

## Path B — PC already had middleware (reinstall / fix V8)

Use when the folder exists but site was wrong, install broke, or you migrated V8 → 1299 and now need **V8 again on this PC**.

### Step 1 — Pull latest code

```powershell
cd C:\hrms-middleware-local-agent
git pull origin main
```

### Step 2 — Stop everything

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_stack.ps1
```

### Step 3 — Reconfigure for V8

```text
1-CONFIGURE_SITE.cmd
```

Enter site code **`V8`**, machine IP, STN.

To **regenerate keys** (only if DevOps agrees — old keys stop working):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\configure_site.ps1 -SiteCode V8 -RegenerateKeys
```

Send new `configs\k95-vps-snippet.env` to DevOps.

### Step 4 — Reinstall

```text
DEPLOY_NEW_SITE.cmd
```

Or: `2-INSTALL_FACTORY.cmd` then `3-CONFIGURE_DEVICE.cmd`.

### Step 5 — Repair Cloudflare if public URL fails

```text
REPAIR_CLOUDFLARE.cmd
```

Must show **v8-middleware** / **v8-mw.k95foods.com** from your yaml, not another site.

---

## Path C — Copy from working V8 PC (no git on factory PC)

If another V8 PC already works:

| Copy | Do NOT copy blindly |
|------|---------------------|
| Whole project folder **or** `git pull` | Do not reuse another site's `site.local.yaml` |
| `%USERPROFILE%\.cloudflared\` | Each PC needs its **own** tunnel credentials OR run tunnel setup fresh |

On new PC: run `1-CONFIGURE_SITE.cmd` for **V8** with **this** machine IP → new keys → DevOps updates VPS if keys are new.

---

## Install order cheat sheet

```
[ ] Windows: disable Store python aliases
[ ] git clone -b main  (or git pull)
[ ] 1-CONFIGURE_SITE.cmd          → site.local.yaml + k95-vps-snippet.env
[ ] Send k95-vps-snippet.env to DevOps
[ ] 2-INSTALL_FACTORY.cmd (Admin) OR DEPLOY_NEW_SITE.cmd (Admin)
[ ] cloudflared tunnel login + setup (once)
[ ] 3-CONFIGURE_DEVICE.cmd (Admin)
[ ] ping + Test-NetConnection :5005
[ ] RESTART_STACK.cmd
[ ] CHECK_STATUS.cmd
[ ] /health local + https://v8-mw.k95foods.com/health
[ ] test-connection → connected true
[ ] finger punch → dashboard + ERP
```

---

## Troubleshooting quick map

| Symptom | Fix |
|---------|-----|
| `DEPLOY_NEW_SITE.cmd` parser error | `git pull origin main` |
| Python not found / Store stub | Aliases off + new Admin cmd + `2-INSTALL_FACTORY.cmd` |
| Gateway crash on start | Check `outbound_api_key` not empty string in yaml |
| Port 8080 bind error | `stop_stack.ps1`; don't run gateway manually |
| Public health fails | `REPAIR_CLOUDFLARE.cmd` |
| Machine port 5005 fails | IP conflict or wrong machine IP — [ROUTER_AND_LAN_IP_RECOVERY.md](ROUTER_AND_LAN_IP_RECOVERY.md) |
| ERP CRUD fails | `middleware_api_key` ↔ VPS `V8_MIDDLEWARE_API_KEY` |
| Punches not in ERP | `outbound_hmac_secret` ↔ VPS `V8_WEBHOOK_SECRET` |
| Live punches missing | `3-CONFIGURE_DEVICE.cmd` or `RECOVER_AFTER_NETWORK_CHANGE.cmd -FixLivePush` |

---

## Related docs

- [MULTI_SITE_CONFIG.md](MULTI_SITE_CONFIG.md) — naming rules, two keys per site
- [SITE_PC_SETUP.md](SITE_PC_SETUP.md) — CMD file reference
- [ROUTER_AND_LAN_IP_RECOVERY.md](ROUTER_AND_LAN_IP_RECOVERY.md) — LAN / router IP changes
- [PRODUCTION_RESILIENCE.md](PRODUCTION_RESILIENCE.md) — auto-heal after reboot
