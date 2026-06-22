from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from attendance_relay.ingress_app import create_ingress_app
from attendance_relay.settings import Settings


def _build_app(tmp_path: Path):
    settings = Settings(
        env="test",
        db_url=f"sqlite:///{tmp_path / 'hrms_phases.db'}",
        log_level="WARNING",
        outbound_api_key="test-outbound",
        middleware_api_key="mw-key",
        agent_api_key="agent-key",
        agent_jwt_token="agent-jwt",
        webhook_hmac_secret="webhook-secret",
    )
    return create_ingress_app(settings), settings


def test_phase1_employee_list_and_sync_status(tmp_path: Path) -> None:
    app, settings = _build_app(tmp_path)
    headers = {"x-api-key": settings.middleware_api_key}
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/employees",
            headers=headers,
            json={"employee_code": "E101", "employee_name": "Phase One User", "card_no": "101"},
        )
        assert created.status_code == 201

        listed = client.get("/api/v1/employees", headers=headers)
        assert listed.status_code == 200
        body = listed.json()
        assert body["total"] >= 1
        assert any(row["employee_code"] == "E101" for row in body["rows"])

        one = client.get("/api/v1/employees/E101", headers=headers)
        assert one.status_code == 200
        assert one.json()["employee_name"] == "Phase One User"

        status = client.get("/api/v1/sync-status", headers=headers)
        assert status.status_code == 200
        assert "devices" in status.json()


def test_phase1_device_registry_and_settings_page(tmp_path: Path) -> None:
    app, settings = _build_app(tmp_path)
    headers = {"x-api-key": settings.middleware_api_key}
    with TestClient(app) as client:
        device = client.post(
            "/api/v1/devices",
            headers=headers,
            json={
                "device_id": "SITE-A-T501",
                "site_id": "SITE-A",
                "device_name": "Gate Device",
                "ip": "192.168.29.44",
                "port": 5005,
                "machine_number": 2,
                "machine_password": "0",
                "middleware_public_url": "https://site-a.example.com",
            },
        )
        assert device.status_code == 201
        assert device.json()["machine_number"] == 2

        patched = client.patch(
            "/api/v1/devices/SITE-A-T501",
            headers=headers,
            json={"ip": "192.168.29.50", "machine_number": 3},
        )
        assert patched.status_code == 200
        assert patched.json()["ip"] == "192.168.29.50"

        detail = client.get("/api/v1/devices/SITE-A-T501", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["device"]["ip"] == "192.168.29.50"

        settings_page = client.get("/settings")
        assert settings_page.status_code == 200
        assert "Device & Site Settings" in settings_page.text


def test_phase2_bulk_mapping(tmp_path: Path) -> None:
    app, settings = _build_app(tmp_path)
    headers = {"x-api-key": settings.middleware_api_key}
    repo = app.state.repo

    with TestClient(app) as client:
        client.post(
            "/api/v1/devices",
            headers=headers,
            json={
                "device_id": "SITE-A-T501",
                "site_id": "SITE-A",
                "ip": "192.168.29.44",
                "port": 5005,
            },
        )

    repo.import_machine_users_to_db(
        rows=[{"user_id": 7, "user_name": "Machine User 7", "enabled": True, "slot_count": 1}],
        machine_ip="192.168.29.44",
        device_id="SITE-A-T501",
        machine_number=2,
        overwrite_existing_names=True,
    )

    with TestClient(app) as client:
        unmapped = client.get(
            "/api/v1/mappings/unmapped",
            headers=headers,
            params={"device_id": "SITE-A-T501"},
        )
        assert unmapped.status_code == 200
        assert unmapped.json()["loaded"] >= 1

        mapped = client.post(
            "/api/v1/devices/SITE-A-T501/mappings/bulk",
            headers=headers,
            json={
                "mappings": [{"user_id": 7, "employee_code": "EMP007", "employee_name": "Mapped User"}],
            },
        )
        assert mapped.status_code == 200
        assert mapped.json()["updated"] == 1

        employee = client.get("/api/v1/employees/EMP007", headers=headers)
        assert employee.status_code == 200


def test_phase3_command_executor_employee_sync(monkeypatch, tmp_path: Path) -> None:
    from attendance_relay.command_executor import execute_command

    captured: dict[str, object] = {}

    def _fake_update(*, repo, settings, employee_code, request):
        captured["employee_code"] = employee_code
        return {"employee_code": employee_code, "synced": True}

    monkeypatch.setattr("attendance_relay.command_executor.update_employee_on_machine", _fake_update)

    app, settings = _build_app(tmp_path)
    headers = {"x-api-key": settings.middleware_api_key}
    with TestClient(app) as client:
        client.post(
            "/api/v1/devices",
            headers=headers,
            json={
                "device_id": "SITE-A-T501",
                "site_id": "SITE-A",
                "ip": "192.168.29.44",
                "port": 5005,
                "machine_number": 2,
            },
        )
        client.post(
            "/api/v1/employees",
            headers=headers,
            json={"employee_code": "E200", "employee_name": "Cmd User", "card_no": "200"},
        )

        result = execute_command(
            command={
                "device_id": "SITE-A-T501",
                "command_type": "employee.sync_one",
                "payload": {"employee_code": "E200"},
            },
            repo=app.state.repo,
            middleware_repo=app.state.middleware_repo,
            settings=settings,
        )
        assert result["synced"] is True
        assert captured["employee_code"] == "E200"
