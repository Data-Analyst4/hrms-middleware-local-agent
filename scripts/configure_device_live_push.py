#!/usr/bin/env python3
"""Configure T501/M50 log server for realtime network push to FK listener."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from attendance_relay.live_push import check_live_push, ensure_live_push
from attendance_relay.settings import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure biometric device live attendance push.")
    parser.add_argument("--config", default="configs/dev.yaml")
    parser.add_argument("--server-ip", default="", help="Middleware PC LAN IP (default: auto-detect).")
    parser.add_argument("--server-port", type=int, default=0, help="FK listener port (default: fk_web_listener_port).")
    parser.add_argument("--dry-run", action="store_true", help="Read settings only; do not write.")
    parser.add_argument("--verify", action="store_true", help="Verify device push target matches this PC; exit 1 on drift.")
    parser.add_argument("--fix-if-needed", action="store_true", help="Reconfigure device only when drift is detected.")
    args = parser.parse_args()

    settings = load_settings(args.config)
    server_ip = (args.server_ip or "").strip() or None
    server_port = int(args.server_port) if args.server_port else None

    if args.verify or args.fix_if_needed:
        status = check_live_push(settings, server_ip=server_ip, server_port=server_port)
        print(json.dumps(status.to_dict(), ensure_ascii=False, indent=2))
        if status.ok:
            return 0
        if args.fix_if_needed and not args.dry_run:
            summary = ensure_live_push(settings, server_ip=server_ip, server_port=server_port)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            recheck = check_live_push(settings, server_ip=server_ip, server_port=server_port)
            return 0 if recheck.ok else 2
        return 1 if args.verify else 2

    summary = ensure_live_push(
        settings,
        server_ip=server_ip,
        server_port=server_port,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
