# Multi-site middleware configuration
# One factory PC = one middleware = one biometric machine = one ERP branch

## Model

| Site | Factory PC | Machine | ERP branch | Tunnel |
|------|------------|---------|------------|--------|
| V8 | PC at gate 1 | 192.168.29.44 | Branch V8 | v8-mw.k95foods.com |
| V9 | PC at gate 2 | 192.168.30.44 | Branch V9 | v9-mw.k95foods.com |

Each site has **its own keys**. Never reuse `middleware_api_key` or `outbound_hmac_secret` across sites.

## Setup a new site (factory PC)

**One script (recommended):**

```text
DEPLOY_NEW_SITE.cmd
```

Or step-by-step:

1. Copy the HR Module folder to the new PC (any path).
2. Double-click **`1-CONFIGURE_SITE.cmd`**
   - Enter site code (e.g. `V9`)
   - Enter machine IP and STN number
   - Script auto-generates keys and tunnel hostname
3. Send **`configs/k95-vps-snippet.env`** to DevOps → paste into K95 VPS `.env` → restart backend.
4. Double-click **`2-INSTALL_FACTORY.cmd`** (Administrator).
5. Verify:
   ```powershell
   .\.venv\Scripts\python.exe scripts\_probe_erp_punch.py
   CHECK_STATUS.cmd
   ```

## Naming rules (auto-applied by configure script)

| Field | Pattern | Example (site V9) |
|-------|---------|-------------------|
| `outbound_site_code` | Your ERP branch code | `V9` |
| `outbound_device_id` | `{SITE}-T501-01` | `V9-T501-01` |
| `cloudflare_public_hostname` | `{site}-mw.k95foods.com` | `v9-mw.k95foods.com` |
| `cloudflare_tunnel_name` | `{site}-middleware` | `v9-middleware` |

## Two keys per site (only these matter for ERP sync)

| Direction | Middleware (`site.local.yaml`) | K95 VPS `.env` |
|-----------|-------------------------------|----------------|
| ERP → machine (CRUD) | `middleware_api_key` | `MIDDLEWARE_API_KEY` / `{SITE}_MIDDLEWARE_API_KEY` |
| Machine → ERP (punches) | `outbound_hmac_secret` | `{SITE}_WEBHOOK_SECRET` |

See **`configs/k95-vps.env.example`** for a multi-branch VPS template.

## VPS global (once per server)

```env
MIDDLEWARE_ENCRYPTION_KEY=<openssl rand -hex 32>
```

Set once on K95 VPS. Do not change after branch secrets are stored.

## Optional fields (usually leave empty/default)

- `outbound_api_key` — not used for punch HMAC auth on dev ERP
- `agent_api_key` — only if using agent APIs
- `webhook_hmac_secret` — middleware outbound webhooks, not K95 punches

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| CRUD works, no punches in ERP | Match `outbound_hmac_secret` ↔ K95 `{SITE}_WEBHOOK_SECRET` |
| Import V8 invalid API key | Match `middleware_api_key` ↔ K95 `MIDDLEWARE_API_KEY` |
| Wrong site receives ERP commands | Each PC must have unique site code + tunnel hostname |

## Resilience (IP changes, reboots, crashes)

| Event | Handled by |
|-------|------------|
| ISP public IP changes | Cloudflare tunnel (outbound connection; ERP URL stays fixed) |
| Factory PC gets new LAN IP (WiFi/DHCP) | SDK pull every 30s; `ensure_device_live_push.py --fix` every 15 min |
| Biometric device still pushes to old PC IP | Live-push auto-heal re-points device to current PC IP |
| Middleware process crash | `run_stack_forever.ps1` restarts gateway, worker, FK listener |
| PC reboot | Scheduled tasks: `HRMS-Middleware-Supervisor` + Cloudflare watchdog |
| Tunnel / cloudflared stops | Watchdog every 3 min + Windows service |
| ERP temporarily down | Outbox retries (8x) + hourly FAILED replay |

**Prevention:** Set **DHCP reservations** on the router for the middleware PC and the biometric device.

See **`docs/PRODUCTION_RESILIENCE.md`** for full detail.
