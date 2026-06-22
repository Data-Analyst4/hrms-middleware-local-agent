"""Production resilience unit tests."""
from __future__ import annotations

from datetime import datetime

from attendance_relay.models import OutboxRecord
from attendance_relay.net_utils import guess_site_lan_ip
from attendance_relay.outbound_client import OutboundClient, _is_transient_send_result, SendResult
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import Settings, load_settings
from attendance_relay.db import create_db_engine, init_local_schema


def test_guess_site_lan_ip_returns_string() -> None:
    ip = guess_site_lan_ip()
    assert isinstance(ip, str)
    assert ip.count(".") == 3 or ip == "127.0.0.1"


def test_is_transient_send_result() -> None:
    assert _is_transient_send_result(SendResult(ok=False, status_code=503, response_text=None, error="x"))
    assert _is_transient_send_result(
        SendResult(ok=False, status_code=None, response_text=None, error="ConnectTimeout: timed out")
    )
    assert not _is_transient_send_result(SendResult(ok=True, status_code=200, response_text="ok", error=None))
    assert not _is_transient_send_result(SendResult(ok=False, status_code=401, response_text=None, error="auth"))


def test_outbound_retries_transient_error(monkeypatch) -> None:
    calls = {"n": 0}

    class FakeResponse:
        status_code = 503
        text = "busy"

    class FakeHttpx:
        def request(self, method, url, content=None, headers=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return FakeResponse()
            class Ok:
                status_code = 200
                text = "ok"
            return Ok()

        def close(self):
            pass

    client = OutboundClient(
        url="https://example.com/punch",
        api_key_header="x-api-key",
        api_key="k",
        timeout_seconds=5.0,
        verify_tls=True,
        enforce_https=True,
        enforce_post=True,
        http_retries=2,
    )
    client.client = FakeHttpx()
    record = OutboxRecord(
        id=1,
        event_hash="h",
        employee_code="1",
        log_datetime=datetime(2026, 6, 13, 10, 0, 0),
        log_time="10:00:00",
        downloaded_at=datetime(2026, 6, 13, 10, 0, 1),
        device_sn="SN",
        attempt_count=0,
    )
    result = client.send(record)
    assert result.ok is True
    assert calls["n"] == 2


def test_replay_failed_outbox(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    settings = Settings(
        db_url=f"sqlite:///{db_path.as_posix()}",
        outbound_api_key="test-key",
    )
    engine = create_db_engine(settings)
    init_local_schema(engine)
    repo = AttendanceRepository(engine)
    now = datetime(2026, 6, 13, 12, 0, 0)
    now_s = "2026-06-13 12:00:00"
    with engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(
            text(
                """
                INSERT INTO attendance_outbox (
                  event_hash, employee_code, log_datetime, log_time, downloaded_at, device_sn,
                  status, attempt_count, max_retries, next_attempt_at, created_at, updated_at
                ) VALUES (
                  'hash1', '100', :now, '12:00:00', :now, 'DEV',
                  'FAILED', 5, 5, :now, :now, :now
                )
                """
            ),
            {"now": now_s},
        )
    replayed = repo.replay_failed_outbox(limit=10, now=now)
    assert replayed == 1
    counts = repo.get_outbox_counts()
    assert counts["FAILED"] == 0
    assert counts["PENDING"] == 1


def test_site_local_yaml_overrides_factory(tmp_path) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "factory.yaml").write_text(
        "outbound_api_key: from-factory\nmachine_sync_ip: 1.1.1.1\n",
        encoding="utf-8",
    )
    (configs / "site.local.yaml").write_text(
        "machine_sync_ip: 192.168.5.44\n",
        encoding="utf-8",
    )
    settings = load_settings(str(configs / "factory.yaml"))
    assert settings.machine_sync_ip == "192.168.5.44"
    assert settings.outbound_api_key == "from-factory"


def test_factory_settings_defaults() -> None:
    settings = Settings(outbound_api_key="k", outbound_relay_enabled=True)
    assert settings.worker_fatal_on_max_loop_errors is False
    assert settings.failed_outbox_replay_enabled is True
    assert settings.outbound_http_retries == 2
