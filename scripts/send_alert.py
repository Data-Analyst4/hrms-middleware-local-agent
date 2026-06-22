"""Send one middleware failure alert (used by supervisor and manual tests)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from attendance_relay.alert_notifier import send_alert  # noqa: E402
from attendance_relay.settings import load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a configured failure alert.")
    parser.add_argument("--config", default=None, help="Path to YAML config.")
    parser.add_argument("--event", required=True, help="Alert event name.")
    parser.add_argument("--title", required=True, help="Short alert title.")
    parser.add_argument("--message", required=True, help="Alert body.")
    parser.add_argument("--context-json", default="{}", help="Optional JSON object with extra fields.")
    args = parser.parse_args()

    settings = load_settings(args.config)
    try:
        context = json.loads(args.context_json)
    except json.JSONDecodeError as exc:
        print(f"Invalid --context-json: {exc}", file=sys.stderr)
        return 2
    if not isinstance(context, dict):
        print("--context-json must be a JSON object", file=sys.stderr)
        return 2

    ok = send_alert(
        settings,
        event=args.event,
        title=args.title,
        message=args.message,
        **{str(k): v for k, v in context.items()},
    )
    print("sent" if ok else "skipped_or_failed")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
