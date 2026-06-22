from __future__ import annotations

from attendance_relay.machine_admin import compute_available_user_ids


def test_compute_available_user_ids_fills_gaps_first() -> None:
    result = compute_available_user_ids([2, 3, 5], limit=3)
    assert result["available_ids"] == [1, 4, 6]
    assert result["suggested_next"] == 6
    assert result["used_count"] == 3


def test_compute_available_user_ids_empty_machine() -> None:
    result = compute_available_user_ids([], limit=5)
    assert result["available_ids"] == [1, 2, 3, 4, 5]
    assert result["suggested_next"] == 1


def test_compute_available_user_ids_suggested_skips_used_tail() -> None:
    result = compute_available_user_ids([1, 2, 3], limit=2)
    assert result["suggested_next"] == 4
    assert result["max_used_id"] == 3
