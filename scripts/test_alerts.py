"""Send a test alert using configs/factory.yaml + site.local.yaml."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from attendance_relay.alert_notifier import send_alert  # noqa: E402
from attendance_relay.settings import load_settings  # noqa: E402


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Send a test failure alert.")
    parser.add_argument("--config", default="configs/factory.yaml")
    args = parser.parse_args()

    settings = load_settings(args.config)
    if not settings.alerts_enabled:
        print("alerts_enabled is false — enable alerts in configs/site.local.yaml first.")
        return 1

    ok = send_alert(
        settings,
        event="process_restart",
        title="Test alert",
        message="If you received this, failure alerts are configured correctly.",
        process="test_alerts.py",
    )
    print("Test alert sent." if ok else "Test alert failed or was suppressed (cooldown).")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
