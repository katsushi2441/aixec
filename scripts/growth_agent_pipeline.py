#!/usr/bin/env python3
"""AIxEC Growth Agent pipeline: observe -> plan -> act -> remember."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "storage" / "growth_agent.lock"
LOG = ROOT / "storage" / "autonomous" / "growth_agent.log"
API_BASE = os.environ.get("AIXEC_API_BASE", "http://127.0.0.1:8081")


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


def report_worker(status, items=0, note=""):
    try:
        payload = json.dumps({
            "name": "aixec-growth-agent-enqueue",
            "status": status,
            "items": int(items or 0),
            "note": str(note or "")[:200],
        }, ensure_ascii=False).encode("utf-8")
        req = Request(
            API_BASE.rstrip("/") + "/worker/report",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=10) as res:
            res.read()
    except Exception as exc:
        log("worker report failed: %s" % exc)


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
    parser.add_argument(
        "--allow-market-registration",
        action="store_true",
        help="allow growth plan market_registration actions to run the market pipeline",
    )
    args = parser.parse_args()
    acquire()
    try:
        report_worker("running", 0, "growth agent running")
        run([sys.executable, "scripts/build_growth_observation.py"], timeout=180)
        if not args.skip_claude:
            run([sys.executable, "scripts/claude_growth_planner.py"], timeout=900)
        cmd = [sys.executable, "scripts/execute_growth_plan.py", "--market-limit", str(args.market_limit)]
        if args.dry_run:
            cmd.append("--dry-run")
        if args.allow_market_registration:
            cmd.append("--allow-market-registration")
        run(cmd, timeout=None)
        report_worker("ok", 1, "growth agent complete dry_run=%s" % args.dry_run)
        log("growth agent complete")
    except Exception as exc:
        report_worker("down", 0, "error=%s" % exc)
        raise
    finally:
        release()


if __name__ == "__main__":
    main()
