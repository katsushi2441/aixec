#!/usr/bin/env python3
"""Full autonomous AIxEC market registration pipeline.

Hermes runs this script on a schedule. OpenClaw can also call this script as the
execution tool. The pipeline delegates marketing judgment to Claude Code OAuth,
then delegates candidate scoring to Ollama gemma4:e4b through
register_market_task_worker.py.
"""
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
LOG_DIR = ROOT / "storage" / "autonomous"
LOCK_PATH = ROOT / "storage" / "autonomous_market_pipeline.lock"
TASK_PATH = ROOT / "tasks" / "market_task.generated.json"
RESULT_PATH = ROOT / "tasks" / "market_task_result.json"
DRY_RESULT_PATH = ROOT / "tasks" / "market_task_dry_run_result.json"
API_BASE = os.environ.get("AIXEC_API_BASE", "http://127.0.0.1:8081")


def log(msg):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with (LOG_DIR / "autonomous_market_pipeline.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def report_worker(status, items=0, note=""):
    try:
        payload = json.dumps({
            "name": "aixec-market-pipeline-enqueue",
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
        log("worker report: status=%s items=%s note=%s" % (status, items, note))
    except Exception as exc:
        log("worker report failed: %s" % exc)


def run_step(cmd, timeout=None):
    log("run: " + " ".join(cmd))
    log_path = LOG_DIR / "autonomous_market_pipeline.log"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(cmd, cwd=str(ROOT), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    import threading, queue as _queue
    q = _queue.Queue()
    def reader():
        for line in proc.stdout:
            q.put(line)
        q.put(None)
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    import time as _time
    start = _time.time()
    while True:
        try:
            line = q.get(timeout=1)
        except _queue.Empty:
            if timeout and (_time.time() - start) > timeout:
                proc.kill()
                raise RuntimeError("timeout: " + " ".join(cmd))
            continue
        if line is None:
            break
        line = line.rstrip()
        ts = _time.strftime("%Y-%m-%d %H:%M:%S")
        out = "[%s] %s" % (ts, line)
        print(out, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(out + "\n")
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("command failed (%s): %s" % (proc.returncode, " ".join(cmd)))


def acquire_lock():
    if LOCK_PATH.exists():
        try:
            pid = int(LOCK_PATH.read_text().strip())
            os.kill(pid, 0)
            raise SystemExit("pipeline already running pid=%s" % pid)
        except ProcessLookupError:
            pass
        except ValueError:
            pass
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")


def release_lock():
    try:
        if LOCK_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def post_to_sns(task, result):
    label = result.get("label") or task.get("label") or "AIxEC商品"
    group = result.get("group") or task.get("group") or ""
    created = int(result.get("created") or 0)
    updated = int(result.get("updated") or 0)
    items = result.get("items") or []
    names = [str(row.get("name") or "") for row in items[:8] if row.get("name")]
    body = "".join("・%s\n" % name for name in names)
    more = "\nほか%d件\n" % (max(0, created - len(names))) if created > len(names) else ""
    content = (
        "AIxEC 自動商品登録完了 — %s（新規%d件 / 更新%d件）\n\n"
        "OpenClaw + Claude Code OAuth がマーケティング判断を行い、Hermesの自動実行フローで商品候補を作成しました。\n"
        "worker.py が Ollama gemma4:e4b で商品を選定し、AIxECへ登録しました。\n\n"
        "%s%s\n"
        "https://aixec.exbridge.jp/market_ranking.php?tab=%s"
    ) % (label, created, updated, body, more, group)
    payload = json.dumps({"author": "register", "content": content}, ensure_ascii=False).encode("utf-8")
    req = Request(API_BASE.rstrip("/") + "/posts", data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=15) as res:
        data = json.loads(res.read().decode("utf-8"))
    log("AIxSNS posted id=%s" % data.get("item", {}).get("id"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="override task target_count")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-claude", action="store_true", help="reuse existing market_task.generated.json")
    parser.add_argument("--skip-sns", action="store_true")
    parser.add_argument("--hits", type=int, default=30)
    parser.add_argument("--pages", type=int, default=10)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--max-candidates", type=int, default=0)
    parser.add_argument("--ollama-timeout", type=int, default=60)
    parser.add_argument("--min-score", type=int, default=45)
    parser.add_argument("--score-mode", choices=("ollama", "heuristic"), default="ollama")
    args = parser.parse_args()

    acquire_lock()
    try:
        log("pipeline start dry_run=%s" % args.dry_run)
        report_worker("running", 0, "商品登録パイプライン実行中")
        run_step([sys.executable, "scripts/build_marketing_context.py"], timeout=120)
        if not args.skip_claude:
            run_step([sys.executable, "scripts/claude_select_market_task.py"], timeout=900)
        if not TASK_PATH.exists():
            raise RuntimeError("task not found: %s" % TASK_PATH)

        worker_cmd = [
            sys.executable,
            "scripts/register_market_task_worker.py",
            "--task",
            str(TASK_PATH),
            "--hits",
            str(args.hits),
            "--pages",
            str(args.pages),
            "--delay",
            str(args.delay),
            "--batch-size",
            str(args.batch_size),
            "--ollama-timeout",
            str(args.ollama_timeout),
            "--min-score",
            str(args.min_score),
            "--score-mode",
            args.score_mode,
        ]
        if args.limit:
            worker_cmd += ["--limit", str(args.limit)]
        if args.max_candidates:
            worker_cmd += ["--max-candidates", str(args.max_candidates)]
        if args.dry_run:
            worker_cmd.append("--dry-run")
        run_step(worker_cmd, timeout=None)

        task = json.loads(TASK_PATH.read_text(encoding="utf-8"))
        result_path = DRY_RESULT_PATH if args.dry_run else RESULT_PATH
        if not result_path.exists():
            raise RuntimeError("result not found: %s" % result_path)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        registered = int(result.get("registered") or 0)
        created = int(result.get("created") or 0)
        updated = int(result.get("updated") or 0)
        selected = int(result.get("selected") or 0)
        candidates = int(result.get("candidates") or 0)
        label = result.get("label") or task.get("label") or "AIxEC商品"
        report_worker(
            "ok",
            registered,
            "%s 登録%d件 新規%d件 更新%d件 選定%d/%d"
            % (label, registered, created, updated, selected, candidates),
        )
        if not args.dry_run and not args.skip_sns and int(result.get("created") or 0) > 0:
            post_to_sns(task, result)
        else:
            log("SNS skipped dry_run=%s skip_sns=%s created=%s" % (args.dry_run, args.skip_sns, result.get("created")))
        log("pipeline complete")
    except Exception as exc:
        report_worker("down", 0, "エラー: %s" % exc)
        raise
    finally:
        release_lock()


if __name__ == "__main__":
    main()
