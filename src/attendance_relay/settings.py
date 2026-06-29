from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


DEFAULT_CONFIG_PATH = Path("configs/factory.yaml")
ENV_PREFIX = "ATT_RELAY_"


class Settings(BaseModel):
    env: str = "dev"
    log_level: str = "INFO"
    tz_name: str = "Asia/Calcutta"

    ingress_host: str = "0.0.0.0"
    ingress_port: int = 8000
    ingress_path: str = "/machine/realtime_glog"
    expected_request_code: str = "realtime_glog"
    machine_ok_response_code: str = "OK"

    direct_listener_host: str = "0.0.0.0"
    direct_listener_port: int = 8010
    direct_listener_path: str = "/machine/realtime_glog"
    direct_listener_jsonl_path: str = "var/direct_listener/punches.jsonl"

    fk_web_listener_host: str = "0.0.0.0"
    fk_web_listener_port: int = 8081

    db_url: str = "sqlite:///attendance.db"
    db_pool_pre_ping: bool = True
    db_echo: bool = False

    outbox_batch_size: int = 100
    outbox_poll_seconds: float = 1.0
    processing_lease_seconds: int = 120
    stale_processing_seconds: int = 300
    max_retries: int = 5
    backoff_base_seconds: float = 1.5
    backoff_max_seconds: float = 60.0
    backoff_jitter_seconds: float = 0.75

    outbound_url: str = "https://localhost:9443/api/attendance"
    outbound_api_key_header: str = "x-api-key"
    outbound_api_key: str = "change-me"
    outbound_timeout_seconds: float = 15.0
    outbound_verify_tls: bool = True
    outbound_method: str = "POST"
    enforce_https: bool = True
    enforce_post: bool = True
    outbound_include_extended_fields: bool = True
    outbound_device_name_default: str = ""
    outbound_device_no_default: str = ""
    outbound_relay_enabled: bool = False
    outbound_site_code: str = ""
    outbound_device_id: str = ""
    outbound_hmac_secret: str = ""

    worker_health_file: str = "var/worker/health.json"
    worker_max_loop_errors: int = 100
    worker_fatal_on_max_loop_errors: bool = False

    outbound_http_retries: int = 2
    failed_outbox_replay_enabled: bool = True
    failed_outbox_replay_interval_seconds: int = 3600
    failed_outbox_replay_batch_size: int = 50

    live_push_auto_heal_enabled: bool = True
    live_push_heal_interval_seconds: int = 900

    fk_health_file: str = "var/fk_listener/health.json"
    supervisor_health_file: str = "var/supervisor/health.json"
    network_ready_max_wait_seconds: int = 120

    machine_sdk_dll_path: str = "sdk_extracted/20211204-SBXPC-1/bin/SBXPCDLL64.dll"
    machine_sync_ip: str = ""
    machine_sync_port: int = 5005
    machine_sync_password: int = 0
    machine_sync_machine_number: int = 1
    machine_sync_timezone1: int = 1
    machine_sync_timezone2: int = 0
    machine_sync_group_no: int = 1

    middleware_api_key: str = "change-me-middleware"
    agent_api_key: str = "change-me-agent"
    agent_jwt_token: str = "change-me-agent-jwt"
    webhook_hmac_secret: str = "change-me-webhook-secret"
    webhook_timeout_seconds: float = 10.0
    webhook_dispatch_batch_size: int = 50

    site_name: str = ""

    alerts_enabled: bool = False
    alerts_provider: str = "k95_erp"
    alerts_fallback_provider: str = "ntfy"
    alerts_erp_url: str = ""
    alerts_webhook_url: str = ""
    alerts_recipient: str = ""
    alerts_api_key: str = ""
    alerts_api_secret: str = ""
    alerts_from: str = ""
    alerts_cooldown_seconds: int = 300
    alerts_timeout_seconds: float = 15.0
    alerts_cooldown_file: str = "var/alerts/last_sent.json"
    alerts_events: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _enforce_transport_policy(self) -> "Settings":
        if not self.outbound_relay_enabled:
            return self
        if self.enforce_https and not self.outbound_url.lower().startswith("https://"):
            raise ValueError("outbound_url must start with https:// when enforce_https=true")
        if self.enforce_post and self.outbound_method.upper() != "POST":
            raise ValueError("outbound_method must be POST when enforce_post=true")
        if not self.outbound_api_key:
            raise ValueError("outbound_api_key cannot be empty")
        if self.outbound_hmac_secret and not self.outbound_url:
            raise ValueError("outbound_url is required when outbound relay is enabled")
        return self


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a top-level object: {path}")
    return data


def _env_overrides() -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for field in Settings.model_fields.keys():
        env_key = f"{ENV_PREFIX}{field.upper()}"
        if env_key in os.environ:
            overrides[field] = os.environ[env_key]
    return overrides


def _merge_config(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
  merged = dict(base)
  for key, value in overlay.items():
    if value is None:
      continue
    if isinstance(value, str) and not value.strip():
      continue
    merged[key] = value
  return merged


def load_settings(config_path: str | None = None) -> Settings:
    raw_path = config_path or os.getenv(f"{ENV_PREFIX}CONFIG") or str(DEFAULT_CONFIG_PATH)
    path = Path(raw_path)
    merged = _read_yaml(path)
    # Per-PC overrides: configs/site.local.yaml (same folder as factory.yaml / dev.yaml).
    merged = _merge_config(merged, _read_yaml(path.resolve().parent / "site.local.yaml"))
    merged = _merge_config(merged, _env_overrides())
    return Settings.model_validate(merged)
