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
import hashlib
import time
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
_GROWTH_LOCK_PATH = ROOT / "storage" / "growth_agent.lock"
_GROWTH_LOG_PATH = ROOT / "storage" / "autonomous" / "growth_agent.log"
_REGISTER_MARKET_PID_PATH = ROOT / "storage" / "register_market_worker.pid"
_REGISTER_MARKET_LOG_PATH = ROOT / "storage" / "register_market_worker.log"
_HERMES_JOBS_PATH = Path("/home/kojima/.hermes/cron/jobs.json")
_worker_status_lock = threading.Lock()
_response_cache_lock = threading.Lock()
_response_cache = {}
_RESPONSE_CACHE_MAX = int(os.environ.get("AIXEC_RESPONSE_CACHE_MAX", "192") or "192")
_RESPONSE_CACHE_MAX_BYTES = int(os.environ.get("AIXEC_RESPONSE_CACHE_MAX_BYTES", "262144") or "262144")
_disk_cache_locks_lock = threading.Lock()
_disk_cache_locks = {}
_rate_limit_lock = threading.Lock()
_rate_limit_hits = {}
_request_stats_lock = threading.Lock()
_request_stats = {}
_lp_generation_lock = threading.Lock()
_lp_generation_active = set()
_LP_GENERATION_MAX = int(os.environ.get("AIXEC_LP_GENERATION_MAX", "0") or "0")
_LP_GENERATION_RATE_PER_MIN = int(os.environ.get("AIXEC_LP_GENERATION_RATE_PER_MIN", "6") or "6")
_BOOKS_RANKING_CACHE_TTL = int(os.environ.get("AIXEC_BOOKS_RANKING_CACHE_TTL", "900") or "900")
_BOOKS_RANKING_STALE_TTL = int(os.environ.get("AIXEC_BOOKS_RANKING_STALE_TTL", "86400") or "86400")
_PRODUCTS_CACHE_TTL = int(os.environ.get("AIXEC_PRODUCTS_CACHE_TTL", "120") or "120")
_PRODUCT_DETAIL_CACHE_TTL = int(os.environ.get("AIXEC_PRODUCT_DETAIL_CACHE_TTL", "600") or "600")
_PRODUCTS_STALE_TTL = int(os.environ.get("AIXEC_PRODUCTS_STALE_TTL", "3600") or "3600")
_PRODUCTS_RATE_PER_MIN = int(os.environ.get("AIXEC_PRODUCTS_RATE_PER_MIN", "60") or "60")
_PRODUCT_DETAIL_RATE_PER_MIN = int(os.environ.get("AIXEC_PRODUCT_DETAIL_RATE_PER_MIN", "120") or "120")
_POSTS_CACHE_TTL = int(os.environ.get("AIXEC_POSTS_CACHE_TTL", "60") or "60")
_POST_DETAIL_CACHE_TTL = int(os.environ.get("AIXEC_POST_DETAIL_CACHE_TTL", "300") or "300")
_POSTS_STALE_TTL = int(os.environ.get("AIXEC_POSTS_STALE_TTL", "1800") or "1800")
ALLOWED_WORKER_NAMES = {
    "url2ai-polymarket-enqueue",
    "url2ai-oss-enqueue",
    "url2ai-finreport-enqueue",
    "buzblogger-enqueue",
    "horizon-worker-enqueue",
    "aixec-market-pipeline-enqueue",
    "aixec-register-market-worker-enqueue",
    "aixec-growth-agent-enqueue",
}

SCHEDULE_NOTES = {
    "url2ai-polymarket-enqueue": "RQDB4AI APIへPolymarket自動サイクルをenqueue",
    "url2ai-oss-enqueue": "RQDB4AI APIへOSS自動サイクルをenqueue",
    "url2ai-finreport-enqueue": "RQDB4AI APIへFinReport自動サイクルをenqueue",
    "buzblogger-enqueue": "RQDB4AI APIへBuzBlogger自動サイクルをenqueue",
    "horizon-worker-enqueue": "RQDB4AI APIへHorizon worker起動ジョブをenqueue",
    "aixec-market-pipeline-enqueue": "RQDB4AI APIへAIxEC market pipelineをenqueue",
    "aixec-register-market-worker-enqueue": "RQDB4AI APIへregister_market_workerをenqueue",
    "aixec-growth-agent-enqueue": "RQDB4AI APIへgrowth_agentをenqueue",
}

def _cron_values(field, min_value, max_value):
    values = set()
    for part in str(field).split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*":
            values.update(range(min_value, max_value + 1))
        elif part.startswith("*/"):
            step = int(part[2:])
            values.update(range(min_value, max_value + 1, step))
        elif "-" in part:
            start, end = [int(x) for x in part.split("-", 1)]
            values.update(range(max(min_value, start), min(max_value, end) + 1))
        else:
            values.add(int(part))
    return sorted(v for v in values if min_value <= v <= max_value)

def _load_schedule_from_hermes():
    workers = []
    if not _HERMES_JOBS_PATH.exists():
        return None
    try:
        data = json.loads(_HERMES_JOBS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    for job in data.get("jobs", []):
        name = job.get("name") or ""
        if name not in ALLOWED_WORKER_NAMES or not job.get("enabled", True):
            continue
        expr = ((job.get("schedule") or {}).get("expr") or job.get("schedule_display") or "").strip()
        parts = expr.split()
        if len(parts) < 2:
            continue
        try:
            minutes = _cron_values(parts[0], 0, 59)
            hours = _cron_values(parts[1], 0, 23)
        except Exception:
            continue
        for hour in hours:
            for minute in minutes:
                workers.append({
                    "time": f"{hour:02d}:{minute:02d}",
                    "name": name,
                    "server": "this",
                    "ollama": False,
                    "hermes": job.get("id"),
                    "cron": expr,
                    "next_run_at": job.get("next_run_at"),
                    "last_run_at": job.get("last_run_at"),
                    "last_status": job.get("last_status"),
                    "note": SCHEDULE_NOTES.get(name, "RQDB4AI APIへenqueue"),
                })
    workers.sort(key=lambda x: (x["time"], x["name"]))
    return {
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": str(_HERMES_JOBS_PATH),
        "note": "Hermes jobs.jsonから生成",
        "workers": workers,
    }

def _cache_get(key, ttl=30):
    now = datetime.datetime.now().timestamp()
    with _response_cache_lock:
        hit = _response_cache.get(key)
        if not hit:
            return None
        expires, value = hit
        if expires < now:
            _response_cache.pop(key, None)
            return None
        return value

def _cache_set(key, value, ttl=30):
    try:
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > _RESPONSE_CACHE_MAX_BYTES:
            return
    except Exception:
        return
    now = datetime.datetime.now().timestamp()
    with _response_cache_lock:
        if len(_response_cache) >= _RESPONSE_CACHE_MAX:
            for old_key in list(_response_cache.keys())[:128]:
                _response_cache.pop(old_key, None)
        _response_cache[key] = (now + ttl, value)

def _disk_cache_path(namespace, key):
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return ROOT / "storage" / "api_cache" / namespace / (digest + ".json")

def _disk_cache_get(namespace, key, ttl):
    cache_file = _disk_cache_path(namespace, key)
    try:
        if not cache_file.exists():
            return None
        age = time.time() - cache_file.stat().st_mtime
        if age > ttl:
            return None
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return data.get("payload")
    except Exception:
        return None

def _disk_cache_set(namespace, key, payload):
    cache_file = _disk_cache_path(namespace, key)
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"payload": payload}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(cache_file)
    except Exception:
        pass

def _singleflight_lock(key):
    with _disk_cache_locks_lock:
        lock = _disk_cache_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _disk_cache_locks[key] = lock
        return lock

def _rate_limit_allow(key, limit, window_seconds=60):
    if limit <= 0:
        return False
    now = time.time()
    cutoff = now - window_seconds
    with _rate_limit_lock:
        hits = [ts for ts in _rate_limit_hits.get(key, []) if ts >= cutoff]
        if len(hits) >= limit:
            _rate_limit_hits[key] = hits
            return False
        hits.append(now)
        _rate_limit_hits[key] = hits
        return True

def _rate_limit_client_key(handler, scope):
    client = "unknown"
    try:
        client = handler.client_address[0]
    except Exception:
        pass
    return scope + ":" + client

def _is_truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

def _compact_product_payload(payload, include_description=True):
    if include_description:
        return payload

    def compact_item(item):
        if not isinstance(item, dict):
            return item
        slim = dict(item)
        slim.pop("description", None)
        slim.pop("book_description_ai", None)
        return slim

    compacted = dict(payload)
    if isinstance(compacted.get("items"), list):
        compacted["items"] = [compact_item(item) for item in compacted["items"]]
    if isinstance(compacted.get("item"), dict):
        compacted["item"] = compact_item(compacted["item"])
    return compacted

def _request_stats_key(method, path):
    if path.startswith("/products/"):
        path = "/products/:id"
    elif path.startswith("/posts/"):
        path = "/posts/:id"
    return method + " " + path

def _record_request(method, path):
    now = time.time()
    key = _request_stats_key(method, path)
    with _request_stats_lock:
        stat = _request_stats.get(key) or {"count": 0, "last_seen": 0}
        stat["count"] += 1
        stat["last_seen"] = now
        _request_stats[key] = stat
        if len(_request_stats) > 128:
            for old_key, _ in sorted(_request_stats.items(), key=lambda item: item[1].get("last_seen", 0))[:32]:
                _request_stats.pop(old_key, None)

def _request_stats_snapshot():
    now = time.time()
    with _request_stats_lock:
        items = [
            {
                "path": key,
                "count": value.get("count", 0),
                "last_seen_seconds_ago": round(now - value.get("last_seen", now), 3),
            }
            for key, value in _request_stats.items()
        ]
    items.sort(key=lambda item: item["count"], reverse=True)
    return items

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
_worker_status = {k: v for k, v in _worker_status.items() if k in ALLOWED_WORKER_NAMES}
_save_worker_status(_worker_status)

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

def _report_register_market(status, items, note):
    record = {
        "status": status,
        "items": items,
        "note": note[:200],
        "reported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with _worker_status_lock:
        _worker_status["aixec-register-market-worker-enqueue"] = record
        _save_worker_status(_worker_status)

def _insert_sns_post(content, author="register"):
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO posts (author, content, created_at, updated_at) VALUES (?, ?, DATETIME('now', 'localtime'), DATETIME('now', 'localtime'))",
            (author, content),
        )
        conn.commit()
        return cur.lastrowid

def _book_payload_from_rq(item):
    isbn = re.sub(r"\D", "", str(item.get("isbn") or item.get("jan") or ""))
    return {
        "title": item.get("title") or item.get("name") or "",
        "author": item.get("author") or "",
        "publisher_name": item.get("publisher_name") or item.get("publisher") or "",
        "isbn": isbn,
        "item_caption": item.get("item_caption") or item.get("caption") or item.get("description") or "",
        "item_price": int(item.get("item_price") or item.get("price") or 0),
        "item_url": item.get("item_url") or item.get("url") or "",
        "affiliate_url": item.get("affiliate_url") or item.get("item_url") or item.get("url") or "",
        "image_url": item.get("image_url") or "",
        "tab_label": item.get("tab_label") or item.get("label") or "書籍",
        "tab_group": item.get("tab_group") or item.get("group") or "books",
    }

def _book_exists(isbn):
    if not isbn:
        return True
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE jan=? OR internal_sku=? LIMIT 1",
            (isbn, "rakuten_books:" + isbn),
        ).fetchone()
    return row is not None

def _register_rq_book(book):
    from importlib import import_module
    ranking = import_module("scripts.register_ranking_books")
    env = ranking.load_env()
    local_image = ranking.download_book_image(book, env)
    book["local_image"] = local_image
    item = ranking.register_book(book)
    product_id = item.get("id")
    if product_id:
        ranking.upsert_book_attrs(product_id, local_image or book.get("image_url"), book)
        ranking.update_book_genre_json(product_id, book.get("tab_label", "書籍"), book.get("tab_group", "books"))
        try:
            ranking.enrich_book_metadata(product_id)
        except Exception:
            pass
    return product_id, item

def _insert_books_sns_post(new_by_label):
    if not new_by_label:
        return None
    lines = ["📚 新着書籍 登録完了", ""]
    total = 0
    for label, names in new_by_label.items():
        total += len(names)
        lines.append(f"{label}（{len(names)}件）")
        for name in names[:10]:
            lines.append("・" + name)
        if len(names) > 10:
            lines.append(f"ほか{len(names) - 10}件")
        lines.append("")
    lines.extend(["AIxEC 人気書籍", "https://aixec.exbridge.jp/books_ranking.php"])
    if total <= 0:
        return None
    return _insert_sns_post("\n".join(lines), "register")

def _insert_market_sns_post(new_by_label):
    if not new_by_label:
        return None
    last_id = None
    for label, names in new_by_label.items():
        if not names:
            continue
        body = "".join("・%s\n" % name for name in names[:10])
        more = "\nほか%d件\n" % (len(names) - 10) if len(names) > 10 else ""
        content = (
            "🛒 楽天市場商品 登録完了 — %s（%d件）\n\n"
            "ランキング巡回ワーカーが、AIxECに未登録だった楽天市場商品を自動登録しました。\n\n"
            "%s%s\n%s"
        ) % (label, len(names), body, more, "https://aixec.exbridge.jp/market_ranking.php")
        last_id = _insert_sns_post(content, "register")
    return last_id

def _pid_alive(pid):
    try:
        pid_int = int(pid)
        stat_path = Path("/proc") / str(pid_int) / "stat"
        if stat_path.exists():
            parts = stat_path.read_text(encoding="utf-8", errors="replace").split()
            if len(parts) > 2 and parts[2] == "Z":
                return False
        os.kill(pid_int, 0)
        return True
    except Exception:
        return False

def _horizon_running():
    if _HORIZON_LOCK_PATH.exists():
        pid = _HORIZON_LOCK_PATH.read_text(encoding="utf-8").strip()
        if pid and _pid_alive(pid):
            return int(pid)
        try:
            _HORIZON_LOCK_PATH.unlink()
        except Exception:
            pass
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
    horizon_dir = Path(os.environ.get("HORIZON_WORKER_DIR", "/home/kojima/bittensorman/aidexx/horizon"))
    worker = horizon_dir / "horizon_worker.py"
    if not worker.exists():
        raise FileNotFoundError(str(worker))
    env = dict(os.environ)
    env.setdefault("OLLAMA_API_KEY", "ollama")
    env.setdefault("KURAGE_API", "http://exbridge.ddns.net:18200")
    env.setdefault("DASHBOARD_API", "http://192.168.0.14:8081/worker/report")
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

def _growth_running():
    if _GROWTH_LOCK_PATH.exists():
        pid = _GROWTH_LOCK_PATH.read_text(encoding="utf-8").strip()
        if pid and _pid_alive(pid):
            return int(pid)
    return 0

def _start_growth_agent(dry_run=False, skip_claude=False, market_limit=20):
    running = _growth_running()
    if running:
        return {"started": False, "already_running": True, "pid": running}
    cmd = [
        sys.executable,
        "scripts/growth_agent_pipeline.py",
        "--market-limit",
        str(int(market_limit or 20)),
    ]
    if dry_run:
        cmd.append("--dry-run")
    if skip_claude:
        cmd.append("--skip-claude")
    _GROWTH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_fh = _GROWTH_LOG_PATH.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return {"started": True, "already_running": False, "pid": proc.pid, "command": " ".join(cmd)}

def _register_market_worker_running():
    if _REGISTER_MARKET_PID_PATH.exists():
        pid = _REGISTER_MARKET_PID_PATH.read_text(encoding="utf-8").strip()
        if pid and _pid_alive(pid):
            return int(pid)
    return 0

def _start_register_market_worker(dry_run=False):
    running = _register_market_worker_running()
    if running:
        return {
            "dry_run": dry_run,
            "running": True,
            "started": False,
            "already_running": True,
            "pid": running,
        }
    cmd = [sys.executable, "scripts/register_market_worker.py", "--once"]
    if dry_run:
        cmd.append("--dry-run")
    _REGISTER_MARKET_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_fh = _REGISTER_MARKET_LOG_PATH.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return {
        "dry_run": dry_run,
        "running": False,
        "started": True,
        "already_running": False,
        "pid": proc.pid,
        "command": " ".join(cmd),
    }

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
        if 'slug' not in columns:
            conn.execute("ALTER TABLE posts ADD COLUMN slug TEXT")
        if 'title' not in columns:
            conn.execute("ALTER TABLE posts ADD COLUMN title TEXT")
        if 'description' not in columns:
            conn.execute("ALTER TABLE posts ADD COLUMN description TEXT")
        if 'kind' not in columns:
            conn.execute("ALTER TABLE posts ADD COLUMN kind TEXT DEFAULT 'post'")
        if 'source_url' not in columns:
            conn.execute("ALTER TABLE posts ADD COLUMN source_url TEXT")
        conn.execute("UPDATE posts SET author = 'AIxTubeG' WHERE lower(author) = 'aixtubeg'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_created_at_id ON posts(created_at DESC, id DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_author_created_at_id ON posts(author, created_at DESC, id DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_kind_created_at_id ON posts(kind, created_at DESC, id DESC)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_slug ON posts(slug) WHERE slug IS NOT NULL AND slug <> ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_jan ON products(jan)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_model_number ON products(model_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_internal_sku ON products(internal_sku)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_asin ON products(asin)")
        conn.commit()


def row_dict(row):
    return dict(row) if row else None


def post_slugify(value):
    slug = re.sub(r"[^0-9A-Za-zぁ-んァ-ン一-龥]+", "-", str(value or "").lower()).strip("-")
    return (slug[:90].strip("-") or "post")


def unique_post_slug(conn, slug, current_id=None):
    base = post_slugify(slug)
    candidate = base
    suffix = 2
    while True:
        if current_id is None:
            row = conn.execute("SELECT id FROM posts WHERE slug = ?", (candidate,)).fetchone()
        else:
            row = conn.execute("SELECT id FROM posts WHERE slug = ? AND id <> ?", (candidate, int(current_id))).fetchone()
        if not row:
            return candidate
        tail = f"-{suffix}"
        candidate = (base[: max(1, 90 - len(tail))].rstrip("-") + tail)
        suffix += 1


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
        request_line = args[0] if args else ''
        quiet_prefixes = (
            'GET /products',
            'GET /posts',
            'GET /books/ranking',
            'GET /worker/status',
            'GET /schedule',
            'GET /ollama/status',
            'GET /market/pipeline/status',
            'GET /lp/generate',
        )
        if isinstance(request_line, str) and request_line.startswith(quiet_prefixes):
            return
        print('%s - %s' % (self.address_string(), fmt % args))

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False
        return True

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
        _record_request("GET", path)
        try:
            if path in ('/', '/health'):
                self.send_json({'ok': True, 'name': 'AIxEC', 'runtime': 'python', 'db': str(DB_PATH)})
                return
            if path == '/debug/stats':
                self.send_json({'ok': True, 'requests': _request_stats_snapshot()})
                return
            if path == '/worker/status':
                with _worker_status_lock:
                    workers = {k: v for k, v in _worker_status.items() if k in ALLOWED_WORKER_NAMES}
                    self.send_json({"ok": True, "workers": workers})
                return
            if path == '/market/pipeline/status':
                self.send_json({"ok": True, "result": _load_market_pipeline_result()})
                return
            if path == '/ollama/status':
                cache_key = self.path
                cached = _cache_get(cache_key, ttl=60)
                if cached is not None:
                    self.send_json(cached)
                    return
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
                payload = {"ok": True, "servers": results}
                _cache_set(cache_key, payload, ttl=60)
                self.send_json(payload)
                return
            if path == '/schedule':
                schedule = _load_schedule_from_hermes() or {
                    "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "source": "fallback",
                    "note": "Hermes jobs.jsonを読めませんでした",
                    "workers": [],
                }
                self.send_json({"ok": True, "schedule": schedule})
                return
            if path == '/books/ranking':
                genre_id = qs.get('genre_id', [''])[0]
                hits     = qs.get('hits',     ['20'])[0]
                sort     = qs.get('sort',     ['sales'])[0]
                keyword  = qs.get('keyword',  [''])[0]
                cache_key = "genre_id=%s&hits=%s&sort=%s&keyword=%s" % (genre_id, hits, sort, keyword)
                cached = _cache_get("books/ranking:" + cache_key, ttl=_BOOKS_RANKING_CACHE_TTL)
                if cached is not None:
                    self.send_json(cached)
                    return
                disk_cached = _disk_cache_get("books_ranking", cache_key, ttl=_BOOKS_RANKING_CACHE_TTL)
                if disk_cached is not None:
                    _cache_set("books/ranking:" + cache_key, disk_cached, ttl=_BOOKS_RANKING_CACHE_TTL)
                    self.send_json(disk_cached)
                    return
                lock = _singleflight_lock("books/ranking:" + cache_key)
                if not lock.acquire(blocking=False):
                    stale = _disk_cache_get("books_ranking", cache_key, ttl=_BOOKS_RANKING_STALE_TTL)
                    if stale is not None:
                        stale = dict(stale)
                        stale["stale"] = True
                        self.send_json(stale)
                        return
                    self.send_json({'ok': False, 'error': 'books ranking refresh is busy'}, 429)
                    return
                try:
                    result = search_rakuten_books(genre_id=genre_id, hits=hits, sort=sort, keyword=keyword)
                    payload = {'ok': True, 'genre_id': genre_id, 'result': result}
                    _cache_set("books/ranking:" + cache_key, payload, ttl=_BOOKS_RANKING_CACHE_TTL)
                    _disk_cache_set("books_ranking", cache_key, payload)
                except Exception as exc:
                    stale = _disk_cache_get("books_ranking", cache_key, ttl=_BOOKS_RANKING_STALE_TTL)
                    if stale is not None:
                        stale = dict(stale)
                        stale["stale"] = True
                        self.send_json(stale)
                        return
                    payload = {'ok': False, 'genre_id': genre_id, 'error': str(exc), 'cached_error': True}
                    _cache_set("books/ranking:" + cache_key, payload, ttl=60)
                    self.send_json(payload, 503)
                    return
                finally:
                    lock.release()
                self.send_json(payload)
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
                cache_key = self.path
                include_description = not (
                    _is_truthy(qs.get("lite", [""])[0])
                    or _is_truthy(qs.get("no_description", [""])[0])
                    or (qs.get("fields", [""])[0] or "").strip().lower() == "lite"
                )
                memory_cache_key = "products:" + cache_key
                cached = _cache_get(memory_cache_key, ttl=_PRODUCTS_CACHE_TTL)
                if cached is not None:
                    self.send_json(cached)
                    return
                disk_cached = _disk_cache_get("products", cache_key, ttl=_PRODUCTS_CACHE_TTL)
                if disk_cached is not None:
                    _cache_set(memory_cache_key, disk_cached, ttl=_PRODUCTS_CACHE_TTL)
                    self.send_json(disk_cached)
                    return
                if not _rate_limit_allow(_rate_limit_client_key(self, "products"), _PRODUCTS_RATE_PER_MIN, 60):
                    stale = _disk_cache_get("products", cache_key, ttl=_PRODUCTS_STALE_TTL)
                    if stale is not None:
                        stale = dict(stale)
                        stale["stale"] = True
                        self.send_json(stale)
                        return
                    self.send_json({'ok': False, 'error': 'products rate limit reached'}, 429)
                    return
                lock = _singleflight_lock(memory_cache_key)
                if not lock.acquire(blocking=False):
                    stale = _disk_cache_get("products", cache_key, ttl=_PRODUCTS_STALE_TTL)
                    if stale is not None:
                        stale = dict(stale)
                        stale["stale"] = True
                        self.send_json(stale)
                        return
                    self.send_json({'ok': False, 'error': 'products refresh is busy'}, 429)
                    return
                limit = min(200, max(1, int(qs.get('limit', ['50'])[0])))
                offset = max(0, int(qs.get('offset', ['0'])[0]))
                query = (qs.get('q', [''])[0] or '').strip()
                has_description = qs.get('has_description', [''])[0].lower() == 'true'
                isbns_raw = qs.get('isbns', [''])[0]
                where, params = [], []
                if query:
                    compact_query = re.sub(r'\D', '', query)
                    if compact_query and compact_query == query and len(compact_query) >= 8:
                        where.append('(jan = ? OR model_number = ? OR asin = ? OR internal_sku = ?)')
                        params.extend([query, query, query, query])
                    else:
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
                try:
                    with connect() as conn:
                        rows = conn.execute(sql, params).fetchall()
                        items = attach_image_urls(conn, rows)
                    payload = _compact_product_payload({'ok': True, 'items': items}, include_description=include_description)
                    _cache_set(memory_cache_key, payload, ttl=_PRODUCTS_CACHE_TTL)
                    _disk_cache_set("products", cache_key, payload)
                except Exception:
                    stale = _disk_cache_get("products", cache_key, ttl=_PRODUCTS_STALE_TTL)
                    if stale is not None:
                        stale = dict(stale)
                        stale["stale"] = True
                        self.send_json(stale)
                        return
                    raise
                finally:
                    lock.release()
                self.send_json(payload)
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
                if _LP_GENERATION_MAX <= 0:
                    self.send_json({'ok': True, 'status': 'disabled', 'message': 'lp generation is disabled'})
                    return
                if not _rate_limit_allow('lp/generate', _LP_GENERATION_RATE_PER_MIN, 60):
                    self.send_json({'ok': True, 'status': 'busy', 'message': 'lp generation rate limit reached'})
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
                with _lp_generation_lock:
                    if len(_lp_generation_active) >= _LP_GENERATION_MAX:
                        self.send_json({'ok': True, 'status': 'busy', 'message': 'lp generation queue is full'})
                        return
                    _lp_generation_active.add(product_id)
                lock_file.write_text('generating')
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
                    try:
                        # gemma4系は思考型: think未指定だと隠れ推論がnum_predictを
                        # 食い潰し応答が空/尻切れになる(再起動でも直らない既知の罠)。
                        payload = json.dumps({'model': ollama_model, 'prompt': prompt, 'stream': False,
                                              'think': False,
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
                        with _lp_generation_lock:
                            _lp_generation_active.discard(product_id)
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
                cache_key = self.path
                memory_cache_key = "posts:" + cache_key
                cached = _cache_get(memory_cache_key, ttl=_POSTS_CACHE_TTL)
                if cached is not None:
                    self.send_json(cached)
                    return
                disk_cached = _disk_cache_get("posts", cache_key, ttl=_POSTS_CACHE_TTL)
                if disk_cached is not None:
                    _cache_set(memory_cache_key, disk_cached, ttl=_POSTS_CACHE_TTL)
                    self.send_json(disk_cached)
                    return
                lock = _singleflight_lock(memory_cache_key)
                if not lock.acquire(blocking=False):
                    stale = _disk_cache_get("posts", cache_key, ttl=_POSTS_STALE_TTL)
                    if stale is not None:
                        stale = dict(stale)
                        stale["stale"] = True
                        self.send_json(stale)
                        return
                    self.send_json({'ok': False, 'error': 'posts refresh is busy'}, 429)
                    return
                try:
                    limit  = min(100, max(1, int(qs.get('limit',  ['20'])[0])))
                    offset = max(0, int(qs.get('offset', ['0'])[0]))
                    author = (qs.get('author', [''])[0] or '').strip()
                    exclude_author = (qs.get('exclude_author', [''])[0] or '').strip()
                    kind = (qs.get('kind', [''])[0] or '').strip()
                    sitemap = (qs.get('sitemap', [''])[0] or '').strip() in ('1', 'true', 'yes')
                    with connect() as conn:
                        where = []
                        params = []
                        if author:
                            where.append('author = ?')
                            params.append(author)
                        elif exclude_author:
                            where.append('author <> ?')
                            params.append(exclude_author)
                        if kind:
                            where.append('kind = ?')
                            params.append(kind)
                        if sitemap:
                            where.append("COALESCE(slug, '') <> ''")
                            where.append("COALESCE(author, '') <> 'register'")
                        where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''
                        rows = conn.execute(
                            'SELECT * FROM posts' + where_sql + ' ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?',
                            (*params, limit, offset),
                        ).fetchall()
                        total = conn.execute('SELECT COUNT(*) FROM posts' + where_sql, tuple(params)).fetchone()[0]
                    payload = {'ok': True, 'items': [row_dict(r) for r in rows], 'total': total}
                    _cache_set(memory_cache_key, payload, ttl=_POSTS_CACHE_TTL)
                    _disk_cache_set("posts", cache_key, payload)
                except Exception:
                    stale = _disk_cache_get("posts", cache_key, ttl=_POSTS_STALE_TTL)
                    if stale is not None:
                        stale = dict(stale)
                        stale["stale"] = True
                        self.send_json(stale)
                        return
                    raise
                finally:
                    lock.release()
                self.send_json(payload)
                return
            if path.startswith('/posts/slug/'):
                post_slug = unquote(path.split('/', 3)[3]).strip()
                if not post_slug:
                    self.send_json({'ok': False, 'error': 'invalid slug'}, 400)
                    return
                cache_key = self.path
                memory_cache_key = "post_detail:" + cache_key
                cached = _cache_get(memory_cache_key, ttl=_POST_DETAIL_CACHE_TTL)
                if cached is not None:
                    self.send_json(cached)
                    return
                disk_cached = _disk_cache_get("post_detail", cache_key, ttl=_POST_DETAIL_CACHE_TTL)
                if disk_cached is not None:
                    _cache_set(memory_cache_key, disk_cached, ttl=_POST_DETAIL_CACHE_TTL)
                    self.send_json(disk_cached)
                    return
                with connect() as conn:
                    row = conn.execute('SELECT * FROM posts WHERE slug = ?', (post_slug,)).fetchone()
                if not row:
                    self.send_json({'ok': False, 'error': 'post not found'}, 404)
                    return
                payload = {'ok': True, 'item': row_dict(row)}
                _cache_set(memory_cache_key, payload, ttl=_POST_DETAIL_CACHE_TTL)
                _disk_cache_set("post_detail", cache_key, payload)
                self.send_json(payload)
                return
            if path.startswith('/posts/'):
                post_id = path.split('/', 2)[2]
                if not post_id.isdigit():
                    self.send_json({'ok': False, 'error': 'invalid id'}, 400)
                    return
                cache_key = self.path
                memory_cache_key = "post_detail:" + cache_key
                cached = _cache_get(memory_cache_key, ttl=_POST_DETAIL_CACHE_TTL)
                if cached is not None:
                    self.send_json(cached)
                    return
                disk_cached = _disk_cache_get("post_detail", cache_key, ttl=_POST_DETAIL_CACHE_TTL)
                if disk_cached is not None:
                    _cache_set(memory_cache_key, disk_cached, ttl=_POST_DETAIL_CACHE_TTL)
                    self.send_json(disk_cached)
                    return
                with connect() as conn:
                    row = conn.execute('SELECT * FROM posts WHERE id = ?', (int(post_id),)).fetchone()
                if not row:
                    self.send_json({'ok': False, 'error': 'post not found'}, 404)
                    return
                payload = {'ok': True, 'item': row_dict(row)}
                _cache_set(memory_cache_key, payload, ttl=_POST_DETAIL_CACHE_TTL)
                _disk_cache_set("post_detail", cache_key, payload)
                self.send_json(payload)
                return
            if path.startswith('/products/'):
                cache_key = self.path
                include_description = not (
                    _is_truthy(qs.get("lite", [""])[0])
                    or _is_truthy(qs.get("no_description", [""])[0])
                    or (qs.get("fields", [""])[0] or "").strip().lower() == "lite"
                )
                memory_cache_key = "product_detail:" + cache_key
                cached = _cache_get(memory_cache_key, ttl=_PRODUCT_DETAIL_CACHE_TTL)
                if cached is not None:
                    self.send_json(cached)
                    return
                disk_cached = _disk_cache_get("product_detail", cache_key, ttl=_PRODUCT_DETAIL_CACHE_TTL)
                if disk_cached is not None:
                    _cache_set(memory_cache_key, disk_cached, ttl=_PRODUCT_DETAIL_CACHE_TTL)
                    self.send_json(disk_cached)
                    return
                if not _rate_limit_allow(_rate_limit_client_key(self, "product_detail"), _PRODUCT_DETAIL_RATE_PER_MIN, 60):
                    stale = _disk_cache_get("product_detail", cache_key, ttl=_PRODUCTS_STALE_TTL)
                    if stale is not None:
                        stale = dict(stale)
                        stale["stale"] = True
                        self.send_json(stale)
                        return
                    self.send_json({'ok': False, 'error': 'product detail rate limit reached'}, 429)
                    return
                lock = _singleflight_lock(memory_cache_key)
                if not lock.acquire(blocking=False):
                    stale = _disk_cache_get("product_detail", cache_key, ttl=_PRODUCTS_STALE_TTL)
                    if stale is not None:
                        stale = dict(stale)
                        stale["stale"] = True
                        self.send_json(stale)
                        return
                    self.send_json({'ok': False, 'error': 'product detail refresh is busy'}, 429)
                    return
                product_key = unquote(path.split('/', 2)[2])
                try:
                    with connect() as conn:
                        row = self.find_product(conn, product_key)
                        if not row:
                            self.send_json({'ok': False, 'error': 'product not found'}, 404)
                            return
                        item = attach_image_urls(conn, row)
                    payload = _compact_product_payload({'ok': True, 'item': item}, include_description=include_description)
                    _cache_set(memory_cache_key, payload, ttl=_PRODUCT_DETAIL_CACHE_TTL)
                    _disk_cache_set("product_detail", cache_key, payload)
                except Exception:
                    stale = _disk_cache_get("product_detail", cache_key, ttl=_PRODUCTS_STALE_TTL)
                    if stale is not None:
                        stale = dict(stale)
                        stale["stale"] = True
                        self.send_json(stale)
                        return
                    raise
                finally:
                    lock.release()
                self.send_json(payload)
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
                if name not in ALLOWED_WORKER_NAMES:
                    self.send_json({"ok": False, "error": "worker not allowed"}, 400)
                    return
                record = {
                    "status":   data.get("status", "ok"),
                    "items":    data.get("items", 0),
                    "note":     data.get("note", ""),
                    "reported_at": data.get("reported_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
                category = {
                    "label": label,
                    "group": group,
                    "genre_id": genre_id,
                    "affiliate_priority": str(task.get("affiliate_priority") or ""),
                }

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
                        for key in list(_worker_status.keys()):
                            if key not in ALLOWED_WORKER_NAMES:
                                _worker_status.pop(key, None)
                        _save_worker_status(_worker_status)

                self.send_json({"ok": True, "result": result})
                return
            if path == '/register-market/run-once':
                if not _require_bearer(self.headers, data):
                    self.send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                dry_run = bool(data.get("dry_run"))
                source = (data.get("source") or "rqdb4ai").strip() or "rqdb4ai"
                books = data.get("books") or []
                market_items = data.get("market_items") or []
                if not isinstance(books, list):
                    self.send_json({"ok": False, "error": "books must be array"}, 400)
                    return
                if not isinstance(market_items, list):
                    self.send_json({"ok": False, "error": "market_items must be array"}, 400)
                    return

                books_registered = books_skipped = market_registered = market_skipped = 0
                book_results = []
                market_results = []
                new_books_by_label = {}
                new_market_by_label = {}

                try:
                    for raw in books:
                        if not isinstance(raw, dict):
                            books_skipped += 1
                            continue
                        book = _book_payload_from_rq(raw)
                        isbn = book.get("isbn") or ""
                        if not book.get("title") or not isbn or _book_exists(isbn):
                            books_skipped += 1
                            book_results.append({"action": "skipped", "isbn": isbn, "title": book.get("title", "")})
                            continue
                        if dry_run:
                            book_results.append({"action": "planned", "isbn": isbn, "title": book.get("title", "")})
                            continue
                        product_id, item = _register_rq_book(book)
                        if product_id:
                            books_registered += 1
                            book_results.append({"action": "created", "product_id": product_id, "isbn": isbn, "title": book["title"]})
                            new_books_by_label.setdefault(book["tab_label"], []).append(book["title"])
                        else:
                            books_skipped += 1
                            book_results.append({"action": "skipped", "isbn": isbn, "title": book.get("title", "")})

                    from importlib import import_module
                    market_importer = import_module("scripts.import_rakuten_market_products")
                    for raw in market_items:
                        if not isinstance(raw, dict):
                            market_skipped += 1
                            continue
                        label = (raw.get("category_label") or raw.get("label") or "楽天市場商品").strip()
                        group = (raw.get("category_group") or raw.get("group") or "market_products").strip()
                        category = {
                            "label": label,
                            "group": group,
                            "genre_id": str(raw.get("genre_id") or ""),
                            "affiliate_priority": str(raw.get("affiliate_priority") or ""),
                        }
                        item_code = raw.get("item_code") or ""
                        jan = raw.get("jan") or ""
                        if dry_run:
                            market_results.append(_market_item_summary(raw, None, "planned"))
                            continue
                        product_id, action = market_importer.upsert_product(raw, category, upload=False)
                        if action == "created":
                            market_registered += 1
                            new_market_by_label.setdefault(label, []).append(raw.get("name") or item_code or jan or "商品")
                        else:
                            market_skipped += 1
                        market_results.append(_market_item_summary(raw, product_id, action))

                    sns_post_ids = []
                    if not dry_run and not data.get("skip_sns"):
                        book_post = _insert_books_sns_post(new_books_by_label)
                        market_post = _insert_market_sns_post(new_market_by_label)
                        sns_post_ids = [pid for pid in (book_post, market_post) if pid]

                    items_count = books_registered + market_registered
                    result = {
                        "dry_run": dry_run,
                        "source": source,
                        "books_received": len(books),
                        "market_received": len(market_items),
                        "books_registered": books_registered,
                        "market_registered": market_registered,
                        "books_skipped": books_skipped,
                        "market_skipped": market_skipped,
                        "items": items_count,
                        "status": "ok",
                        "book_items": book_results[:50],
                        "market_items": market_results[:50],
                        "sns_post_ids": sns_post_ids,
                    }
                    _report_register_market(
                        "ok",
                        items_count,
                        f"books={books_registered} market={market_registered} dry_run={str(dry_run).lower()} source={source}",
                    )
                    self.send_json({"ok": True, "result": result})
                    return
                except Exception as exc:
                    _report_register_market("down", 0, "error=" + str(exc))
                    self.send_json({"ok": False, "error": str(exc)}, 500)
                    return
            if path == '/register-market/run-worker':
                if not _require_bearer(self.headers, data):
                    self.send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                dry_run = bool(data.get("dry_run"))
                check_only = bool(data.get("check_only"))
                running_pid = _register_market_worker_running()
                if check_only:
                    self.send_json({
                        "ok": True,
                        "result": {
                            "dry_run": dry_run,
                            "running": bool(running_pid),
                            "started": False,
                            "already_running": bool(running_pid),
                            "pid": running_pid,
                            "dry_run_supported": True,
                        },
                    })
                    return
                result = _start_register_market_worker(dry_run=dry_run)
                with _worker_status_lock:
                    _worker_status["aixec-register-market-worker-enqueue"] = {
                        "status": "running" if result.get("started") or result.get("already_running") else "down",
                        "items": 0,
                        "note": f"triggered started={result.get('started')} already_running={result.get('already_running')} pid={result.get('pid')}"[:200],
                        "reported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    _save_worker_status(_worker_status)
                result["dry_run_supported"] = True
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
                            "command": f"cd {os.environ.get('HORIZON_WORKER_DIR', '/home/kojima/bittensorman/aidexx/horizon')} && OLLAMA_API_KEY=ollama python3 horizon_worker.py",
                        },
                    })
                    return
                result = _start_horizon_worker()
                with _worker_status_lock:
                    _worker_status["horizon-worker-enqueue"] = {
                        "status": "running" if result.get("started") or result.get("already_running") else "down",
                        "items": 0,
                        "note": f"triggered started={result.get('started')} pid={result.get('pid')}"[:200],
                        "reported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    _save_worker_status(_worker_status)
                self.send_json({"ok": True, "result": result})
                return
            if path == '/growth/run-agent':
                if not _require_bearer(self.headers, data):
                    self.send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                dry_run = bool(data.get("dry_run"))
                skip_claude = bool(data.get("skip_claude"))
                market_limit = int(data.get("market_limit") or 20)
                running_pid = _growth_running()
                if dry_run and bool(data.get("check_only")):
                    self.send_json({
                        "ok": True,
                        "result": {
                            "dry_run": True,
                            "running": bool(running_pid),
                            "pid": running_pid,
                        },
                    })
                    return
                result = _start_growth_agent(dry_run=dry_run, skip_claude=skip_claude, market_limit=market_limit)
                with _worker_status_lock:
                    _worker_status["aixec-growth-agent-enqueue"] = {
                        "status": "running" if result.get("started") or result.get("already_running") else "down",
                        "items": 0,
                        "note": f"triggered started={result.get('started')} already_running={result.get('already_running')} pid={result.get('pid')}"[:200],
                        "reported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    _save_worker_status(_worker_status)
                self.send_json({"ok": True, "result": result})
                return
            if path == '/posts':
                content = (data.get('content') or '').strip()
                author = (data.get('author') or 'xb_bittensor').strip()
                title = (data.get('title') or '').strip()
                description = (data.get('description') or '').strip()
                kind = (data.get('kind') or 'post').strip()
                source_url = (data.get('source_url') or '').strip()
                requested_slug = (data.get('slug') or title or content[:80]).strip()
                if not re.match(r'^[A-Za-z0-9_\\-]{1,32}$', author):
                    author = 'xb_bittensor'
                if not re.match(r'^[A-Za-z0-9_.\\-]{1,64}$', kind):
                    kind = 'post'
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
                    slug = unique_post_slug(conn, requested_slug) if requested_slug else None
                    cur = conn.execute(
                        """
                        INSERT INTO posts (author, content, slug, title, description, kind, source_url, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, DATETIME('now', 'localtime'), DATETIME('now', 'localtime'))
                        """,
                        (author, content, slug, title, description, kind, source_url)
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
                    title = (data.get('title') if 'title' in data else current['title'] if 'title' in current.keys() else '') or ''
                    description = (data.get('description') if 'description' in data else current['description'] if 'description' in current.keys() else '') or ''
                    kind = (data.get('kind') if 'kind' in data else current['kind'] if 'kind' in current.keys() else 'post') or 'post'
                    source_url = (data.get('source_url') if 'source_url' in data else current['source_url'] if 'source_url' in current.keys() else '') or ''
                    slug_input = (data.get('slug') if 'slug' in data else current['slug'] if 'slug' in current.keys() else '') or title or content[:80]
                    slug = unique_post_slug(conn, slug_input, int(post_id)) if slug_input else None
                    if not re.match(r'^[A-Za-z0-9_.\\-]{1,64}$', str(kind)):
                        kind = current['kind'] if 'kind' in current.keys() else 'post'
                    conn.execute(
                        """
                        UPDATE posts
                        SET author = ?, content = ?, slug = ?, title = ?, description = ?, kind = ?, source_url = ?,
                            updated_at = DATETIME('now', 'localtime')
                        WHERE id = ?
                        """,
                        (author, content, slug, str(title).strip(), str(description).strip(), str(kind).strip(), str(source_url).strip(), int(post_id))
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
    httpd.daemon_threads = True
    print('AIxEC API listening on http://%s:%s' % (host, port), flush=True)
    httpd.serve_forever()


if __name__ == '__main__':
    main()
