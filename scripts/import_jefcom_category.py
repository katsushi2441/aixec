#!/usr/bin/env python3
"""Import JEFCOM category/search pages into AIxEC.

Usage:
  python3 scripts/import_jefcom_category.py --url 'https://www.jefcom.co.jp/lineup/search?...' --name measuring
"""
import argparse
import csv
import html
import json
import mimetypes
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "storage" / "aixec.sqlite"
DATA_DIR = ROOT / "data" / "jefcom"
IMAGE_DIR = ROOT / "webapps" / "images" / "products" / "jefcom"
PUBLIC_IMAGE_PREFIX = "/images/products/jefcom"
AMAZON_BANNER = "https://www.exdirect.net/data/xdirect/image/amazon.png"
RAKUTEN_BANNER = "https://www.exdirect.net/data/xdirect/image/rakuten.png"
HEADERS = {"User-Agent": "AIxEC JEFCOM importer/1.0 (+https://aixec.exbridge.jp/)"}


def page_url(base_url, page):
    return base_url if page == 1 else base_url + ("&" if "?" in base_url else "?") + "page=%d" % page


def fetch_soup(url):
    res = requests.get(url, timeout=30, headers=HEADERS)
    if res.status_code == 404:
        return None
    res.raise_for_status()
    return BeautifulSoup(res.text, "html.parser")


def scrape_products(base_url, max_pages=200):
    items = []
    seen = set()
    for page in range(1, max_pages + 1):
        soup = fetch_soup(page_url(base_url, page))
        if soup is None:
            break
        cells = soup.select(".search-result-cell")
        if not cells:
            break
        page_added = 0
        for cell in cells:
            title_a = None
            for a in cell.select('a.ible-systemlink[href*="/lineup/"]'):
                if a.get_text(" ", strip=True):
                    title_a = a
                    break
            if title_a is None:
                title_a = cell.select_one('a.ible-systemlink[href*="/lineup/"]')
            img = cell.select_one("img")
            data = {
                "title": " ".join(title_a.get_text(" ", strip=True).split()) if title_a else "",
                "url": urljoin("https://www.jefcom.co.jp", title_a["href"]) if title_a and title_a.has_attr("href") else "",
                "image": urljoin("https://www.jefcom.co.jp", img["src"]) if img and img.has_attr("src") else "",
            }
            for dl in cell.select("dl"):
                dt = dl.find("dt")
                dd = dl.find("dd")
                if dt and dd:
                    data[" ".join(dt.get_text(" ", strip=True).split())] = " ".join(dd.get_text(" ", strip=True).split())
            status_parts = []
            for tag in cell.select(".tag .ible-part__core, .ible-part__html.tag"):
                text = " ".join(tag.get_text(" ", strip=True).split())
                if text and text not in status_parts:
                    status_parts.append(text)
            if status_parts:
                data["販売状態"] = " / ".join(status_parts)
            code = (data.get("品番") or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            items.append(data)
            page_added += 1
        print("page=%d cells=%d added=%d total=%d" % (page, len(cells), page_added, len(items)))
        time.sleep(0.15)
    return items


def save_csv(items, name):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / ("jefcom_%s.csv" % safe_slug(name))
    fields = ["品番", "JANコード", "title", "標準販売価格（税抜）", "梱数", "個口数", "入数", "発売日", "価格改定日", "販売状態", "url", "image", "local_image"]
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(items)
    return out_path


def normalize_jan(value):
    return re.sub(r"\D", "", value or "")


def is_discontinued(item):
    return "販売終了" in (item.get("販売状態") or "")


def parse_price(value):
    digits = re.sub(r"\D", "", value or "")
    return int(digits) if digits else None


def safe_slug(value):
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "").strip("._")
    return value or "category"


def image_extension(content_type, url):
    content_type = (content_type or "").split(";")[0].strip().lower()
    if content_type == "image/jpeg":
        return ".jpg"
    if content_type == "image/png":
        return ".png"
    if content_type == "image/webp":
        return ".webp"
    return mimetypes.guess_extension(content_type) or Path(urlparse(url).path).suffix or ".jpg"


def download_image(item):
    url = item.get("image") or ""
    code = item.get("品番") or ""
    if not url or not code:
        return ""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    res = requests.get(url, timeout=30, headers=HEADERS)
    res.raise_for_status()
    if not res.headers.get("Content-Type", "").lower().startswith("image/"):
        return ""
    ext = image_extension(res.headers.get("Content-Type"), url)
    path = IMAGE_DIR / ("%s_01%s" % (safe_slug(code), ext))
    path.write_bytes(res.content)
    return "%s/%s" % (PUBLIC_IMAGE_PREFIX, path.name)


def go_url(provider, keyword, model):
    params = {"to": provider, "kw": keyword, "model": model}
    return "https://aixec.exbridge.jp/go.php?" + urlencode(params)


def go_url_with_jan(provider, keyword, model, jan):
    params = {"to": provider, "kw": keyword, "model": model}
    if provider == "rakuten" and jan:
        params["jan"] = jan
    return "https://aixec.exbridge.jp/go.php?" + urlencode(params)


def build_description(item, amazon_url, rakuten_url):
    code = item.get("品番") or ""
    title = item.get("title") or code
    jan = normalize_jan(item.get("JANコード"))
    price = item.get("標準販売価格（税抜）") or ""
    official_url = item.get("url") or ""
    local_image = item.get("local_image") or item.get("image") or ""
    parts = []
    parts.append('<p style="margin-bottom:16px; padding:12px; background:#fff8f0; border:1px solid #e8a000; border-radius:4px;"><a href="%s" target="_blank" rel="nofollow sponsored noopener" style="color:#e47911; font-weight:bold;">Amazonでも商品を探してみてください →</a><br><span style="font-size:0.9em; color:#555;">上のリンクをクリックしてAmazonのサイトでも商品をご確認ください。価格を比べてみて、お得な方でご購入ください。</span></p>' % html.escape(amazon_url, quote=True))
    parts.append('<p style="margin-bottom:16px;"><a href="%s" target="_blank" rel="nofollow sponsored noopener"><img src="%s" alt="Amazonで価格をチェックする" style="max-width:100%%;"></a></p>' % (html.escape(amazon_url, quote=True), AMAZON_BANNER))
    parts.append('<p style="margin-bottom:16px; padding:12px; background:#fff7f7; border:1px solid #bf0000; border-radius:4px;"><a href="%s" target="_blank" rel="nofollow sponsored noopener" style="color:#bf0000; font-weight:bold;">楽天市場でも商品を探してみてください →</a><br><span style="font-size:0.9em; color:#555;">上のリンクをクリックして楽天市場でも商品をご確認ください。価格を比べてみて、お得な方でご購入ください。</span></p>' % html.escape(rakuten_url, quote=True))
    parts.append('<p style="margin-bottom:16px;"><a href="%s" target="_blank" rel="nofollow sponsored noopener"><img src="%s" alt="楽天市場で価格をチェックする" style="max-width:100%%;"></a></p>' % (html.escape(rakuten_url, quote=True), RAKUTEN_BANNER))
    if local_image:
        parts.append('<p><img src="%s" alt="%s" style="max-width:100%%;"></p>' % (html.escape(local_image, quote=True), html.escape(title, quote=True)))
    parts.append("<p><strong>%s</strong></p>" % html.escape(title))
    parts.append("<p>メーカー: ジェフコム<br>品番: %s<br>JANコード: %s<br>標準販売価格（税抜）: %s</p>" % (html.escape(code), html.escape(jan), html.escape(price)))
    if official_url:
        parts.append('<p><a href="%s" target="_blank" rel="noopener noreferrer">ジェフコム公式商品ページ</a></p>' % html.escape(official_url, quote=True))
    return "".join(parts)


def find_existing(conn, code, jan):
    if jan:
        row = conn.execute("SELECT * FROM products WHERE jan=? OR gtin=? LIMIT 1", (jan, jan)).fetchone()
        if row:
            return row
    row = conn.execute("SELECT * FROM products WHERE internal_sku=? LIMIT 1", ("jefcom_official:" + code,)).fetchone()
    if row:
        return row
    row = conn.execute(
        "SELECT p.* FROM products p JOIN product_identifiers i ON i.product_id=p.id WHERE i.id_type='jefcom_model' AND i.id_value=? LIMIT 1",
        (code,),
    ).fetchone()
    if row:
        return row
    return conn.execute(
        """SELECT * FROM products
           WHERE maker='ジェフコム'
             AND (
               model_number=?
               OR model_number LIKE ?
               OR name LIKE ?
             )
           LIMIT 1""",
        (code, "%-" + code, code + " %"),
    ).fetchone()


def upsert_attr(conn, product_id, name, value):
    if value:
        conn.execute(
            """INSERT INTO product_attributes(product_id,attr_name,attr_value,source,created_at,updated_at)
               VALUES(?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
               ON CONFLICT(product_id,attr_name,source) DO UPDATE SET attr_value=excluded.attr_value, updated_at=CURRENT_TIMESTAMP""",
            (product_id, name, str(value), "jefcom_official"),
        )


def mark_existing_and_skips(items, include_discontinued=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    for item in items:
        code = (item.get("品番") or "").strip()
        jan = normalize_jan(item.get("JANコード"))
        existing = find_existing(conn, code, jan) if code else None
        item["_existing_internal_sku"] = existing["internal_sku"] if existing else ""
        item["_skip_new_discontinued"] = bool(is_discontinued(item) and not existing and not include_discontinued)
    conn.close()


def update_db(items, category_name, include_discontinued=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    matched = updated = inserted = skipped = 0
    with conn:
        for item in items:
            code = (item.get("品番") or "").strip()
            jan = normalize_jan(item.get("JANコード"))
            if not code:
                skipped += 1
                continue
            if item.get("_skip_new_discontinued"):
                skipped += 1
                continue
            title = item.get("title") or code
            name = "%s %s" % (code, title)
            keyword = "ジェフコム %s %s" % (code, title)
            amazon_url = go_url("amazon", keyword, code)
            rakuten_url = go_url_with_jan("rakuten", keyword, code, jan)
            description = build_description(item, amazon_url, rakuten_url)
            existing = find_existing(conn, code, jan)
            if is_discontinued(item) and not existing and not include_discontinued:
                skipped += 1
                continue
            payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            if existing:
                product_id = existing["id"]
                matched += 1
                conn.execute(
                    """UPDATE products SET
                       jan=COALESCE(NULLIF(?,''), jan),
                       gtin=COALESCE(NULLIF(?,''), gtin),
                       amazon_url=?, rakuten_url=?,
                       source_url=COALESCE(NULLIF(source_url,''), ?),
                       description=CASE WHEN COALESCE(description,'')='' THEN ? ELSE description END,
                       status='active', updated_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (jan, jan, amazon_url, rakuten_url, item.get("url") or "", description, product_id),
                )
                updated += 1
            else:
                cur = conn.execute(
                    """INSERT INTO products
                       (internal_sku, jan, gtin, maker, model_number, name, source_url, description,
                        sale_price, amazon_url, rakuten_url, affiliate_priority, status,
                        created_at, updated_at)
                       VALUES (?, ?, ?, 'ジェフコム', ?, ?, ?, ?, ?, ?, ?, 'auto', 'active',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                    ("jefcom_official:" + code, jan, jan, code, name, item.get("url") or "", description, parse_price(item.get("標準販売価格（税抜）")), amazon_url, rakuten_url),
                )
                product_id = cur.lastrowid
                inserted += 1
            for id_type, id_value in (("jan", jan), ("gtin", jan), ("jefcom_model", code)):
                if id_value:
                    conn.execute("INSERT OR IGNORE INTO product_identifiers(product_id,id_type,id_value,source) VALUES(?,?,?,'jefcom_official')", (product_id, id_type, id_value))
            upsert_attr(conn, product_id, "jefcom_official_url", item.get("url"))
            if item.get("local_image"):
                upsert_attr(conn, product_id, "jefcom_image", item.get("local_image"))
            upsert_attr(conn, product_id, "jefcom_source_image", item.get("image"))
            upsert_attr(conn, product_id, "jefcom_list_price", item.get("標準販売価格（税抜）"))
            upsert_attr(conn, product_id, "jefcom_release_date", item.get("発売日"))
            upsert_attr(conn, product_id, "jefcom_sales_status", item.get("販売状態"))
            upsert_attr(conn, product_id, "jefcom_category_import", category_name)
            conn.execute(
                """INSERT INTO channel_payloads(product_id, channel, external_id, payload_json, created_at, updated_at)
                   VALUES(?, 'jefcom_official', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                   ON CONFLICT(channel, external_id) DO UPDATE SET product_id=excluded.product_id, payload_json=excluded.payload_json, updated_at=CURRENT_TIMESTAMP""",
                (product_id, code, payload),
            )
    return matched, updated, inserted, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--no-db", action="store_true")
    parser.add_argument("--no-images", action="store_true")
    parser.add_argument("--include-discontinued", action="store_true")
    args = parser.parse_args()

    items = scrape_products(args.url, max_pages=args.max_pages)
    mark_existing_and_skips(items, include_discontinued=args.include_discontinued)
    if not args.no_images:
        for idx, item in enumerate(items, 1):
            if item.get("_skip_new_discontinued"):
                print("image_skip_discontinued=%d/%d code=%s" % (idx, len(items), item.get("品番")))
                continue
            try:
                item["local_image"] = download_image(item)
                print("image=%d/%d %s" % (idx, len(items), item.get("local_image") or ""))
                time.sleep(0.1)
            except Exception as exc:
                item["local_image"] = ""
                print("image_failed=%d/%d code=%s error=%s" % (idx, len(items), item.get("品番"), exc))
    out_path = save_csv(items, args.name)
    matched = updated = inserted = skipped = 0
    if not args.no_db:
        matched, updated, inserted, skipped = update_db(items, args.name, include_discontinued=args.include_discontinued)
    jan_count = sum(1 for item in items if normalize_jan(item.get("JANコード")))
    print("saved=%s" % out_path)
    print("scraped=%d jan=%d matched=%d updated=%d inserted=%d skipped=%d" % (len(items), jan_count, matched, updated, inserted, skipped))


if __name__ == "__main__":
    main()
