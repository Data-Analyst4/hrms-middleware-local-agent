from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from attendance_relay.logging_utils import configure_logging, log_event
from attendance_relay.outbound_client import OutboundClient
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import Settings
from attendance_relay.time_utils import format_datetime, now_local


LOGGER = logging.getLogger("attendance_relay.worker")


class RelayWorker:
    def __init__(self, *, settings: Settings, repo: AttendanceRepository, outbound: OutboundClient) -> None:
        self.settings = settings
        self.repo = repo
        self.outbound = outbound
        self.health_file = Path(settings.worker_health_file)
        self.health_file.parent.mkdir(parents=True, exist_ok=True)
        self._last_failed_replay_at: datetime | None = None

    def run_forever(self) -> None:
        configure_logging(self.settings.log_level)
        loop_errors = 0
        log_event(LOGGER, "info", "worker_started", outbound_url=self.settings.outbound_url)
        try:
            while True:
                try:
                    processed = self.run_once()
                    loop_errors = 0
                    if processed == 0:
                        time.sleep(self.settings.outbox_poll_seconds)
                except Exception as exc:  # noqa: BLE001
                    loop_errors += 1
                    log_event(
                        LOGGER,
                        "error",
                        "worker_loop_error",
                        error=f"{type(exc).__name__}: {exc}",
                        loop_errors=loop_errors,
                    )
                    if loop_errors >= self.settings.worker_max_loop_errors:
                        if self.settings.worker_fatal_on_max_loop_errors:
                            raise RuntimeError("worker exceeded maximum loop errors") from exc
                        log_event(
                            LOGGER,
                            "error",
                            "worker_loop_error_limit_reached_continuing",
                            loop_errors=loop_errors,
                        )
                        loop_errors = 0
                    time.sleep(self.settings.outbox_poll_seconds)
        finally:
            self.outbound.close()

    def run_once(self) -> int:
        now = now_local(self.settings.tz_name)
        self._maybe_replay_failed(now)
        batch = self.repo.claim_outbox_batch(
            limit=self.settings.outbox_batch_size,
            now=now,
            lease_seconds=self.settings.processing_lease_seconds,
        )
        if not batch:
            self._write_health(last_processed=0)
            return 0

        sent = 0
        failed = 0
        for row in batch:
            payload = self._build_outbound_payload(row)
            attempt = row.attempt_count + 1
            result = self.outbound.send(row, payload_override=payload)
            current_now = now_local(self.settings.tz_name)
            if result.ok:
                self.repo.mark_sent(
                    outbox_id=row.id,
                    response_code=result.status_code,
                    response_body=result.response_text,
                    now=current_now,
                )
                sent += 1
                log_event(
                    LOGGER,
                    "info",
                    "outbox_sent",
                    outbox_id=row.id,
                    employee_code=row.employee_code,
                    attempt=attempt,
                    status_code=result.status_code,
                )
                continue

            next_attempt = (
                None
                if attempt >= self.settings.max_retries
                else current_now + timedelta(seconds=_compute_backoff_seconds(self.settings, attempt))
            )
            self.repo.mark_failed(
                outbox_id=row.id,
                attempt_count=attempt,
                error_message=result.error or "unknown error",
                next_attempt_at=next_attempt,
                now=current_now,
                max_retries=self.settings.max_retries,
            )
            failed += 1
            log_event(
                LOGGER,
                "warning",
                "outbox_send_failed",
                outbox_id=row.id,
                employee_code=row.employee_code,
                attempt=attempt,
                next_attempt_at=(format_datetime(next_attempt) if next_attempt else None),
                error=result.error,
                status_code=result.status_code,
            )

        self._write_health(last_processed=len(batch), sent=sent, failed=failed)
        return len(batch)

    def _maybe_replay_failed(self, now: datetime) -> None:
        if not self.settings.failed_outbox_replay_enabled:
            return
        interval = max(60, int(self.settings.failed_outbox_replay_interval_seconds))
        if self._last_failed_replay_at is not None:
            elapsed = (now - self._last_failed_replay_at).total_seconds()
            if elapsed < interval:
                return
        replayed = self.repo.replay_failed_outbox(
            limit=self.settings.failed_outbox_replay_batch_size,
            now=now,
        )
        self._last_failed_replay_at = now
        if replayed:
            log_event(LOGGER, "warning", "outbox_failed_replayed", count=replayed)

    def _build_outbound_payload(self, row: Any) -> dict[str, Any]:
        master = self.repo.find_employee_master(row.employee_code)
        employee_code = master.get("employee_code") if master else row.employee_code
        raw_preview = getattr(row, "raw_preview", None)
        enroll_no = employee_code
        if raw_preview and "user_id" in str(raw_preview):
            try:
                start = str(raw_preview).find("{")
                end = str(raw_preview).rfind("}")
                if start >= 0 and end > start:
                    import json as _json

                    parsed = _json.loads(str(raw_preview)[start : end + 1])
                    uid = str(parsed.get("user_id") or "").strip()
                    if uid:
                        enroll_no = uid.lstrip("0") or uid
            except Exception:  # noqa: BLE001
                pass

        branch_code = self.settings.outbound_site_code or (master.get("branch_name") if master else "") or ""
        payload: dict[str, Any] = {
            "employee_code_raw": employee_code,
            "enroll_no": enroll_no,
            "employee_code": employee_code,
            "log_datetime": format_datetime(row.log_datetime),
            "log_time": row.log_time,
            "downloaded_at": format_datetime(row.downloaded_at),
            "device_sn": row.device_sn,
            "branch_code": branch_code,
            "device_id": self.settings.outbound_device_id or row.device_sn,
            "raw_preview": raw_preview,
        }

        if raw_preview and "io_time" in str(raw_preview):
            try:
                start = str(raw_preview).find("{")
                end = str(raw_preview).rfind("}")
                if start >= 0 and end > start:
                    import json as _json

                    parsed = _json.loads(str(raw_preview)[start : end + 1])
                    payload["io_time"] = str(parsed.get("io_time") or "")
                    payload["raw_payload"] = parsed
            except Exception:  # noqa: BLE001
                payload["raw_payload"] = {"preview": str(raw_preview)[:500]}
        else:
            payload["raw_payload"] = {}

        if not self.settings.outbound_include_extended_fields:
            return payload

        payload["employee_name"] = (master.get("employee_name") if master else "") or ""
        return payload

    def _write_health(self, *, last_processed: int, sent: int = 0, failed: int = 0) -> None:
        payload = {
            "updated_at": format_datetime(now_local(self.settings.tz_name)),
            "last_processed": last_processed,
            "sent": sent,
            "failed": failed,
            "counts": self.repo.get_outbox_counts(),
        }
        self.health_file.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


def _compute_backoff_seconds(settings: Settings, attempt: int) -> float:
    base = settings.backoff_base_seconds
    max_delay = settings.backoff_max_seconds
    jitter = settings.backoff_jitter_seconds
    exp = min(max_delay, base * (2 ** max(attempt - 1, 0)))
    return exp + random.uniform(0.0, jitter)
