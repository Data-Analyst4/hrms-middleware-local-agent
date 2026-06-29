# Site PC Installation Guide (Windows 10 / 11)

**Multi-site:** one PC = one machine = one ERP branch. See [MULTI_SITE_CONFIG.md](MULTI_SITE_CONFIG.md).

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
| **Optional step 3** | `3-CONFIGURE_DEVICE.cmd` | **Lock PC LAN IP** + firewall + device live-push (Admin) |
| **Optional step 3b** | `4-CONFIGURE_LAN_IP.cmd` | LAN static IP only (Admin) |
| **Check** | `CHECK_STATUS.cmd` | Health check |
| **Router / LAN IP change** | `RECOVER_AFTER_NETWORK_CHANGE.cmd` | Reconnect PC to attendance machine — see [ROUTER_AND_LAN_IP_RECOVERY.md](ROUTER_AND_LAN_IP_RECOVERY.md) |
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
| `pc_lan_ip` | Optional; middleware PC LAN IP (auto-filled by step 3) |
| `pc_lan_static_enabled` | `true` = lock PC IP during `3-CONFIGURE_DEVICE.cmd` |

**LAN IP during install (recommended):**

Run **`3-CONFIGURE_DEVICE.cmd`** as Administrator after step 2. It will:

1. **Option B (automatic):** set a Windows static IP on the adapter on the same subnet as the T501 (locks current IP if `pc_lan_ip` is empty)
2. **Option A (guide only):** write `var\lan_setup\router_dhcp_reservation.txt` with MAC + IP for your router admin (routers cannot be configured from the PC app)
3. Open firewall port 8081 and point the device live-push at this PC

To skip Windows static IP: set `pc_lan_static_enabled: false` in `site.local.yaml`, or run `3-CONFIGURE_DEVICE.cmd` with `-SkipLanStatic` via PowerShell.

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
