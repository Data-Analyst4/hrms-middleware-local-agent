# Site PC Installation Guide (Windows 10 / 11)

Copy the **entire project folder** to the target PC (any path). Examples:

- `D:\HRMS`
- `C:\Apps\HR Module`
- USB stick then paste to `C:\Factory\HR Module`

Do **not** depend on `C:\Users\YourName\...` — all scripts resolve paths from the folder they live in.

---

## One-click install (recommended)

| Order | File | What it does |
|-------|------|----------------|
| **All-in-one** | `SETUP_NEW_PC.cmd` | Configure + install + autostart |
| **Or step 1** | `1-CONFIGURE_SITE.cmd` | Create `configs\site.local.yaml` |
| **Or step 2** | `2-INSTALL_FACTORY.cmd` | Install + autostart (Admin) |
| **Optional step 3** | `3-CONFIGURE_DEVICE.cmd` | Firewall + device live-push (Admin) |
| **Check** | `CHECK_STATUS.cmd` | Health check |
| **After moving folder** | `REPAIR_AUTOSTART.cmd` | Re-register tasks with new path (Admin) |

---

## What to change on each PC

Edit **`configs\site.local.yaml`** (created from `site.local.yaml.example`):

| Setting | Description |
|---------|-------------|
| `machine_sync_ip` | Biometric device IP on LAN |
| `machine_sync_port` | Usually `5005` |
| `machine_sync_password` | Device comm password (`0` if disabled) |
| `machine_sync_machine_number` | STN on device (often `1` or `2`) |
| `machine_sdk_dll_path` | Relative path to `SBXPCDLL64.dll` inside this folder |
| `outbound_site_code` | ERP branch code (e.g. `V8`) |
| `outbound_device_id` | ERP device id (e.g. `V8-T501-01`) |
| `outbound_url` | ERP punch API URL |
| `outbound_api_key` | ERP webhook API key |
| `outbound_hmac_secret` | HMAC secret (match ERP) |
| `middleware_api_key` | Key for `/api/v1/*` calls |
| `cloudflare_public_hostname` | Public hostname (no `https://`) |
| `device_lan_ip_for_firewall` | Optional; defaults to `machine_sync_ip` |

**Cloudflare tunnel (one-time per site):**

- Copy `%USERPROFILE%\.cloudflared` from an existing site PC, **or**
- Run `cloudflared tunnel login` then `scripts\setup_cloudflare_tunnel.ps1`

**Ship with the folder:**

- `sdk_extracted\` (biometric SDK DLL)
- `configs\site.local.yaml` (per PC)
- Optional: `.cloudflared\` credentials on first PC setup

---

## Windows 10 notes

- Requires **Python 3.11+** (installer uses winget when available).
- If winget is missing, install Python from [python.org](https://www.python.org/downloads/) then run `2-INSTALL_FACTORY.cmd` with `-SkipPrereqInstall` via PowerShell.
- Run install CMDs **as Administrator** for firewall + boot autostart.

---

## After install

- Local API: `http://127.0.0.1:8080`
- Dashboard: `http://127.0.0.1:8080/dashboard`
- Public (ERP): `https://<cloudflare_public_hostname>/health`
- Logs: `var\logs\supervisor.log`, `var\logs\cloudflared-watchdog.log`

---

## Moving the folder to another PC or path

1. Copy entire folder to new location
2. Edit `configs\site.local.yaml` if device/network changed
3. Run **`REPAIR_AUTOSTART.cmd`** as Administrator (updates scheduled task paths)
