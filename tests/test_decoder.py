from datetime import datetime

from attendance_relay.decoder import decode_machine_payload


def test_decode_payload_from_key_values() -> None:
    body = b"user_id=E1023\tio_time=20260501103005\tdev_id=SN-ABCD\n"
    punch = decode_machine_payload(raw_body=body, downloaded_at=datetime(2026, 5, 1, 10, 30, 6))
    assert punch.employee_code == "E1023"
    assert punch.device_sn == "SN-ABCD"
    assert punch.log_time == "10:30:05"
    assert punch.log_datetime.strftime("%Y-%m-%d %H:%M:%S") == "2026-05-01 10:30:05"


def test_decode_fk_web_json_with_header_dev_id() -> None:
    body = b'{"user_id":"167","verify_mode":1,"io_mode":0,"io_time":"20260614220000"}'
    punch = decode_machine_payload(
        raw_body=body,
        downloaded_at=datetime(2026, 6, 14, 22, 0, 1),
        device_sn_override="2",
    )
    assert punch.employee_code == "167"
    assert punch.device_sn == "2"
    assert punch.log_datetime.strftime("%Y-%m-%d %H:%M:%S") == "2026-06-14 22:00:00"
