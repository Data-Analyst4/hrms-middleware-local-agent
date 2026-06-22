"""Outbound punch client edge-case unit tests."""
from __future__ import annotations

import json
from datetime import datetime

from attendance_relay.models import OutboxRecord
from attendance_relay.outbound_client import OutboundClient, _build_hmac_signature


def _client(**kwargs) -> OutboundClient:
    defaults = dict(
        url="https://dev.erp.k95foods.com/api/integrations/middleware/punch",
        api_key_header="x-api-key",
        api_key="test-key",
        timeout_seconds=5.0,
        verify_tls=True,
        enforce_https=True,
        enforce_post=True,
        site_code="V8",
        device_id="V8-T501-01",
        hmac_secret="secret-hmac",
    )
    defaults.update(kwargs)
    return OutboundClient(**defaults)


def test_hmac_signature_stable() -> None:
    body = b'{"enroll_no":"88001"}'
    assert _build_hmac_signature("secret", body).startswith("sha256=")
    assert _build_hmac_signature("secret", body) == _build_hmac_signature("secret", body)
    assert _build_hmac_signature("other", body) != _build_hmac_signature("secret", body)


def test_send_includes_required_headers(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

    class FakeHttpx:
        def request(self, method, url, content=None, headers=None):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers
            captured["content"] = content
            return FakeResponse()

        def close(self):
            pass

    client = _client()
    client.client = FakeHttpx()
    record = OutboxRecord(
        id=1,
        event_hash="h",
        employee_code="88001",
        log_datetime=datetime(2026, 6, 13, 10, 0, 0),
        log_time="10:00:00",
        downloaded_at=datetime(2026, 6, 13, 10, 0, 1),
        device_sn="SN1",
        attempt_count=0,
    )
    payload = {
        "enroll_no": "88001",
        "log_datetime": "2026-06-13 10:00:00",
        "io_time": "20260613100000",
        "device_sn": "SN1",
    }
    result = client.send(record, payload_override=payload)
    assert result.ok is True
    h = captured["headers"]
    assert h["X-Site-Code"] == "V8"
    assert h["X-Device-Id"] == "V8-T501-01"
    assert h["X-Idempotency-Key"] == "SN1:88001:20260613100000"
    assert h["X-Middleware-Signature"].startswith("sha256=")


def test_enforce_https_rejects_http() -> None:
    try:
        _client(url="http://insecure.example/punch")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "HTTPS" in str(exc)


def test_extract_enroll_from_raw_preview() -> None:
    from attendance_relay.outbound_client import _extract_enroll_no

    preview = 'prefix {"user_id":"0088001","io_time":"x"} suffix'
    assert _extract_enroll_no("fallback", preview) == "88001"
