#!/usr/bin/env python3
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import datetime
import glob
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse, unquote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Worker status store (JSON永続化)
_WORKER_STATUS_PATH = ROOT / "storage" / "worker_status.json"
_MARKET_TASK_RESULT_PATH = ROOT / "tasks" / "market_task_result.json"
_HORIZON_LOCK_PATH = Path("/tmp/horizon_worker_api.pid")
_HORIZON_LOG_PATH = Path("/tmp/horizon_worker.log")
_worker_status_lock = threading.Lock()

def _load_worker_status():
    try:
        if _WORKER_STATUS_PATH.exists():
            return json.loads(_WORKER_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_worker_status(data):
    try:
        _WORKER_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _WORKER_STATUS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

_worker_status = _load_worker_status()

def _require_bearer(headers, data=None):
    token = os.environ.get("AIXEC_MARKET_REGISTER_TOKEN") or os.environ.get("AIXEC_API_TOKEN")
    if not token:
        return True
    auth = headers.get("Authorization", "")
    api_token = headers.get("X-AIXEC-API-TOKEN", "")
    body_token = ""
    if isinstance(data, dict):
        body_token = data.get("api_token") or data.get("token") or ""
    return auth == "Bearer " + token or api_token == token or body_token == token

def _upsert_market_attr(product_id, name, value):
    if value is None or value == "":
        return
    with connect() as conn:
        conn.execute(
            """INSERT INTO product_attributes (product_id, attr_name, attr_value, source, created_at, updated_at)
               VALUES (?, ?, ?, 'market_selection', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
               ON CONFLICT(product_id, attr_name, source)
               DO UPDATE SET attr_value=excluded.attr_value, updated_at=CURRENT_TIMESTAMP""",
            (product_id, name, str(value)),
        )
        conn.commit()

def _market_item_summary(item, product_id=None, action="planned"):
    return {
        "product_id": product_id,
        "action": action,
        "name": item.get("name", ""),
        "item_code": item.get("item_code", ""),
        "jan": item.get("jan", ""),
        "price": item.get("price"),
        "shop_name": item.get("shop_name", ""),
        "keyword": item.get("keyword", ""),
        "score": (item.get("_selection") or {}).get("score"),
        "reason": (item.get("_selection") or {}).get("reason", ""),
    }

def _insert_register_sns_post(result):
    if result.get("created", 0) <= 0:
        return None
    label = result.get("label") or "AIxEC商品"
    created = result.get("created", 0)
    updated = result.get("updated", 0)
    lines = [
        "AIxECに新しい市場選定商品を登録しました。",
        "",
        f"ジャンル: {label}",
        f"新規登録: {created}件 / 更新: {updated}件",
        "",
        "AIxEC",
        "https://aixec.exbridge.jp/",
    ]
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO posts (author, content, created_at, updated_at) VALUES (?, ?, DATETIME('now', 'localtime'), DATETIME('now', 'localtime'))",
            ("register", "\n".join(lines)),
        )
        conn.commit()
        return cur.lastrowid

def _write_market_result(result):
    _MARKET_TASK_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(result)
    payload["saved_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _MARKET_TASK_RESULT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False

def _horizon_running():
    if _HORIZON_LOCK_PATH.exists():
        pid = _HORIZON_LOCK_PATH.read_text(encoding="utf-8").strip()
        if pid and _pid_alive(pid):
            return int(pid)
    return 0

def _find_ssh_agent_sock():
    current = os.environ.get("SSH_AUTH_SOCK", "")
    if current:
        return current
    for sock in glob.glob("/tmp/ssh-*/agent.*"):
        result = subprocess.run(["ssh-add", "-l"], env={**os.environ, "SSH_AUTH_SOCK": sock}, capture_output=True)
        if result.returncode == 0:
            return sock
    return ""

def _start_horizon_worker():
    running = _horizon_running()
    if running:
        return {"started": False, "already_running": True, "pid": running}
    horizon_dir = Path("/home/kojima/exdirect/horizon")
    worker = horizon_dir / "horizon_worker.py"
    if not worker.exists():
        raise FileNotFoundError(str(worker))
    env = dict(os.environ)
    env.setdefault("OLLAMA_API_KEY", "ollama")
    ssh_sock = _find_ssh_agent_sock()
    if ssh_sock:
        env["SSH_AUTH_SOCK"] = ssh_sock
    _HORIZON_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_fh = _HORIZON_LOG_PATH.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        ["python3", str(worker)],
        cwd=str(horizon_dir),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _HORIZON_LOCK_PATH.write_text(str(proc.pid), encoding="utf-8")
    return {"started": True, "already_running": False, "pid": proc.pid, "ssh_agent": bool(ssh_sock)}

def _load_market_pipeline_result():
    if not _MARKET_TASK_RESULT_PATH.exists():
        return {}
    data = json.loads(_MARKET_TASK_RESULT_PATH.read_text(encoding="utf-8"))
    items = data.get("items") or []
    data["items_count"] = len(items)
    data["items"] = items[:10]
    try:
        mtime = _MARKET_TASK_RESULT_PATH.stat().st_mtime
        data["updated_at"] = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        data["updated_at"] = ""
    return data

OLLAMA_SERVERS = [
    {"name": "main",  "url": "https://exbridge.ddns.net/api/tags"},
    {"name": "sub",   "url": "http://192.168.0.3:11434/api/tags"},
    {"name": "sub2",  "url": "http://192.168.0.11:11434/api/tags"},
]

WORKER_SCHEDULE = [
    {"time": "00:05", "name": "url2ai-polymarket-enqueue", "server": "this", "ollama": False},
    {"time": "00:10", "name": "url2ai-oss-enqueue", "server": "this", "ollama": False},
    {"time": "01:30", "name": "aixec-register-market-worker-enqueue", "server": "this", "ollama": False},
    {"time": "01:20", "name": "buzblogger-enqueue", "server": "this", "ollama": False},
    {"time": "03:00", "name": "aixec-growth-agent-enqueue", "server": "this", "ollama": False},
    {"time": "06:05", "name": "url2ai-polymarket-enqueue", "server": "this", "ollama": False},
    {"time": "06:10", "name": "url2ai-oss-enqueue", "server": "this", "ollama": False},
    {"time": "07:30", "name": "aixec-register-market-worker-enqueue", "server": "this", "ollama": False},
    {"time": "07:20", "name": "buzblogger-enqueue", "server": "this", "ollama": False},
    {"time": "08:00", "name": "aixec-market-pipeline-enqueue", "server": "this", "ollama": False},
    {"time": "09:10", "name": "url2ai-finreport-enqueue", "server": "this", "ollama": False},
    {"time": "12:05", "name": "url2ai-polymarket-enqueue", "server": "this", "ollama": False},
    {"time": "12:10", "name": "url2ai-oss-enqueue", "server": "this", "ollama": False},
    {"time": "13:30", "name": "aixec-register-market-worker-enqueue", "server": "this", "ollama": False},
    {"time": "13:20", "name": "buzblogger-enqueue", "server": "this", "ollama": False},
    {"time": "15:00", "name": "aixec-growth-agent-enqueue", "server": "this", "ollama": False},
    {"time": "16:30", "name": "horizon-worker-enqueue", "server": "this", "ollama": False},
    {"time": "18:05", "name": "url2ai-polymarket-enqueue", "server": "this", "ollama": False},
    {"time": "18:10", "name": "url2ai-oss-enqueue", "server": "this", "ollama": False},
    {"time": "19:30", "name": "aixec-register-market-worker-enqueue", "server": "this", "ollama": False},
    {"time": "19:20", "name": "buzblogger-enqueue", "server": "this", "ollama": False},
    {"time": "20:00", "name": "aixec-market-pipeline-enqueue", "server": "this", "ollama": False},
    {"time": "21:10", "name": "url2ai-finreport-enqueue", "server": "this", "ollama": False},
]
DB_PATH = Path(os.environ.get('AIXEC_DB', ROOT / 'storage' / 'aixec.sqlite'))
SCHEMA_PATH = ROOT / 'database' / 'schema.sql'
RAKUTEN_ITEM_SEARCH_ENDPOINT = os.environ.get(
    'RAKUTEN_ITEM_SEARCH_ENDPOINT',
    'https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401'
)
RAKUTEN_BOOKS_SEARCH_ENDPOINT = os.environ.get(
    'RAKUTEN_BOOKS_SEARCH_ENDPOINT',
    'https://openapi.rakuten.co.jp/services/api/BooksBook/Search/20170404'
)


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def migrate():
    with connect() as conn:
        exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'").fetchone()
        if not exists:
            conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        conn.execute('''CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author TEXT DEFAULT 'xb_bittensor',
            content TEXT NOT NULL,
            views INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (DATETIME('now', 'localtime')),
            updated_at TEXT DEFAULT (DATETIME('now', 'localtime'))
        )''')
        columns = [row['name'] for row in conn.execute("PRAGMA table_info(posts)").fetchall()]
        if 'author' not in columns:
            conn.execute("ALTER TABLE posts ADD COLUMN author TEXT DEFAULT 'xb_bittensor'")
            conn.execute("UPDATE posts SET author = 'xb_bittensor' WHERE author IS NULL OR author = ''")
        if 'views' not in columns:
            conn.execute("ALTER TABLE posts ADD COLUMN views INTEGER DEFAULT 0")
            conn.execute("UPDATE posts SET views = 0 WHERE views IS NULL")
        conn.execute("UPDATE posts SET author = 'AIxTubeG' WHERE lower(author) = 'aixtubeg'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_created_at_id ON posts(created_at DESC, id DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_author_created_at_id ON posts(author, created_at DESC, id DESC)")
        conn.commit()


def row_dict(row):
    return dict(row) if row else None


def attach_image_urls(conn, items):
    single = False
    if isinstance(items, sqlite3.Row):
        items = [row_dict(items)]
        single = True
    elif isinstance(items, dict):
        items = [items]
        single = True
    else:
        items = [row_dict(item) if isinstance(item, sqlite3.Row) else dict(item) for item in items]
    ids = [item.get('id') for item in items if item.get('id')]
    if not ids:
        return items[0] if single and items else ({} if single else items)
    placeholders = ','.join('?' for _ in ids)
    rows = conn.execute(
        "SELECT product_id, attr_name, attr_value FROM product_attributes WHERE attr_name IN ('product_image', 'jefcom_image', 'book_image', 'book_description_ai') AND product_id IN (%s)" % placeholders,
        ids,
    ).fetchall()
    image_by_id = {}
    ai_desc_by_id = {}
    # product_image を優先、旧名はレガシー fallback（上書きしない）
    LEGACY_IMAGE_ATTRS = ('jefcom_image', 'book_image')
    for row in rows:
        if row['attr_name'] == 'product_image' and row['attr_value']:
            image_by_id[row['product_id']] = row['attr_value']
        elif row['attr_name'] in LEGACY_IMAGE_ATTRS and row['attr_value']:
            if row['product_id'] not in image_by_id:
                image_by_id[row['product_id']] = row['attr_value']
        elif row['attr_name'] == 'book_description_ai' and row['attr_value']:
            ai_desc_by_id[row['product_id']] = row['attr_value']
    for item in items:
        item['image_url'] = image_by_id.get(item.get('id'), '/images/noimage.jpg')
        item['book_description_ai'] = ai_desc_by_id.get(item.get('id'), '')
    return items[0] if single else items


def get_rakuten_credentials():
    app_id = os.environ.get('RAKUTEN_APPLICATION_ID') or os.environ.get('RAKUTEN_APP_ID')
    access_key = os.environ.get('RAKUTEN_ACCESS_KEY')
    affiliate_id = os.environ.get('RAKUTEN_AFFILIATE_ID')
    if not app_id:
        raise ValueError('RAKUTEN_APPLICATION_ID is not set')
    if not access_key:
        raise ValueError('RAKUTEN_ACCESS_KEY is not set')
    return app_id, access_key, affiliate_id


def lookup_rakuten_by_isbn(isbn):
    """ISBNで楽天BooksBook APIを検索。"""
    app_id, access_key, affiliate_id = get_rakuten_credentials()
    request_origin = os.environ.get('RAKUTEN_REFERER', 'https://aixec.exbridge.jp').rstrip('/')
    params = {'applicationId': app_id, 'format': 'json', 'isbn': isbn}
    if affiliate_id:
        params['affiliateId'] = affiliate_id
    url = RAKUTEN_BOOKS_SEARCH_ENDPOINT + '?' + urlencode(params)
    req = Request(url, headers={
        'User-Agent': 'AIxEC/0.1',
        'Referer': request_origin + '/',
        'Origin': request_origin,
        'accessKey': access_key,
    })
    try:
        with urlopen(req, timeout=15) as res:
            payload = json.loads(res.read().decode('utf-8'))
        items = payload.get('Items', [])
        if not items:
            return None
        item = normalize_rakuten_book(items[0])
        return {
            'name': item['title'],
            'maker': item['author'],
            'jan': isbn,
            'description': item['item_caption'],
            'sale_price': int(item['item_price'] or 0),
            'image_url': item['image_url'],
            'rakuten_url': item['affiliate_url'] or item['item_url'],
        }
    except Exception:
        return None


def lookup_rakuten_by_keyword(keyword):
    """タイトルキーワードで楽天BooksTotal APIを検索し最初の商品を返す。"""
    app_id, access_key, affiliate_id = get_rakuten_credentials()
    request_origin = os.environ.get('RAKUTEN_REFERER', 'https://aixec.exbridge.jp').rstrip('/')
    base = RAKUTEN_BOOKS_SEARCH_ENDPOINT.rsplit('/BooksBook/', 1)[0]
    # BooksTotal は keyword パラメータ、BooksBook は title パラメータ
    endpoints = [
        (base + '/BooksTotal/Search/20170404', 'keyword'),
        (RAKUTEN_BOOKS_SEARCH_ENDPOINT, 'title'),
    ]
    for endpoint, kw_param in endpoints:
        params = {'applicationId': app_id, 'format': 'json', 'hits': '1', kw_param: keyword}
        if affiliate_id:
            params['affiliateId'] = affiliate_id
        url = endpoint + '?' + urlencode(params)
        req = Request(url, headers={
            'User-Agent': 'AIxEC/0.1',
            'Referer': request_origin + '/',
            'Origin': request_origin,
            'accessKey': access_key,
        })
        try:
            with urlopen(req, timeout=15) as res:
                payload = json.loads(res.read().decode('utf-8'))
            items = payload.get('Items', [])
            if not items:
                continue
            item = normalize_rakuten_book(items[0])
            return {
                'name': item['title'],
                'maker': item['author'],
                'jan': item['isbn'] or '',
                'description': item['item_caption'],
                'sale_price': int(item['item_price'] or 0),
                'image_url': item['image_url'],
                'rakuten_url': item['affiliate_url'] or item['item_url'],
            }
        except Exception:
            continue
    return None




def normalize_rakuten_item(item):
    if isinstance(item, dict) and 'Item' in item and isinstance(item['Item'], dict):
        item = item['Item']
    images = item.get('mediumImageUrls') or item.get('smallImageUrls') or []
    image_url = ''
    if images:
        first = images[0]
        image_url = first.get('imageUrl') if isinstance(first, dict) else str(first)
    return {
        'item_name': item.get('itemName') or '',
        'item_price': item.get('itemPrice'),
        'item_url': item.get('itemUrl') or item.get('affiliateUrl') or '',
        'affiliate_url': item.get('affiliateUrl') or item.get('itemUrl') or '',
        'image_url': image_url,
        'shop_name': item.get('shopName') or '',
        'shop_code': item.get('shopCode') or '',
        'item_code': item.get('itemCode') or '',
        'review_average': item.get('reviewAverage'),
        'review_count': item.get('reviewCount'),
    }


def normalize_rakuten_book(item):
    if isinstance(item, dict) and 'Item' in item and isinstance(item['Item'], dict):
        item = item['Item']
    image_url = item.get('largeImageUrl') or item.get('mediumImageUrl') or item.get('smallImageUrl') or ''
    return {
        'title': item.get('title') or '',
        'author': item.get('author') or '',
        'publisher_name': item.get('publisherName') or '',
        'isbn': item.get('isbn') or '',
        'item_caption': item.get('itemCaption') or '',
        'item_price': item.get('itemPrice'),
        'item_url': item.get('itemUrl') or item.get('affiliateUrl') or '',
        'affiliate_url': item.get('affiliateUrl') or item.get('itemUrl') or '',
        'image_url': image_url,
        'sales_date': item.get('salesDate') or '',
        'review_average': item.get('reviewAverage'),
        'review_count': item.get('reviewCount'),
    }


def search_rakuten_books(genre_id='', hits=20, sort='sales', keyword=''):
    app_id, access_key, affiliate_id = get_rakuten_credentials()
    hits = min(30, max(1, int(hits)))
    params = {
        'applicationId': app_id,
        'format': 'json',
        'hits': str(hits),
        'sort': sort,
    }
    if genre_id:
        params['booksGenreId'] = genre_id
    if keyword:
        params['title'] = keyword
    if affiliate_id:
        params['affiliateId'] = affiliate_id
    url = RAKUTEN_BOOKS_SEARCH_ENDPOINT + '?' + urlencode(params)
    request_origin = os.environ.get('RAKUTEN_REFERER', 'https://aixec.exbridge.jp').rstrip('/')
    req = Request(url, headers={
        'User-Agent': 'AIxEC/0.1',
        'Referer': request_origin + '/',
        'Origin': request_origin,
        'accessKey': access_key,
    })
    try:
        with urlopen(req, timeout=20) as res:
            payload = json.loads(res.read().decode('utf-8'))
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError('Rakuten Books API HTTP %s: %s' % (exc.code, detail[:300]))
    except URLError as exc:
        raise RuntimeError('Rakuten Books API request failed: %s' % exc)
    items = [normalize_rakuten_book(item) for item in payload.get('Items', [])]
    return {
        'count': payload.get('count'),
        'page': payload.get('page'),
        'hits': payload.get('hits'),
        'items': items,
    }


def search_rakuten_items(keyword, hits=10, sort='standard'):
    app_id, access_key, affiliate_id = get_rakuten_credentials()
    hits = min(30, max(1, int(hits)))
    params = {
        'applicationId': app_id,
        'accessKey': access_key,
        'format': 'json',
        'keyword': keyword,
        'hits': str(hits),
        'sort': sort,
        'elements': ','.join([
            'itemName', 'itemPrice', 'itemUrl', 'affiliateUrl', 'mediumImageUrls',
            'shopName', 'shopCode', 'itemCode', 'reviewAverage', 'reviewCount'
        ]),
    }
    if affiliate_id:
        params['affiliateId'] = affiliate_id
    url = RAKUTEN_ITEM_SEARCH_ENDPOINT + '?' + urlencode(params)
    request_origin = os.environ.get('RAKUTEN_REFERER', 'https://aixec.exbridge.jp').rstrip('/')
    req = Request(url, headers={
        'User-Agent': 'AIxEC/0.1',
        'Referer': request_origin + '/',
        'Origin': request_origin,
        'accessKey': access_key,
    })
    try:
        with urlopen(req, timeout=20) as res:
            payload = json.loads(res.read().decode('utf-8'))
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError('Rakuten API HTTP %s: %s' % (exc.code, detail[:300]))
    except URLError as exc:
        raise RuntimeError('Rakuten API request failed: %s' % exc)
    items = [normalize_rakuten_item(item) for item in payload.get('Items', [])]
    return {
        'count': payload.get('count'),
        'page': payload.get('page'),
        'first': payload.get('first'),
        'last': payload.get('last'),
        'hits': payload.get('hits'),
        'items': items,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = 'AIxEC/0.2'

    def log_message(self, fmt, *args):
        print('%s - %s' % (self.address_string(), fmt % args))

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode('utf-8')
        return json.loads(raw)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        qs = parse_qs(parsed.query)
        try:
            if path in ('/', '/health'):
                self.send_json({'ok': True, 'name': 'AIxEC', 'runtime': 'python', 'db': str(DB_PATH)})
                return
            if path == '/worker/status':
                with _worker_status_lock:
                    self.send_json({"ok": True, "workers": dict(_worker_status)})
                return
            if path == '/market/pipeline/status':
                self.send_json({"ok": True, "result": _load_market_pipeline_result()})
                return
            if path == '/ollama/status':
                results = []
                for srv in OLLAMA_SERVERS:
                    try:
                        req = Request(srv["url"], headers={"User-Agent": "aixec-watchdog/1.0"})
                        with urlopen(req, timeout=5) as r:
                            data = json.loads(r.read().decode())
                        models = [m["name"] for m in data.get("models", [])]
                        results.append({"name": srv["name"], "url": srv["url"],
                                        "status": "ok", "models": models})
                    except Exception as e:
                        results.append({"name": srv["name"], "url": srv["url"],
                                        "status": "down", "error": str(e)})
                self.send_json({"ok": True, "servers": results})
                return
            if path == '/schedule':
                schedule = {
                    "updated": "2026-05-24",
                    "note": "Ollama使用workerは競合しないよう1時間以上あけて配置",
                    "workers": [
                        {"time": "00:05", "name": "url2ai-polymarket-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへPolymarket自動サイクルをenqueue"},
                        {"time": "00:10", "name": "url2ai-oss-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへOSS自動サイクルをenqueue"},
                        {"time": "01:20", "name": "buzblogger-enqueue", "server": "this", "ollama": False, "hermes": "af345fc38800", "note": "RQDB4AI APIへBuzBlogger自動サイクルをenqueue"},
                        {"time": "01:30", "name": "aixec-register-market-worker-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへregister_market_workerをenqueue"},
                        {"time": "03:00", "name": "aixec-growth-agent-enqueue", "server": "this", "ollama": False, "hermes": "2fc0d9ebb81f", "note": "RQDB4AI APIへgrowth_agentをenqueue"},
                        {"time": "06:05", "name": "url2ai-polymarket-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへPolymarket自動サイクルをenqueue"},
                        {"time": "06:10", "name": "url2ai-oss-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへOSS自動サイクルをenqueue"},
                        {"time": "07:20", "name": "buzblogger-enqueue", "server": "this", "ollama": False, "hermes": "af345fc38800", "note": "RQDB4AI APIへBuzBlogger自動サイクルをenqueue"},
                        {"time": "07:30", "name": "aixec-register-market-worker-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへregister_market_workerをenqueue"},
                        {"time": "08:00", "name": "aixec-market-pipeline-enqueue", "server": "this", "ollama": False, "hermes": "91de360198b2", "note": "RQDB4AI APIへAIxEC market pipelineをenqueue"},
                        {"time": "09:10", "name": "url2ai-finreport-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへFinReport自動サイクルをenqueue"},
                        {"time": "12:05", "name": "url2ai-polymarket-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへPolymarket自動サイクルをenqueue"},
                        {"time": "12:10", "name": "url2ai-oss-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへOSS自動サイクルをenqueue"},
                        {"time": "13:20", "name": "buzblogger-enqueue", "server": "this", "ollama": False, "hermes": "af345fc38800", "note": "RQDB4AI APIへBuzBlogger自動サイクルをenqueue"},
                        {"time": "13:30", "name": "aixec-register-market-worker-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへregister_market_workerをenqueue"},
                        {"time": "15:00", "name": "aixec-growth-agent-enqueue", "server": "this", "ollama": False, "hermes": "2fc0d9ebb81f", "note": "RQDB4AI APIへgrowth_agentをenqueue"},
                        {"time": "16:30", "name": "horizon-worker-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへHorizon worker起動ジョブをenqueue"},
                        {"time": "18:05", "name": "url2ai-polymarket-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへPolymarket自動サイクルをenqueue"},
                        {"time": "18:10", "name": "url2ai-oss-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへOSS自動サイクルをenqueue"},
                        {"time": "19:20", "name": "buzblogger-enqueue", "server": "this", "ollama": False, "hermes": "af345fc38800", "note": "RQDB4AI APIへBuzBlogger自動サイクルをenqueue"},
                        {"time": "19:30", "name": "aixec-register-market-worker-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへregister_market_workerをenqueue"},
                        {"time": "20:00", "name": "aixec-market-pipeline-enqueue", "server": "this", "ollama": False, "hermes": "91de360198b2", "note": "RQDB4AI APIへAIxEC market pipelineをenqueue"},
                        {"time": "21:10", "name": "url2ai-finreport-enqueue", "server": "this", "ollama": False, "note": "RQDB4AI APIへFinReport自動サイクルをenqueue"},
                    ]
                }
                self.send_json({"ok": True, "schedule": schedule})
                return
            if path == '/books/ranking':
                genre_id = qs.get('genre_id', [''])[0]
                hits     = qs.get('hits',     ['20'])[0]
                sort     = qs.get('sort',     ['sales'])[0]
                keyword  = qs.get('keyword',  [''])[0]
                result = search_rakuten_books(genre_id=genre_id, hits=hits, sort=sort, keyword=keyword)
                self.send_json({'ok': True, 'genre_id': genre_id, 'result': result})
                return
            if path == '/rakuten/search':
                keyword = (qs.get('keyword', qs.get('q', ['']))[0] or '').strip()
                if not keyword:
                    self.send_json({'ok': False, 'error': 'keyword is required'}, 400)
                    return
                hits = qs.get('hits', ['10'])[0]
                sort = qs.get('sort', ['standard'])[0]
                result = search_rakuten_items(keyword, hits=hits, sort=sort)
                self.send_json({'ok': True, 'keyword': keyword, 'result': result})
                return
            if path == '/products':
                limit = min(200, max(1, int(qs.get('limit', ['50'])[0])))
                offset = max(0, int(qs.get('offset', ['0'])[0]))
                query = (qs.get('q', [''])[0] or '').strip()
                has_description = qs.get('has_description', [''])[0].lower() == 'true'
                isbns_raw = qs.get('isbns', [''])[0]
                where, params = [], []
                if query:
                    like = '%' + query + '%'
                    where.append('(name LIKE ? OR maker LIKE ? OR model_number LIKE ? OR jan LIKE ? OR asin LIKE ? OR internal_sku LIKE ?)')
                    params.extend([like, like, like, like, like, like])
                if has_description:
                    where.append("EXISTS (SELECT 1 FROM product_attributes WHERE product_id=products.id AND attr_name='book_description_source' AND attr_value != 'basic')")
                if isbns_raw:
                    import re as _re
                    isbns = [_re.sub(r'\D', '', s) for s in isbns_raw.split(',') if s.strip()]
                    isbns = [i for i in isbns if i]
                    if isbns:
                        where.append('jan IN (%s)' % ','.join('?' * len(isbns)))
                        params.extend(isbns)
                ids_raw = qs.get('ids', [''])[0]
                if ids_raw:
                    ids_list = [s.strip() for s in ids_raw.split(',') if s.strip().isdigit()]
                    if ids_list:
                        where.append('id IN (%s)' % ','.join('?' * len(ids_list)))
                        params.extend([int(i) for i in ids_list])
                if qs.get('affiliate', [''])[0].lower() == 'true':
                    where.append("affiliate_priority = 'affiliate'")
                if qs.get('no_xdirect', [''])[0].lower() == 'true':
                    where.append("affiliate_priority IN ('rakuten','affiliate')")
                maker_filter = qs.get('maker', [''])[0].strip()
                if maker_filter:
                    where.append('maker = ?')
                    params.append(maker_filter)
                attr_name = qs.get('attr_name', [''])[0].strip()
                attr_value = qs.get('attr_value', [''])[0].strip()
                attr_source = qs.get('attr_source', [''])[0].strip()
                if attr_name:
                    attr_where = ['product_id=products.id', 'attr_name=?']
                    attr_params = [attr_name]
                    if attr_value:
                        attr_where.append('attr_value=?')
                        attr_params.append(attr_value)
                    if attr_source:
                        attr_where.append('source=?')
                        attr_params.append(attr_source)
                    where.append('EXISTS (SELECT 1 FROM product_attributes WHERE ' + ' AND '.join(attr_where) + ')')
                    params.extend(attr_params)
                sql = 'SELECT * FROM products' + (' WHERE ' + ' AND '.join(where) if where else '') + ' ORDER BY updated_at DESC LIMIT ? OFFSET ?'
                params.extend([limit, offset])
                with connect() as conn:
                    rows = conn.execute(sql, params).fetchall()
                self.send_json({'ok': True, 'items': attach_image_urls(conn, rows)})
                return
            if path == '/lp/generate':
                product_id = qs.get('id', [''])[0].strip()
                if not product_id:
                    self.send_json({'ok': False, 'error': 'id is required'}, 400)
                    return
                lp_cache_dir = ROOT / 'storage' / 'lp_cache'
                lp_cache_dir.mkdir(exist_ok=True)
                cache_file = lp_cache_dir / (product_id + '.html')
                # すでに生成済み
                if cache_file.exists():
                    self.send_json({'ok': True, 'status': 'ready', 'html': cache_file.read_text('utf-8')})
                    return
                lock_file = lp_cache_dir / (product_id + '.lock')
                # 生成中
                if lock_file.exists():
                    self.send_json({'ok': True, 'status': 'generating'})
                    return
                # 商品情報取得
                with connect() as conn:
                    row = self.find_product(conn, product_id)
                    if not row:
                        self.send_json({'ok': False, 'error': 'product not found'}, 404)
                        return
                    product = dict(row)
                    attrs = {r['attr_name']: r['attr_value'] for r in conn.execute(
                        "SELECT attr_name, attr_value FROM product_attributes WHERE product_id=?", (product['id'],)
                    ).fetchall()}
                description = attrs.get('book_description_openbd') or attrs.get('book_description_google') or ''
                author = attrs.get('book_openbd_author') or attrs.get('book_google_authors') or product.get('maker', '')
                publisher = attrs.get('book_openbd_publisher') or attrs.get('book_google_publisher') or ''
                prompt = (
                    "あなたは書籍レビューの専門家です。以下の書籍について、読者が購入判断できるよう日本語で詳細な説明と深い考察を書いてください。\n\n"
                    "書籍名: {title}\n著者: {author}\n出版社: {publisher}\nISBN: {isbn}\n"
                    "書籍解説: {desc}\n\n"
                    "以下の各セクションを<p>タグと<ul><li>タグのみ使ってHTMLで書いてください（h2などの見出しタグ・strongなどの装飾タグは不要）:\n"
                    "1. この本の詳しい内容紹介（500〜700字。章構成・主要テーマ・核心的なメッセージを具体的に）\n"
                    "2. この本のハイライト・見どころ（箇条書き6〜8点。具体的なトピックや学べること）\n"
                    "3. この本から得られる知識・スキル（箇条書き5〜7点）\n"
                    "4. こんな方におすすめ（箇条書き4〜5点。具体的な読者像）\n"
                    "5. 著者について（200字程度。経歴・専門性・他の著作）\n"
                    "6. 類似書籍・関連テーマとの比較・位置づけ（200字程度）\n"
                    "7. 総評・まとめ（300字程度。この本の価値・独自性・読後に得られるもの）\n\n"
                    "各セクションは十分な文量で書き、表面的な説明でなく深い考察を含めてください。\n"
                    "日本語のHTMLのみ出力し、余計な説明・前置き・英語は不要です。"
                ).format(
                    title=product.get('name', ''),
                    author=author,
                    publisher=publisher,
                    isbn=product.get('jan', ''),
                    desc=description[:1500] if description else 'なし',
                )
                ollama_endpoint = os.environ.get(
                    'OLLAMA_ENDPOINT',
                    os.environ.get('OLLAMA_BASE_URL', 'http://192.168.0.3:11434'),
                ).rstrip('/')
                ollama_url = ollama_endpoint + '/api/generate'
                ollama_model = os.environ.get('OLLAMA_MODEL', 'gemma4:26b')
                # バックグラウンドスレッドで生成
                pid = product['id']
                def generate():
                    lock_file.write_text('generating')
                    try:
                        payload = json.dumps({'model': ollama_model, 'prompt': prompt, 'stream': False,
                                              'options': {'temperature': 0.7, 'num_predict': 5000}}).encode('utf-8')
                        req = Request(ollama_url, data=payload, headers={'Content-Type': 'application/json'})
                        with urlopen(req, timeout=180) as res:
                            result = json.loads(res.read().decode('utf-8'))
                        raw = result.get('response', '').strip()
                        # マークダウンコードフェンスを除去
                        import re as _re
                        raw = _re.sub(r'```[a-z]*\n?', '', raw).strip()
                        # html/head/body タグを除去
                        raw = _re.sub(r'(?i)</?(?:html|head|body)[^>]*>', '', raw).strip()
                        cache_file.write_text(raw, encoding='utf-8')
                        # product_attributesに保存
                        with connect() as conn:
                            conn.execute(
                                """INSERT INTO product_attributes (product_id, attr_name, attr_value, source, created_at, updated_at)
                                   VALUES (?, 'book_description_ai', ?, 'ollama', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                                   ON CONFLICT(product_id, attr_name, source)
                                   DO UPDATE SET attr_value=excluded.attr_value, updated_at=CURRENT_TIMESTAMP""",
                                (pid, raw)
                            )
                            conn.commit()
                    except Exception as exc:
                        cache_file.write_text('<p>生成エラー: ' + str(exc)[:200] + '</p>', encoding='utf-8')
                    finally:
                        lock_file.unlink(missing_ok=True)
                threading.Thread(target=generate, daemon=True).start()
                self.send_json({'ok': True, 'status': 'generating'})
                return
            if path == '/lp/status':
                product_id = qs.get('id', [''])[0].strip()
                lp_cache_dir = ROOT / 'storage' / 'lp_cache'
                cache_file = lp_cache_dir / (product_id + '.html')
                if cache_file.exists():
                    self.send_json({'ok': True, 'ready': True, 'html': cache_file.read_text('utf-8')})
                else:
                    self.send_json({'ok': True, 'ready': False})
                return
            if path == '/sitemap-products':
                limit = min(50000, max(1, int(qs.get('limit', ['50000'])[0])))
                offset = max(0, int(qs.get('offset', ['0'])[0]))
                with connect() as conn:
                    rows = conn.execute('SELECT id, updated_at FROM products ORDER BY id ASC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
                self.send_json({'ok': True, 'items': [row_dict(r) for r in rows]})
                return
            if path == '/products/makers':
                with connect() as conn:
                    rows = conn.execute(
                        "SELECT maker, COUNT(*) as cnt FROM products WHERE affiliate_priority IN ('rakuten','affiliate') AND maker IS NOT NULL AND maker!='' GROUP BY maker ORDER BY cnt DESC LIMIT 200"
                    ).fetchall()
                self.send_json({'ok': True, 'makers': [{'maker': r['maker'], 'count': r['cnt']} for r in rows]})
                return
            if path == '/lookup':
                jan     = qs.get('jan',     [''])[0].strip()
                asin    = qs.get('asin',    [''])[0].strip()
                keyword = qs.get('keyword', [''])[0].strip()
                result = {}
                if keyword:
                    result = lookup_rakuten_by_keyword(keyword) or {}
                if not result and jan:
                    try:
                        from urllib.request import urlopen as _urlopen
                        with _urlopen('https://api.openbd.jp/v1/get?isbn=' + jan, timeout=10) as r:
                            data = json.loads(r.read().decode('utf-8'))
                        entry = data[0] if data and data[0] else None
                        if entry:
                            summary = entry.get('summary', {})
                            texts = entry.get('onix', {}).get('CollateralDetail', {}).get('TextContent', [])
                            desc = texts[0].get('Text', '') if texts else ''
                            price_str = summary.get('price', '0') or '0'
                            import re as _re2
                            price_val = int(_re2.sub(r'\D', '', price_str) or 0)
                            result = {
                                'name': summary.get('title', ''),
                                'maker': summary.get('author', ''),
                                'jan': jan,
                                'publisher': summary.get('publisher', ''),
                                'description': desc,
                                'sale_price': price_val,
                                'image_url': summary.get('cover', ''),
                            }
                    except Exception:
                        pass
                if not result and jan:
                    try:
                        result = lookup_rakuten_by_isbn(jan) or {}
                    except Exception:
                        pass
                if not result and asin:
                    with connect() as conn:
                        row = conn.execute('SELECT * FROM products WHERE asin=?', (asin,)).fetchone()
                        if row:
                            result = row_dict(row)
                elif asin and result:
                    result['asin'] = asin
                self.send_json({'ok': True, 'found': bool(result), 'product': result})
                return
            if path == '/posts':
                limit  = min(100, max(1, int(qs.get('limit',  ['20'])[0])))
                offset = max(0, int(qs.get('offset', ['0'])[0]))
                author = (qs.get('author', [''])[0] or '').strip()
                exclude_author = (qs.get('exclude_author', [''])[0] or '').strip()
                with connect() as conn:
                    if author:
                        rows  = conn.execute('SELECT * FROM posts WHERE author = ? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?', (author, limit, offset)).fetchall()
                        total = conn.execute('SELECT COUNT(*) FROM posts WHERE author = ?', (author,)).fetchone()[0]
                    elif exclude_author:
                        rows  = conn.execute('SELECT * FROM posts WHERE author <> ? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?', (exclude_author, limit, offset)).fetchall()
                        total = conn.execute('SELECT COUNT(*) FROM posts WHERE author <> ?', (exclude_author,)).fetchone()[0]
                    else:
                        rows  = conn.execute('SELECT * FROM posts ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
                        total = conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
                self.send_json({'ok': True, 'items': [row_dict(r) for r in rows], 'total': total})
                return
            if path.startswith('/posts/'):
                post_id = path.split('/', 2)[2]
                if not post_id.isdigit():
                    self.send_json({'ok': False, 'error': 'invalid id'}, 400)
                    return
                with connect() as conn:
                    row = conn.execute('SELECT * FROM posts WHERE id = ?', (int(post_id),)).fetchone()
                if not row:
                    self.send_json({'ok': False, 'error': 'post not found'}, 404)
                    return
                self.send_json({'ok': True, 'item': row_dict(row)})
                return
            if path.startswith('/products/'):
                product_key = unquote(path.split('/', 2)[2])
                with connect() as conn:
                    row = self.find_product(conn, product_key)
                if not row:
                    self.send_json({'ok': False, 'error': 'product not found'}, 404)
                    return
                self.send_json({'ok': True, 'item': attach_image_urls(conn, row)})
                return
            self.send_json({'ok': False, 'error': 'not found'}, 404)
        except Exception as exc:
            self.send_json({'ok': False, 'error': str(exc)}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        try:
            data = self.read_json()
            if path == '/worker/report':
                name = (data.get('name') or '').strip()
                if not name:
                    self.send_json({"ok": False, "error": "name required"}, 400)
                    return
                record = {
                    "status":   data.get("status", "ok"),
                    "items":    data.get("items", 0),
                    "note":     data.get("note", ""),
                    "reported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                with _worker_status_lock:
                    _worker_status[name] = record
                    _save_worker_status(_worker_status)
                self.send_json({"ok": True})
                return
            if path == '/market/register-task':
                if not _require_bearer(self.headers, data):
                    self.send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                task = data.get("task") or {}
                items = data.get("items") or []
                if not isinstance(task, dict):
                    self.send_json({"ok": False, "error": "task must be object"}, 400)
                    return
                if not isinstance(items, list):
                    self.send_json({"ok": False, "error": "items must be array"}, 400)
                    return

                dry_run = bool(data.get("dry_run"))
                label = (task.get("label") or "AIxEC商品").strip()
                group = (task.get("group") or "market_products").strip()
                genre_id = str(task.get("genre_id") or "").strip()
                category = {"label": label, "group": group, "genre_id": genre_id}

                result_items = []
                registered = created = updated = skipped = 0
                if dry_run:
                    result_items = [_market_item_summary(item) for item in items]
                else:
                    from importlib import import_module
                    market_importer = import_module("scripts.import_rakuten_market_products")
                    for item in items:
                        if not isinstance(item, dict):
                            skipped += 1
                            continue
                        product_id, action = market_importer.upsert_product(item, category, upload=False)
                        if action == "created":
                            created += 1
                            registered += 1
                        elif action == "updated":
                            updated += 1
                            registered += 1
                        else:
                            skipped += 1

                        selection = item.get("_selection") or {}
                        if product_id:
                            _upsert_market_attr(product_id, "market_selection_score", selection.get("score"))
                            _upsert_market_attr(product_id, "market_selection_reason", selection.get("reason"))
                            _upsert_market_attr(product_id, "market_selection_source", selection.get("source"))
                        result_items.append(_market_item_summary(item, product_id, action))

                result = {
                    "label": label,
                    "group": group,
                    "genre_id": genre_id,
                    "dry_run": dry_run,
                    "candidates": int((data.get("counts") or {}).get("candidates") or len(items)),
                    "selected": int((data.get("counts") or {}).get("selected") or len(items)),
                    "registered": registered,
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                    "items": result_items,
                    "generated_at": data.get("generated_at") or "",
                    "received_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                if not dry_run and not data.get("skip_sns"):
                    result["sns_post_id"] = _insert_register_sns_post(result)
                if not dry_run:
                    _write_market_result(result)

                if not dry_run:
                    with _worker_status_lock:
                        _worker_status["market-register-api"] = {
                            "status": "ok",
                            "items": registered,
                            "note": f"{label} registered={registered} created={created} updated={updated}"[:200],
                            "reported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                        _save_worker_status(_worker_status)

                self.send_json({"ok": True, "result": result})
                return
            if path == '/horizon/run-worker':
                if not _require_bearer(self.headers, data):
                    self.send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                dry_run = bool(data.get("dry_run"))
                running_pid = _horizon_running()
                if dry_run:
                    self.send_json({
                        "ok": True,
                        "result": {
                            "dry_run": True,
                            "running": bool(running_pid),
                            "pid": running_pid,
                            "command": "cd /home/kojima/exdirect/horizon && OLLAMA_API_KEY=ollama python3 horizon_worker.py",
                        },
                    })
                    return
                result = _start_horizon_worker()
                with _worker_status_lock:
                    _worker_status["horizon-worker-trigger"] = {
                        "status": "ok",
                        "items": 1 if result.get("started") else 0,
                        "note": f"triggered started={result.get('started')} pid={result.get('pid')}"[:200],
                        "reported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    _save_worker_status(_worker_status)
                self.send_json({"ok": True, "result": result})
                return
            if path == '/posts':
                content = (data.get('content') or '').strip()
                author = (data.get('author') or 'xb_bittensor').strip()
                if not re.match(r'^[A-Za-z0-9_\\-]{1,32}$', author):
                    author = 'xb_bittensor'
                if not content:
                    self.send_json({'ok': False, 'error': 'content is required'}, 400)
                    return
                with connect() as conn:
                    if author == 'AIxTubeG' and content.startswith('新しい商品紹介動画を公開しました。'):
                        recent = conn.execute(
                            "SELECT * FROM posts WHERE author = ? AND created_at >= DATETIME('now', 'localtime', '-30 minutes') ORDER BY created_at DESC, id DESC LIMIT 1",
                            (author,)
                        ).fetchone()
                        if recent:
                            self.send_json({'ok': True, 'skipped': True, 'reason': 'AIxTubeG post throttled', 'item': row_dict(recent)}, 200)
                            return
                    cur = conn.execute(
                        "INSERT INTO posts (author, content, created_at, updated_at) VALUES (?, ?, DATETIME('now', 'localtime'), DATETIME('now', 'localtime'))",
                        (author, content)
                    )
                    conn.commit()
                    row = conn.execute('SELECT * FROM posts WHERE id = ?', (cur.lastrowid,)).fetchone()
                self.send_json({'ok': True, 'item': row_dict(row)}, 201)
                return
            if path == '/posts/update':
                post_id = data.get('id')
                content = (data.get('content') or '').strip()
                if not post_id:
                    self.send_json({'ok': False, 'error': 'id is required'}, 400)
                    return
                if not content:
                    self.send_json({'ok': False, 'error': 'content is required'}, 400)
                    return
                with connect() as conn:
                    current = conn.execute('SELECT * FROM posts WHERE id = ?', (int(post_id),)).fetchone()
                    if not current:
                        self.send_json({'ok': False, 'error': 'post not found'}, 404)
                        return
                    author = (data.get('author') or current['author'] or 'xb_bittensor').strip()
                    if not re.match(r'^[A-Za-z0-9_\\-]{1,32}$', author):
                        author = current['author'] or 'xb_bittensor'
                    conn.execute(
                        "UPDATE posts SET author = ?, content = ?, updated_at = DATETIME('now', 'localtime') WHERE id = ?",
                        (author, content, int(post_id))
                    )
                    conn.commit()
                    row = conn.execute('SELECT * FROM posts WHERE id = ?', (int(post_id),)).fetchone()
                self.send_json({'ok': True, 'item': row_dict(row)})
                return
            if path == '/posts/delete':
                post_id = data.get('id')
                if not post_id:
                    self.send_json({'ok': False, 'error': 'id is required'}, 400)
                    return
                with connect() as conn:
                    conn.execute('DELETE FROM posts WHERE id = ?', (int(post_id),))
                    conn.commit()
                self.send_json({'ok': True})
                return
            if path == '/posts/view':
                post_id = data.get('id')
                if not post_id:
                    self.send_json({'ok': False, 'error': 'id is required'}, 400)
                    return
                with connect() as conn:
                    row = conn.execute('SELECT * FROM posts WHERE id = ?', (int(post_id),)).fetchone()
                    if not row:
                        self.send_json({'ok': False, 'error': 'post not found'}, 404)
                        return
                    conn.execute('UPDATE posts SET views = COALESCE(views, 0) + 1 WHERE id = ?', (int(post_id),))
                    conn.commit()
                    row = conn.execute('SELECT * FROM posts WHERE id = ?', (int(post_id),)).fetchone()
                self.send_json({'ok': True, 'item': row_dict(row)})
                return
            if path == '/products':
                item = self.upsert_product(data)
                self.send_json({'ok': True, 'item': item}, 201)
                return
            if path == '/claude/generate':
                prompt = data.get('prompt', '')
                if not prompt:
                    self.send_json({'ok': False, 'error': 'prompt is required'}, 400)
                    return
                model = data.get('model', 'claude-cli/claude-sonnet-4-6')
                openclaw_bin = os.environ.get('OPENCLAW_BIN', 'openclaw')
                # nvm 環境の openclaw を使う
                nvm_node = '/home/kojima/.nvm/versions/node/v22.22.3/bin'
                env = dict(os.environ)
                env['PATH'] = nvm_node + ':' + env.get('PATH', '')
                cmd = [
                    openclaw_bin, 'capability', 'model', 'run',
                    '--model', model,
                    '--prompt', prompt,
                    '--local', '--json',
                ]
                try:
                    result = subprocess.run(cmd, text=True, capture_output=True, timeout=120, env=env)
                    if result.returncode != 0:
                        self.send_json({'ok': False, 'error': result.stderr or result.stdout}, 500)
                        return
                    out = json.loads(result.stdout)
                    outputs = out.get('outputs') or []
                    text = outputs[0].get('text', '') if outputs else ''
                    self.send_json({'ok': True, 'response': text})
                except subprocess.TimeoutExpired:
                    self.send_json({'ok': False, 'error': 'timeout'}, 504)
                    return
                return
            if path == '/import/url':
                url = data.get('url')
                if not url:
                    self.send_json({'ok': False, 'error': 'url is required'}, 400)
                    return
                with connect() as conn:
                    cur = conn.execute(
                        'INSERT INTO import_jobs (source_url, status, raw_payload, created_at, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)',
                        (url, 'queued', json.dumps(data, ensure_ascii=False)),
                    )
                    conn.commit()
                    row = conn.execute('SELECT * FROM import_jobs WHERE id = ?', (cur.lastrowid,)).fetchone()
                self.send_json({'ok': True, 'job': row_dict(row)}, 202)
                return
            self.send_json({'ok': False, 'error': 'not found'}, 404)
        except json.JSONDecodeError:
            self.send_json({'ok': False, 'error': 'invalid json'}, 400)
        except Exception as exc:
            self.send_json({'ok': False, 'error': str(exc)}, 500)

    def find_product(self, conn, value):
        if value.isdigit():
            row = conn.execute('SELECT * FROM products WHERE id = ?', (int(value),)).fetchone()
            if row:
                return row
        for field in ('jan', 'gtin', 'asin', 'internal_sku'):
            row = conn.execute('SELECT * FROM products WHERE ' + field + ' = ?', (value,)).fetchone()
            if row:
                return row
        row = conn.execute(
            'SELECT p.* FROM products p JOIN product_identifiers i ON i.product_id = p.id WHERE i.id_value = ? LIMIT 1',
            (value,),
        ).fetchone()
        if row:
            return row
        return self.find_by_slug(conn, value)

    @staticmethod
    def make_slug(maker, model, name=''):
        parts = model.split('-', 1)
        if len(parts) == 2 and name and parts[0] not in name:
            model = parts[1]
        digits = re.sub(r'\D', '', model or '')
        if re.match(r'^[0-9]{10,14}$', digits) and (name or '').strip():
            s = digits + '-' + (name or '')
        else:
            s = (maker or '') + '-' + (model or '')
        s = re.sub(r'[\s/\(\)\[\]\\\.]+', '-', s)
        s = re.sub(r'-+', '-', s)
        return s.strip('-')

    def find_by_slug(self, conn, slug):
        rows = conn.execute('SELECT * FROM products').fetchall()
        for row in rows:
            maker = row['maker'] or ''
            model = row['model_number'] or ''
            name = row['name'] or ''
            legacy = re.sub(r'[\s/\(\)\[\]\\\.]+', '-', (maker + '-' + model).strip('-'))
            legacy = re.sub(r'-+', '-', legacy).strip('-')
            maker_only = re.sub(r'[\s/\(\)\[\]\\\.]+', '-', maker)
            maker_only = re.sub(r'-+', '-', maker_only).strip('-')
            if self.make_slug(maker, model, name) == slug or legacy == slug or maker_only == slug:
                return row
        return None

    def resolve_existing_product(self, conn, values):
        if values.get('id'):
            row = conn.execute('SELECT * FROM products WHERE id = ?', (values['id'],)).fetchone()
            if row:
                return row
        for field in ('jan', 'gtin', 'asin', 'internal_sku'):
            if values.get(field):
                row = conn.execute('SELECT * FROM products WHERE ' + field + ' = ?', (values[field],)).fetchone()
                if row:
                    return row
        if values.get('maker') and values.get('model_number'):
            row = conn.execute(
                'SELECT * FROM products WHERE maker = ? AND model_number = ? LIMIT 1',
                (values['maker'], values['model_number']),
            ).fetchone()
            if row:
                return row
        return None

    def sync_identifiers(self, conn, product_id, values):
        for id_type in ('jan', 'gtin', 'asin', 'internal_sku'):
            id_value = values.get(id_type)
            if id_value:
                conn.execute(
                    'INSERT OR IGNORE INTO product_identifiers (product_id, id_type, id_value, source) VALUES (?, ?, ?, ?)',
                    (product_id, id_type, id_value, 'products'),
                )

    def upsert_product(self, data):
        if not data.get('name'):
            raise ValueError('name is required')
        fields = [
            'id', 'internal_sku', 'jan', 'gtin', 'asin', 'name', 'maker', 'model_number',
            'source_url', 'description', 'cost_price', 'sale_price', 'amazon_url',
            'rakuten_url', 'own_store_url', 'affiliate_priority', 'status'
        ]
        values = {k: data.get(k) for k in fields}
        values['affiliate_priority'] = values.get('affiliate_priority') or 'auto'
        values['status'] = values.get('status') or 'draft'
        with connect() as conn:
            existing = self.resolve_existing_product(conn, values)
            if existing:
                values['id'] = existing['id']
                conn.execute("""UPDATE products SET
                    internal_sku=:internal_sku, jan=:jan, gtin=:gtin, asin=:asin,
                    name=:name, maker=:maker, model_number=:model_number,
                    source_url=:source_url, description=:description, cost_price=:cost_price,
                    sale_price=:sale_price, amazon_url=:amazon_url, rakuten_url=:rakuten_url,
                    own_store_url=:own_store_url, affiliate_priority=:affiliate_priority,
                    status=:status, updated_at=CURRENT_TIMESTAMP WHERE id=:id""", values)
                product_id = existing['id']
            else:
                insert_values = {k: v for k, v in values.items() if k != 'id'}
                conn.execute("""INSERT INTO products
                    (internal_sku, jan, gtin, asin, name, maker, model_number, source_url, description,
                     cost_price, sale_price, amazon_url, rakuten_url, own_store_url, affiliate_priority,
                     status, created_at, updated_at)
                    VALUES
                    (:internal_sku, :jan, :gtin, :asin, :name, :maker, :model_number, :source_url, :description,
                     :cost_price, :sale_price, :amazon_url, :rakuten_url, :own_store_url, :affiliate_priority,
                     :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""", insert_values)
                product_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            self.sync_identifiers(conn, product_id, values)
            image_url = data.get('image_url', '').strip()
            if image_url:
                conn.execute("""INSERT INTO product_attributes (product_id, attr_name, attr_value, source, created_at, updated_at)
                    VALUES (?, 'book_image', ?, 'affiliate', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(product_id, attr_name, source) DO UPDATE SET attr_value=excluded.attr_value, updated_at=CURRENT_TIMESTAMP""",
                    (product_id, image_url))
            conn.commit()
            row = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
            return row_dict(row)


def main():
    migrate()
    host = os.environ.get('AIXEC_HOST', '0.0.0.0')
    port = int(os.environ.get('AIXEC_PORT', '8022'))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print('AIxEC API listening on http://%s:%s' % (host, port), flush=True)
    httpd.serve_forever()


if __name__ == '__main__':
    main()
