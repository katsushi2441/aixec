#!/usr/bin/env python3
"""Repair ranking-imported Rakuten Books descriptions to the rich book format."""
import argparse
import json
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from register_ranking_books import (
    DB_PATH,
    RAKUTEN_BOOKS_ENDPOINT,
    description,
    download_book_image,
    load_env,
    upsert_book_attrs,
)


def fetch_book_by_isbn(env, isbn):
    params = {
        "applicationId": env.get("RAKUTEN_APPLICATION_ID", ""),
        "format": "json",
        "isbn": isbn,
    }
    if env.get("RAKUTEN_AFFILIATE_ID"):
        params["affiliateId"] = env["RAKUTEN_AFFILIATE_ID"]
    req = Request(
        RAKUTEN_BOOKS_ENDPOINT + "?" + urlencode(params),
        headers={
            "User-Agent": "AIxEC/0.1",
            "Referer": "https://aixec.exbridge.jp/",
            "Origin": "https://aixec.exbridge.jp",
            "accessKey": env.get("RAKUTEN_ACCESS_KEY", ""),
        },
    )
    with urlopen(req, timeout=20) as res:
        payload = json.loads(res.read().decode("utf-8"))
    items = payload.get("Items") or []
    if not items:
        return None
    item = items[0].get("Item", items[0])
    return {
        "title": item.get("title", ""),
        "author": item.get("author", ""),
        "publisher_name": item.get("publisherName", ""),
        "isbn": item.get("isbn", isbn),
        "item_caption": item.get("itemCaption", ""),
        "item_price": item.get("itemPrice"),
        "item_url": item.get("itemUrl", ""),
        "affiliate_url": item.get("affiliateUrl") or item.get("itemUrl", ""),
        "image_url": item.get("largeImageUrl") or item.get("mediumImageUrl") or "",
    }


def target_rows(conn, min_id, max_id, only_plain):
    where = ["internal_sku LIKE 'rakuten_books:%'", "jan IS NOT NULL", "jan != ''"]
    params = []
    if min_id is not None:
        where.append("id >= ?")
        params.append(min_id)
    if max_id is not None:
        where.append("id <= ?")
        params.append(max_id)
    if only_plain:
        where.append("(COALESCE(description,'') = '' OR description NOT LIKE '<p style=%')")
    sql = "SELECT * FROM products WHERE %s ORDER BY id" % " AND ".join(where)
    return conn.execute(sql, params).fetchall()


def repair_one(conn, env, row, dry_run=False):
    book = fetch_book_by_isbn(env, row["jan"])
    if not book:
        return "not_found"
    local_image = download_book_image(book, env)
    book["local_image"] = local_image
    rich_description = description(book, local_image)
    if dry_run:
        return "dry_run"
    with conn:
        conn.execute(
            """UPDATE products
               SET maker=COALESCE(NULLIF(?, ''), maker),
                   model_number=COALESCE(NULLIF(?, ''), model_number),
                   source_url=COALESCE(NULLIF(?, ''), source_url),
                   description=?,
                   sale_price=COALESCE(?, sale_price),
                   rakuten_url=COALESCE(NULLIF(?, ''), rakuten_url),
                   affiliate_priority='rakuten',
                   status='active',
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (
                book.get("publisher_name") or "",
                book.get("isbn") or row["jan"],
                book.get("item_url") or "",
                rich_description,
                book.get("item_price"),
                book.get("affiliate_url") or "",
                row["id"],
            ),
        )
    upsert_book_attrs(row["id"], local_image or book.get("image_url") or "", book)
    return "updated"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-id", type=int, default=60600)
    parser.add_argument("--max-id", type=int)
    parser.add_argument("--all", action="store_true", help="repair all matching books, not only plain/empty descriptions")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env = load_env()
    counts = {"updated": 0, "not_found": 0, "dry_run": 0, "error": 0}
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = target_rows(conn, args.min_id, args.max_id, only_plain=not args.all)
        if args.limit:
            rows = rows[: args.limit]
        for idx, row in enumerate(rows, 1):
            try:
                status = repair_one(conn, env, row, dry_run=args.dry_run)
            except Exception as exc:
                status = "error"
                print("[%d/%d] id=%s error=%s %s" % (idx, len(rows), row["id"], exc, row["name"][:50]), flush=True)
            else:
                print("[%d/%d] id=%s %s %s" % (idx, len(rows), row["id"], status, row["name"][:50]), flush=True)
            counts[status] = counts.get(status, 0) + 1
            time.sleep(args.sleep)
    print("summary " + " ".join("%s=%s" % (k, v) for k, v in counts.items()))


if __name__ == "__main__":
    main()
