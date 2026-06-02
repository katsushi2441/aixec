#!/usr/bin/env python3
"""Generate Google Merchant Center product feed for AIxEC."""
import html
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "storage" / "aixec.sqlite"
OUT = ROOT / "webapps" / "google_products.xml"
SITE = "https://aixec.exbridge.jp"


def slug(maker, model, name):
    model = model or ""
    m = re.match(r"^([^-]+)-(.+)$", model)
    if m and (not name or m.group(1) not in name):
        model = m.group(2)
    digits = re.sub(r"\D", "", model)
    if re.match(r"^[0-9]{10,14}$", digits) and (name or "").strip():
        value = f"{digits}-{name or ''}"
    else:
        value = f"{maker or ''}-{model}".strip("-")
    value = re.sub(r"[\s/()\[\]\\\.]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "product"


def clean_text(value, max_len=5000):
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = value.replace("Amazonでも商品を探してみてください →", " ")
    value = value.replace("楽天市場でも商品を探してみてください →", " ")
    value = value.replace("上のリンクをクリックしてAmazonのサイトでも商品をご確認ください。価格を比べてみて、お得な方でご購入ください。", " ")
    value = value.replace("上のリンクをクリックして楽天市場でも商品をご確認ください。価格を比べてみて、お得な方でご購入ください。", " ")
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > max_len:
        value = value[:max_len].rstrip()
    return value


def x(value):
    return html.escape(str(value or ""), quote=True)


def absolute_site_url(url):
    url = str(url or "")
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return SITE + url
    return SITE + "/" + url


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT p.*, img.attr_value AS image_url
        FROM products p
        JOIN product_attributes img
         ON img.product_id = p.id
         AND img.attr_name IN ('product_image', 'jefcom_image', 'book_image')
         AND img.attr_value != ''
        WHERE p.status = 'active'
          AND p.sale_price IS NOT NULL
          AND p.sale_price > 0
        ORDER BY p.id ASC
        """
    ).fetchall()

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">',
        "<channel>",
        "<title>AIxEC Products</title>",
        f"<link>{SITE}/</link>",
        "<description>AIxEC product feed</description>",
    ]
    for row in rows:
        product_url = f"{SITE}/product/{quote(slug(row['maker'], row['model_number'], row['name']))}"
        desc = clean_text(row["description"]) or clean_text(
            f"{row['name']} {row['maker']} {row['model_number']} の商品情報・価格比較ページです。"
        )
        lines.extend(
            [
                "<item>",
                f"<g:id>{x(row['internal_sku'] or row['id'])}</g:id>",
                f"<title>{x(row['name'])}</title>",
                f"<description>{x(desc)}</description>",
                f"<link>{x(product_url)}</link>",
                f"<g:image_link>{x(absolute_site_url(row['image_url']))}</g:image_link>",
                "<g:condition>new</g:condition>",
                "<g:availability>in_stock</g:availability>",
                f"<g:price>{int(row['sale_price'])} JPY</g:price>",
                f"<g:brand>{x(row['maker'])}</g:brand>",
                f"<g:mpn>{x(row['model_number'])}</g:mpn>",
            ]
        )
        jan = re.sub(r"\D", "", row["jan"] or row["gtin"] or "")
        if len(jan) in (8, 12, 13, 14):
            lines.append(f"<g:gtin>{x(jan)}</g:gtin>")
        lines.extend(
            [
                "<g:identifier_exists>yes</g:identifier_exists>" if jan else "<g:identifier_exists>no</g:identifier_exists>",
                "</item>",
            ]
        )
    lines.extend(["</channel>", "</rss>", ""])
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} items={len(rows)}")


if __name__ == "__main__":
    main()
