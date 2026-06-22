#!/usr/bin/env python3
"""Verify or auto-heal biometric device live-push target after LAN IP changes."""
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
    parser = argparse.ArgumentParser(description="Ensure device live push points at this middleware PC.")
    parser.add_argument("--config", default="configs/factory.yaml")
    parser.add_argument("--fix", action="store_true", help="Reconfigure device when drift is detected.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    settings = load_settings(args.config)
    if not settings.live_push_auto_heal_enabled and not args.fix:
        if not args.quiet:
            print(json.dumps({"skipped": True, "reason": "live_push_auto_heal_enabled=false"}, indent=2))
        return 0

    status = check_live_push(settings)
    if status.ok:
        if not args.quiet:
            print(json.dumps({"ok": True, **status.to_dict()}, indent=2))
        return 0

    if not args.fix:
        if not args.quiet:
            print(json.dumps({"ok": False, "action": "run_with_--fix", **status.to_dict()}, indent=2))
        return 1

    summary = ensure_live_push(settings)
    recheck = check_live_push(settings)
    payload = {"healed": recheck.ok, "before": status.to_dict(), "apply": summary, "after": recheck.to_dict()}
    if not args.quiet:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if recheck.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
