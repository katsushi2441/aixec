#!/usr/bin/env python3
"""Generate AI descriptions for AI PC / gaming Rakuten products."""
import argparse
import html
import json
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "storage" / "aixec.sqlite"
START = "<!-- aixec-ai-description:start -->"
END = "<!-- aixec-ai-description:end -->"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def strip_tags(value):
    value = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", value or "")
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def remove_existing_ai_block(description):
    return re.sub(
        re.escape(START) + r".*?" + re.escape(END),
        "",
        description or "",
        flags=re.S,
    ).strip()


def sentence_trim(text):
    text = re.sub(r"```[a-zA-Z]*|```", "", text or "").strip()
    text = re.sub(r"(?is)</?(?:html|body|head)[^>]*>", "", text).strip()
    text = strip_tags(text)
    text = re.sub(r"^(商品説明|説明文|AI説明文)[:：]\s*", "", text)
    if len(text) > 520:
        text = text[:520]
    m = re.search(r"^(.+[。！？])", text)
    if m:
        text = m.group(1)
    return text.strip()


def fallback_description(product, attrs):
    name = product["name"] or "この商品"
    display_name = re.sub(r"\s+", " ", name).strip()
    if len(display_name) > 120:
        display_name = display_name[:120].rstrip() + "..."
    keyword = attrs.get("rakuten_keyword", "")
    if "モニター" in name:
        focus = "作業領域を広げたい人や、動画編集・ゲーム・資料作成を快適にしたい人に向いた候補です。"
    elif "キーボード" in name:
        focus = "毎日の入力作業を快適にし、仕事やゲームで使うPC環境を整えたい人に向いた候補です。"
    elif "マイク" in name or "Webカメラ" in name or "カメラ" in name:
        focus = "オンライン会議、配信、動画制作など、音声や映像の品質を上げたい人に向いた候補です。"
    elif "ミニPC" in name or "AI PC" in name:
        focus = "省スペースでAI活用や業務作業を進めたい人に向いた、AI時代のPC環境づくりの候補です。"
    elif "ゲーミングPC" in name:
        focus = "ゲームだけでなく、動画編集やAI活用など高負荷なPC作業にも使いやすい比較候補です。"
    elif "SSD" in name or "NVMe" in name:
        focus = "AIデータ、動画、ゲーム、業務ファイルなど大容量データを扱うPC環境の強化に向いた候補です。"
    elif "GPU" in name or "グラフィック" in name or "RTX" in name:
        focus = "AI活用、ゲーム、動画編集、3D制作など、GPU性能を重視するPC環境の比較候補になります。"
    else:
        focus = "AI時代のPC作業、制作、配信、業務効率化に向けて周辺環境を整えたい人に向いた候補です。"
    price = product["sale_price"]
    price_text = f"参考価格は{price:,}円です。" if price else ""
    shop = attrs.get("rakuten_shop_name", "")
    shop_text = f"楽天市場の{shop}で取り扱いがあります。" if shop else "楽天市場で取り扱いがあります。"
    return f"{display_name}は、{keyword or 'AI PC・ゲーミング'}関連の商品です。{focus}{price_text}{shop_text}購入前には対応機器、サイズ、保証、在庫、最新価格を確認してください。"


def call_ollama(product, attrs, endpoint, model, timeout):
    caption = strip_tags(product["description"] or "")
    caption = re.sub(r"楽天市場でこの商品を見る.*?ください。", "", caption).strip()
    prompt = f"""あなたは日本語ECの商品紹介担当です。
次の商品について、検索ユーザーが比較しやすいAI説明文を180〜260字で書いてください。
条件:
- 与えた情報にないCPU世代、容量、性能値、対応機能を捏造しない
- 断定しすぎず「候補」「確認したい」など自然に書く
- HTMLやMarkdownを使わず、日本語本文だけ出力

商品名: {product['name']}
価格: {product['sale_price'] or ''}
ショップ: {attrs.get('rakuten_shop_name', '')}
検索カテゴリ: AI PC・ゲーミング
登録キーワード: {attrs.get('rakuten_keyword', '')}
レビュー: {attrs.get('rakuten_review_average', '')} / {attrs.get('rakuten_review_count', '')}件
元説明抜粋: {caption[:700]}
"""
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.25, "num_predict": 180},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = Request(endpoint.rstrip("/") + "/api/generate", data=payload, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as res:
        data = json.loads(res.read().decode("utf-8"))
    return sentence_trim(data.get("response", ""))


def build_ai_block(ai_text, product, attrs):
    safe_text = html.escape(ai_text)
    review = attrs.get("rakuten_review_average")
    review_count = attrs.get("rakuten_review_count")
    notes = [
        "AI PC・ゲーミング用途の比較候補として、商品名・価格・レビュー・ショップ情報をあわせて確認できます。",
        "購入前にはスペック、対応OS、サイズ、保証、在庫、最新価格を楽天市場の商品ページで確認してください。",
    ]
    if review:
        notes.insert(1, f"楽天レビューは {html.escape(review)}（{html.escape(review_count or '0')}件）として登録されています。")
    lis = "".join(f"<li>{note}</li>" for note in notes)
    return (
        f"{START}\n"
        '<section class="aixec-ai-description" style="margin:16px 0;padding:14px 16px;border:1px solid #d8e5ef;border-radius:8px;background:#f7fbff;">'
        '<h2 style="margin:0 0 8px;font-size:1.15rem;">AIによる商品説明</h2>'
        f"<p>{safe_text}</p>"
        f'<ul style="margin:10px 0 0 1.2em;padding:0;">{lis}</ul>'
        "</section>\n"
        f"{END}\n"
    )


def load_targets(limit):
    sql = """
        SELECT DISTINCT p.*
        FROM products p
        JOIN product_attributes a ON a.product_id=p.id
        WHERE a.attr_name='rakuten_genre_group' AND a.attr_value='ai_pc_gaming'
        ORDER BY p.id
    """
    with connect() as conn:
        rows = conn.execute(sql).fetchall()
        if limit:
            rows = rows[:limit]
        ids = [r["id"] for r in rows]
        attrs = {pid: {} for pid in ids}
        if ids:
            placeholders = ",".join("?" for _ in ids)
            for row in conn.execute(
                f"SELECT product_id, attr_name, attr_value FROM product_attributes WHERE product_id IN ({placeholders})",
                ids,
            ):
                attrs[row["product_id"]][row["attr_name"]] = row["attr_value"] or ""
    return rows, attrs


def generate_one(row, attrs, args):
    product = dict(row)
    if args.template_only:
        text = fallback_description(product, attrs)
        error = ""
    else:
        try:
            text = call_ollama(product, attrs, args.endpoint, args.model, args.timeout)
        except Exception as exc:
            text = ""
            error = str(exc)[:160]
        else:
            error = ""
        if len(text) < 60:
            text = fallback_description(product, attrs)
            if not error:
                error = "ollama_empty"
    block = build_ai_block(text, product, attrs)
    base = remove_existing_ai_block(product.get("description") or "")
    description = block + base
    return product["id"], text, description, error


def upsert_attr(conn, product_id, name, value):
    conn.execute(
        """INSERT INTO product_attributes (product_id, attr_name, attr_value, source, created_at, updated_at)
           VALUES (?, ?, ?, 'aixec_ai_description', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
           ON CONFLICT(product_id, attr_name, source)
           DO UPDATE SET attr_value=excluded.attr_value, updated_at=CURRENT_TIMESTAMP""",
        (product_id, name, value),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="llama3.1:latest")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--template-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows, attrs_by_id = load_targets(args.limit)
    print(f"targets={len(rows)} model={args.model} endpoint={args.endpoint}", flush=True)
    if not rows:
        return 0

    updated = 0
    errors = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(generate_one, row, attrs_by_id[row["id"]], args) for row in rows]
        with connect() as conn:
            for future in as_completed(futures):
                product_id, text, description, error = future.result()
                if error:
                    errors += 1
                if not args.dry_run:
                    conn.execute(
                        "UPDATE products SET description=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (description, product_id),
                    )
                    upsert_attr(conn, product_id, "market_description_ai", text)
                    upsert_attr(conn, product_id, "market_description_ai_generated_at", time.strftime("%Y-%m-%d %H:%M:%S"))
                    if updated % 20 == 0:
                        conn.commit()
                updated += 1
                print(f"{updated}/{len(rows)} id={product_id} chars={len(text)} error={error}", flush=True)
            if not args.dry_run:
                conn.commit()
    print(f"done updated={updated} errors_or_fallbacks={errors} elapsed={time.time()-started:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
