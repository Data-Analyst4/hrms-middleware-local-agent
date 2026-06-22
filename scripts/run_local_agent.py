from __future__ import annotations

import argparse
import os
import time
from typing import Any

import httpx

from attendance_relay.command_executor import execute_command_safe
from attendance_relay.db import create_db_engine, init_local_schema, is_sqlite
from attendance_relay.middleware_repository import MiddlewareRepository
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import load_settings


def _headers(api_key: str, jwt_token: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json",
    }


def run_local_executor(
    *,
    settings_path: str,
    agent_id: str,
    device_ids: list[str],
    poll_seconds: float,
    once: bool,
    use_http_claim: bool,
    base_url: str,
) -> int:
    settings = load_settings(settings_path)
    engine = create_db_engine(settings)
    if is_sqlite(engine):
        init_local_schema(engine)
    repo = AttendanceRepository(engine)
    middleware_repo = MiddlewareRepository(engine)

    api_key = os.getenv("ATT_RELAY_AGENT_API_KEY", settings.agent_api_key)
    jwt_token = os.getenv("ATT_RELAY_AGENT_JWT_TOKEN", settings.agent_jwt_token)

    while True:
        if use_http_claim:
            claimed = _claim_via_http(
                base_url=base_url,
                api_key=api_key,
                jwt_token=jwt_token,
                agent_id=agent_id,
                device_ids=device_ids,
            )
        else:
            claimed = middleware_repo.claim_commands(
                agent_id=agent_id,
                device_ids=device_ids,
                limit=10,
            )

        for command in claimed:
            command_id = str(command.get("command_id") or "")
            ok, result, error = execute_command_safe(
                command=command,
                repo=repo,
                middleware_repo=middleware_repo,
                settings=settings,
            )
            if use_http_claim:
                _submit_result_http(
                    base_url=base_url,
                    api_key=api_key,
                    jwt_token=jwt_token,
                    agent_id=agent_id,
                    command_id=command_id,
                    ok=ok,
                    result=result,
                    error=error,
                )
            else:
                middleware_repo.submit_command_result(
                    command_id=command_id,
                    agent_id=agent_id,
                    success=ok,
                    error_code=None if ok else "EXEC_FAILED",
                    error_message=error,
                    result_payload=result,
                )
            print(f"command_id={command_id} type={command.get('command_type')} ok={ok}")

        if once:
            break
        time.sleep(max(0.5, poll_seconds))
    return 0


def _claim_via_http(
    *,
    base_url: str,
    api_key: str,
    jwt_token: str,
    agent_id: str,
    device_ids: list[str],
) -> list[dict[str, Any]]:
    with httpx.Client(timeout=30.0) as client:
        client.post(
            f"{base_url.rstrip('/')}/api/v1/agent/heartbeat",
            headers=_headers(api_key, jwt_token),
            json={"agent_id": agent_id, "details": {"executor": "local"}},
        )
        response = client.post(
            f"{base_url.rstrip('/')}/api/v1/agent/commands/claim",
            headers=_headers(api_key, jwt_token),
            json={"agent_id": agent_id, "device_ids": device_ids, "limit": 10},
        )
        response.raise_for_status()
        return list(response.json().get("rows") or [])


def _submit_result_http(
    *,
    base_url: str,
    api_key: str,
    jwt_token: str,
    agent_id: str,
    command_id: str,
    ok: bool,
    result: dict[str, Any],
    error: str | None,
) -> None:
    with httpx.Client(timeout=30.0) as client:
        client.post(
            f"{base_url.rstrip('/')}/api/v1/agent/commands/{command_id}/result",
            headers=_headers(api_key, jwt_token),
            json={
                "agent_id": agent_id,
                "success": ok,
                "error_code": None if ok else "EXEC_FAILED",
                "error_message": error,
                "result_payload": result,
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute queued HRMS commands against local biometric devices.")
    parser.add_argument("--config", default="configs/dev.yaml")
    parser.add_argument("--agent-id", default="LOCAL_AGENT")
    parser.add_argument("--device-ids", default="", help="Comma-separated device IDs this PC manages.")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--http-claim", action="store_true", help="Claim via HTTP instead of direct DB.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    device_ids = [part.strip() for part in args.device_ids.split(",") if part.strip()]
    raise SystemExit(
        run_local_executor(
            settings_path=args.config,
            agent_id=args.agent_id,
            device_ids=device_ids,
            poll_seconds=args.poll_seconds,
            once=args.once,
            use_http_claim=args.http_claim,
            base_url=args.base_url,
        )
    )


if __name__ == "__main__":
    main()
