#!/usr/bin/env python3
"""楽天市場商品登録ワーカー — 書籍以外の楽天市場ジャンルを定期巡回する。"""
import json
import argparse
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "storage" / "register_market_worker.log"
PID_PATH = ROOT / "storage" / "register_market_worker.pid"
API_BASE = "http://localhost:8081"

INTERVAL = int(os.environ.get("REGISTER_MARKET_WORKER_INTERVAL", str(6 * 3600)))
HITS = int(os.environ.get("REGISTER_MARKET_WORKER_HITS", "10"))
DELAY = float(os.environ.get("REGISTER_MARKET_WORKER_DELAY", os.environ.get("RAKUTEN_MARKET_IMPORT_DELAY", "6.0")))
UPLOAD_IMAGES = os.environ.get("REGISTER_MARKET_WORKER_UPLOAD_IMAGES", "").lower() == "true"

CATEGORY_URLS = {
    "トレカ": "https://aixec.exbridge.jp/market_ranking.php?tab=trading_cards",
    "美容・コスメ": "https://aixec.exbridge.jp/market_ranking.php?tab=beauty_cosmetics",
    "サプリ": "https://aixec.exbridge.jp/market_ranking.php?tab=supplements",
    "AI PC・ゲーミング": "https://aixec.exbridge.jp/market_ranking.php?tab=ai_pc_gaming",
    "型番商品・工具機器": "https://aixec.exbridge.jp/market_ranking.php?tab=model_number_products",
}

_running = True


def handle_signal(signum, frame):
    global _running
    log("シグナル %s 受信 — 次のループ後に終了します" % signum)
    _running = False


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "[%s] %s" % (ts, msg)
    print(line, flush=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def post_to_sns(content):
    data = json.dumps({"author": "register", "content": content}, ensure_ascii=False).encode("utf-8")
    req = Request(API_BASE + "/posts", data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode("utf-8")).get("item", {}).get("id")


def report_worker(status, items, note=""):
    try:
        payload = json.dumps({
            "name": "aixec-register-market-worker-enqueue",
            "status": status,
            "items": items,
            "note": note,
        }).encode()
        req = Request(API_BASE + "/worker/report", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        urlopen(req, timeout=10)
    except Exception as exc:
        log("worker/report エラー: %s" % exc)


def run_once(dry_run=False):
    sys.path.insert(0, str(ROOT / "scripts"))
    import import_rakuten_market_products as market_import

    log("--- 楽天市場商品チェック開始 dry_run=%s ---" % dry_run)
    report_worker("running", 0, "register_market_worker running dry_run=%s" % str(dry_run).lower())
    new_by_category = market_import.run_categories(hits=HITS, delay=DELAY, upload_images=UPLOAD_IMAGES, dry_run=dry_run)
    stats = getattr(market_import, "LAST_RUN_STATS", {}) or {}
    total = sum(len(v) for v in new_by_category.values())
    updated = int(stats.get("updated") or 0)
    skipped = int(stats.get("skipped") or 0)
    log("--- 完了: 新規 %d件 ---" % total)
    report_worker(
        "ok",
        total,
        "register_market_worker complete books=0 market=%d created=%d updated=%d skipped=%d dry_run=%s"
        % (total, total, updated, skipped, str(dry_run).lower()),
    )

    if not dry_run:
        for label, names in new_by_category.items():
            if not names:
                continue
            url = CATEGORY_URLS.get(label, "https://aixec.exbridge.jp/market_ranking.php")
            body = "".join("・%s\n" % name for name in names[:10])
            more = "\nほか%d件\n" % (len(names) - 10) if len(names) > 10 else ""
            content = (
                "🛒 楽天市場商品 登録完了 — %s（%d件）\n\n"
                "ランキング巡回ワーカーが、AIxECに未登録だった楽天市場商品を自動登録しました。\n\n"
                "%s%s\n%s"
            ) % (label, len(names), body, more, url)
            try:
                post_id = post_to_sns(content)
                log("sns.php 投稿完了 [%s] (id=%s)" % (label, post_id))
            except Exception as exc:
                log("sns.php 投稿エラー [%s]: %s" % (label, exc))

    return total


def main():
    global _running
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()))
    log("register_market_worker 起動 (PID=%s, once=%s, dry_run=%s, interval=%ss, hits=%s, delay=%ss)" % (os.getpid(), args.once, args.dry_run, INTERVAL, HITS, DELAY))

    try:
        if args.once:
            try:
                run_once(dry_run=args.dry_run)
            except Exception as exc:
                log("run_once 例外: %s" % exc)
                report_worker("down", 0, "error=%s" % exc)
                raise
            return
        while _running:
            try:
                run_once(dry_run=args.dry_run)
            except Exception as exc:
                log("run_once 例外: %s" % exc)

            if not _running:
                break
            log("次回実行まで %d秒 待機..." % INTERVAL)
            waited = 0
            while _running and waited < INTERVAL:
                time.sleep(min(10, INTERVAL - waited))
                waited += 10
    finally:
        try:
            PID_PATH.unlink()
        except FileNotFoundError:
            pass
        log("register_market_worker 終了")


if __name__ == "__main__":
    main()
