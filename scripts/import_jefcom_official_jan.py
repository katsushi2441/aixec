#!/usr/bin/env python3
import csv
import html
import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "storage" / "aixec.sqlite"
OUT_PATH = ROOT / "data" / "jefcom_official_products.csv"
AMAZON_BANNER = "https://www.exdirect.net/data/xdirect/image/amazon.png"
RAKUTEN_BANNER = "https://www.exdirect.net/data/xdirect/image/rakuten.png"
BASE_URL = (
    "https://www.jefcom.co.jp/lineup/search"
    "?ible-searchKeyword=&ible-textbox1=&ible-rangeinput1_from=&ible-rangeinput1_to="
    "&ible-rangeinput2_from=&ible-rangeinput2_to=&ible-checkboxsolo17=1"
    "&formid=shared-area6.formgrid1col2-form"
)


def fetch_page(page):
    url = BASE_URL if page == 1 else BASE_URL + "&page=%d" % page
    res = requests.get(url, timeout=20)
    if res.status_code == 404:
        return None
    res.raise_for_status()
    return BeautifulSoup(res.text, "html.parser")


def scrape_products():
    items = []
    for page in range(1, 200):
        soup = fetch_page(page)
        if soup is None:
            break
        cells = soup.select(".search-result-cell")
        if not cells:
            break
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
            if data.get("品番") and data.get("JANコード"):
                items.append(data)
        print("page=%d items=%d total=%d" % (page, len(cells), len(items)))
        time.sleep(0.1)
    return items


def save_csv(items):
    fields = ["品番", "JANコード", "title", "標準販売価格（税抜）", "梱数", "個口数", "入数", "発売日", "価格改定日", "url", "image"]
    with OUT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(items)


def normalize_jan(value):
    return re.sub(r"\D", "", value or "")


def parse_price(value):
    digits = re.sub(r"\D", "", value or "")
    return int(digits) if digits else None


def go_url(provider, keyword, model):
    return "https://aixec.exbridge.jp/go.php?" + urlencode({
        "to": provider,
        "kw": keyword,
        "model": model,
    })


def build_description(item, amazon_url, rakuten_url):
    code = item.get("品番") or ""
    title = item.get("title") or code
    jan = normalize_jan(item.get("JANコード"))
    price = item.get("標準販売価格（税抜）") or ""
    official_url = item.get("url") or ""
    image = item.get("image") or ""
    parts = []
    parts.append('<p style="margin-bottom:16px; padding:12px; background:#fff8f0; border:1px solid #e8a000; border-radius:4px;"><a href="%s" target="_blank" rel="nofollow sponsored noopener" style="color:#e47911; font-weight:bold;">Amazonでも商品を探してみてください →</a><br><span style="font-size:0.9em; color:#555;">上のリンクをクリックしてAmazonのサイトでも商品をご確認ください。価格を比べてみて、お得な方でご購入ください。</span></p>' % html.escape(amazon_url, quote=True))
    parts.append('<p style="margin-bottom:16px;"><a href="%s" target="_blank" rel="nofollow sponsored noopener"><img src="%s" alt="Amazonで価格をチェックする" style="max-width:100%%;"></a></p>' % (html.escape(amazon_url, quote=True), AMAZON_BANNER))
    parts.append('<p style="margin-bottom:16px; padding:12px; background:#fff7f7; border:1px solid #bf0000; border-radius:4px;"><a href="%s" target="_blank" rel="nofollow sponsored noopener" style="color:#bf0000; font-weight:bold;">楽天市場でも商品を探してみてください →</a><br><span style="font-size:0.9em; color:#555;">上のリンクをクリックして楽天市場でも商品をご確認ください。価格を比べてみて、お得な方でご購入ください。</span></p>' % html.escape(rakuten_url, quote=True))
    parts.append('<p style="margin-bottom:16px;"><a href="%s" target="_blank" rel="nofollow sponsored noopener"><img src="%s" alt="楽天市場で価格をチェックする" style="max-width:100%%;"></a></p>' % (html.escape(rakuten_url, quote=True), RAKUTEN_BANNER))
    if image:
        parts.append('<p><img src="%s" alt="%s" style="max-width:100%%;"></p>' % (html.escape(image, quote=True), html.escape(title, quote=True)))
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
    internal_sku = "jefcom_official:" + code
    row = conn.execute("SELECT * FROM products WHERE internal_sku=? LIMIT 1", (internal_sku,)).fetchone()
    if row:
        return row
    row = conn.execute(
        "SELECT p.* FROM products p JOIN product_identifiers i ON i.product_id=p.id WHERE i.id_type='jefcom_model' AND i.id_value=? LIMIT 1",
        (code,),
    ).fetchone()
    if row:
        return row
    return conn.execute(
        """
        SELECT * FROM products
        WHERE maker='ジェフコム'
          AND (model_number=? OR model_number LIKE ? OR name LIKE ? OR name LIKE ?)
        LIMIT 1
        """,
        (code, "%-" + code, code + " %", "% " + code + " %"),
    ).fetchone()


def update_db(items):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    matched = 0
    updated = 0
    inserted = 0
    skipped = 0
    with conn:
        for item in items:
            code = (item.get("品番") or "").strip()
            jan = normalize_jan(item.get("JANコード"))
            if not code or not jan:
                skipped += 1
                continue
            title = item.get("title") or code
            name = "%s %s" % (code, title)
            keyword = "ジェフコム %s %s" % (code, title)
            amazon_url = go_url("amazon", keyword, code)
            rakuten_url = go_url("rakuten", keyword, code)
            description = build_description(item, amazon_url, rakuten_url)
            existing = find_existing(conn, code, jan)
            payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            if existing:
                product_id = existing["id"]
                matched += 1
                conn.execute(
                    """UPDATE products SET
                       jan=?, gtin=?, amazon_url=?, rakuten_url=?,
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
                    (
                        "jefcom_official:" + code,
                        jan,
                        jan,
                        code,
                        name,
                        item.get("url") or "",
                        description,
                        parse_price(item.get("標準販売価格（税抜）")),
                        amazon_url,
                        rakuten_url,
                    ),
                )
                product_id = cur.lastrowid
                inserted += 1
            conn.execute(
                "INSERT OR IGNORE INTO product_identifiers(product_id,id_type,id_value,source) VALUES(?,?,?,'jefcom_official')",
                (product_id, "jan", jan),
            )
            conn.execute(
                "INSERT OR IGNORE INTO product_identifiers(product_id,id_type,id_value,source) VALUES(?,?,?,'jefcom_official')",
                (product_id, "gtin", jan),
            )
            conn.execute(
                "INSERT OR IGNORE INTO product_identifiers(product_id,id_type,id_value,source) VALUES(?,?,?,'jefcom_official')",
                (product_id, "jefcom_model", code),
            )
            for attr_name, attr_value in {
                "jefcom_official_url": item.get("url"),
                "jefcom_image": item.get("image"),
                "jefcom_list_price": item.get("標準販売価格（税抜）"),
                "jefcom_release_date": item.get("発売日"),
            }.items():
                if attr_value:
                    conn.execute(
                        """INSERT INTO product_attributes(product_id,attr_name,attr_value,source,created_at,updated_at)
                           VALUES(?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                           ON CONFLICT(product_id,attr_name,source) DO UPDATE SET attr_value=excluded.attr_value, updated_at=CURRENT_TIMESTAMP""",
                        (product_id, attr_name, str(attr_value), "jefcom_official"),
                    )
            conn.execute(
                """INSERT INTO channel_payloads(product_id, channel, external_id, payload_json, created_at, updated_at)
                   VALUES(?, 'jefcom_official', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                   ON CONFLICT(channel, external_id) DO UPDATE SET product_id=excluded.product_id, payload_json=excluded.payload_json, updated_at=CURRENT_TIMESTAMP""",
                (product_id, code, payload),
            )
    return matched, updated, inserted, skipped


def main():
    items = scrape_products()
    save_csv(items)
    matched, updated, inserted, skipped = update_db(items)
    jan_count = sum(1 for item in items if normalize_jan(item.get("JANコード")))
    print("saved=%s" % OUT_PATH)
    print("scraped=%d jan=%d matched=%d updated=%d inserted=%d skipped=%d" % (len(items), jan_count, matched, updated, inserted, skipped))


if __name__ == "__main__":
    main()
