#!/usr/bin/env python3
"""Build marketing context for AIxEC product registration planning."""
from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "storage" / "aixec.sqlite"
OUT = ROOT / "tasks" / "marketing_context.md"
LOG_CANDIDATES = [
    ROOT / "webapps" / "access.log",
    Path("/tmp/aixec_access.log"),
]


def rows(conn, sql, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params)]


def analyze_go_log():
    path = next((p for p in LOG_CANDIDATES if p.exists()), None)
    if not path:
        return "access.logは未取得。simpletrack本番ログ取得後に再生成すること。"
    raw = Counter()
    valid = Counter()
    froms = Counter()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split(" | ")
        if len(parts) < 5:
            continue
        ts, _ip, url, ref, _ua = parts[:5]
        if "go.php" not in url:
            continue
        q = parse_qs(urlparse(url).query)
        to = (q.get("to") or q.get("click") or [""])[0] or "(unknown)"
        raw[to] += 1
        fr = (q.get("from") or [""])[0]
        if fr or ref:
            valid[to] += 1
            froms[unquote(fr or ref)] += 1
    lines = ["### go.phpクリック"]
    lines.append("- raw: " + ", ".join(f"{k}={v}" for k, v in raw.most_common()) if raw else "- raw: 0")
    lines.append("- valid(from/refあり): " + ", ".join(f"{k}={v}" for k, v in valid.most_common()) if valid else "- valid(from/refあり): 0")
    if froms:
        lines.append("- 呼び出し元上位: " + ", ".join(f"{k}={v}" for k, v in froms.most_common(10)))
    return "\n".join(lines)


def main():
    conn = sqlite3.connect(DB)
    total = conn.execute("select count(*) from products").fetchone()[0]
    group_counts = rows(
        conn,
        """
        select attr_value as group_name, count(distinct product_id) as count
        from product_attributes
        where attr_name='rakuten_genre_group'
        group by attr_value
        order by count desc
        limit 30
        """,
    )
    keyword_counts = rows(
        conn,
        """
        select attr_value as keyword, count(*) as count
        from product_attributes
        where attr_name in ('rakuten_keyword','book_keyword')
        group by attr_value
        order by count desc
        limit 40
        """,
    )
    recent = rows(
        conn,
        """
        select id, name, created_at
        from products
        order by id desc
        limit 12
        """,
    )

    # 登録が少ない・未登録のジャンル候補
    registered_groups = {r['group_name'] for r in group_counts}
    all_candidate_groups = [
        # 書籍系
        ("副業・フリーランス書籍", "sidejob_books"),
        ("投資・NISA書籍", "investment_books"),
        ("プログラミング書籍", "programming_books"),
        ("ブロックチェーン・Web3書籍", "blockchain_books"),
        ("AI・機械学習書籍", "ai_ml_books"),
        ("ビジネス・経営書籍", "business_books"),
        ("資格・IT書籍", "certification_textbooks"),
        ("心理学・メンタル書籍", "psychology_books"),
        ("語学・英語書籍", "language_books"),
        ("料理・レシピ書籍", "cooking_books"),
        ("子育て・育児書籍", "parenting_books"),
        ("マンガ・コミック", "manga_comics"),
        ("小説・文芸書籍", "fiction_books"),
        ("資産形成・FIREムーブメント書籍", "fire_books"),
        # PC・ガジェット系
        ("ゲーミングPC・GPU", "ai_pc_gaming"),
        ("スマホアクセサリー", "smartphone_accessories"),
        ("モバイルバッテリー・充電器", "mobile_chargers"),
        ("Webカメラ・マイク・配信機材", "streaming_gear"),
        ("キーボード・マウス", "pc_peripherals"),
        ("外付けSSD・ストレージ", "external_storage"),
        ("プリンター・スキャナー", "printers_scanners"),
        # 工具・DIY系
        ("型番商品・工具機器", "model_number_products"),
        ("DIY・電動工具", "diy_tools"),
        ("測定工具・計測器", "measuring_tools"),
        ("収納・整理グッズ", "storage_organizers"),
        # 健康・美容系
        ("健康・サプリメント", "supplements"),
        ("美容・コスメ", "beauty_cosmetics"),
        ("フィットネス・トレーニング用品", "fitness_equipment"),
        ("マッサージ・リラクゼーション", "massage_relax"),
        ("プロテイン・スポーツ栄養", "sports_nutrition"),
        # ライフスタイル系
        ("トレカ", "trading_cards"),
        ("キッチン・調理器具", "kitchen_tools"),
        ("コーヒー・お茶用品", "coffee_tea"),
        ("アウトドア・キャンプ用品", "outdoor_camping"),
        ("ペット用品", "pet_supplies"),
        ("文具・オフィス用品", "stationery_office"),
        ("防災・緊急用品", "disaster_prevention"),
        ("節電・省エネグッズ", "energy_saving"),
        ("インテリア・照明", "interior_lighting"),
        # ビジネス・仕事系
        ("名刺・印刷サービス関連", "business_printing"),
        ("セキュリティ・監視カメラ", "security_cameras"),
        ("ビジネスバッグ・鞄", "business_bags"),
        # アクセス拡大を狙う人気・実用品系
        ("スマートウォッチ・ウェアラブル", "smartwatch_wearables"),
        ("ワイヤレスイヤホン・ヘッドホン", "wireless_audio"),
        ("タブレット・電子書籍リーダー", "tablets_ereaders"),
        ("生活家電・時短家電", "home_appliances"),
        ("ロボット掃除機・掃除家電", "robot_cleaners"),
        ("空調服・暑さ対策", "cooling_workwear"),
        ("冷感グッズ・猛暑対策", "summer_cooling_goods"),
        ("電気代節約・省エネ家電", "energy_saving_appliances"),
        ("コンタクトレンズ・アイケア", "contact_lenses_eye_care"),
        ("成分美容・スキンケア", "ingredient_skincare"),
        ("ヘアケア・頭皮ケア", "hair_scalp_care"),
        ("オーラルケア・電動歯ブラシ", "oral_care"),
        ("睡眠改善グッズ", "sleep_improvement"),
        ("水・ソフトドリンク", "water_soft_drinks"),
        ("冷凍食品・時短食品", "frozen_ready_meals"),
        ("キッズ学習・知育玩具", "kids_learning_toys"),
        ("介護用品・見守り機器", "caregiving_monitoring"),
    ]
    unregistered = [(label, gid) for label, gid in all_candidate_groups if gid not in registered_groups]
    low_count = [(r['group_name'], r['count']) for r in group_counts if r['count'] < 100]

    lines = [
        "# AIxEC Marketing Context",
        "",
        "Claude Code OAuth / OpenClawが、次に登録する楽天市場商品ジャンルを選ぶための文脈。",
        "",
        f"- 総商品数: {total}",
        "- 方針: AIxECらしい専門性、検索需要、アフィリエイト送客、解説記事化しやすさを重視する。",
        "- 成長方針: 既存ジャンル周辺にこだわりすぎず、楽天ランキング・季節需要・検索ボリュームが大きい人気ジャンルを優先する。",
        "- 件数方針: 1回のパイプラインで500件前後の商品登録を狙う。狭い書籍ジャンルより、商品母数が大きいジャンルを優先する。",
        "- 画像方針: 楽天市場商品画像は保存せず、楽天API画像URLを使う。",
        "- bot対策: ref/fromなしのgo.php直踏みは204で遮断済み。クリック評価はvalid(from/refあり)を重視する。",
        "",
        "## 登録済みジャンルと充足度（件数が多いほど飽和）",
    ]
    for r in group_counts:
        saturation = "★充足" if r['count'] >= 300 else ("△やや少ない" if r['count'] >= 100 else "◎少ない・伸びしろあり")
        lines.append(f"- {r['group_name']}: {r['count']}件 {saturation}")

    if unregistered:
        lines += ["", "## 未登録ジャンル（優先度高）"]
        for label, gid in unregistered:
            lines.append(f"- {gid} ({label}): 0件 ◎未登録・最優先")

    lines += [
        "",
        "## 人気ジャンルの選定指針",
        "- 公式ランキングやリアルタイムランキングで露出しやすい商品カテゴリを重視する。",
        "- 日用品・美容・健康・食品は検索需要が強いが、AIxECでは「成分比較」「時短」「健康管理」「防災」「仕事効率化」の切り口で記事化する。",
        "- 季節性の強いカテゴリ（暑さ対策、空調服、冷感、災害対策）は短期アクセスを狙いやすい。",
        "- PC・AI機器だけに偏らない。検索流入を増やすため、生活改善・健康・美容・家電・学習も選定対象にする。",
        "- 500件登録を狙うため、keywordsは25〜40個に増やし、用途・悩み・型番・比較語を混ぜる。",
    ]

    if low_count:
        lines += ["", "## 登録が少ないジャンル（伸びしろあり）"]
        for gid, cnt in low_count:
            lines.append(f"- {gid}: {cnt}件")

    lines += ["", "## 登録キーワード上位（重複登録を避けるための参考）"]
    for r in keyword_counts:
        lines.append(f"- {r['keyword']}: {r['count']}件")
    lines += ["", analyze_go_log(), "", "## 最近登録された商品"]
    for r in recent:
        lines.append(f"- #{r['id']} {r['name']} ({r['created_at']})")
    lines += [
        "",
        "## 今回Claude Codeにしてほしい判断",
        "",
        "次に攻める楽天市場商品ジャンルを1つ選び、500件程度の商品登録に向いたtask.jsonを作る。",
        "【重要】未登録ジャンルだけに固執しない。検索需要が強ければ、既存ジャンルの隣接領域や一般人気ジャンルも選んでよい。",
        "充足済み（★充足）のジャンルを選ぶ場合は、切り口が明確に違い、500件規模で新規登録できる根拠を書くこと。",
        "AIxECの文脈に無理やり寄せるより、アクセス増につながる需要を優先し、その上で記事化・SNS化・動画化できる切り口を作る。",
    ]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
