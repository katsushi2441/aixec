#!/usr/bin/env python3
"""Import programming/IT/crypto books from Rakuten Books APIs into AIxEC."""
import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "storage" / "aixec.sqlite"
IMAGE_DIR = ROOT / "webapps" / "images" / "products" / "books"

BOOK_ENDPOINT = os.environ.get(
    "RAKUTEN_BOOK_SEARCH_ENDPOINT",
    "https://openapi.rakuten.co.jp/services/api/BooksBook/Search/20170404",
)
KOBO_ENDPOINT = os.environ.get(
    "RAKUTEN_KOBO_SEARCH_ENDPOINT",
    "https://openapi.rakuten.co.jp/services/api/Kobo/EbookSearch/20170426",
)

DEFAULT_KEYWORDS = [
    "バイブコーディング",
    "生成AI プログラミング",
    "ChatGPT プログラミング",
    "Python プログラミング",
    "JavaScript TypeScript",
    "React Next.js",
    "Laravel PHP",
    "データベース SQL",
    "Linux サーバー",
    "IT エンジニア",
    "暗号資産",
    "ブロックチェーン",
    "Web3",
]


def env_file(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def credentials():
    app_id = os.environ.get("RAKUTEN_APPLICATION_ID") or os.environ.get("RAKUTEN_APP_ID")
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY")
    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID")
    if not app_id:
        raise SystemExit("RAKUTEN_APPLICATION_ID is not set")
    if not access_key:
        raise SystemExit("RAKUTEN_ACCESS_KEY is not set")
    return app_id, access_key, affiliate_id


def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def fetch_json(endpoint, params):
    app_id, access_key, affiliate_id = credentials()
    payload = {
        "applicationId": app_id,
        "accessKey": access_key,
        "format": "json",
        "formatVersion": "2",
    }
    if affiliate_id:
        payload["affiliateId"] = affiliate_id
    payload.update(params)
    url = endpoint + "?" + urlencode(payload)
    request_origin = os.environ.get("RAKUTEN_REFERER", "https://aixec.exbridge.jp").rstrip("/")
    req = Request(url, headers={
        "User-Agent": "AIxEC/0.1",
        "Referer": request_origin + "/",
        "Origin": request_origin,
        "accessKey": access_key,
    })
    for attempt in range(1, 6):
        try:
            with urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < 5:
                wait = attempt * 2
                print("rate_limit wait=%ds" % wait)
                time.sleep(wait)
                continue
            raise RuntimeError("Rakuten API HTTP %s: %s" % (exc.code, detail[:300]))
        except URLError as exc:
            if attempt < 5:
                time.sleep(attempt * 2)
                continue
            raise RuntimeError("Rakuten API failed: %s" % exc)
    raise RuntimeError("Rakuten API failed")


def first_value(item, names):
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            return value
    return ""


def normalize_item(raw, source, keyword):
    item = raw.get("Item", raw) if isinstance(raw, dict) else {}
    title = first_value(item, ["title", "itemName"])
    author = first_value(item, ["author", "authorName"])
    publisher = first_value(item, ["publisherName", "publisher"])
    isbn = re.sub(r"\D", "", str(first_value(item, ["isbn", "jan", "itemNumber"])))
    item_code = str(first_value(item, ["itemCode", "itemNumber"]))
    url = first_value(item, ["itemUrl"])
    affiliate_url = first_value(item, ["affiliateUrl"]) or url
    price = first_value(item, ["itemPrice"])
    caption = first_value(item, ["itemCaption", "caption", "salesDate"])
    sales_date = first_value(item, ["salesDate"])
    image = first_value(item, ["largeImageUrl", "mediumImageUrl", "smallImageUrl"])
    if not image:
        images = item.get("mediumImageUrls") or item.get("smallImageUrls") or []
        if images:
            first = images[0]
            image = first.get("imageUrl") if isinstance(first, dict) else str(first)
    if image:
        image = re.sub(r"\?_ex=\d+x\d+$", "", str(image))
    return {
        "source": source,
        "keyword": keyword,
        "title": str(title or "").strip(),
        "author": str(author or "").strip(),
        "publisher": str(publisher or "").strip(),
        "isbn": isbn,
        "item_code": item_code.strip(),
        "item_url": str(url or "").strip(),
        "affiliate_url": str(affiliate_url or "").strip(),
        "price": int(price) if str(price).isdigit() else None,
        "caption": str(caption or "").strip(),
        "sales_date": str(sales_date or "").strip(),
        "image_url": str(image or "").strip(),
        "raw": item,
    }


def search_books(keyword, source, page, hits):
    if source == "book":
        endpoint = BOOK_ENDPOINT
        params = {"title": keyword, "page": str(page), "hits": str(hits), "sort": "-releaseDate"}
    else:
        endpoint = KOBO_ENDPOINT
        params = {"keyword": keyword, "page": str(page), "hits": str(hits), "sort": "-releaseDate"}
    data = fetch_json(endpoint, params)
    items = data.get("Items") or []
    return [normalize_item(item, source, keyword) for item in items]


def image_ext(url):
    path = urlparse(url).path.lower()
    if path.endswith(".png"):
        return ".png"
    if path.endswith(".webp"):
        return ".webp"
    return ".jpg"


def image_basename(book):
    key = book["isbn"] or book["item_code"] or book["title"] or json.dumps(book["raw"], ensure_ascii=False)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", key).strip("-")
    if not safe:
        safe = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return safe[:80]


def download_image(book):
    url = book.get("image_url") or ""
    if not url:
        return ""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    rel = "/images/products/books/" + image_basename(book) + image_ext(url)
    dest = ROOT / "webapps" / rel.lstrip("/")
    if dest.exists() and dest.stat().st_size > 0:
        return rel
    req = Request(url, headers={"User-Agent": "AIxEC/0.1"})
    try:
        with urlopen(req, timeout=30) as res:
            data = res.read()
        if data:
            dest.write_bytes(data)
            return rel
    except Exception as exc:
        print("image_error %s %s" % (book.get("isbn") or book.get("title"), exc))
    return ""


def rakuten_go_url(book):
    params = {
        "to": "rakuten",
        "kw": book["title"] or "本",
    }
    if book.get("isbn"):
        params["jan"] = book["isbn"]
        params["model"] = book["isbn"]
    elif book.get("item_code"):
        params["model"] = book["item_code"]
    return "/go.php?" + urlencode(params)


def description(book, local_image):
    title = html.escape(book["title"])
    author = html.escape(book["author"])
    publisher = html.escape(book["publisher"])
    isbn = html.escape(book["isbn"])
    caption = html.escape(book["caption"])
    rakuten = html.escape(rakuten_go_url(book), quote=True)
    parts = []
    if rakuten:
        parts.append(
            '<p style="margin-bottom:16px; padding:12px; background:#fff7f7; border:1px solid #bf0000; border-radius:4px;">'
            '<a href="%s" target="_blank" rel="nofollow sponsored noopener" style="color:#bf0000; font-weight:bold;">楽天でこの本を見る →</a><br>'
            '<span style="font-size:0.9em; color:#555;">楽天ブックスの商品ページで価格・在庫・電子書籍版をご確認ください。</span>'
            '</p>' % rakuten
        )
    if local_image:
        parts.append('<p><img src="%s" alt="%s" style="max-width:100%%;"></p>' % (html.escape(local_image), title))
    parts.append("<p><strong>%s</strong></p>" % title)
    meta = []
    if author:
        meta.append("著者: %s" % author)
    if publisher:
        meta.append("出版社: %s" % publisher)
    if isbn:
        meta.append("ISBN/JAN: %s" % isbn)
    if book["source"] == "kobo":
        meta.append("形式: 電子書籍")
    else:
        meta.append("形式: 書籍")
    parts.append("<p>%s</p>" % "<br>".join(meta))
    if caption:
        parts.append("<p>%s</p>" % caption)
    return "".join(parts)


def resolve_existing(conn, book):
    for value in (book["isbn"], book["item_code"]):
        if not value:
            continue
        row = conn.execute(
            "SELECT p.* FROM products p LEFT JOIN product_identifiers i ON i.product_id=p.id "
            "WHERE p.jan=? OR p.gtin=? OR p.internal_sku=? OR i.id_value=? LIMIT 1",
            (value, value, "rakuten_books:" + value, value),
        ).fetchone()
        if row:
            return row
    return None


def upsert_book(conn, book, local_image):
    sku_key = book["isbn"] or book["item_code"] or hashlib.sha1(book["title"].encode("utf-8")).hexdigest()[:16]
    internal_sku = "rakuten_books:" + sku_key
    maker = book["publisher"] or ("楽天Kobo" if book["source"] == "kobo" else "楽天ブックス")
    model = book["isbn"] or book["item_code"]
    name = book["title"]
    desc = description(book, local_image)
    existing = resolve_existing(conn, book)
    payload = json.dumps(book["raw"], ensure_ascii=False, separators=(",", ":"))
    with conn:
        if existing:
            product_id = existing["id"]
            conn.execute(
                """UPDATE products SET
                   internal_sku=COALESCE(NULLIF(?,''), internal_sku),
                   jan=COALESCE(NULLIF(?,''), jan),
                   gtin=COALESCE(NULLIF(?,''), gtin),
                   maker=?, model_number=?, name=?, source_url=?, description=?,
                   sale_price=COALESCE(?, sale_price), rakuten_url=?,
                   affiliate_priority='rakuten', status='active', updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (internal_sku, book["isbn"], book["isbn"], maker, model, name, book["item_url"], desc, book["price"], book["affiliate_url"], product_id),
            )
            changed = "updated"
        else:
            cur = conn.execute(
                """INSERT INTO products
                   (internal_sku, jan, gtin, maker, model_number, name, source_url, description,
                    sale_price, rakuten_url, affiliate_priority, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'rakuten', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (internal_sku, book["isbn"], book["isbn"], maker, model, name, book["item_url"], desc, book["price"], book["affiliate_url"]),
            )
            product_id = cur.lastrowid
            changed = "inserted"
        for id_type, id_value in (("isbn", book["isbn"]), ("jan", book["isbn"]), ("gtin", book["isbn"]), ("rakuten_item_code", book["item_code"])):
            if id_value:
                conn.execute(
                    "INSERT OR IGNORE INTO product_identifiers (product_id, id_type, id_value, source) VALUES (?, ?, ?, 'rakuten_books')",
                    (product_id, id_type, id_value),
                )
        attrs = {
            "book_image": local_image,
            "book_author": book["author"],
            "book_publisher": book["publisher"],
            "book_source": book["source"],
            "book_keyword": book["keyword"],
            "book_sales_date": book["sales_date"],
        }
        for key, value in attrs.items():
            if value:
                conn.execute(
                    """INSERT INTO product_attributes (product_id, attr_name, attr_value, source, created_at, updated_at)
                       VALUES (?, ?, ?, 'rakuten_books', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                       ON CONFLICT(product_id, attr_name, source)
                       DO UPDATE SET attr_value=excluded.attr_value, updated_at=CURRENT_TIMESTAMP""",
                    (product_id, key, str(value)),
                )
        conn.execute(
            """INSERT INTO channel_payloads (product_id, channel, external_id, payload_json, created_at, updated_at)
               VALUES (?, 'rakuten_books', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
               ON CONFLICT(channel, external_id)
               DO UPDATE SET payload_json=excluded.payload_json, updated_at=CURRENT_TIMESTAMP""",
            (product_id, book["item_code"] or book["isbn"] or str(product_id), payload),
        )
    return changed


def main():
    env_file(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--keywords", help="comma separated keywords")
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--hits", type=int, default=30)
    parser.add_argument("--source", choices=["all", "book", "kobo"], default="all")
    parser.add_argument("--sleep", type=float, default=0.35)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    keywords = [k.strip() for k in (args.keywords.split(",") if args.keywords else DEFAULT_KEYWORDS) if k.strip()]
    sources = ["book", "kobo"] if args.source == "all" else [args.source]
    stats = {"scraped": 0, "inserted": 0, "updated": 0, "image": 0}
    seen = set()
    with connect() as conn:
        for source in sources:
            for keyword in keywords:
                for page in range(1, args.max_pages + 1):
                    items = search_books(keyword, source, page, args.hits)
                    print("source=%s keyword=%s page=%d items=%d" % (source, keyword, page, len(items)))
                    if not items:
                        break
                    for book in items:
                        key = (book["source"], book["isbn"] or book["item_code"] or book["title"])
                        if key in seen or not book["title"]:
                            continue
                        seen.add(key)
                        stats["scraped"] += 1
                        local_image = download_image(book)
                        if local_image:
                            stats["image"] += 1
                        if args.dry_run:
                            continue
                        changed = upsert_book(conn, book, local_image)
                        stats[changed] += 1
                    time.sleep(args.sleep)
    print("scraped=%d inserted=%d updated=%d image=%d" % (stats["scraped"], stats["inserted"], stats["updated"], stats["image"]))


if __name__ == "__main__":
    main()
