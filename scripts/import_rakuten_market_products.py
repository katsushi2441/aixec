#!/usr/bin/env python3
"""Import Rakuten Ichiba products into AIxEC by market category keywords."""
import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import time
import ftplib
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "webapps" / "images" / "products" / "rakuten"
RAKUTEN_ITEM_ENDPOINT = os.environ.get(
    "RAKUTEN_ITEM_SEARCH_ENDPOINT",
    "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401",
)
DEFAULT_DELAY = float(os.environ.get("RAKUTEN_MARKET_IMPORT_DELAY", "4.0"))
LAST_RUN_STATS = {"created": 0, "updated": 0, "skipped": 0}

CATEGORIES = [
    {
        "label": "トレカ",
        "group": "trading_cards",
        "genre_id": "207659",
        "keywords": [
            "ポケモンカード BOX",
            "ポケモンカード シングル 高額",
            "ポケモンカード SAR シングル",
            "ポケモンカード UR シングル",
            "ポケモンカード イラストレア",
            "ポケモンカード リザードン シングル",
            "ポケモンカード 旧裏 高額",
            "遊戯王 シングルカード 高額",
            "遊戯王 BOX",
            "ワンピースカード BOX",
            "ワンピースカード シングル",
            "デュエルマスターズ BOX",
            "マジックザギャザリング",
            "トレーディングカード 高額",
        ],
    },
    {
        "label": "美容・コスメ",
        "group": "beauty_cosmetics",
        "genre_id": "100939",
        "keywords": ["美容 コスメ", "スキンケア", "化粧品"],
    },
    {
        "label": "サプリ",
        "group": "supplements",
        "genre_id": "100938",
        "keywords": ["サプリメント", "プロテイン", "ビタミン サプリ"],
    },
    {
        "label": "AI PC・ゲーミング",
        "group": "ai_pc_gaming",
        "genre_id": "",
        "keywords": [
            "RTX ゲーミングPC",
            "ゲーミングPC RTX",
            "RTX 5090 ゲーミングPC",
            "RTX 5080 ゲーミングPC",
            "RTX 5070 ゲーミングPC",
            "RTX 4090 ゲーミングPC",
            "RTX 4080 ゲーミングPC",
            "GeForce RTX グラフィックボード",
            "NVIDIA GPU",
            "AI ワークステーション",
            "GPU サーバー",
            "GPU ワークステーション RTX",
            "生成AI PC RTX",
            "ローカルLLM PC RTX",
            "NVIDIA RTX 5090",
            "NVIDIA RTX 5080",
            "NVIDIA RTX 6000",
            "NVIDIA RTX A6000",
            "NVIDIA RTX A5000",
            "NVIDIA RTX A4000",
            "NVIDIA Tesla P100",
            "NVIDIA Tesla K80",
            "ワークステーション PC",
            "AI PC",
            "ミニPC 32GB",
            "ミニPC 64GB",
            "GPU グラフィックボード",
            "DDR5 メモリ 64GB",
            "DDR5 メモリ 128GB",
            "ECC メモリ",
            "4K モニター",
            "ウルトラワイドモニター",
            "メカニカルキーボード",
            "USB マイク 配信",
            "Webカメラ 4K",
            "外付けSSD 2TB",
            "NVMe SSD 2TB",
            "キャプチャーボード",
        ],
    },
    {
        "label": "型番商品・工具機器",
        "group": "model_number_products",
        "genre_id": "",
        "keywords": [
            "マキタ TD173",
            "マキタ BL1860B",
            "マキタ 充電式 インパクト 型番",
            "HiKOKI WH36DC",
            "HiKOKI BSL36A18",
            "ボッシュ GDX18V",
            "ボッシュ GLM50",
            "タジマ レーザー墨出し器 ZEROG",
            "シンワ 測定器 デジタル",
            "ムラテックKDS レーザー墨出し器",
            "リョービ 京セラ 電動工具",
            "パナソニック EZ1PD1",
            "オムロン HEM 血圧計",
            "エプソン PX プリンター",
            "ブラザー MFC プリンター",
            "Canon CRG トナー",
            "Buffalo WXR ルーター",
            "YAMAHA RTX ルーター",
            "Synology DS NAS",
            "QNAP TS NAS",
            "APC UPS 型番",
            "APC BR550S-JP",
            "APC SMT750J",
            "Logicool MX MASTER4",
            "Logicool MX Keys S",
            "Logicool KX850",
            "エレコム WRC-X6000QS",
            "エレコム WRC-BE94XS",
            "サンワサプライ CMS-V",
            "Brother MFC-J7300CDW",
            "Canon Satera LBP",
        ],
    },
]

EXCLUDE_NAME_PATTERNS = [
    "ふるさと納税",
    "GPUサポート",
    "GPU サポート",
    "グラフィックボード サポート",
    "グラボサポート",
    "グラボ サポート",
    "グラボステー",
    "グラボ ステー",
    "GPUステー",
    "GPU ステー",
    "ビデオカードホルダー",
    "ブラケット",
    "Nvidia GPU なし",
    "NVIDIA GPU なし",
    "ACアダプター",
    "AC アダプター",
    "Surface",
    "BarraCuda",
    "Barracuda",
    "HDD",
    "ハードディスク",
    "ヘッドセット",
    "グリス",
    "電源ケーブル",
    "Power Adapter",
    "アダプター",
    "ケーブル",
    "ラック",
    "収納ボックス",
    "RAIDコントローラ",
    "RAID コントローラ",
    "G検定",
    "書籍",
    "単行本",
    "電子書籍",
    "コーヒーサーバー",
    "ケーキサーバー",
    "GPU Guard",
    "熱伝導シート",
    "ライザーケーブル",
    "ケースのみ",
    "収納ケース（ケースのみ）",
    "カラープレート",
    "インレイ",
    "キートップ引抜工具",
    "粘着テープ",
    "電源コード",
    "SDカードスロット用キャップ",
    "液晶保護フィルム",
    "保護フィルム",
    "のぞき見防止 フィルター",
    "南京錠用マスターキー",
    "イヤーパッド",
    "キーボードカバー",
    "ダストカバー",
    "マウスソール",
    "専用収納ケース",
    "互換性のある",
]


def load_env():
    for env_path in (ROOT.parent / ".env", ROOT / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def db_path():
    configured = os.environ.get("AIXEC_DB")
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else ROOT / path
    return ROOT / "storage" / "aixec.sqlite"


def connect():
    conn = sqlite3.connect(str(db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def credentials():
    app_id = os.environ.get("RAKUTEN_APPLICATION_ID") or os.environ.get("RAKUTEN_APP_ID")
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY")
    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID")
    if not app_id:
        raise SystemExit("RAKUTEN_APPLICATION_ID is not set")
    if not access_key:
        raise SystemExit("RAKUTEN_ACCESS_KEY is not set")
    return app_id, access_key, affiliate_id


def fetch_items(keyword, genre_id="", hits=10, page=1, sort="standard"):
    app_id, access_key, affiliate_id = credentials()
    params = {
        "applicationId": app_id,
        "accessKey": access_key,
        "format": "json",
        "keyword": keyword,
        "hits": str(min(30, max(1, int(hits)))),
        "page": str(page),
        "sort": sort,
        "elements": ",".join([
            "itemName", "catchcopy", "itemCaption", "itemPrice", "itemUrl",
            "affiliateUrl", "mediumImageUrls", "shopName", "shopCode",
            "itemCode", "genreId", "reviewAverage", "reviewCount", "jan",
        ]),
    }
    if genre_id:
        params["genreId"] = genre_id
    if affiliate_id:
        params["affiliateId"] = affiliate_id
    request_origin = os.environ.get("RAKUTEN_REFERER", "https://aixec.exbridge.jp").rstrip("/")
    req = Request(RAKUTEN_ITEM_ENDPOINT + "?" + urlencode(params), headers={
        "User-Agent": "AIxEC/0.1",
        "Referer": request_origin + "/",
        "Origin": request_origin,
        "accessKey": access_key,
    })
    for attempt in range(1, 5):
        try:
            with urlopen(req, timeout=30) as res:
                payload = json.loads(res.read().decode("utf-8"))
            return [normalize_item(item, keyword) for item in payload.get("Items", [])]
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 400:
                print("  invalid_keyword keyword=%s detail=%s" % (keyword, detail[:160]), flush=True)
                return []
            if exc.code in (403, 429) and genre_id:
                print("  genre_search_fallback keyword=%s genre_id=%s http=%s" % (keyword, genre_id, exc.code), flush=True)
                return fetch_items(keyword, genre_id="", hits=hits, page=page, sort=sort)
            if exc.code == 429 and attempt < 4:
                wait = DEFAULT_DELAY * attempt
                print("  rate_limit wait=%ss keyword=%s" % (wait, keyword), flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError("Rakuten API HTTP %s: %s" % (exc.code, detail[:300]))
        except URLError as exc:
            if attempt < 4:
                time.sleep(DEFAULT_DELAY * attempt)
                continue
            raise RuntimeError("Rakuten API failed: %s" % exc)
    return []


def first_image(item):
    images = item.get("mediumImageUrls") or []
    if images:
        first = images[0]
        return first.get("imageUrl") if isinstance(first, dict) else str(first)
    return ""


def normalize_item(raw, keyword):
    item = raw.get("Item", raw) if isinstance(raw, dict) else {}
    image = first_image(item)
    if image:
        image = re.sub(r"\?_ex=\d+x\d+$", "", image)
    return {
        "keyword": keyword,
        "name": str(item.get("itemName") or "").strip(),
        "catchcopy": str(item.get("catchcopy") or "").strip(),
        "caption": str(item.get("itemCaption") or "").strip(),
        "price": int(item.get("itemPrice")) if str(item.get("itemPrice") or "").isdigit() else None,
        "item_url": str(item.get("itemUrl") or "").strip(),
        "affiliate_url": str(item.get("affiliateUrl") or item.get("itemUrl") or "").strip(),
        "image_url": image,
        "shop_name": str(item.get("shopName") or "").strip(),
        "shop_code": str(item.get("shopCode") or "").strip(),
        "item_code": str(item.get("itemCode") or "").strip(),
        "genre_id": str(item.get("genreId") or "").strip(),
        "review_average": str(item.get("reviewAverage") or "").strip(),
        "review_count": str(item.get("reviewCount") or "").strip(),
        "jan": re.sub(r"\D", "", str(item.get("jan") or "")),
        "raw": item,
    }


def image_ext(url):
    path = urlparse(url).path.lower()
    if path.endswith(".png"):
        return ".png"
    if path.endswith(".webp"):
        return ".webp"
    return ".jpg"


def safe_key(value):
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", value or "").strip("-")
    return value[:90] if value else ""


def image_basename(item):
    key = item.get("item_code") or item.get("jan") or item.get("name") or json.dumps(item.get("raw"), ensure_ascii=False)
    return safe_key(key) or hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def download_image(item):
    url = item.get("image_url") or ""
    if not url:
        return ""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    rel = "/images/products/rakuten/" + image_basename(item) + image_ext(url)
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
        print("  image_error %s %s" % (item.get("item_code") or item.get("name"), exc), flush=True)
    return ""


def ensure_remote_dir(ftp, remote_dir):
    try:
        ftp.cwd(remote_dir)
    except ftplib.error_perm:
        ftp.mkd(remote_dir)
        ftp.cwd(remote_dir)


def upload_image(rel_path):
    host = os.environ.get("FTP_HOST")
    user = os.environ.get("FTP_USER")
    password = os.environ.get("FTP_PASS")
    remote_root = os.environ.get("FTP_REMOTE") or "/web/aixec_exbridge_jp"
    if not (host and user and password and rel_path):
        return False
    local_path = ROOT / "webapps" / rel_path.lstrip("/")
    if not local_path.exists():
        return False
    parts = rel_path.strip("/").split("/")
    with ftplib.FTP(host, timeout=60) as ftp:
        ftp.login(user, password)
        ensure_remote_dir(ftp, remote_root)
        for part in parts[:-1]:
            ensure_remote_dir(ftp, part)
        with local_path.open("rb") as fh:
            ftp.storbinary("STOR " + parts[-1], fh)
    return True


def go_url(item):
    params = {
        "to": "rakuten",
        "kw": item.get("name") or item.get("keyword") or "楽天市場",
    }
    if item.get("jan"):
        params["jan"] = item["jan"]
    if item.get("item_code"):
        params["model"] = item["item_code"]
    if item.get("affiliate_url"):
        params["url"] = item["affiliate_url"]
    return "/go.php?" + urlencode(params)


def build_description(item, category, local_image):
    name = html.escape(item.get("name") or "")
    catch = html.escape(item.get("catchcopy") or "")
    raw_caption = re.sub(r"\s+", " ", item.get("caption") or "").strip()
    if len(raw_caption) > 1200:
        raw_caption = raw_caption[:1200].rstrip() + "..."
    caption = html.escape(raw_caption)
    shop = html.escape(item.get("shop_name") or "")
    genre = html.escape(category["label"])
    rakuten = html.escape(go_url(item), quote=True)
    parts = [
        '<p style="margin-bottom:16px; padding:12px; background:#fff7f7; border:1px solid #bf0000; border-radius:4px;">'
        '<a href="%s" target="_blank" rel="nofollow sponsored noopener" style="color:#bf0000; font-weight:bold;">楽天市場でこの商品を見る →</a><br>'
        '<span style="font-size:0.9em; color:#555;">楽天市場の商品ページで価格・在庫・レビューをご確認ください。</span>'
        '</p>' % rakuten
    ]
    if local_image:
        parts.append('<p><img src="%s" alt="%s" style="max-width:100%%;"></p>' % (html.escape(local_image), name))
    parts.append("<p><strong>%s</strong></p>" % name)
    meta = ["ジャンル: %s" % genre]
    if shop:
        meta.append("ショップ: %s" % shop)
    if item.get("jan"):
        meta.append("JAN: %s" % html.escape(item["jan"]))
    if item.get("item_code"):
        meta.append("商品コード: %s" % html.escape(item["item_code"]))
    if item.get("review_average"):
        meta.append("レビュー: %s（%s件）" % (html.escape(item["review_average"]), html.escape(item.get("review_count") or "0")))
    parts.append("<p>%s</p>" % "<br>".join(meta))
    if catch:
        parts.append("<p>%s</p>" % catch)
    if caption:
        parts.append("<p>%s</p>" % caption)
    return "".join(parts)


def upsert_attr(conn, product_id, name, value, source="rakuten_market"):
    if value is None or value == "":
        return
    conn.execute(
        """INSERT INTO product_attributes (product_id, attr_name, attr_value, source, created_at, updated_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
           ON CONFLICT(product_id, attr_name, source)
           DO UPDATE SET attr_value=excluded.attr_value, updated_at=CURRENT_TIMESTAMP""",
        (product_id, name, str(value), source),
    )


def resolve_existing(conn, item):
    if item.get("jan"):
        row = conn.execute("SELECT * FROM products WHERE jan = ?", (item["jan"],)).fetchone()
        if row:
            return row
    if item.get("item_code"):
        sku = "rakuten_market:" + item["item_code"]
        row = conn.execute("SELECT * FROM products WHERE internal_sku = ?", (sku,)).fetchone()
        if row:
            return row
    return None


def upsert_product(item, category, upload=False):
    if not item.get("name") or not item.get("item_code"):
        return None, "skip"
    if any(pattern in item["name"] for pattern in EXCLUDE_NAME_PATTERNS):
        return None, "skip"
    rakuten_image_url = item.get("image_url") or ""
    image_for_display = rakuten_image_url  # default: use Rakuten CDN URL directly
    if upload and rakuten_image_url:
        local_image = download_image(item)
        if local_image:
            try:
                upload_image(local_image)
                image_for_display = local_image
            except Exception as exc:
                print("  upload_error %s %s" % (local_image, exc), flush=True)
    desc = build_description(item, category, image_for_display)
    values = {
        "internal_sku": "rakuten_market:" + item["item_code"],
        "jan": item.get("jan") or None,
        "gtin": item.get("jan") or None,
        "asin": None,
        "name": item["name"],
        "maker": item.get("shop_name") or "楽天市場",
        "model_number": item["item_code"],
        "source_url": item.get("item_url"),
        "description": desc,
        "cost_price": None,
        "sale_price": item.get("price"),
        "amazon_url": None,
        "rakuten_url": item.get("affiliate_url") or item.get("item_url"),
        "own_store_url": None,
        "affiliate_priority": "rakuten",
        "status": "active",
    }
    with connect() as conn:
        existing = resolve_existing(conn, item)
        if existing:
            values["id"] = existing["id"]
            conn.execute(
                """UPDATE products SET
                   internal_sku=:internal_sku, jan=COALESCE(:jan, jan), gtin=COALESCE(:gtin, gtin),
                   name=:name, maker=:maker, model_number=:model_number, source_url=:source_url,
                   description=:description, sale_price=:sale_price, rakuten_url=:rakuten_url,
                   affiliate_priority=:affiliate_priority, status=:status, updated_at=CURRENT_TIMESTAMP
                   WHERE id=:id""",
                values,
            )
            product_id = existing["id"]
            action = "updated"
        else:
            conn.execute(
                """INSERT INTO products
                   (internal_sku, jan, gtin, asin, name, maker, model_number, source_url, description,
                    cost_price, sale_price, amazon_url, rakuten_url, own_store_url, affiliate_priority,
                    status, created_at, updated_at)
                   VALUES
                   (:internal_sku, :jan, :gtin, :asin, :name, :maker, :model_number, :source_url, :description,
                    :cost_price, :sale_price, :amazon_url, :rakuten_url, :own_store_url, :affiliate_priority,
                    :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                values,
            )
            product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            action = "created"
        for id_type, id_value in (("jan", item.get("jan")), ("gtin", item.get("jan")), ("rakuten_item_code", item.get("item_code"))):
            if id_value:
                conn.execute(
                    "INSERT OR IGNORE INTO product_identifiers (product_id, id_type, id_value, source) VALUES (?, ?, ?, 'rakuten_market')",
                    (product_id, id_type, id_value),
                )
        upsert_attr(conn, product_id, "product_image", image_for_display)
        upsert_attr(conn, product_id, "rakuten_genre_label", category["label"])
        upsert_attr(conn, product_id, "rakuten_genre_group", category["group"])
        upsert_attr(conn, product_id, "rakuten_genre_id", item.get("genre_id") or category.get("genre_id"))
        upsert_attr(conn, product_id, "rakuten_keyword", item.get("keyword"))
        upsert_attr(conn, product_id, "rakuten_shop_name", item.get("shop_name"))
        upsert_attr(conn, product_id, "rakuten_shop_code", item.get("shop_code"))
        upsert_attr(conn, product_id, "rakuten_review_average", item.get("review_average"))
        upsert_attr(conn, product_id, "rakuten_review_count", item.get("review_count"))
        conn.commit()
    return product_id, action


def selected_categories(names):
    if not names:
        return CATEGORIES
    wanted = set(names)
    return [cat for cat in CATEGORIES if cat["group"] in wanted or cat["label"] in wanted]


def run_categories(categories=None, hits=10, delay=DEFAULT_DELAY, upload_images=False, dry_run=False):
    """Rakuten Market categoriesを巡回してAIxECに登録する。

    Returns:
        dict: {category_label: [新規登録商品名, ...]}
    """
    global LAST_RUN_STATS
    load_env()
    cats = selected_categories(categories or [])
    if not cats:
        raise SystemExit("no category selected")
    created_by_category = {}
    total_created = total_updated = total_skipped = 0
    for cat in cats:
        print("== %s ==" % cat["label"], flush=True)
        seen_codes = set()
        for keyword in cat["keywords"]:
            print(" search keyword=%s genre=%s" % (keyword, cat.get("genre_id") or "-"), flush=True)
            items = fetch_items(keyword, genre_id=cat.get("genre_id") or "", hits=hits)
            print("  fetched=%d" % len(items), flush=True)
            for item in items:
                code = item.get("item_code")
                if not code or code in seen_codes:
                    total_skipped += 1
                    continue
                seen_codes.add(code)
                if dry_run:
                    print("  dry %s / %s" % (item.get("name")[:70], item.get("shop_name")), flush=True)
                    continue
                product_id, action = upsert_product(item, cat, upload=upload_images)
                if action == "created":
                    total_created += 1
                    created_by_category.setdefault(cat["label"], []).append(item.get("name") or "")
                elif action == "updated":
                    total_updated += 1
                else:
                    total_skipped += 1
                print("  %s id=%s %s" % (action, product_id, item.get("name")[:70]), flush=True)
            time.sleep(delay)
    LAST_RUN_STATS = {"created": total_created, "updated": total_updated, "skipped": total_skipped}
    print("done created=%d updated=%d skipped=%d" % (total_created, total_updated, total_skipped), flush=True)
    return created_by_category


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", action="append", help="group or label. repeatable")
    parser.add_argument("--hits", type=int, default=10)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--upload-images", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_categories(
        categories=args.category,
        hits=args.hits,
        delay=args.delay,
        upload_images=args.upload_images,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
