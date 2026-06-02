#!/usr/bin/env python3
import argparse
import re
import sqlite3
import time
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "storage" / "aixec.sqlite"
PRODUCT_URL_RE = re.compile(r"https?://(?:www\.)?exdirect\.net/product/(\d+)")
PRODUCT_MARKERS = (
    'property="og:type" content="product"',
    'property="product:product_link"',
)
DEAD_MARKERS = (
    'http-equiv="refresh"',
    'content="noindex"',
    "404 Not Found",
)


def connect(db_path):
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def product_id_from_url(url):
    if not url:
        return ""
    m = PRODUCT_URL_RE.search(url)
    return m.group(1) if m else ""


def fetch_status(url, timeout):
    req = Request(
        url,
        headers={
            "User-Agent": "AIxEC-LinkChecker/1.0",
            "Accept": "text/html,*/*;q=0.8",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as res:
            code = res.getcode()
            body = res.read(120000).decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read(30000).decode("utf-8", errors="replace")
        return "alive" if exc.code == 200 else "dead", exc.code, body[:200]
    except URLError as exc:
        return "unknown", 0, str(exc)

    normalized = unescape(body)
    if code == 200 and any(marker in normalized for marker in PRODUCT_MARKERS):
        return "alive", code, ""
    if code >= 400 or any(marker in normalized for marker in DEAD_MARKERS):
        return "dead", code, ""
    return "unknown", code, "product marker not found"


def load_targets(conn, limit, only_model):
    where = ["i.id_type = 'ocnk_product_id'"]
    params = []
    if only_model:
        where.append("model_number = ?")
        params.append(only_model)
    sql = (
        "SELECT p.id, p.internal_sku, p.model_number, p.name, p.own_store_url, p.source_url, i.id_value AS ocnk_product_id "
        "FROM products p JOIN product_identifiers i ON i.product_id = p.id "
        "WHERE " + " AND ".join(where) + " ORDER BY p.id"
    )
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


def clear_deleted_link(conn, product_id, ocnk_id):
    conn.execute(
        "UPDATE products SET own_store_url = NULL, source_url = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (product_id,),
    )
    if ocnk_id:
        conn.execute(
            "DELETE FROM product_identifiers WHERE product_id = ? AND id_type = 'ocnk_product_id' AND id_value = ?",
            (product_id, ocnk_id),
        )


def main():
    parser = argparse.ArgumentParser(description="Check XDirect product pages and remove dead OCNK links from AIxEC DB.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = connect(Path(args.db))
    targets = load_targets(conn, args.limit, args.model)
    alive = dead = unknown = cleared = 0

    for i, row in enumerate(targets, 1):
        ocnk_id = str(row["ocnk_product_id"])
        url = "https://www.exdirect.net/product/" + ocnk_id
        status, http_code, reason = fetch_status(url, args.timeout)
        if status == "alive":
            alive += 1
            if not args.dry_run and (row["own_store_url"] != url or row["source_url"] != url):
                with conn:
                    conn.execute(
                        "UPDATE products SET own_store_url = ?, source_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (url, url, row["id"]),
                    )
        elif status == "dead":
            dead += 1
            if not args.dry_run:
                with conn:
                    clear_deleted_link(conn, row["id"], ocnk_id)
                cleared += 1
        else:
            unknown += 1

        suffix = (" " + reason[:80]) if reason else ""
        print("[%d/%d] %s %s http=%s %s%s" % (i, len(targets), status, row["model_number"], http_code, url, suffix), flush=True)
        if args.sleep:
            time.sleep(args.sleep)

    print("summary targets=%d alive=%d dead=%d unknown=%d cleared=%d dry_run=%s" % (
        len(targets), alive, dead, unknown, cleared, args.dry_run
    ))


if __name__ == "__main__":
    main()
