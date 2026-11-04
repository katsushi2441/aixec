#!/usr/bin/env python3
"""AIxSNS の告知に残っている github.io のブログURLを /vibeblog/ に直す（2026-11-04）。

  set -a; . /home/kojima/work/aixec/.env; set +a
  /usr/bin/python3 scripts/fix_github_io_urls.py --dry-run          # 何件・どう変わるかだけ
  /usr/bin/python3 scripts/fix_github_io_urls.py --only 14970        # 1件だけ本番で直して確かめる
  /usr/bin/python3 scripts/fix_github_io_urls.py                     # 全部

- 対象: 公開 API（https://aixec.exbridge.jp/api.php?path=posts）の全投稿のうち
  https://katsushi2441.github.io/vwork/blog/<slug>.html → https://exbridge.jp/vibeblog/<slug>.html（ブログは全部 /vibeblog/ が正）
  https://katsushi2441.github.io/vwork/articles/<slug>.html → /vibeblog/ に移した記事（vwork/_data/vibeblog_moved_articles.yml）だけ置き換える。
  Horizon の自動ニュースまとめ（移していないもの）はそのまま。
- 置き換え先は必ず HEAD で 200 を確かめる（無いものは変えない）。
- 更新は POST api.php?path=posts/update（X-AIXEC-API-TOKEN）。slug・title・description・kind・source_url・author は今の値をそのまま送る（slug が変わらないように）。
- 記録: outputs/fix_github_io_urls_<日時>.json（id・前後の URL）
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime

import yaml

API = "https://aixec.exbridge.jp/api.php?path=posts"
UPDATE = "https://aixec.exbridge.jp/api.php?path=posts/update"
TOKEN = os.environ.get("AIXEC_API_TOKEN", "")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOVED = set(yaml.safe_load(open("/home/kojima/work/vwork/_data/vibeblog_moved_articles.yml")))
PAT = re.compile(r"https?://katsushi2441\.github\.io/vwork/(blog|articles)/([A-Za-z0-9._-]+?)\.html(\?[^\s)\]」、。]*)?")
UA = {"User-Agent": "Mozilla/5.0 (fix_github_io_urls)"}


def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))


def head_ok(url, cache={}):
    if url in cache:
        return cache[url]
    try:
        cache[url] = urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=UA), timeout=15).status == 200
    except Exception:  # noqa: BLE001
        cache[url] = False
    return cache[url]


def fetch_all():
    first = get(f"{API}&limit=100&offset=0")
    items, total, off = list(first["items"]), first["total"], 100
    while off < total:
        d = get(f"{API}&limit=100&offset={off}")
        if not d["items"]:
            break
        items += d["items"]
        off += 100
        time.sleep(0.2)
    return items


def rewrite(text):
    """置き換え後の文字列と、置き換えた (前, 後) の一覧。置き換え先が無いものは触らない。"""
    changes = []

    def sub(m):
        kind, slug = m.group(1), m.group(2)
        if kind == "articles" and slug not in MOVED:
            return m.group(0)
        new = f"https://exbridge.jp/vibeblog/{slug}.html"
        if not head_ok(new):
            return m.group(0)
        changes.append((m.group(0), new))
        return new
    return PAT.sub(sub, text or ""), changes


def main():
    dry = "--dry-run" in sys.argv
    only = None
    if "--only" in sys.argv:
        only = int(sys.argv[sys.argv.index("--only") + 1])
    if not dry and not TOKEN:
        sys.exit("AIXEC_API_TOKEN が無い（set -a; . aixec/.env; set +a）")
    items = fetch_all()
    print(f"投稿 {len(items)} 件を読んだ")
    log, n_touch, n_skip = [], 0, 0
    for it in items:
        if only and it["id"] != only:
            continue
        if "github.io/vwork/" not in ((it.get("content") or "") + (it.get("source_url") or "")):
            continue
        content, ch1 = rewrite(it.get("content"))
        source_url, ch2 = rewrite(it.get("source_url"))
        if not ch1 and not ch2:
            n_skip += 1
            continue
        n_touch += 1
        log.append({"id": it["id"], "changes": ch1 + ch2})
        if dry:
            continue
        body = {"id": it["id"], "content": content, "author": it.get("author") or "xb_bittensor",
                "slug": it.get("slug") or "", "title": it.get("title") or "", "description": it.get("description") or "",
                "kind": it.get("kind") or "post", "source_url": source_url}
        req = urllib.request.Request(UPDATE, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     headers={**UA, "Content-Type": "application/json", "X-AIXEC-API-TOKEN": TOKEN}, method="POST")
        try:
            res = json.load(urllib.request.urlopen(req, timeout=60))
            log[-1]["ok"] = bool(res.get("ok"))
            if not res.get("ok"):
                log[-1]["error"] = res
        except Exception as e:  # noqa: BLE001
            log[-1]["ok"] = False
            log[-1]["error"] = str(e)
        time.sleep(0.4)
    print(f"直す対象 {n_touch} 件（置き換え先が無く触らない github.io 入り投稿 {n_skip} 件）")
    if not dry:
        print("成功", sum(1 for x in log if x.get("ok")), "失敗", sum(1 for x in log if x.get("ok") is False))
    os.makedirs(os.path.join(ROOT, "outputs"), exist_ok=True)
    path = os.path.join(ROOT, "outputs", f"fix_github_io_urls_{datetime.now():%Y%m%d_%H%M%S}{'_dry' if dry else ''}.json")
    json.dump(log, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("記録:", path)


if __name__ == "__main__":
    main()
