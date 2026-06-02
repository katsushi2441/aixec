#!/usr/bin/env python3
"""Build observation report for AIxEC Growth Agent."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "storage" / "aixec.sqlite"
OUT = ROOT / "tasks" / "growth_observation.md"
MEMORY = ROOT / "tasks" / "growth_memory.md"
MARKETING_CONTEXT = ROOT / "tasks" / "marketing_context.md"
LOG_CANDIDATES = [ROOT / "webapps" / "access.log", Path("/tmp/aixec_access.log")]


def run_marketing_context():
    subprocess.run([sys.executable, "scripts/build_marketing_context.py"], cwd=str(ROOT), check=False)


def table_rows(conn, sql, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params)]


def analyze_clicks():
    path = next((p for p in LOG_CANDIDATES if p.exists()), None)
    if not path:
        return ["- access.log未取得"]
    raw = Counter()
    valid = Counter()
    froms = Counter()
    botlike = 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split(" | ")
        if len(parts) < 5:
            continue
        ts, _ip, url, ref, ua = parts[:5]
        if "go.php" not in url:
            continue
        q = parse_qs(urlparse(url).query)
        to = (q.get("to") or q.get("click") or [""])[0] or "(unknown)"
        fr = (q.get("from") or [""])[0]
        raw[to] += 1
        if fr or ref:
            valid[to] += 1
            froms[unquote(fr or ref)] += 1
        else:
            botlike += 1
    lines = [
        "- raw: " + (", ".join(f"{k}={v}" for k, v in raw.most_common()) or "0"),
        "- valid(from/refあり): " + (", ".join(f"{k}={v}" for k, v in valid.most_common()) or "0"),
        f"- botlike(from/refなし): {botlike}",
    ]
    if froms:
        lines.append("- 呼び出し元上位: " + ", ".join(f"{k}={v}" for k, v in froms.most_common(10)))
    return lines


def main():
    run_marketing_context()
    conn = sqlite3.connect(DB)
    total_products = conn.execute("select count(*) from products").fetchone()[0]
    total_posts = conn.execute("select count(*) from posts").fetchone()[0]
    groups = table_rows(conn, """
        select attr_value as group_name, count(distinct product_id) as count
        from product_attributes
        where attr_name='rakuten_genre_group'
        group by attr_value
        order by count desc
        limit 20
    """)
    recent_posts = table_rows(conn, """
        select id, author, substr(content,1,120) as content, created_at, views
        from posts
        order by id desc
        limit 12
    """)
    recent_products = table_rows(conn, """
        select id, name, created_at
        from products
        order by id desc
        limit 12
    """)
    lines = [
        "# AIxEC Growth Observation",
        "",
        "OpenClaw / Claude Code OAuthが、商品登録だけでなくAIxEC全体の成長戦略を判断するための観察レポート。",
        "",
        f"- products: {total_products}",
        f"- AIxSNS posts: {total_posts}",
        "",
        "## go.php Click Quality",
        *analyze_clicks(),
        "",
        "## Market Groups",
    ]
    for row in groups:
        lines.append(f"- {row['group_name']}: {row['count']}件")
    lines += ["", "## Recent AIxSNS Posts"]
    for row in recent_posts:
        lines.append(f"- #{row['id']} {row['author']} views={row['views']} {row['created_at']} {row['content']}")
    lines += ["", "## Recent Products"]
    for row in recent_products:
        lines.append(f"- #{row['id']} {row['created_at']} {row['name']}")
    if MARKETING_CONTEXT.exists():
        lines += ["", "## Marketing Context Digest", ""]
        digest = MARKETING_CONTEXT.read_text(encoding="utf-8", errors="ignore")
        lines.append(digest[:5000])
    if MEMORY.exists():
        lines += ["", "## Memory", ""]
        lines.append(MEMORY.read_text(encoding="utf-8", errors="ignore")[-5000:])
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()

