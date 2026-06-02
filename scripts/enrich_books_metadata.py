#!/usr/bin/env python3
"""Enrich Rakuten Books products with openBD and Google Books metadata."""
import argparse
import html
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "storage" / "aixec.sqlite"
OPENBD_ENDPOINT = os.environ.get("OPENBD_ENDPOINT", "https://api.openbd.jp/v1/get")
GOOGLE_BOOKS_ENDPOINT = os.environ.get("GOOGLE_BOOKS_ENDPOINT", "https://www.googleapis.com/books/v1/volumes")
GOOGLE_BOOKS_DELAY = float(os.environ.get("GOOGLE_BOOKS_DELAY", "5.0"))


def connect():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def fetch_json(url, retries=3, sleep=1.0):
    req = Request(url, headers={"User-Agent": "AIxEC/0.1"})
    for attempt in range(1, retries + 1):
        try:
            with urlopen(req, timeout=25) as res:
                return json.loads(res.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if attempt < retries and exc.code in (429, 500, 502, 503, 504):
                time.sleep(sleep * attempt)
                continue
            raise RuntimeError("HTTP %s: %s" % (exc.code, detail[:200]))
        except URLError as exc:
            if attempt < retries:
                time.sleep(sleep * attempt)
                continue
            raise RuntimeError(str(exc))


def text_from(value):
    if isinstance(value, dict):
        return str(value.get("content") or "").strip()
    if value is None:
        return ""
    return str(value).strip()


def openbd_text_content(entry):
    onix = (entry or {}).get("onix") or {}
    collateral = onix.get("CollateralDetail") or {}
    texts = collateral.get("TextContent") or []
    if isinstance(texts, dict):
        texts = [texts]
    candidates = []
    for text in texts:
        body = text_from(text.get("Text"))
        if not body:
            continue
        text_type = str(text.get("TextType") or "")
        candidates.append((text_type, body))
    # 03/02 are commonly description/short description in ONIX data.
    for preferred in ("03", "02"):
        for text_type, body in candidates:
            if text_type == preferred:
                return body
    return candidates[0][1] if candidates else ""


def openbd_lookup(isbn):
    url = OPENBD_ENDPOINT + "?" + urlencode({"isbn": isbn})
    data = fetch_json(url)
    if not data or not isinstance(data, list) or data[0] is None:
        return {}
    entry = data[0]
    summary = entry.get("summary") or {}
    return {
        "raw": entry,
        "description": openbd_text_content(entry),
        "cover": summary.get("cover") or "",
        "title": summary.get("title") or "",
        "author": summary.get("author") or "",
        "publisher": summary.get("publisher") or "",
        "pubdate": summary.get("pubdate") or "",
    }


def google_lookup(isbn):
    url = GOOGLE_BOOKS_ENDPOINT + "?" + urlencode({"q": "isbn:" + isbn, "country": "JP"})
    data = fetch_json(url)
    items = data.get("items") or []
    if not items:
        return {}
    item = items[0]
    info = item.get("volumeInfo") or {}
    images = info.get("imageLinks") or {}
    return {
        "raw": item,
        "description": info.get("description") or "",
        "cover": images.get("large") or images.get("medium") or images.get("small") or images.get("thumbnail") or "",
        "title": info.get("title") or "",
        "subtitle": info.get("subtitle") or "",
        "authors": ", ".join(info.get("authors") or []),
        "publisher": info.get("publisher") or "",
        "published_date": info.get("publishedDate") or "",
        "categories": ", ".join(info.get("categories") or []),
        "google_volume_id": item.get("id") or "",
        "preview_link": info.get("previewLink") or "",
    }


def upsert_attr(conn, product_id, name, value, source):
    if value is None or value == "":
        return
    conn.execute(
        """INSERT INTO product_attributes (product_id, attr_name, attr_value, source, created_at, updated_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
           ON CONFLICT(product_id, attr_name, source)
           DO UPDATE SET attr_value=excluded.attr_value, updated_at=CURRENT_TIMESTAMP""",
        (product_id, name, str(value), source),
    )


def upsert_payload(conn, product_id, channel, external_id, payload):
    conn.execute(
        """INSERT INTO channel_payloads (product_id, channel, external_id, payload_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
           ON CONFLICT(channel, external_id)
           DO UPDATE SET payload_json=excluded.payload_json, updated_at=CURRENT_TIMESTAMP""",
        (product_id, channel, external_id, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
    )


def clean_description(text):
    text = str(text or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?is)<script.*?</script>", "", text)
    text = re.sub(r"(?is)<style.*?</style>", "", text)
    text = re.sub(r"(?i)<br\\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_description(row, image_url, enriched_text, source_label):
    title = html.escape(row["name"] or "")
    author = html.escape(row["book_author"] or "")
    publisher = html.escape(row["maker"] or "")
    isbn = html.escape(row["jan"] or "")
    rakuten = html.escape(rakuten_go_url(row), quote=True)
    parts = [
        '<p style="margin-bottom:16px; padding:12px; background:#fff7f7; border:1px solid #bf0000; border-radius:4px;">'
        '<a href="%s" target="_blank" rel="nofollow sponsored noopener" style="color:#bf0000; font-weight:bold;">楽天でこの本を見る →</a><br>'
        '<span style="font-size:0.9em; color:#555;">楽天ブックスの商品ページで価格・在庫・電子書籍版をご確認ください。</span>'
        "</p>" % rakuten,
    ]
    if image_url:
        parts.append('<p><img src="%s" alt="%s" style="max-width:100%%;"></p>' % (html.escape(image_url), title))
    parts.append("<p><strong>%s</strong></p>" % title)
    meta = []
    if author:
        meta.append("著者: %s" % author)
    if publisher:
        meta.append("出版社: %s" % publisher)
    if isbn:
        meta.append("ISBN/JAN: %s" % isbn)
    if row["book_source"] == "kobo":
        meta.append("形式: 電子書籍")
    else:
        meta.append("形式: 書籍")
    if source_label:
        meta.append("内容紹介: %s" % html.escape(source_label))
    parts.append("<p>%s</p>" % "<br>".join(meta))
    if enriched_text:
        escaped = html.escape(enriched_text).replace("\n", "<br>")
        parts.append("<p>%s</p>" % escaped)
    return "".join(parts)


def rakuten_go_url(row):
    params = {"to": "rakuten", "kw": row["name"] or "本"}
    if row["jan"]:
        params["jan"] = row["jan"]
        params["model"] = row["jan"]
    elif row["model_number"]:
        params["model"] = row["model_number"]
    if row["id"]:
        params["pid"] = row["id"]
    return "/go.php?" + urlencode(params)


def load_books(conn, limit=None, offset=0, only_missing=False, min_id=None, max_id=None):
    where = ["p.internal_sku LIKE 'rakuten_books:%'", "p.jan IS NOT NULL", "p.jan != ''"]
    params = []
    if only_missing:
        where.append(
            "NOT EXISTS (SELECT 1 FROM product_attributes x WHERE x.product_id=p.id AND x.attr_name='book_description_source')"
        )
    if min_id is not None:
        where.append("p.id >= ?")
        params.append(min_id)
    if max_id is not None:
        where.append("p.id <= ?")
        params.append(max_id)
    sql = """
        SELECT p.*,
               MAX(CASE WHEN a.attr_name='book_image' THEN a.attr_value END) AS book_image,
               MAX(CASE WHEN a.attr_name='book_author' THEN a.attr_value END) AS book_author,
               MAX(CASE WHEN a.attr_name='book_source' THEN a.attr_value END) AS book_source,
               MAX(CASE WHEN a.attr_name='book_description_rakuten' THEN a.attr_value END) AS book_description_rakuten
        FROM products p
        LEFT JOIN product_attributes a ON a.product_id=p.id
        WHERE %s
        GROUP BY p.id
        ORDER BY p.id
        LIMIT ? OFFSET ?
    """ % " AND ".join(where)
    if limit is None:
        limit = 1000000
    params.extend([limit, offset])
    return conn.execute(sql, params).fetchall()


def enrich_one(conn, row, dry_run=False):
    isbn = re.sub(r"\D", "", row["jan"] or "")
    stats = {"openbd_hit": 0, "google_hit": 0, "description": 0, "updated": 0}
    openbd = {}
    google = {}
    try:
        openbd = openbd_lookup(isbn)
    except Exception as exc:
        upsert_attr(conn, row["id"], "book_openbd_error", str(exc)[:500], "metadata_enrich")
    if GOOGLE_BOOKS_DELAY > 0:
        time.sleep(GOOGLE_BOOKS_DELAY)
    try:
        google = google_lookup(isbn)
    except Exception as exc:
        upsert_attr(conn, row["id"], "book_google_error", str(exc)[:500], "metadata_enrich")
    if openbd:
        stats["openbd_hit"] = 1
    if google:
        stats["google_hit"] = 1

    openbd_desc = clean_description(openbd.get("description", ""))
    google_desc = clean_description(google.get("description", ""))
    rakuten_desc = clean_description(row["book_description_rakuten"] if "book_description_rakuten" in row.keys() else "")
    source = ""
    selected = ""
    if openbd_desc:
        selected = openbd_desc
        source = "openBD"
    elif google_desc:
        selected = google_desc
        source = "Google Books"
    elif rakuten_desc:
        selected = rakuten_desc
        source = "楽天ブックス"

    if not dry_run:
        with conn:
            if openbd:
                upsert_payload(conn, row["id"], "openbd", isbn, openbd.get("raw") or openbd)
                for key in ("title", "author", "publisher", "pubdate", "cover"):
                    upsert_attr(conn, row["id"], "book_openbd_" + key, openbd.get(key), "metadata_enrich")
                if openbd_desc:
                    upsert_attr(conn, row["id"], "book_description_openbd", openbd_desc, "metadata_enrich")
            if google:
                upsert_payload(conn, row["id"], "google_books", isbn, google.get("raw") or google)
                for key in ("title", "subtitle", "authors", "publisher", "published_date", "categories", "cover", "google_volume_id", "preview_link"):
                    upsert_attr(conn, row["id"], "book_google_" + key, google.get(key), "metadata_enrich")
                if google_desc:
                    upsert_attr(conn, row["id"], "book_description_google", google_desc, "metadata_enrich")
            image_url = row["book_image"] or ""
            desc = build_description(row, image_url, selected, source)
            conn.execute(
                "UPDATE products SET description=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (desc, row["id"]),
            )
            upsert_attr(conn, row["id"], "book_description_source", source or "basic", "metadata_enrich")
            stats["description"] = 1
            stats["updated"] = 1
    else:
        stats["description"] = 1
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--min-id", type=int)
    parser.add_argument("--max-id", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=5.0)
    args = parser.parse_args()
    totals = {"rows": 0, "openbd_hit": 0, "google_hit": 0, "description": 0, "updated": 0}
    with connect() as conn:
        rows = load_books(conn, args.limit, args.offset, args.only_missing, args.min_id, args.max_id)
        for row in rows:
            totals["rows"] += 1
            stats = enrich_one(conn, row, dry_run=args.dry_run)
            for key in stats:
                totals[key] += stats[key]
            print(
                "[%d/%d] id=%s isbn=%s openbd=%d google=%d desc=%d %s"
                % (totals["rows"], len(rows), row["id"], row["jan"], stats["openbd_hit"], stats["google_hit"], stats["description"], row["name"][:60])
            )
            time.sleep(args.sleep)
    print("summary " + " ".join("%s=%s" % (k, v) for k, v in totals.items()))


if __name__ == "__main__":
    main()
