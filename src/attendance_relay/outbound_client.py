from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

import time

import httpx

from attendance_relay.models import OutboxRecord
from attendance_relay.time_utils import format_datetime


@dataclass(slots=True)
class SendResult:
    ok: bool
    status_code: int | None
    response_text: str | None
    error: str | None


def _build_hmac_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _extract_enroll_no(employee_code: str, raw_preview: str | None) -> str:
    if raw_preview:
        start = raw_preview.find("{")
        end = raw_preview.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(raw_preview[start : end + 1])
                user_id = str(payload.get("user_id") or "").strip()
                if user_id:
                    digits = user_id.lstrip("0") or user_id
                    return digits
            except json.JSONDecodeError:
                pass
    code = str(employee_code or "").strip()
    return code.lstrip("0") or code


_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


def _is_transient_send_result(result: SendResult) -> bool:
    if result.ok:
        return False
    if result.status_code is not None and result.status_code in _RETRYABLE_STATUS:
        return True
    if result.error and any(
        token in result.error
        for token in ("ConnectError", "ConnectTimeout", "ReadTimeout", "TimeoutException", "RemoteProtocolError")
    ):
        return True
    return False


class OutboundClient:
    def __init__(
        self,
        *,
        url: str,
        api_key_header: str,
        api_key: str,
        timeout_seconds: float,
        verify_tls: bool,
        enforce_https: bool,
        enforce_post: bool,
        method: str = "POST",
        site_code: str = "",
        device_id: str = "",
        hmac_secret: str = "",
        http_retries: int = 0,
    ) -> None:
        self.url = url
        self.method = method.upper()
        self.api_key_header = api_key_header
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.verify_tls = verify_tls
        self.enforce_https = enforce_https
        self.enforce_post = enforce_post
        self.site_code = site_code.strip()
        self.device_id = device_id.strip()
        self.hmac_secret = hmac_secret.strip()
        self.http_retries = max(0, int(http_retries))
        self._validate_policy()
        self.client = httpx.Client(timeout=self.timeout_seconds, verify=self.verify_tls)

    def close(self) -> None:
        self.client.close()

    def send(self, record: OutboxRecord, payload_override: dict[str, Any] | None = None) -> SendResult:
        payload = payload_override or {
            "employee_code": record.employee_code,
            "log_datetime": format_datetime(record.log_datetime),
            "log_time": record.log_time,
            "downloaded_at": format_datetime(record.downloaded_at),
            "device_sn": record.device_sn,
        }
        body_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            self.api_key_header: self.api_key,
        }
        enroll = str(payload.get("enroll_no") or _extract_enroll_no(record.employee_code, payload.get("raw_preview")))
        io_time = str(payload.get("io_time") or "").replace("-", "").replace(":", "").replace(" ", "")
        if not io_time and payload.get("log_datetime"):
            io_time = str(payload["log_datetime"]).replace("-", "").replace(":", "").replace(" ", "")[:14]
        idempotency = f"{record.device_sn}:{enroll}:{io_time or record.log_time}"
        headers["X-Idempotency-Key"] = idempotency
        if self.site_code:
            headers["X-Site-Code"] = self.site_code
        if self.device_id:
            headers["X-Device-Id"] = self.device_id
        if self.hmac_secret:
            headers["X-Middleware-Signature"] = _build_hmac_signature(self.hmac_secret, body_bytes)
        last_result: SendResult | None = None
        attempts = self.http_retries + 1
        for attempt in range(attempts):
            last_result = self._send_once(body_bytes=body_bytes, headers=headers)
            if last_result.ok or not _is_transient_send_result(last_result):
                return last_result
            if attempt < attempts - 1:
                time.sleep(min(2.0 ** attempt, 8.0))
        assert last_result is not None
        return last_result

    def _send_once(self, *, body_bytes: bytes, headers: dict[str, str]) -> SendResult:
        try:
            response = self.client.request(self.method, self.url, content=body_bytes, headers=headers)
            if 200 <= response.status_code < 300:
                return SendResult(ok=True, status_code=response.status_code, response_text=response.text[:1000], error=None)
            return SendResult(
                ok=False,
                status_code=response.status_code,
                response_text=response.text[:1000],
                error=f"Non-2xx response: {response.status_code}",
            )
        except Exception as exc:  # noqa: BLE001
            return SendResult(ok=False, status_code=None, response_text=None, error=f"{type(exc).__name__}: {exc}")

    def _validate_policy(self) -> None:
        if self.enforce_https and not self.url.lower().startswith("https://"):
            raise ValueError("Outbound URL must be HTTPS.")
        if self.enforce_post and self.method != "POST":
            raise ValueError("Outbound method must be POST.")
