from __future__ import annotations

import json
from pathlib import Path

import httpx

from attendance_relay.alert_notifier import (
    ALERT_EVENT_OUTBOX_DEAD,
    send_alert,
)
from attendance_relay.settings import Settings


def test_send_alert_webhook(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None):
            calls.append({"url": url, "json": json})

            class Response:
                status_code = 200

                def raise_for_status(self):
                    return None

            return Response()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    cooldown_file = tmp_path / "cooldown.json"
    settings = Settings(
        alerts_enabled=True,
        alerts_provider="webhook",
        alerts_webhook_url="https://hooks.example.com/alert",
        outbound_site_code="V8",
        site_name="V8 Factory",
        alerts_cooldown_file=str(cooldown_file),
        alerts_cooldown_seconds=0,
        outbound_api_key="test-key",
    )

    ok = send_alert(
        settings,
        event=ALERT_EVENT_OUTBOX_DEAD,
        title="Punch failed",
        message="Could not deliver punch.",
        outbox_id=42,
        employee_code="E1001",
        error="timeout",
    )
    assert ok is True
    assert len(calls) == 1
    body = calls[0]["json"]
    assert body["event"] == ALERT_EVENT_OUTBOX_DEAD
    assert body["site"] == "V8 Factory"
    assert "V8 Factory" in body["text"]
    assert body["context"]["outbox_id"] == 42


def test_send_alert_respects_cooldown(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None):
            calls["n"] += 1

            class Response:
                status_code = 200

                def raise_for_status(self):
                    return None

            return Response()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    cooldown_file = tmp_path / "cooldown.json"
    settings = Settings(
        alerts_enabled=True,
        alerts_provider="webhook",
        alerts_webhook_url="https://hooks.example.com/alert",
        alerts_cooldown_file=str(cooldown_file),
        alerts_cooldown_seconds=3600,
        outbound_api_key="test-key",
    )

    assert send_alert(settings, event=ALERT_EVENT_OUTBOX_DEAD, title="A", message="B", outbox_id=1) is True
    assert send_alert(settings, event=ALERT_EVENT_OUTBOX_DEAD, title="A", message="B", outbox_id=1) is False
    assert calls["n"] == 1
    state = json.loads(cooldown_file.read_text(encoding="utf-8"))
    assert isinstance(state, dict)


def test_send_alert_disabled_by_event_filter(monkeypatch) -> None:
    calls = {"n": 0}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None):
            calls["n"] += 1

            class Response:
                status_code = 200

                def raise_for_status(self):
                    return None

            return Response()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    settings = Settings(
        alerts_enabled=True,
        alerts_provider="webhook",
        alerts_webhook_url="https://hooks.example.com/alert",
        alerts_events=["process_restart"],
        outbound_api_key="test-key",
    )

    ok = send_alert(settings, event=ALERT_EVENT_OUTBOX_DEAD, title="A", message="B")
    assert ok is False
    assert calls["n"] == 0


def test_send_alert_callmebot_url(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            captured["url"] = url

            class Response:
                status_code = 200

                def raise_for_status(self):
                    return None

            return Response()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    settings = Settings(
        alerts_enabled=True,
        alerts_provider="callmebot",
        alerts_recipient="+919999999999",
        alerts_api_key="abc123",
        alerts_cooldown_seconds=0,
        outbound_api_key="test-key",
    )

    ok = send_alert(settings, event="process_restart", title="Test", message="Hello")
    assert ok is True
    assert "api.callmebot.com/whatsapp.php" in captured["url"]
    assert "phone=%2B919999999999" in captured["url"]
    assert "apikey=abc123" in captured["url"]
