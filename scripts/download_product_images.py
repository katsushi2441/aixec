#!/usr/bin/env python3
"""Download remote product images and rewrite DB image URLs to local paths."""
import mimetypes
import re
import sqlite3
import time
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "storage" / "aixec.sqlite"
IMAGE_ROOT = ROOT / "webapps" / "images" / "products" / "jefcom"
PUBLIC_PREFIX = "/images/products/jefcom"


def ext_from_content_type(content_type):
    content_type = (content_type or "").split(";")[0].strip().lower()
    if content_type == "image/jpeg":
        return ".jpg"
    if content_type == "image/png":
        return ".png"
    if content_type == "image/webp":
        return ".webp"
    return mimetypes.guess_extension(content_type) or ".jpg"


def safe_name(url, product_id):
    path = urlparse(url).path
    stem = Path(path).stem or f"product_{product_id}"
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._")
    return stem or f"product_{product_id}"


def download(url, product_id):
    req = Request(
        url,
        headers={
            "User-Agent": "AIxEC image cache/1.0 (+https://aixec.exbridge.jp/)",
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.5",
        },
    )
    with urlopen(req, timeout=30) as res:
        content_type = res.headers.get("Content-Type", "")
        if not content_type.lower().startswith("image/"):
            raise RuntimeError(f"not image: {content_type}")
        data = res.read()
        if len(data) < 100:
            raise RuntimeError("image too small")
        ext = ext_from_content_type(content_type)
        name = safe_name(url, product_id) + ext
        path = IMAGE_ROOT / name
        path.write_bytes(data)
        return f"{PUBLIC_PREFIX}/{name}", len(data)


def main():
    IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT product_id, attr_value
        FROM product_attributes
        WHERE attr_name = 'jefcom_image'
          AND attr_value LIKE 'https://www.jefcom.co.jp/%'
        ORDER BY product_id
        """
    ).fetchall()
    ok = 0
    failed = 0
    with conn:
        for idx, row in enumerate(rows, 1):
            product_id = row["product_id"]
            url = row["attr_value"]
            try:
                local_url, size = download(url, product_id)
                conn.execute(
                    """
                    UPDATE product_attributes
                    SET attr_value = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE product_id = ? AND attr_name = 'jefcom_image'
                    """,
                    (local_url, product_id),
                )
                ok += 1
                print(f"[{idx}/{len(rows)}] ok product_id={product_id} {local_url} bytes={size}")
                time.sleep(0.1)
            except (HTTPError, URLError, RuntimeError) as exc:
                failed += 1
                print(f"[{idx}/{len(rows)}] failed product_id={product_id} {url} error={exc}")
    print(f"summary targets={len(rows)} downloaded={ok} failed={failed}")


if __name__ == "__main__":
    main()
