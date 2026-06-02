#!/usr/bin/env python3
"""ランキング書籍登録ワーカー — 常駐プロセスとして定期実行する"""
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / 'storage' / 'register_worker.log'
PID_PATH = ROOT / 'storage' / 'register_worker.pid'
API_BASE = 'http://localhost:8081'

INTERVAL = int(os.environ.get('REGISTER_WORKER_INTERVAL', str(6 * 3600)))

TAB_URLS = {
    '健康・医療':         'https://aixec.exbridge.jp/books_ranking.php',
    '医学':               'https://aixec.exbridge.jp/books_ranking.php',
    '漢方・東洋医学':     'https://aixec.exbridge.jp/books_ranking.php',
    '看護':               'https://aixec.exbridge.jp/books_ranking.php',
    '介護・認知症':       'https://aixec.exbridge.jp/books_ranking.php',
    'リハビリ':           'https://aixec.exbridge.jp/books_ranking.php',
    'AI・テクノロジー':   'https://aixec.exbridge.jp/books_ranking.php?tab=ai',
    'Web3・暗号資産':     'https://aixec.exbridge.jp/books_ranking.php?tab=web3',
    'プログラミング・IT': 'https://aixec.exbridge.jp/books_ranking.php?tab=programming',
}

_running = True


def handle_signal(signum, frame):
    global _running
    log(f'シグナル {signum} 受信 — 次のループ後に終了します')
    _running = False


def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    with LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(line + '\n')


def post_to_sns(content: str):
    data = json.dumps({'author': 'register', 'content': content}, ensure_ascii=False).encode('utf-8')
    req = Request(API_BASE + '/posts', data=data,
                  headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode('utf-8')).get('item', {}).get('id')


def run_once():
    from register_ranking_books import run_all_tabs
    log('--- ランキング書籍チェック開始 ---')
    new_by_tab = run_all_tabs()
    total = sum(len(v) for v in new_by_tab.values())
    log(f'--- 完了: 新規 {total}件 ---')

    for label, titles in new_by_tab.items():
        tab_url = TAB_URLS.get(label, 'https://aixec.exbridge.jp/books_ranking.php')
        body = ''.join(f'・{t}\n' for t in titles)
        content = (
            f'📚 新着書籍 登録完了 — {label} カテゴリ（{len(titles)}件）\n\n'
            f'ランキング巡回ワーカーが以下の書籍を自動登録しました。\n\n'
            f'{body}\n'
            f'{tab_url}'
        )
        try:
            pid = post_to_sns(content)
            log(f'sns.php 投稿完了 [{label}] (id={pid})')
        except Exception as e:
            log(f'sns.php 投稿エラー [{label}]: {e}')

    return total


def main():
    global _running

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    PID_PATH.write_text(str(os.getpid()))
    log(f'register_worker 起動 (PID={os.getpid()}, interval={INTERVAL}s)')

    try:
        while _running:
            try:
                run_once()
            except Exception as e:
                log(f'run_once 例外: {e}')

            if not _running:
                break

            log(f'次回実行まで {INTERVAL}秒 待機...')
            waited = 0
            while _running and waited < INTERVAL:
                time.sleep(min(10, INTERVAL - waited))
                waited += 10
    finally:
        PID_PATH.unlink(missing_ok=True)
        log('register_worker 終了')


if __name__ == '__main__':
    main()
