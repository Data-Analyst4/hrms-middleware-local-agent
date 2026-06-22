from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from attendance_relay.master_data import normalize_employee_code
from attendance_relay.models import MachinePunch, OutboxRecord
from attendance_relay.time_utils import format_datetime


class AttendanceRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @property
    def is_sqlite(self) -> bool:
        return self.engine.dialect.name == "sqlite"

    def persist_punch(
        self,
        punch: MachinePunch,
        event_hash: str,
        max_retries: int,
        *,
        enqueue_outbound: bool = True,
    ) -> tuple[int, bool]:
        now = format_datetime(punch.downloaded_at)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tbl_realtime_glog (
                      employee_code, log_datetime, log_time, downloaded_at, device_sn,
                      raw_user_id, raw_io_time, source_ip, raw_preview, created_at
                    ) VALUES (
                      :employee_code, :log_datetime, :log_time, :downloaded_at, :device_sn,
                      :raw_user_id, :raw_io_time, :source_ip, :raw_preview, :created_at
                    )
                    """
                ),
                {
                    "employee_code": punch.employee_code,
                    "log_datetime": format_datetime(punch.log_datetime),
                    "log_time": punch.log_time,
                    "downloaded_at": format_datetime(punch.downloaded_at),
                    "device_sn": punch.device_sn,
                    "raw_user_id": punch.raw_user_id,
                    "raw_io_time": punch.raw_io_time,
                    "source_ip": punch.source_ip,
                    "raw_preview": punch.raw_preview,
                    "created_at": now,
                },
            )

            deduped = False
            if enqueue_outbound:
                try:
                    conn.execute(
                        text(
                            """
                            INSERT INTO attendance_outbox (
                              event_hash, employee_code, log_datetime, log_time, downloaded_at, device_sn,
                              status, attempt_count, max_retries, next_attempt_at, created_at, updated_at
                            ) VALUES (
                              :event_hash, :employee_code, :log_datetime, :log_time, :downloaded_at, :device_sn,
                              'PENDING', 0, :max_retries, :next_attempt_at, :created_at, :updated_at
                            )
                            """
                        ),
                        {
                            "event_hash": event_hash,
                            "employee_code": punch.employee_code,
                            "log_datetime": format_datetime(punch.log_datetime),
                            "log_time": punch.log_time,
                            "downloaded_at": format_datetime(punch.downloaded_at),
                            "device_sn": punch.device_sn,
                            "max_retries": max_retries,
                            "next_attempt_at": now,
                            "created_at": now,
                            "updated_at": now,
                        },
                    )
                except IntegrityError:
                    deduped = True

            row = conn.execute(text("SELECT last_insert_rowid() AS id")) if self.is_sqlite else None
            inserted_id = int(row.scalar()) if row is not None else 0
            return inserted_id, deduped

    def claim_outbox_batch(
        self,
        *,
        limit: int,
        now: datetime,
        lease_seconds: int,
    ) -> list[OutboxRecord]:
        now_s = format_datetime(now)
        lease_until = format_datetime(now + timedelta(seconds=lease_seconds))

        if self.is_sqlite:
            return self._claim_sqlite(limit=limit, now_s=now_s, lease_until=lease_until)
        return self._claim_mssql(limit=limit, now_s=now_s, lease_until=lease_until)

    def _claim_sqlite(self, *, limit: int, now_s: str, lease_until: str) -> list[OutboxRecord]:
        with self.engine.begin() as conn:
            eligible_ids = [
                int(row.id)
                for row in conn.execute(
                    text(
                        """
                        SELECT id
                        FROM attendance_outbox
                        WHERE (
                          status = 'PENDING'
                          OR (status = 'PROCESSING' AND lease_until IS NOT NULL AND lease_until < :now_s)
                        )
                        AND attempt_count < max_retries
                        AND next_attempt_at <= :now_s
                        ORDER BY id
                        LIMIT :batch_limit
                        """
                    ),
                    {"now_s": now_s, "batch_limit": limit},
                )
            ]
            if not eligible_ids:
                return []

            for outbox_id in eligible_ids:
                conn.execute(
                    text(
                        """
                        UPDATE attendance_outbox
                        SET status = 'PROCESSING',
                            processing_started_at = :now_s,
                            lease_until = :lease_until,
                            updated_at = :now_s
                        WHERE id = :outbox_id
                        """
                    ),
                    {"now_s": now_s, "lease_until": lease_until, "outbox_id": outbox_id},
                )

            rows: list[OutboxRecord] = []
            for outbox_id in eligible_ids:
                row = conn.execute(
                    text(
                        """
                        SELECT id, event_hash, employee_code, log_datetime, log_time, downloaded_at, device_sn, attempt_count
                        FROM attendance_outbox
                        WHERE id = :outbox_id
                        """
                    ),
                    {"outbox_id": outbox_id},
                ).mappings().first()
                if row:
                    rows.append(_row_to_outbox_record(row))
            return rows

    def _claim_mssql(self, *, limit: int, now_s: str, lease_until: str) -> list[OutboxRecord]:
        query = text(
            f"""
            ;WITH cte AS (
              SELECT TOP ({int(limit)}) *
              FROM attendance_outbox WITH (ROWLOCK, UPDLOCK, READPAST)
              WHERE (
                status = 'PENDING'
                OR (status = 'PROCESSING' AND lease_until IS NOT NULL AND lease_until < :now_s)
              )
              AND attempt_count < max_retries
              AND next_attempt_at <= :now_s
              ORDER BY id
            )
            UPDATE cte
            SET status = 'PROCESSING',
                processing_started_at = :now_s,
                lease_until = :lease_until,
                updated_at = :now_s
            OUTPUT
              INSERTED.id,
              INSERTED.event_hash,
              INSERTED.employee_code,
              INSERTED.log_datetime,
              INSERTED.log_time,
              INSERTED.downloaded_at,
              INSERTED.device_sn,
              INSERTED.attempt_count
            """
        )
        with self.engine.begin() as conn:
            result = conn.execute(query, {"now_s": now_s, "lease_until": lease_until}).mappings().all()
        return [_row_to_outbox_record(row) for row in result]

    def mark_sent(self, *, outbox_id: int, response_code: int | None, response_body: str | None, now: datetime) -> None:
        now_s = format_datetime(now)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE attendance_outbox
                    SET status = 'SENT',
                        sent_at = :sent_at,
                        response_code = :response_code,
                        response_body = :response_body,
                        last_error = NULL,
                        updated_at = :updated_at
                    WHERE id = :outbox_id
                    """
                ),
                {
                    "sent_at": now_s,
                    "response_code": response_code,
                    "response_body": response_body,
                    "updated_at": now_s,
                    "outbox_id": outbox_id,
                },
            )

    def mark_failed(
        self,
        *,
        outbox_id: int,
        attempt_count: int,
        error_message: str,
        next_attempt_at: datetime | None,
        now: datetime,
        max_retries: int,
    ) -> None:
        now_s = format_datetime(now)
        is_final = attempt_count >= max_retries or next_attempt_at is None
        status = "FAILED" if is_final else "PENDING"
        next_s = format_datetime(next_attempt_at) if next_attempt_at else now_s

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE attendance_outbox
                    SET status = :status,
                        attempt_count = :attempt_count,
                        last_error = :last_error,
                        next_attempt_at = :next_attempt_at,
                        lease_until = NULL,
                        updated_at = :updated_at
                    WHERE id = :outbox_id
                    """
                ),
                {
                    "status": status,
                    "attempt_count": attempt_count,
                    "last_error": error_message[:1000],
                    "next_attempt_at": next_s,
                    "updated_at": now_s,
                    "outbox_id": outbox_id,
                },
            )

    def replay_failed_outbox(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> int:
        """Reset FAILED rows to PENDING so they can be delivered after extended ERP outages."""
        now_s = format_datetime(now)
        safe_limit = max(1, min(int(limit), 5000))
        with self.engine.begin() as conn:
            if self.is_sqlite:
                ids = [
                    int(row.id)
                    for row in conn.execute(
                        text(
                            """
                            SELECT id
                            FROM attendance_outbox
                            WHERE status = 'FAILED'
                            ORDER BY id
                            LIMIT :batch_limit
                            """
                        ),
                        {"batch_limit": safe_limit},
                    )
                ]
                if not ids:
                    return 0
                for outbox_id in ids:
                    conn.execute(
                        text(
                            """
                            UPDATE attendance_outbox
                            SET status = 'PENDING',
                                attempt_count = 0,
                                next_attempt_at = :next_attempt_at,
                                lease_until = NULL,
                                last_error = NULL,
                                updated_at = :updated_at
                            WHERE id = :outbox_id
                              AND status = 'FAILED'
                            """
                        ),
                        {
                            "next_attempt_at": now_s,
                            "updated_at": now_s,
                            "outbox_id": outbox_id,
                        },
                    )
                return len(ids)

            result = conn.execute(
                text(
                    f"""
                    ;WITH cte AS (
                      SELECT TOP ({safe_limit}) id
                      FROM attendance_outbox WITH (ROWLOCK, READPAST)
                      WHERE status = 'FAILED'
                      ORDER BY id
                    )
                    UPDATE cte
                    SET status = 'PENDING',
                        attempt_count = 0,
                        next_attempt_at = :next_attempt_at,
                        lease_until = NULL,
                        last_error = NULL,
                        updated_at = :updated_at
                    """
                ),
                {"next_attempt_at": now_s, "updated_at": now_s},
            )
        return int(result.rowcount or 0)

    def get_outbox_counts(self) -> dict[str, int]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM attendance_outbox
                    GROUP BY status
                    """
                )
            ).all()
        counts = {"PENDING": 0, "PROCESSING": 0, "SENT": 0, "FAILED": 0}
        for status, count in rows:
            counts[str(status)] = int(count)
        return counts

    def upsert_employee_master_records(self, records: list[dict[str, str]]) -> dict[str, int]:
        if not records:
            return {"inserted": 0, "updated": 0, "skipped": 0}

        update_stmt = text(
            """
            UPDATE employee_master
            SET employee_code_normalized = :employee_code_normalized,
                employee_name = :employee_name,
                father_name = :father_name,
                card_no = :card_no,
                proximity_card_no = :proximity_card_no,
                email_id = :email_id,
                phone_no = :phone_no,
                department = :department,
                designation = :designation,
                branch_name = :branch_name,
                office_time_policy = :office_time_policy,
                date_of_birth = :date_of_birth,
                date_of_join = :date_of_join,
                shift_start_date = :shift_start_date,
                shift_code = :shift_code,
                weekly_off = :weekly_off,
                company_name = :company_name,
                updated_at = :updated_at
            WHERE employee_code = :employee_code
            """
        )

        insert_stmt = text(
            """
            INSERT INTO employee_master (
              employee_code,
              employee_code_normalized,
              employee_name,
              father_name,
              card_no,
              proximity_card_no,
              email_id,
              phone_no,
              department,
              designation,
              branch_name,
              office_time_policy,
              date_of_birth,
              date_of_join,
              shift_start_date,
              shift_code,
              weekly_off,
              company_name,
              created_at,
              updated_at
            ) VALUES (
              :employee_code,
              :employee_code_normalized,
              :employee_name,
              :father_name,
              :card_no,
              :proximity_card_no,
              :email_id,
              :phone_no,
              :department,
              :designation,
              :branch_name,
              :office_time_policy,
              :date_of_birth,
              :date_of_join,
              :shift_start_date,
              :shift_code,
              :weekly_off,
              :company_name,
              :created_at,
              :updated_at
            )
            """
        )

        inserted = 0
        updated = 0
        skipped = 0
        timestamp = format_datetime(datetime.now().replace(microsecond=0))
        with self.engine.begin() as conn:
            for record in records:
                employee_code = (record.get("employee_code") or "").strip()
                employee_code_normalized = (record.get("employee_code_normalized") or "").strip()
                if not employee_code:
                    skipped += 1
                    continue
                if not employee_code_normalized:
                    employee_code_normalized = normalize_employee_code(employee_code)
                if not employee_code_normalized:
                    skipped += 1
                    continue

                params = {
                    "employee_code": employee_code,
                    "employee_code_normalized": employee_code_normalized,
                    "employee_name": record.get("employee_name"),
                    "father_name": record.get("father_name"),
                    "card_no": record.get("card_no"),
                    "proximity_card_no": record.get("proximity_card_no"),
                    "email_id": record.get("email_id"),
                    "phone_no": record.get("phone_no"),
                    "department": record.get("department"),
                    "designation": record.get("designation"),
                    "branch_name": record.get("branch_name"),
                    "office_time_policy": record.get("office_time_policy"),
                    "date_of_birth": record.get("date_of_birth"),
                    "date_of_join": record.get("date_of_join"),
                    "shift_start_date": record.get("shift_start_date"),
                    "shift_code": record.get("shift_code"),
                    "weekly_off": record.get("weekly_off"),
                    "company_name": record.get("company_name"),
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }

                result = conn.execute(update_stmt, params)
                if int(result.rowcount or 0) > 0:
                    updated += 1
                    continue

                try:
                    conn.execute(insert_stmt, params)
                    inserted += 1
                except IntegrityError:
                    conn.execute(update_stmt, params)
                    updated += 1

        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    def find_employee_master(self, employee_code: str) -> dict[str, Any] | None:
        code = (employee_code or "").strip()
        if not code:
            return None

        normalized = normalize_employee_code(code)
        if self.is_sqlite:
            query = text(
                """
                SELECT
                  employee_code,
                  employee_code_normalized,
                  employee_name,
                  father_name,
                  card_no,
                  proximity_card_no,
                  email_id,
                  phone_no,
                  department,
                  designation,
                  branch_name,
                  office_time_policy,
                  date_of_birth,
                  date_of_join,
                  shift_start_date,
                  shift_code,
                  weekly_off,
                  company_name
                FROM employee_master
                WHERE employee_code = :employee_code
                   OR employee_code_normalized = :normalized
                ORDER BY CASE WHEN employee_code = :employee_code THEN 0 ELSE 1 END
                LIMIT 1
                """
            )
        else:
            query = text(
                """
                SELECT TOP (1)
                  employee_code,
                  employee_code_normalized,
                  employee_name,
                  father_name,
                  card_no,
                  proximity_card_no,
                  email_id,
                  phone_no,
                  department,
                  designation,
                  branch_name,
                  office_time_policy,
                  date_of_birth,
                  date_of_join,
                  shift_start_date,
                  shift_code,
                  weekly_off,
                  company_name
                FROM employee_master
                WHERE employee_code = :employee_code
                   OR employee_code_normalized = :normalized
                ORDER BY CASE WHEN employee_code = :employee_code THEN 0 ELSE 1 END
                """
            )
        with self.engine.begin() as conn:
            row = conn.execute(query, {"employee_code": code, "normalized": normalized}).mappings().first()
        return dict(row) if row else None

    def list_employee_master(
        self,
        *,
        limit: int = 500,
        offset: int = 0,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 5000))
        safe_offset = max(0, int(offset))
        params: dict[str, Any] = {"limit": safe_limit, "offset": safe_offset}
        filters = ""
        if search and str(search).strip():
            params["search"] = f"%{str(search).strip()}%"
            filters = """
              WHERE employee_code LIKE :search
                 OR employee_code_normalized LIKE :search
                 OR employee_name LIKE :search
                 OR department LIKE :search
            """
        query = text(
            f"""
            SELECT
              employee_code,
              employee_code_normalized,
              employee_name,
              father_name,
              card_no,
              proximity_card_no,
              email_id,
              phone_no,
              department,
              designation,
              branch_name,
              office_time_policy,
              date_of_birth,
              date_of_join,
              shift_start_date,
              shift_code,
              weekly_off,
              company_name,
              created_at,
              updated_at
            FROM employee_master
            {filters}
            ORDER BY employee_code
            LIMIT :limit OFFSET :offset
            """
        )
        with self.engine.begin() as conn:
            rows = conn.execute(query, params).mappings().all()
        return [dict(row) for row in rows]

    def count_employee_master(self) -> int:
        with self.engine.begin() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM employee_master")).scalar_one()
        return int(total)

    def count_attendance_events(self) -> int:
        with self.engine.begin() as conn:
            try:
                total = conn.execute(text("SELECT COUNT(*) FROM attendance_events")).scalar_one()
            except Exception:
                return 0
        return int(total)

    def map_machine_user_to_employee(
        self,
        *,
        user_id: int,
        employee_code: str,
        device_id: str,
        user_name: str | None = None,
        overwrite_name: bool = False,
    ) -> dict[str, Any]:
        code = str(employee_code or "").strip()
        if not code:
            raise ValueError("employee_code is required")
        normalized = normalize_employee_code(code)
        registry_rows = self.list_machine_user_registry(device_id=device_id, limit=50000)
        match = next((row for row in registry_rows if int(row.get("user_id", -1)) == user_id), None)
        if not match:
            raise ValueError(f"machine user_id={user_id} not found for device_id={device_id}")

        machine_ip = str(match.get("machine_ip") or "")
        existing = self.find_employee_master(code)
        record = {
            "employee_code": code,
            "employee_name": user_name or str(match.get("user_name") or "").strip() or code,
            "card_no": str(user_id),
        }
        if existing and not overwrite_name and str(existing.get("employee_name") or "").strip():
            record["employee_name"] = str(existing.get("employee_name") or "")

        summary = self.upsert_employee_master_records([record])
        now = format_datetime(datetime.now().replace(microsecond=0))
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE machine_user_registry
                    SET employee_code = :employee_code,
                        user_name = COALESCE(:user_name, user_name),
                        synced_at = :synced_at
                    WHERE user_id = :user_id
                      AND device_id = :device_id
                      AND machine_ip = :machine_ip
                    """
                ),
                {
                    "employee_code": code,
                    "user_name": record.get("employee_name"),
                    "synced_at": now,
                    "user_id": user_id,
                    "device_id": device_id,
                    "machine_ip": machine_ip,
                },
            )
        return {"updated": True, "summary": summary, "employee_code": code, "user_id": user_id}

    def delete_employee_master(self, employee_code: str) -> bool:
        code = (employee_code or "").strip()
        if not code:
            return False
        normalized = normalize_employee_code(code)
        with self.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    DELETE FROM employee_master
                    WHERE employee_code = :employee_code
                       OR employee_code_normalized = :normalized
                    """
                ),
                {"employee_code": code, "normalized": normalized},
            )
        return int(result.rowcount or 0) > 0

    def list_attendance(
        self,
        *,
        limit: int = 500,
        employee_code: str | None = None,
        device_sn: str | None = None,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 5000))
        employee_code_normalized = normalize_employee_code(employee_code or "") if employee_code else None
        since_value = (since or "").strip() or None
        bind_values = {
            "employee_code": employee_code,
            "employee_code_normalized": employee_code_normalized,
            "device_sn": device_sn,
            "since": since_value,
        }
        since_filter = "AND g.log_datetime >= :since" if since_value else ""

        if self.is_sqlite:
            query = text(
                f"""
                SELECT
                    g.id,
                    g.employee_code,
                    g.log_datetime,
                    g.log_time,
                    g.downloaded_at,
                    g.device_sn,
                    g.source_ip,
                    g.created_at,
                    em.employee_name
                FROM tbl_realtime_glog g
                LEFT JOIN employee_master em
                  ON em.employee_code = g.employee_code
                WHERE (
                  :employee_code IS NULL
                  OR g.employee_code = :employee_code
                  OR g.employee_code = :employee_code_normalized
                )
                  AND (:device_sn IS NULL OR g.device_sn = :device_sn)
                  {since_filter}
                ORDER BY g.id DESC
                LIMIT :row_limit
                """
            )
            bind_values["row_limit"] = safe_limit
            with self.engine.begin() as conn:
                rows = conn.execute(query, bind_values).mappings().all()
        else:
            query = text(
                f"""
                SELECT TOP ({safe_limit})
                    g.id,
                    g.employee_code,
                    g.log_datetime,
                    g.log_time,
                    g.downloaded_at,
                    g.device_sn,
                    g.source_ip,
                    g.created_at,
                    em.employee_name
                FROM tbl_realtime_glog g
                LEFT JOIN employee_master em
                  ON em.employee_code = g.employee_code
                WHERE (
                  :employee_code IS NULL
                  OR g.employee_code = :employee_code
                  OR g.employee_code = :employee_code_normalized
                )
                  AND (:device_sn IS NULL OR g.device_sn = :device_sn)
                  {since_filter}
                ORDER BY g.id DESC
                """
            )
            with self.engine.begin() as conn:
                rows = conn.execute(query, bind_values).mappings().all()

        output = [dict(row) for row in rows]
        for row in output:
            if row.get("employee_name"):
                continue
            master = self.find_employee_master(str(row.get("employee_code") or ""))
            if master:
                row["employee_name"] = master.get("employee_name")
        return output

    def import_machine_users_to_db(
        self,
        rows: list[dict[str, Any]],
        *,
        machine_ip: str,
        device_id: str = "",
        machine_number: int = 1,
        overwrite_existing_names: bool = True,
    ) -> dict[str, int]:
        if not rows:
            return {
                "employee_inserted": 0,
                "employee_updated": 0,
                "employee_skipped": 0,
                "registry_inserted": 0,
                "registry_updated": 0,
            }

        employee_update_stmt = text(
            """
            UPDATE employee_master
            SET employee_code_normalized = :employee_code_normalized,
                employee_name = CASE
                  WHEN :overwrite = 1 OR employee_name IS NULL OR TRIM(employee_name) = ''
                  THEN :employee_name
                  ELSE employee_name
                END,
                card_no = CASE
                  WHEN card_no IS NULL OR TRIM(card_no) = ''
                  THEN :card_no
                  ELSE card_no
                END,
                updated_at = :updated_at
            WHERE employee_code = :employee_code
            """
        )
        employee_insert_stmt = text(
            """
            INSERT INTO employee_master (
              employee_code,
              employee_code_normalized,
              employee_name,
              father_name,
              card_no,
              proximity_card_no,
              email_id,
              phone_no,
              department,
              designation,
              branch_name,
              office_time_policy,
              date_of_birth,
              date_of_join,
              shift_start_date,
              shift_code,
              weekly_off,
              company_name,
              created_at,
              updated_at
            ) VALUES (
              :employee_code,
              :employee_code_normalized,
              :employee_name,
              '', '', :card_no, '', '', '',
              '', '', '', '', '', '', '', '', '',
              :created_at,
              :updated_at
            )
            """
        )
        registry_upsert_sqlite = text(
            """
            INSERT INTO machine_user_registry (
              user_id, device_id, machine_ip, employee_code, user_name,
              enabled, slot_count, machine_number, synced_at
            ) VALUES (
              :user_id, :device_id, :machine_ip, :employee_code, :user_name,
              :enabled, :slot_count, :machine_number, :synced_at
            )
            ON CONFLICT(user_id, device_id, machine_ip) DO UPDATE SET
              employee_code = excluded.employee_code,
              user_name = excluded.user_name,
              enabled = excluded.enabled,
              slot_count = excluded.slot_count,
              machine_number = excluded.machine_number,
              synced_at = excluded.synced_at
            """
        )
        registry_update_stmt = text(
            """
            UPDATE machine_user_registry
            SET employee_code = :employee_code,
                user_name = :user_name,
                enabled = :enabled,
                slot_count = :slot_count,
                machine_number = :machine_number,
                synced_at = :synced_at
            WHERE user_id = :user_id
              AND device_id = :device_id
              AND machine_ip = :machine_ip
            """
        )
        registry_insert_stmt = text(
            """
            INSERT INTO machine_user_registry (
              user_id, device_id, machine_ip, employee_code, user_name,
              enabled, slot_count, machine_number, synced_at
            ) VALUES (
              :user_id, :device_id, :machine_ip, :employee_code, :user_name,
              :enabled, :slot_count, :machine_number, :synced_at
            )
            """
        )

        employee_inserted = 0
        employee_updated = 0
        employee_skipped = 0
        registry_inserted = 0
        registry_updated = 0
        timestamp = format_datetime(datetime.now().replace(microsecond=0))
        overwrite_flag = 1 if overwrite_existing_names else 0

        with self.engine.begin() as conn:
            for row in rows:
                user_id = int(row.get("user_id", -1))
                if user_id < 0:
                    employee_skipped += 1
                    continue

                employee_code = str(user_id)
                normalized = normalize_employee_code(employee_code)
                if not normalized:
                    employee_skipped += 1
                    continue

                user_name = str(row.get("user_name") or "").strip() or employee_code
                enabled = 1 if bool(row.get("enabled")) else 0
                slot_count = max(1, int(row.get("slot_count") or 1))

                employee_params = {
                    "employee_code": employee_code,
                    "employee_code_normalized": normalized,
                    "employee_name": user_name,
                    "card_no": employee_code,
                    "overwrite": overwrite_flag,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                result = conn.execute(employee_update_stmt, employee_params)
                if int(result.rowcount or 0) > 0:
                    employee_updated += 1
                else:
                    try:
                        conn.execute(employee_insert_stmt, employee_params)
                        employee_inserted += 1
                    except IntegrityError:
                        conn.execute(employee_update_stmt, employee_params)
                        employee_updated += 1

                registry_params = {
                    "user_id": user_id,
                    "device_id": device_id or "",
                    "machine_ip": machine_ip,
                    "employee_code": employee_code,
                    "user_name": user_name,
                    "enabled": enabled,
                    "slot_count": slot_count,
                    "machine_number": machine_number,
                    "synced_at": timestamp,
                }
                if self.is_sqlite:
                    before = conn.execute(
                        text(
                            """
                            SELECT 1 FROM machine_user_registry
                            WHERE user_id = :user_id AND device_id = :device_id AND machine_ip = :machine_ip
                            """
                        ),
                        registry_params,
                    ).first()
                    conn.execute(registry_upsert_sqlite, registry_params)
                    if before:
                        registry_updated += 1
                    else:
                        registry_inserted += 1
                else:
                    result = conn.execute(registry_update_stmt, registry_params)
                    if int(result.rowcount or 0) > 0:
                        registry_updated += 1
                    else:
                        conn.execute(registry_insert_stmt, registry_params)
                        registry_inserted += 1

        return {
            "employee_inserted": employee_inserted,
            "employee_updated": employee_updated,
            "employee_skipped": employee_skipped,
            "registry_inserted": registry_inserted,
            "registry_updated": registry_updated,
        }

    def list_machine_user_registry(
        self,
        *,
        machine_ip: str | None = None,
        device_id: str | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 50000))
        filters = []
        params: dict[str, Any] = {"limit": safe_limit}
        if machine_ip:
            filters.append("machine_ip = :machine_ip")
            params["machine_ip"] = machine_ip
        if device_id:
            filters.append("device_id = :device_id")
            params["device_id"] = device_id
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = text(
            f"""
            SELECT
              user_id,
              device_id,
              machine_ip,
              employee_code,
              user_name,
              enabled,
              slot_count,
              machine_number,
              synced_at
            FROM machine_user_registry
            {where}
            ORDER BY user_id
            LIMIT :limit
            """
        )
        with self.engine.begin() as conn:
            rows = conn.execute(query, params).mappings().all()
        return [dict(row) for row in rows]

    def store_machine_user_detail(
        self,
        *,
        profile: dict[str, Any],
        enrollments: list[dict[str, Any]],
        machine_ip: str,
        device_id: str = "",
        machine_number: int = 1,
        profile_json: str | None = None,
    ) -> dict[str, Any]:
        user_id = int(profile.get("user_id", -1))
        if user_id < 0:
            raise ValueError("profile.user_id is required")

        employee_code = str(profile.get("employee_code") or user_id).strip()
        timestamp = format_datetime(datetime.now().replace(microsecond=0))
        enabled_value = profile.get("enabled")
        if isinstance(enabled_value, bool):
            enabled_int: int | None = 1 if enabled_value else 0
        elif enabled_value is None:
            enabled_int = None
        else:
            enabled_int = 1 if int(enabled_value) != 0 else 0

        profile_params = {
            "user_id": user_id,
            "device_id": device_id or "",
            "machine_ip": machine_ip,
            "employee_code": employee_code,
            "user_name": profile.get("user_name"),
            "timezone1": profile.get("timezone1"),
            "timezone2": profile.get("timezone2"),
            "group_no": profile.get("group_no"),
            "privilege": profile.get("privilege"),
            "enabled": enabled_int,
            "card_no_low": profile.get("card_no_low"),
            "card_no_high": profile.get("card_no_high"),
            "card_no_combined": profile.get("card_no_combined"),
            "machine_number": machine_number,
            "profile_json": profile_json,
            "synced_at": timestamp,
        }

        profile_upsert_sqlite = text(
            """
            INSERT INTO machine_user_profile (
              user_id, device_id, machine_ip, employee_code, user_name,
              timezone1, timezone2, group_no, privilege, enabled,
              card_no_low, card_no_high, card_no_combined,
              machine_number, profile_json, synced_at
            ) VALUES (
              :user_id, :device_id, :machine_ip, :employee_code, :user_name,
              :timezone1, :timezone2, :group_no, :privilege, :enabled,
              :card_no_low, :card_no_high, :card_no_combined,
              :machine_number, :profile_json, :synced_at
            )
            ON CONFLICT(user_id, device_id, machine_ip) DO UPDATE SET
              employee_code = excluded.employee_code,
              user_name = excluded.user_name,
              timezone1 = excluded.timezone1,
              timezone2 = excluded.timezone2,
              group_no = excluded.group_no,
              privilege = excluded.privilege,
              enabled = excluded.enabled,
              card_no_low = excluded.card_no_low,
              card_no_high = excluded.card_no_high,
              card_no_combined = excluded.card_no_combined,
              machine_number = excluded.machine_number,
              profile_json = excluded.profile_json,
              synced_at = excluded.synced_at
            """
        )
        profile_update_stmt = text(
            """
            UPDATE machine_user_profile
            SET employee_code = :employee_code,
                user_name = :user_name,
                timezone1 = :timezone1,
                timezone2 = :timezone2,
                group_no = :group_no,
                privilege = :privilege,
                enabled = :enabled,
                card_no_low = :card_no_low,
                card_no_high = :card_no_high,
                card_no_combined = :card_no_combined,
                machine_number = :machine_number,
                profile_json = :profile_json,
                synced_at = :synced_at
            WHERE user_id = :user_id AND device_id = :device_id AND machine_ip = :machine_ip
            """
        )
        profile_insert_stmt = text(
            """
            INSERT INTO machine_user_profile (
              user_id, device_id, machine_ip, employee_code, user_name,
              timezone1, timezone2, group_no, privilege, enabled,
              card_no_low, card_no_high, card_no_combined,
              machine_number, profile_json, synced_at
            ) VALUES (
              :user_id, :device_id, :machine_ip, :employee_code, :user_name,
              :timezone1, :timezone2, :group_no, :privilege, :enabled,
              :card_no_low, :card_no_high, :card_no_combined,
              :machine_number, :profile_json, :synced_at
            )
            """
        )

        with self.engine.begin() as conn:
            if self.is_sqlite:
                conn.execute(profile_upsert_sqlite, profile_params)
            else:
                result = conn.execute(profile_update_stmt, profile_params)
                if int(result.rowcount or 0) == 0:
                    conn.execute(profile_insert_stmt, profile_params)

            conn.execute(
                text(
                    """
                    DELETE FROM machine_user_enrollments
                    WHERE user_id = :user_id AND device_id = :device_id AND machine_ip = :machine_ip
                    """
                ),
                {"user_id": user_id, "device_id": device_id or "", "machine_ip": machine_ip},
            )

            enrollment_inserted = 0
            for row in enrollments:
                fp_number = row.get("fp_number")
                conn.execute(
                    text(
                        """
                        INSERT INTO machine_user_enrollments (
                          user_id, device_id, machine_ip, backup_number, credential_type,
                          fp_number, privilege, template_base64, credential_value, synced_at
                        ) VALUES (
                          :user_id, :device_id, :machine_ip, :backup_number, :credential_type,
                          :fp_number, :privilege, :template_base64, :credential_value, :synced_at
                        )
                        """
                    ),
                    {
                        "user_id": user_id,
                        "device_id": device_id or "",
                        "machine_ip": machine_ip,
                        "backup_number": int(row.get("backup_number") or 0),
                        "credential_type": str(row.get("credential_type") or ""),
                        "fp_number": fp_number,
                        "privilege": row.get("privilege"),
                        "template_base64": row.get("template_base64"),
                        "credential_value": row.get("credential_value"),
                        "synced_at": timestamp,
                    },
                )
                enrollment_inserted += 1

        if profile.get("user_name") or profile.get("card_no_combined"):
            self.upsert_employee_master_records(
                [
                    {
                        "employee_code": employee_code,
                        "employee_name": str(profile.get("user_name") or employee_code),
                        "card_no": str(profile.get("card_no_combined") or employee_code),
                    }
                ]
            )

        return {
            "stored": True,
            "profile_upserted": 1,
            "enrollments_inserted": enrollment_inserted,
            "synced_at": timestamp,
        }

    def get_machine_user_detail(
        self,
        user_id: int,
        *,
        machine_ip: str | None = None,
        device_id: str | None = None,
    ) -> dict[str, Any] | None:
        filters = ["user_id = :user_id"]
        params: dict[str, Any] = {"user_id": int(user_id)}
        if machine_ip:
            filters.append("machine_ip = :machine_ip")
            params["machine_ip"] = machine_ip
        if device_id:
            filters.append("device_id = :device_id")
            params["device_id"] = device_id
        where = " AND ".join(filters)

        profile_query = text(
            f"""
            SELECT
              user_id, device_id, machine_ip, employee_code, user_name,
              timezone1, timezone2, group_no, privilege, enabled,
              card_no_low, card_no_high, card_no_combined,
              machine_number, profile_json, synced_at
            FROM machine_user_profile
            WHERE {where}
            ORDER BY synced_at DESC
            LIMIT 1
            """
        )
        with self.engine.begin() as conn:
            profile_row = conn.execute(profile_query, params).mappings().first()
            if not profile_row:
                return None
            profile = dict(profile_row)
            enrollment_params = {
                "user_id": profile["user_id"],
                "device_id": profile["device_id"],
                "machine_ip": profile["machine_ip"],
            }
            enrollment_rows = conn.execute(
                text(
                    """
                    SELECT
                      id, backup_number, credential_type, fp_number, privilege,
                      template_base64, credential_value, synced_at
                    FROM machine_user_enrollments
                    WHERE user_id = :user_id AND device_id = :device_id AND machine_ip = :machine_ip
                    ORDER BY credential_type, backup_number, fp_number
                    """
                ),
                enrollment_params,
            ).mappings().all()

        enrollments = []
        for row in enrollment_rows:
            item = dict(row)
            template = item.get("template_base64")
            if template:
                item["template_size_bytes"] = int(len(template) * 3 / 4)
            enrollments.append(item)

        return {
            "profile": profile,
            "enrollments": enrollments,
            "enrollments_loaded": len(enrollments),
        }

    def upsert_device_capabilities(
        self,
        *,
        machine_ip: str,
        machine_port: int,
        device_id: str,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        now = format_datetime(datetime.now())
        payload = {
            "machine_ip": machine_ip,
            "machine_port": int(machine_port),
            "device_id": device_id or "",
            "detected_machine_number": int(profile.get("detected_machine_number") or profile.get("connection_machine_number") or 1),
            "model_name": profile.get("model_name"),
            "manufacturer": profile.get("manufacturer"),
            "firmware": profile.get("firmware"),
            "adapter_profile": str(profile.get("adapter_profile") or "unknown"),
            "user_count": profile.get("user_count"),
            "fp_count": profile.get("fp_count"),
            "face_count": profile.get("face_count"),
            "capabilities_json": json.dumps(profile, ensure_ascii=False),
            "detected_at": now,
        }
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO device_capabilities (
                      machine_ip, machine_port, device_id, detected_machine_number,
                      model_name, manufacturer, firmware, adapter_profile,
                      user_count, fp_count, face_count, capabilities_json, detected_at
                    ) VALUES (
                      :machine_ip, :machine_port, :device_id, :detected_machine_number,
                      :model_name, :manufacturer, :firmware, :adapter_profile,
                      :user_count, :fp_count, :face_count, :capabilities_json, :detected_at
                    )
                    ON CONFLICT(machine_ip, machine_port, device_id) DO UPDATE SET
                      detected_machine_number = excluded.detected_machine_number,
                      model_name = excluded.model_name,
                      manufacturer = excluded.manufacturer,
                      firmware = excluded.firmware,
                      adapter_profile = excluded.adapter_profile,
                      user_count = excluded.user_count,
                      fp_count = excluded.fp_count,
                      face_count = excluded.face_count,
                      capabilities_json = excluded.capabilities_json,
                      detected_at = excluded.detected_at
                    """
                ),
                payload,
            )
        return payload

    def get_device_capabilities(
        self,
        *,
        machine_ip: str | None = None,
        machine_port: int | None = None,
        device_id: str | None = None,
    ) -> dict[str, Any] | None:
        filters: list[str] = []
        params: dict[str, Any] = {}
        if machine_ip:
            filters.append("machine_ip = :machine_ip")
            params["machine_ip"] = machine_ip
        if machine_port is not None:
            filters.append("machine_port = :machine_port")
            params["machine_port"] = int(machine_port)
        if device_id is not None:
            filters.append("device_id = :device_id")
            params["device_id"] = device_id
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    f"""
                    SELECT
                      machine_ip, machine_port, device_id, detected_machine_number,
                      model_name, manufacturer, firmware, adapter_profile,
                      user_count, fp_count, face_count, capabilities_json, detected_at
                    FROM device_capabilities
                    {where}
                    ORDER BY detected_at DESC
                    LIMIT 1
                    """
                ),
                params,
            ).mappings().first()
        if not row:
            return None
        item = dict(row)
        raw = item.pop("capabilities_json", None)
        if raw:
            try:
                item["profile"] = json.loads(raw)
            except json.JSONDecodeError:
                item["profile"] = None
        return item

    def get_attendance_total(self) -> int:
        with self.engine.begin() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM tbl_realtime_glog")).scalar_one()
        return int(total)


def _row_to_outbox_record(row: Any) -> OutboxRecord:
    return OutboxRecord(
        id=int(row["id"]),
        event_hash=str(row["event_hash"]),
        employee_code=str(row["employee_code"]),
        log_datetime=_safe_parse_datetime(row["log_datetime"]),
        log_time=str(row["log_time"]),
        downloaded_at=_safe_parse_datetime(row["downloaded_at"]),
        device_sn=str(row["device_sn"]),
        attempt_count=int(row["attempt_count"]),
    )


def _safe_parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    if isinstance(value, str):
        return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
    raise TypeError(f"Unexpected datetime value: {value!r}")
