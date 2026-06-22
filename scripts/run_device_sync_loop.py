#!/usr/bin/env python3
"""Poll T501 for new punches and import into local DB (worker forwards to ERP)."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Background device log sync loop.")
    parser.add_argument("--config", default="configs/dev.yaml")
    parser.add_argument("--interval", type=float, default=30.0, help="Seconds between pulls.")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    pull_script = ROOT / "scripts" / "pull_device_logs_to_db.py"
    python = sys.executable
    print(f"device_sync_loop started interval={args.interval}s config={args.config}", flush=True)

    while True:
        try:
            proc = subprocess.run(
                [python, str(pull_script), "--config", args.config, "--incremental", "--limit", str(args.limit)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.stdout.strip():
                print(proc.stdout.strip(), flush=True)
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "unknown error").strip()
                print(f"device_sync_pull_failed: {err}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"device_sync_loop_error: {exc}", flush=True)
        time.sleep(max(5.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
