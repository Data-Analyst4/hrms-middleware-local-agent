from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from attendance_relay.settings import Settings

LOGGER = logging.getLogger("attendance_relay.alerts")

# Event names used across worker, webhook dispatch, and supervisor.
ALERT_EVENT_OUTBOX_DEAD = "outbox_dead"
ALERT_EVENT_OUTBOX_SEND_FAILED = "outbox_send_failed"
ALERT_EVENT_OUTBOX_FAILED_REPLAYED = "outbox_failed_replayed"
ALERT_EVENT_WORKER_LOOP_ERROR = "worker_loop_error"
ALERT_EVENT_WORKER_LOOP_ERROR_LIMIT = "worker_loop_error_limit"
ALERT_EVENT_WEBHOOK_DEAD = "webhook_dead"
ALERT_EVENT_PROCESS_RESTART = "process_restart"
ALERT_EVENT_GATEWAY_UNHEALTHY = "gateway_unhealthy"
ALERT_EVENT_FK_HEALTH_STALE = "fk_health_stale"
ALERT_EVENT_WORKER_HEALTH_STALE = "worker_health_stale"
ALERT_EVENT_LIVE_PUSH_HEAL_FAILED = "live_push_heal_failed"
ALERT_EVENT_DEVICE_PULL_FAILED = "device_pull_failed"
ALERT_EVENT_WEBHOOK_DISPATCH_FAILED = "webhook_dispatch_failed"
ALERT_EVENT_TUNNEL_UNHEALTHY = "tunnel_unhealthy"

ALL_ALERT_EVENTS = frozenset(
    {
        ALERT_EVENT_OUTBOX_DEAD,
        ALERT_EVENT_OUTBOX_SEND_FAILED,
        ALERT_EVENT_OUTBOX_FAILED_REPLAYED,
        ALERT_EVENT_WORKER_LOOP_ERROR,
        ALERT_EVENT_WORKER_LOOP_ERROR_LIMIT,
        ALERT_EVENT_WEBHOOK_DEAD,
        ALERT_EVENT_PROCESS_RESTART,
        ALERT_EVENT_GATEWAY_UNHEALTHY,
        ALERT_EVENT_FK_HEALTH_STALE,
        ALERT_EVENT_WORKER_HEALTH_STALE,
        ALERT_EVENT_LIVE_PUSH_HEAL_FAILED,
        ALERT_EVENT_DEVICE_PULL_FAILED,
        ALERT_EVENT_WEBHOOK_DISPATCH_FAILED,
        ALERT_EVENT_TUNNEL_UNHEALTHY,
    }
)

_LOCK = threading.Lock()


def _site_label(settings: Settings) -> str:
    if settings.site_name.strip():
        return settings.site_name.strip()
    if settings.outbound_site_code.strip():
        return settings.outbound_site_code.strip()
    return "middleware"


def _event_allowed(settings: Settings, event: str) -> bool:
    if not settings.alerts_enabled:
        return False
    configured = {item.strip() for item in settings.alerts_events if item.strip()}
    if configured and event not in configured:
        return False
    return event in ALL_ALERT_EVENTS


def _load_cooldown_state(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(raw, dict):
        return {}
    state: dict[str, float] = {}
    for key, value in raw.items():
        try:
            state[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return state


def _save_cooldown_state(path: Path, state: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")


def _cooldown_key(event: str, context: dict[str, Any]) -> str:
    parts = [event]
    for field in ("process", "outbox_id", "delivery_id", "employee_code"):
        value = context.get(field)
        if value is not None and str(value).strip():
            parts.append(f"{field}={value}")
    return "|".join(parts)


def _cooldown_ok(settings: Settings, event: str, context: dict[str, Any]) -> bool:
    cooldown = max(0, int(settings.alerts_cooldown_seconds))
    if cooldown == 0:
        return True
    path = Path(settings.alerts_cooldown_file)
    key = _cooldown_key(event, context)
    now = time.time()
    with _LOCK:
        state = _load_cooldown_state(path)
        last = state.get(key)
        if last is not None and (now - last) < cooldown:
            return False
        state[key] = now
        _save_cooldown_state(path, state)
    return True


def _format_message(*, settings: Settings, event: str, title: str, message: str, context: dict[str, Any]) -> str:
    site = _site_label(settings)
    lines = [f"[{site}] {title}", f"Event: {event}", message]
    detail_keys = (
        "process",
        "outbox_id",
        "employee_code",
        "attempt",
        "error",
        "status_code",
        "delivery_id",
        "count",
        "exit_code",
    )
    for key in detail_keys:
        value = context.get(key)
        if value is not None and str(value).strip():
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _send_via_webhook(settings: Settings, body: dict[str, Any]) -> None:
    url = settings.alerts_webhook_url.strip()
    if not url:
        raise ValueError("alerts_webhook_url is required for webhook provider")
    with httpx.Client(timeout=settings.alerts_timeout_seconds, verify=settings.outbound_verify_tls) as client:
        response = client.post(url, json=body)
        response.raise_for_status()


def _send_via_callmebot(settings: Settings, text: str) -> None:
    phone = settings.alerts_recipient.strip()
    api_key = settings.alerts_api_key.strip()
    if not phone or not api_key:
        raise ValueError("alerts_recipient (phone) and alerts_api_key (CallMeBot key) are required")
    url = (
        "https://api.callmebot.com/whatsapp.php"
        f"?phone={quote(phone)}&text={quote(text)}&apikey={quote(api_key)}"
    )
    with httpx.Client(timeout=settings.alerts_timeout_seconds) as client:
        response = client.get(url)
        response.raise_for_status()


def _send_via_telegram(settings: Settings, text: str) -> None:
    token = settings.alerts_api_key.strip()
    chat_id = settings.alerts_recipient.strip()
    if not token or not chat_id:
        raise ValueError("alerts_api_key (bot token) and alerts_recipient (chat id) are required")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with httpx.Client(timeout=settings.alerts_timeout_seconds) as client:
        response = client.post(url, json={"chat_id": chat_id, "text": text})
        response.raise_for_status()


def _send_via_ntfy(settings: Settings, text: str) -> None:
    topic = settings.alerts_recipient.strip()
    if not topic:
        raise ValueError("alerts_recipient (ntfy topic name) is required")
    url = f"https://ntfy.sh/{quote(topic, safe='')}"
    headers: dict[str, str] = {"Title": _site_label(settings)[:64]}
    token = settings.alerts_api_key.strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=settings.alerts_timeout_seconds) as client:
        response = client.post(url, content=text.encode("utf-8"), headers=headers)
        response.raise_for_status()


def _send_via_twilio(settings: Settings, text: str) -> None:
    account_sid = settings.alerts_api_key.strip()
    auth_token = settings.alerts_api_secret.strip()
    from_number = settings.alerts_from.strip()
    to_number = settings.alerts_recipient.strip()
    if not account_sid or not auth_token or not from_number or not to_number:
        raise ValueError("Twilio requires alerts_api_key (account sid), alerts_api_secret, alerts_from, alerts_recipient")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    with httpx.Client(timeout=settings.alerts_timeout_seconds) as client:
        response = client.post(
            url,
            data={"From": from_number, "To": to_number, "Body": text},
            auth=(account_sid, auth_token),
        )
        response.raise_for_status()


def send_alert(
    settings: Settings,
    *,
    event: str,
    title: str,
    message: str,
    **context: Any,
) -> bool:
    """Send a failure alert if enabled. Never raises."""
    if not _event_allowed(settings, event):
        return False
    if not _cooldown_ok(settings, event, context):
        LOGGER.debug("alert suppressed by cooldown", extra={"event": event})
        return False

    site = _site_label(settings)
    text = _format_message(settings=settings, event=event, title=title, message=message, context=context)
    payload = {
        "event": event,
        "site": site,
        "title": title,
        "message": message,
        "text": text,
        "context": context,
    }

    provider = settings.alerts_provider.strip().lower()
    try:
        if provider == "webhook":
            _send_via_webhook(settings, payload)
        elif provider == "callmebot":
            _send_via_callmebot(settings, text)
        elif provider == "telegram":
            _send_via_telegram(settings, text)
        elif provider == "ntfy":
            _send_via_ntfy(settings, text)
        elif provider == "twilio":
            _send_via_twilio(settings, text)
        else:
            raise ValueError(f"unsupported alerts_provider: {provider}")
        LOGGER.info("alert_sent", extra={"event": event, "provider": provider})
        return True
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "alert_send_failed",
            extra={"event": event, "provider": provider, "error": f"{type(exc).__name__}: {exc}"},
        )
        return False
