# WhatsApp failure alerts (V8 and other sites)

The middleware can send WhatsApp messages when something breaks. Alerts use the same config as `configs/site.local.yaml` and never block punch processing.

## Quick setup (CallMeBot — free)

1. On your phone, add **+34 644 44 96 44** as a WhatsApp contact.
2. Send this exact message to that contact:
   ```text
   I allow callmebot to send me messages
   ```
3. CallMeBot replies with your **API key**. Copy it.
4. Edit `configs/site.local.yaml`:

   ```yaml
   alerts_enabled: true
   alerts_provider: "callmebot"
   alerts_recipient: "+919876543210"    # your WhatsApp number with country code
   alerts_api_key: "123456"             # key from CallMeBot reply
   alerts_cooldown_seconds: 300         # min 5 min between repeat alerts for same event
   ```

5. Test (middleware can be running or stopped):

   ```powershell
   .\.venv\Scripts\python.exe scripts\test_alerts.py --config configs\factory.yaml
   ```

6. Restart the stack so the supervisor picks up config:

   ```powershell
   .\RESTART_STACK.cmd
   ```

## What triggers a WhatsApp message

| Event | When you get notified |
|-------|----------------------|
| `outbox_dead` | Punch stuck in FAILED after all retries |
| `outbox_send_failed` | ERP rejected or unreachable for a punch |
| `outbox_failed_replayed` | Hourly replay started for dead punches |
| `process_restart` | Gateway, worker, or FK listener crashed and restarted |
| `gateway_unhealthy` | Local API `/health` failed; supervisor restarted gateway |
| `fk_health_stale` | No device punch traffic on port 8081 for ~10 min |
| `worker_health_stale` | Outbox worker stopped updating health file |
| `live_push_heal_failed` | Auto-heal could not fix device push IP |
| `device_pull_failed` | SDK pull from biometric device failed |
| `tunnel_unhealthy` | Cloudflare tunnel down after watchdog restart attempt |
| `webhook_dead` | Outbound webhook delivery failed permanently |
| `worker_loop_error` / `worker_loop_error_limit` | Worker internal errors |

Leave `alerts_events: []` empty (default) to receive **all** events. To reduce noise, list only what you care about:

```yaml
alerts_events:
  - outbox_dead
  - tunnel_unhealthy
  - fk_health_stale
  - live_push_heal_failed
```

## Other providers

| Provider | `alerts_provider` | Notes |
|----------|-------------------|-------|
| Custom webhook (n8n, Zapier) | `webhook` | Set `alerts_webhook_url`; JSON body includes `text` field |
| Telegram | `telegram` | `alerts_api_key` = bot token, `alerts_recipient` = chat id |
| Twilio WhatsApp Business | `twilio` | Needs `alerts_from`, `alerts_api_secret` |

## Cooldown

Same event (e.g. `fk_health_stale`) will not spam you more than once per `alerts_cooldown_seconds` (default 300). State is stored in `var/alerts/last_sent.json`.

## Verify alerts are armed

```powershell
# Should print alerts_enabled: true after you edit site.local.yaml
.\.venv\Scripts\python.exe -c "from attendance_relay.settings import load_settings; s=load_settings('configs/factory.yaml'); print('alerts_enabled', s.alerts_enabled, 'provider', s.alerts_provider)"
```
