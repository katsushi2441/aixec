#!/usr/bin/env python3
"""AIxEC Growth Agent pipeline: observe -> plan -> act -> remember."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "storage" / "growth_agent.lock"
LOG = ROOT / "storage" / "autonomous" / "growth_agent.log"


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(cmd, timeout=None):
    log("run: " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)
    if result.stdout:
        log("stdout:\n" + result.stdout[-4000:])
    if result.stderr:
        log("stderr:\n" + result.stderr[-4000:])
    if result.returncode != 0:
        raise RuntimeError("failed: " + " ".join(cmd))


def acquire():
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip())
            os.kill(pid, 0)
            raise SystemExit("growth agent already running pid=%s" % pid)
        except ProcessLookupError:
            pass
        except ValueError:
            pass
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()), encoding="utf-8")


def release():
    try:
        if LOCK.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK.unlink()
    except FileNotFoundError:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-claude", action="store_true", help="reuse existing growth_plan.generated.json")
    parser.add_argument("--market-limit", type=int, default=20)
    args = parser.parse_args()
    acquire()
    try:
        run([sys.executable, "scripts/build_growth_observation.py"], timeout=180)
        if not args.skip_claude:
            run([sys.executable, "scripts/claude_growth_planner.py"], timeout=900)
        cmd = [sys.executable, "scripts/execute_growth_plan.py", "--market-limit", str(args.market_limit)]
        if args.dry_run:
            cmd.append("--dry-run")
        run(cmd, timeout=None)
        log("growth agent complete")
    finally:
        release()


if __name__ == "__main__":
    main()

