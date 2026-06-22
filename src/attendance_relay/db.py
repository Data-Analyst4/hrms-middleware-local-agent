from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from attendance_relay.settings import Settings


def create_db_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.db_url,
        echo=settings.db_echo,
        pool_pre_ping=settings.db_pool_pre_ping,
        future=True,
    )


def is_sqlite(engine: Engine) -> bool:
    return engine.dialect.name == "sqlite"


def init_local_schema(engine: Engine) -> None:
    """Initialize local schema for quick development/testing.

    Production SQL Server environments should use scripts under sql/.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS tbl_realtime_glog (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  employee_code TEXT NOT NULL,
                  log_datetime TEXT NOT NULL,
                  log_time TEXT NOT NULL,
                  downloaded_at TEXT NOT NULL,
                  device_sn TEXT NOT NULL,
                  raw_user_id TEXT NOT NULL,
                  raw_io_time TEXT NOT NULL,
                  source_ip TEXT NULL,
                  raw_preview TEXT NULL,
                  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS attendance_outbox (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  event_hash TEXT NOT NULL UNIQUE,
                  employee_code TEXT NOT NULL,
                  log_datetime TEXT NOT NULL,
                  log_time TEXT NOT NULL,
                  downloaded_at TEXT NOT NULL,
                  device_sn TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'PENDING',
                  attempt_count INTEGER NOT NULL DEFAULT 0,
                  max_retries INTEGER NOT NULL DEFAULT 5,
                  next_attempt_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                  processing_started_at TEXT NULL,
                  lease_until TEXT NULL,
                  sent_at TEXT NULL,
                  last_error TEXT NULL,
                  response_code INTEGER NULL,
                  response_body TEXT NULL,
                  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                  updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS employee_master (
                  employee_code TEXT PRIMARY KEY,
                  employee_code_normalized TEXT NOT NULL,
                  employee_name TEXT NULL,
                  father_name TEXT NULL,
                  card_no TEXT NULL,
                  proximity_card_no TEXT NULL,
                  email_id TEXT NULL,
                  phone_no TEXT NULL,
                  department TEXT NULL,
                  designation TEXT NULL,
                  branch_name TEXT NULL,
                  office_time_policy TEXT NULL,
                  date_of_birth TEXT NULL,
                  date_of_join TEXT NULL,
                  shift_start_date TEXT NULL,
                  shift_code TEXT NULL,
                  weekly_off TEXT NULL,
                  company_name TEXT NULL,
                  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                  updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS IX_employee_master_employee_code_normalized
                ON employee_master (employee_code_normalized)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS machine_user_registry (
                  user_id INTEGER NOT NULL,
                  device_id TEXT NOT NULL DEFAULT '',
                  machine_ip TEXT NOT NULL DEFAULT '',
                  employee_code TEXT NOT NULL,
                  user_name TEXT NULL,
                  enabled INTEGER NOT NULL DEFAULT 1,
                  slot_count INTEGER NOT NULL DEFAULT 1,
                  machine_number INTEGER NOT NULL DEFAULT 1,
                  synced_at TEXT NOT NULL,
                  PRIMARY KEY (user_id, device_id, machine_ip)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS IX_machine_user_registry_employee_code
                ON machine_user_registry (employee_code)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS machine_user_profile (
                  user_id INTEGER NOT NULL,
                  device_id TEXT NOT NULL DEFAULT '',
                  machine_ip TEXT NOT NULL DEFAULT '',
                  employee_code TEXT NOT NULL,
                  user_name TEXT NULL,
                  timezone1 INTEGER NULL,
                  timezone2 INTEGER NULL,
                  group_no INTEGER NULL,
                  privilege INTEGER NULL,
                  enabled INTEGER NULL,
                  card_no_low TEXT NULL,
                  card_no_high TEXT NULL,
                  card_no_combined TEXT NULL,
                  machine_number INTEGER NOT NULL DEFAULT 1,
                  profile_json TEXT NULL,
                  synced_at TEXT NOT NULL,
                  PRIMARY KEY (user_id, device_id, machine_ip)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS machine_user_enrollments (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  device_id TEXT NOT NULL DEFAULT '',
                  machine_ip TEXT NOT NULL DEFAULT '',
                  backup_number INTEGER NOT NULL DEFAULT 0,
                  credential_type TEXT NOT NULL,
                  fp_number INTEGER NULL,
                  privilege INTEGER NULL,
                  template_base64 TEXT NULL,
                  credential_value TEXT NULL,
                  synced_at TEXT NOT NULL,
                  UNIQUE(user_id, device_id, machine_ip, credential_type, backup_number, fp_number)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS IX_machine_user_enrollments_user
                ON machine_user_enrollments (user_id, device_id, machine_ip)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS devices (
                  device_id TEXT PRIMARY KEY,
                  device_name TEXT NULL,
                  site_id TEXT NULL,
                  ip TEXT NOT NULL,
                  port INTEGER NOT NULL DEFAULT 5005,
                  timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
                  is_active INTEGER NOT NULL DEFAULT 1,
                  sdk_protocol TEXT NOT NULL DEFAULT 'sbxpc_tcp',
                  machine_password TEXT NULL,
                  machine_number INTEGER NOT NULL DEFAULT 1,
                  middleware_public_url TEXT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  last_seen_at TEXT NULL,
                  last_sync_at TEXT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS device_capabilities (
                  machine_ip TEXT NOT NULL,
                  machine_port INTEGER NOT NULL DEFAULT 5005,
                  device_id TEXT NOT NULL DEFAULT '',
                  detected_machine_number INTEGER NOT NULL DEFAULT 1,
                  model_name TEXT NULL,
                  manufacturer TEXT NULL,
                  firmware TEXT NULL,
                  adapter_profile TEXT NOT NULL DEFAULT 'unknown',
                  user_count INTEGER NULL,
                  fp_count INTEGER NULL,
                  face_count INTEGER NULL,
                  capabilities_json TEXT NULL,
                  detected_at TEXT NOT NULL,
                  PRIMARY KEY (machine_ip, machine_port, device_id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS IX_device_capabilities_device_id
                ON device_capabilities (device_id)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS agent_nodes (
                  agent_id TEXT PRIMARY KEY,
                  site_id TEXT NULL,
                  version TEXT NULL,
                  host_name TEXT NULL,
                  local_ip TEXT NULL,
                  status TEXT NOT NULL DEFAULT 'ONLINE',
                  last_seen_at TEXT NOT NULL,
                  details_json TEXT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS attendance_events (
                  event_id TEXT PRIMARY KEY,
                  idempotency_key TEXT NOT NULL UNIQUE,
                  agent_id TEXT NULL,
                  device_id TEXT NOT NULL,
                  device_ip TEXT NULL,
                  employee_code TEXT NOT NULL,
                  machine_user_id TEXT NULL,
                  timestamp_local TEXT NOT NULL,
                  timestamp_utc TEXT NOT NULL,
                  timezone TEXT NOT NULL,
                  verification_mode TEXT NULL,
                  source TEXT NOT NULL,
                  raw_payload TEXT NULL,
                  created_at TEXT NOT NULL,
                  synced_at TEXT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS IX_attendance_events_device_time
                ON attendance_events (device_id, timestamp_utc)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS command_jobs (
                  command_id TEXT PRIMARY KEY,
                  request_id TEXT NOT NULL UNIQUE,
                  device_id TEXT NOT NULL,
                  command_type TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'PENDING',
                  priority INTEGER NOT NULL DEFAULT 100,
                  retry_count INTEGER NOT NULL DEFAULT 0,
                  next_attempt_at TEXT NOT NULL,
                  claimed_at TEXT NULL,
                  claimed_by TEXT NULL,
                  completed_at TEXT NULL,
                  error_code TEXT NULL,
                  last_error TEXT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS IX_command_jobs_queue
                ON command_jobs (status, next_attempt_at, priority, created_at)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS command_history (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  command_id TEXT NOT NULL,
                  attempt_no INTEGER NOT NULL,
                  agent_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  error_code TEXT NULL,
                  error_message TEXT NULL,
                  result_json TEXT NULL,
                  started_at TEXT NOT NULL,
                  finished_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS webhook_subscriptions (
                  subscription_id TEXT PRIMARY KEY,
                  event_type TEXT NOT NULL,
                  target_url TEXT NOT NULL,
                  is_active INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                  delivery_id TEXT PRIMARY KEY,
                  subscription_id TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  event_id TEXT NOT NULL,
                  target_url TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'PENDING',
                  attempt_no INTEGER NOT NULL DEFAULT 0,
                  next_attempt_at TEXT NOT NULL,
                  last_status_code INTEGER NULL,
                  last_error TEXT NULL,
                  last_response TEXT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS IX_webhook_deliveries_queue
                ON webhook_deliveries (status, next_attempt_at)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS dead_letter_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  entity_type TEXT NOT NULL,
                  entity_id TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  payload_json TEXT NULL,
                  created_at TEXT NOT NULL
                )
                """
            )
        )
        if engine.dialect.name == "sqlite":
            from attendance_relay.db_migrate import migrate_local_schema

            migrate_local_schema(conn)
