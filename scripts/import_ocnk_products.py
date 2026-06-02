#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "storage" / "aixec.sqlite"
SCHEMA = ROOT / "database" / "schema.sql"
EXDIRECT_ENV = ROOT.parent / ".env"


def connect(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def migrate(conn):
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


def clean(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value if value else None
    return value


def product_values(p):
    ocnk_id = str(p.get("id"))
    groups = p.get("groups") or []
    category = p.get("category") or {}
    desc = p.get("description") or {}
    jan = clean(p.get("jan_code") or p.get("jan"))
    return {
        "internal_sku": "ocnk:" + ocnk_id,
        "jan": jan,
        "gtin": jan,
        "asin": None,
        "maker": clean(groups[0].get("name")) if groups else None,
        "model_number": clean(p.get("model_number")),
        "name": clean(p.get("name")) or "(no name)",
        "source_url": clean(p.get("url") or p.get("public_url")),
        "description": clean(desc.get("text") if isinstance(desc, dict) else None),
        "cost_price": None,
        "sale_price": p.get("price"),
        "amazon_url": None,
        "rakuten_url": None,
        "own_store_url": clean(p.get("url") or p.get("public_url")),
        "affiliate_priority": "auto",
        "status": "active",
        "ocnk_id": ocnk_id,
        "category_name": clean(category.get("parent_name")),
        "subcategory_name": clean(category.get("name")),
        "category_id": category.get("parent_id"),
        "subcategory_id": category.get("id"),
        "stock": p.get("stock"),
        "stock_unlimited": p.get("stock_unlimited"),
        "list_price": p.get("list_price"),
    }


def upsert_product(conn, p):
    v = product_values(p)
    existing = conn.execute("SELECT id FROM products WHERE internal_sku = ?", (v["internal_sku"],)).fetchone()
    if existing:
        product_id = existing["id"]
        conn.execute(
            """UPDATE products SET
                jan=:jan, gtin=:gtin, asin=:asin, maker=:maker, model_number=:model_number,
                name=:name, source_url=:source_url, description=:description, cost_price=:cost_price,
                sale_price=:sale_price, amazon_url=:amazon_url, rakuten_url=:rakuten_url,
                own_store_url=:own_store_url, affiliate_priority=:affiliate_priority,
                status=:status, updated_at=CURRENT_TIMESTAMP
               WHERE id=:product_id""",
            dict(v, product_id=product_id),
        )
    else:
        cur = conn.execute(
            """INSERT INTO products
                (internal_sku, jan, gtin, asin, maker, model_number, name, source_url, description,
                 cost_price, sale_price, amazon_url, rakuten_url, own_store_url, affiliate_priority,
                 status, created_at, updated_at)
               VALUES
                (:internal_sku, :jan, :gtin, :asin, :maker, :model_number, :name, :source_url, :description,
                 :cost_price, :sale_price, :amazon_url, :rakuten_url, :own_store_url, :affiliate_priority,
                 :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            v,
        )
        product_id = cur.lastrowid

    identifiers = {
        "ocnk_product_id": v["ocnk_id"],
        "internal_sku": v["internal_sku"],
        "jan": v["jan"],
        "gtin": v["gtin"],
        "model_number": v["model_number"],
    }
    for id_type, id_value in identifiers.items():
        if id_value is not None and str(id_value).strip() != "":
            conn.execute(
                """INSERT OR IGNORE INTO product_identifiers
                   (product_id, id_type, id_value, source) VALUES (?, ?, ?, ?)""",
                (product_id, id_type, str(id_value), "ocnk"),
            )

    attrs = {
        "ocnk_category": v["category_name"],
        "ocnk_subcategory": v["subcategory_name"],
        "ocnk_category_id": v["category_id"],
        "ocnk_subcategory_id": v["subcategory_id"],
        "ocnk_stock": v["stock"],
        "ocnk_stock_unlimited": v["stock_unlimited"],
        "ocnk_list_price": v["list_price"],
    }
    for name, value in attrs.items():
        if value is not None:
            conn.execute(
                """INSERT INTO product_attributes
                   (product_id, attr_name, attr_value, source, created_at, updated_at)
                   VALUES (?, ?, ?, 'ocnk', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                   ON CONFLICT(product_id, attr_name, source) DO UPDATE SET
                     attr_value=excluded.attr_value,
                     updated_at=CURRENT_TIMESTAMP""",
                (product_id, name, str(value)),
            )

    conn.execute(
        """INSERT INTO channel_payloads
           (product_id, channel, external_id, payload_json, created_at, updated_at)
           VALUES (?, 'ocnk', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
           ON CONFLICT(channel, external_id) DO UPDATE SET
             product_id=excluded.product_id,
             payload_json=excluded.payload_json,
             updated_at=CURRENT_TIMESTAMP""",
        (product_id, v["ocnk_id"], json.dumps(p, ensure_ascii=False, separators=(",", ":"))),
    )
    return product_id


def fetch_page(base_url, token, max_id, limit, view_hidden):
    params = {"limit": limit}
    if max_id:
        params["max_id"] = max_id
    if view_hidden:
        params["view_hidden"] = "true"
    resp = requests.get(
        base_url.rstrip("/") + "/products",
        headers={"Authorization": "Bearer " + token},
        params=params,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Import all OCNK products into AIxEC SQLite")
    parser.add_argument("--db", default=os.environ.get("AIXEC_DB", str(DEFAULT_DB)))
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--no-hidden", action="store_true")
    parser.add_argument("--max-pages", type=int, default=0)
    args = parser.parse_args()

    load_dotenv(EXDIRECT_ENV)
    load_dotenv(ROOT / ".env")
    token = os.environ.get("OCNK_API_TOKEN")
    base_url = os.environ.get("OCNK_API_BASE_URL", "https://api.ocnk.net/v1")
    if not token:
        raise SystemExit("OCNK_API_TOKEN is missing")

    conn = connect(Path(args.db))
    migrate(conn)

    max_id = None
    total_imported = 0
    page = 0
    started = time.time()
    while True:
        page += 1
        result = fetch_page(base_url, token, max_id, args.limit, not args.no_hidden)
        products = result.get("data") or []
        pagination = result.get("pagination") or {}
        total_count = pagination.get("total_count", "?")
        if not products:
            break
        with conn:
            for p in products:
                upsert_product(conn, p)
        total_imported += len(products)
        print(f"page={page} imported={total_imported}/{total_count} last_id={products[-1].get('id')}", flush=True)
        next_max_id = pagination.get("next_max_id")
        if args.max_pages and page >= args.max_pages:
            break
        if not next_max_id or len(products) < args.limit:
            break
        max_id = next_max_id
        time.sleep(args.sleep)

    product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    payload_count = conn.execute("SELECT COUNT(*) FROM channel_payloads WHERE channel='ocnk'").fetchone()[0]
    elapsed = time.time() - started
    print(json.dumps({
        "ok": True,
        "imported_this_run": total_imported,
        "products_total": product_count,
        "ocnk_payloads_total": payload_count,
        "elapsed_sec": round(elapsed, 1),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
