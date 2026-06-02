#!/usr/bin/env python3
"""Scrape Tajima Tool new-products page and register into AIxEC DB."""
import argparse
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
BASE_URL = "https://jpn.tajimatool.co.jp"
NEW_URL = BASE_URL + "/new"
ASSET_BASE = "https://jpn-assets.tajimatool.co.jp/img"
AMAZON_BANNER = "https://www.exdirect.net/data/xdirect/image/amazon.png"
RAKUTEN_BANNER = "https://www.exdirect.net/data/xdirect/image/rakuten.png"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; AIxEC/0.1)"})


def fetch(url, sleep=0.5):
    time.sleep(sleep)
    res = SESSION.get(url, timeout=20)
    res.raise_for_status()
    return BeautifulSoup(res.text, "html.parser")


def scrape_product_urls():
    soup = fetch(NEW_URL, sleep=0)
    urls = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.match(r"^(/product/\d{8,14})(?:\?.*)?$", href)
        if not m:
            full = urljoin(BASE_URL, href)
            m2 = re.match(r"https://jpn\.tajimatool\.co\.jp(/product/\d{8,14})", full)
            if m2:
                path = m2.group(1)
            else:
                continue
        else:
            path = m.group(1)
        if path not in seen:
            seen.add(path)
            urls.append(BASE_URL + path)
    return urls


def clean_product_name(h1):
    for tag in h1.find_all(class_=["new-badge", "product-word"]):
        tag.decompose()
    return " ".join(h1.get_text(" ", strip=True).split())


def parse_info_rows(soup):
    info = {}
    for div in soup.select(".info-container .info-left"):
        text = div.get_text("\n", strip=True)
        for line in text.split("\n"):
            if "品番" in line and "：" in line:
                info["品番"] = line.split("：", 1)[-1].strip().replace("　", "").strip()
            elif "JAN" in line and "：" in line:
                info["JAN"] = re.sub(r"\D", "", line.split("：", 1)[-1])
            elif "税込価格" in line and "：" in line:
                info["税込価格"] = line.split("：", 1)[-1].strip()
    return info


def parse_spec(soup):
    items = []
    for li in soup.select(".product-specification-container li"):
        t = li.get_text(" ", strip=True)
        if t:
            items.append(t)
    return items


def parse_description_paragraphs(soup):
    paragraphs = []
    for p in soup.find_all("p"):
        t = p.get_text(" ", strip=True)
        if len(t) >= 30:
            paragraphs.append(t)
    return paragraphs


def scrape_product(url, sleep=0.5):
    jan_from_url = url.rstrip("/").split("/")[-1]
    soup = fetch(url, sleep=sleep)

    h1 = soup.find("h1", class_="product-name")
    name = clean_product_name(h1) if h1 else ""

    info = parse_info_rows(soup)
    code = info.get("品番", "")
    jan = info.get("JAN", "") or re.sub(r"\D", "", jan_from_url)
    price_str = info.get("税込価格", "")

    spec = parse_spec(soup)
    description_paras = parse_description_paragraphs(soup)
    image_url = "%s/%s_l.jpg" % (ASSET_BASE, jan) if jan else ""

    return {
        "url": url,
        "name": name,
        "code": code,
        "jan": jan,
        "price_str": price_str,
        "image_url": image_url,
        "spec": spec,
        "description_paras": description_paras,
    }


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


def build_description(item):
    code = item["code"]
    name = item["name"] or code
    jan = item["jan"]
    price_str = item["price_str"]
    image_url = item["image_url"]
    official_url = item["url"]
    keyword = "タジマ %s %s" % (code, name)
    amazon_url = go_url("amazon", keyword, code)
    rakuten_url = go_url("rakuten", keyword, code)

    parts = []
    parts.append(
        '<p style="margin-bottom:16px; padding:12px; background:#fff8f0; border:1px solid #e8a000; border-radius:4px;">'
        '<a href="%s" target="_blank" rel="nofollow sponsored noopener" style="color:#e47911; font-weight:bold;">Amazonでも商品を探してみてください →</a><br>'
        '<span style="font-size:0.9em; color:#555;">上のリンクをクリックしてAmazonのサイトでも商品をご確認ください。価格を比べてみて、お得な方でご購入ください。</span>'
        "</p>" % html.escape(amazon_url, quote=True)
    )
    parts.append(
        '<p style="margin-bottom:16px;"><a href="%s" target="_blank" rel="nofollow sponsored noopener">'
        '<img src="%s" alt="Amazonで価格をチェックする" style="max-width:100%%;">'
        "</a></p>" % (html.escape(amazon_url, quote=True), AMAZON_BANNER)
    )
    parts.append(
        '<p style="margin-bottom:16px; padding:12px; background:#fff7f7; border:1px solid #bf0000; border-radius:4px;">'
        '<a href="%s" target="_blank" rel="nofollow sponsored noopener" style="color:#bf0000; font-weight:bold;">楽天市場でも商品を探してみてください →</a><br>'
        '<span style="font-size:0.9em; color:#555;">上のリンクをクリックして楽天市場でも商品をご確認ください。価格を比べてみて、お得な方でご購入ください。</span>'
        "</p>" % html.escape(rakuten_url, quote=True)
    )
    parts.append(
        '<p style="margin-bottom:16px;"><a href="%s" target="_blank" rel="nofollow sponsored noopener">'
        '<img src="%s" alt="楽天市場で価格をチェックする" style="max-width:100%%;">'
        "</a></p>" % (html.escape(rakuten_url, quote=True), RAKUTEN_BANNER)
    )
    if image_url:
        parts.append(
            '<p><img src="%s" alt="%s" style="max-width:100%%;"></p>'
            % (html.escape(image_url, quote=True), html.escape(name))
        )
    parts.append("<p><strong>%s</strong></p>" % html.escape(name))
    meta_lines = ["メーカー: タジマ"]
    if code:
        meta_lines.append("品番: %s" % html.escape(code))
    if jan:
        meta_lines.append("JANコード: %s" % html.escape(jan))
    if price_str:
        meta_lines.append("税込価格: %s円" % html.escape(price_str))
    parts.append("<p>%s</p>" % "<br>".join(meta_lines))
    if item["spec"]:
        spec_html = "<br>".join(html.escape(s) for s in item["spec"])
        parts.append("<p><strong>仕様</strong><br>%s</p>" % spec_html)
    for para in item["description_paras"]:
        parts.append("<p>%s</p>" % html.escape(para))
    if official_url:
        parts.append(
            '<p><a href="%s" target="_blank" rel="noopener noreferrer">タジマツール公式商品ページ</a></p>'
            % html.escape(official_url, quote=True)
        )
    return "".join(parts)


def find_existing(conn, code, jan):
    if jan:
        row = conn.execute(
            "SELECT * FROM products WHERE jan=? OR gtin=? LIMIT 1", (jan, jan)
        ).fetchone()
        if row:
            return row
    internal_sku = "tajima_official:" + code
    row = conn.execute(
        "SELECT * FROM products WHERE internal_sku=? LIMIT 1", (internal_sku,)
    ).fetchone()
    if row:
        return row
    row = conn.execute(
        "SELECT p.* FROM products p JOIN product_identifiers i ON i.product_id=p.id "
        "WHERE i.id_type='tajima_model' AND i.id_value=? LIMIT 1",
        (code,),
    ).fetchone()
    if row:
        return row
    return conn.execute(
        "SELECT * FROM products WHERE maker='タジマ' AND model_number=? LIMIT 1",
        (code,),
    ).fetchone()


def update_db(items, dry_run=False):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    matched = updated = inserted = skipped = 0
    with conn:
        for item in items:
            code = item["code"]
            jan = normalize_jan(item["jan"])
            if not code and not jan:
                skipped += 1
                continue
            name_short = item["name"] or code
            full_name = ("%s %s" % (code, name_short)).strip()
            keyword = "タジマ %s %s" % (code, name_short)
            amazon_url = go_url("amazon", keyword, code)
            rakuten_url = go_url("rakuten", keyword, code)
            description = build_description(item)
            price = parse_price(item["price_str"])
            source_url = item["url"]
            payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))

            if dry_run:
                print("  [dry] code=%s jan=%s name=%s" % (code, jan, full_name[:60]))
                inserted += 1
                continue

            image_url = item.get("image_url") or ""
            existing = find_existing(conn, code, jan)
            if existing:
                product_id = existing["id"]
                matched += 1
                conn.execute(
                    """UPDATE products SET
                       jan=COALESCE(NULLIF(jan,''), ?),
                       gtin=COALESCE(NULLIF(gtin,''), ?),
                       image_url=COALESCE(NULLIF(image_url,''), ?),
                       amazon_url=?, rakuten_url=?,
                       source_url=COALESCE(NULLIF(source_url,''), ?),
                       description=CASE WHEN COALESCE(description,'')='' THEN ? ELSE description END,
                       status='active', updated_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (jan, jan, image_url, amazon_url, rakuten_url, source_url, description, product_id),
                )
                updated += 1
            else:
                cur = conn.execute(
                    """INSERT INTO products
                       (internal_sku, jan, gtin, maker, model_number, name, image_url, source_url, description,
                        sale_price, amazon_url, rakuten_url, affiliate_priority, status,
                        created_at, updated_at)
                       VALUES (?, ?, ?, 'タジマ', ?, ?, ?, ?, ?, ?, ?, ?, 'auto', 'active',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                    (
                        "tajima_official:" + code,
                        jan,
                        jan,
                        code,
                        full_name,
                        image_url,
                        source_url,
                        description,
                        price,
                        amazon_url,
                        rakuten_url,
                    ),
                )
                product_id = cur.lastrowid
                inserted += 1

            if jan:
                conn.execute(
                    "INSERT OR IGNORE INTO product_identifiers(product_id,id_type,id_value,source) VALUES(?,?,?,'tajima_official')",
                    (product_id, "jan", jan),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO product_identifiers(product_id,id_type,id_value,source) VALUES(?,?,?,'tajima_official')",
                    (product_id, "gtin", jan),
                )
            if code:
                conn.execute(
                    "INSERT OR IGNORE INTO product_identifiers(product_id,id_type,id_value,source) VALUES(?,?,?,'tajima_official')",
                    (product_id, "tajima_model", code),
                )
            for attr_name, attr_value in {
                "tajima_official_url": item.get("url"),
                "product_image": item.get("image_url"),
                "tajima_list_price": item.get("price_str"),
            }.items():
                if attr_value:
                    conn.execute(
                        """INSERT INTO product_attributes(product_id,attr_name,attr_value,source,created_at,updated_at)
                           VALUES(?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                           ON CONFLICT(product_id,attr_name,source) DO UPDATE SET attr_value=excluded.attr_value, updated_at=CURRENT_TIMESTAMP""",
                        (product_id, attr_name, str(attr_value), "tajima_official"),
                    )
            conn.execute(
                """INSERT INTO channel_payloads(product_id, channel, external_id, payload_json, created_at, updated_at)
                   VALUES(?, 'tajima_official', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                   ON CONFLICT(channel, external_id) DO UPDATE SET product_id=excluded.product_id, payload_json=excluded.payload_json, updated_at=CURRENT_TIMESTAMP""",
                (product_id, code or jan, payload),
            )
    return matched, updated, inserted, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()

    print("商品URL一覧を取得中...")
    urls = scrape_product_urls()
    print("  %d件" % len(urls))
    if args.limit:
        urls = urls[: args.limit]

    items = []
    for i, url in enumerate(urls, 1):
        try:
            item = scrape_product(url, sleep=args.sleep)
            items.append(item)
            print("[%d/%d] %s  %s" % (i, len(urls), item.get("code", ""), item.get("name", "")[:60]))
        except Exception as exc:
            print("[%d/%d] ERROR %s: %s" % (i, len(urls), url, exc))

    matched, updated, inserted, skipped = update_db(items, dry_run=args.dry_run)
    print(
        "完了: scraped=%d matched=%d updated=%d inserted=%d skipped=%d%s"
        % (len(items), matched, updated, inserted, skipped, " [dry-run]" if args.dry_run else "")
    )


if __name__ == "__main__":
    main()
