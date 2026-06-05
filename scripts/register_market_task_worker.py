#!/usr/bin/env python3
"""Register Rakuten Market products from a Claude/OpenClaw task using Ollama for selection."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TASK_DEFAULT = ROOT / "tasks" / "market_task.generated.json"
RESULT_MD = ROOT / "tasks" / "market_task_result.md"
RESULT_JSON = ROOT / "tasks" / "market_task_result.json"

sys.path.insert(0, str(SCRIPTS))
import import_rakuten_market_products as market  # noqa: E402


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_env():
    market.load_env()


def compact_text(value, limit=500):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value[:limit]


def is_excluded(item, task):
    name = item.get("name") or ""
    text = " ".join([
        item.get("name") or "",
        item.get("catchcopy") or "",
        item.get("caption") or "",
        item.get("shop_name") or "",
    ])
    for word in task.get("exclude_keywords") or []:
        if word and word in text:
            return True, "task_exclude:" + word
    for word in market.EXCLUDE_NAME_PATTERNS:
        if word and word in name:
            return True, "common_exclude:" + word
    return False, ""


def exists_in_db(item):
    with market.connect() as conn:
        return market.resolve_existing(conn, item) is not None


def collect_candidates(task, hits=30, pages=2, delay=4.0, max_candidates=1200):
    seen = set()
    candidates = []
    keywords = task.get("keywords") or []
    min_price = int(task.get("min_price") or 0)
    max_price = int(task.get("max_price") or 0)
    raw_genre_id = task.get("genre_id") or ""
    # 楽天ブックスAPI形式(001xxxxxx)は市場検索APIに使えない(上限999999)→空にする
    try:
        genre_id = raw_genre_id if raw_genre_id and int(raw_genre_id) <= 999999 else ""
    except (ValueError, TypeError):
        genre_id = ""
    if raw_genre_id and not genre_id:
        print("genre_id %s is books-format, ignored for item search" % raw_genre_id, flush=True)
    for keyword in keywords:
        for page in range(1, pages + 1):
            print("fetch keyword=%s page=%s" % (keyword, page), flush=True)
            try:
                items = market.fetch_items(keyword, genre_id=genre_id, hits=hits, page=page)
            except Exception as exc:
                print("fetch_skip keyword=%s page=%s error=%s" % (keyword, page, str(exc)[:200]), flush=True)
                time.sleep(delay)
                continue
            for item in items:
                price = item.get("price") or 0
                try:
                    price = int(price)
                except (TypeError, ValueError):
                    price = 0
                if min_price and price < min_price:
                    continue
                if max_price and price > max_price:
                    continue
                code = item.get("item_code")
                if not code or code in seen:
                    continue
                seen.add(code)
                excluded, reason = is_excluded(item, task)
                if excluded:
                    continue
                if exists_in_db(item):
                    continue
                candidates.append(item)
                if len(candidates) >= max_candidates:
                    return candidates
            time.sleep(delay)
    return candidates


def parse_json_object(text):
    text = str(text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        return json.loads(match.group(0))
    raise ValueError("Ollama did not return JSON")


def ollama_generate(prompt, model="gemma4:e4b", timeout=180):
    endpoint = os.environ.get("OLLAMA_ENDPOINT") or os.environ.get("OLLAMA_BASE_URL") or "http://192.168.0.3:11434"
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 1024,
        },
    }, ensure_ascii=False).encode("utf-8")
    req = Request(endpoint.rstrip("/") + "/api/generate", data=payload, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as res:
        data = json.loads(res.read().decode("utf-8"))
    return data.get("response") or ""


def heuristic_score(item, task):
    text = " ".join([item.get("name") or "", item.get("catchcopy") or "", item.get("caption") or ""])
    score = 50
    for keyword in task.get("keywords") or []:
        for part in keyword.split():
            if part and part in text:
                score += 8
    if item.get("review_count") and str(item["review_count"]).isdigit():
        score += min(15, int(item["review_count"]) // 20)
    price = item.get("price") or 0
    try:
        price = int(price)
    except (TypeError, ValueError):
        price = 0
    min_price = int(task.get("min_price") or 0)
    if price:
        score += 5
    if min_price and price >= min_price:
        score += 8
    if price >= 200000:
        score += 6
    elif price >= 150000:
        score += 4
    return min(score, 95)


def score_batch_with_ollama(batch, task, model, timeout):
    payload = []
    for idx, item in enumerate(batch):
        payload.append({
            "idx": idx,
            "name": compact_text(item.get("name"), 180),
            "catchcopy": compact_text(item.get("catchcopy"), 160),
            "caption": compact_text(item.get("caption"), 360),
            "price": item.get("price"),
            "review_average": item.get("review_average"),
            "review_count": item.get("review_count"),
            "shop": item.get("shop_name"),
            "keyword": item.get("keyword"),
        })
    prompt = """AIxECの商品登録候補を評価してください。

AIxECの方針:
- AI、PC、業務効率化、専門知識、経営、医療、介護、学習、開発者向けを優先
- アフィリエイト送客と検索流入に向く商品を優先
- ノイズ、無関係、ふるさと納税、中古リスクが高い商品は除外

今回のジャンル:
label: {label}
group: {group}
description_policy: {policy}
reason: {reason}

候補:
{items}

JSONだけで返してください。
形式:
{{"items":[{{"idx":0,"accept":true,"score":80,"reason":"短い理由"}}]}}
scoreは0-100。accept=falseは登録しません。
""".format(
        label=task.get("label", ""),
        group=task.get("group", ""),
        policy=task.get("description_policy", ""),
        reason=task.get("reason", ""),
        items=json.dumps(payload, ensure_ascii=False),
    )
    try:
        response = ollama_generate(prompt, model=model, timeout=timeout)
        data = parse_json_object(response)
        results = {}
        for row in data.get("items") or []:
            idx = int(row.get("idx"))
            results[idx] = {
                "accept": bool(row.get("accept")),
                "score": int(row.get("score") or 0),
                "reason": compact_text(row.get("reason"), 200),
                "source": "ollama",
            }
        return results
    except Exception as exc:
        print("ollama_error: %s; fallback heuristic" % exc, flush=True)
        return {
            i: {
                "accept": True,
                "score": heuristic_score(item, task),
                "reason": "Ollama失敗のためキーワード一致とレビュー情報で暫定評価",
                "source": "heuristic",
            }
            for i, item in enumerate(batch)
        }


def score_candidates(candidates, task, model, batch_size=20, limit=0, timeout=60, score_mode="ollama", min_score=45):
    if score_mode == "heuristic":
        selected = []
        for item in candidates:
            score = heuristic_score(item, task)
            if score >= min_score:
                item["_selection"] = {
                    "accept": True,
                    "score": score,
                    "reason": "商品名・レビュー・価格・キーワード一致による高速評価",
                    "source": "heuristic",
                }
                selected.append(item)
            if limit and len(selected) >= limit:
                break
        selected.sort(key=lambda item: item.get("_selection", {}).get("score", 0), reverse=True)
        return selected

    selected = []
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start:start + batch_size]
        scores = score_batch_with_ollama(batch, task, model, timeout)
        for idx, item in enumerate(batch):
            s = scores.get(idx) or {"accept": False, "score": 0, "reason": "no score", "source": "none"}
            if s["accept"] and s["score"] >= min_score:
                item["_selection"] = s
                selected.append(item)
        print("scored %d/%d selected=%d" % (min(start + batch_size, len(candidates)), len(candidates), len(selected)), flush=True)
        if limit and len(selected) >= limit:
            break
    selected.sort(key=lambda item: item.get("_selection", {}).get("score", 0), reverse=True)
    return selected


def upsert_selection_attrs(product_id, item):
    selection = item.get("_selection") or {}
    with market.connect() as conn:
        market.upsert_attr(conn, product_id, "market_selection_score", selection.get("score"))
        market.upsert_attr(conn, product_id, "market_selection_reason", selection.get("reason"))
        market.upsert_attr(conn, product_id, "market_selection_source", selection.get("source"))
        conn.commit()


def write_report(task, candidates_count, selected, registered, dry_run):
    result_json = ROOT / "tasks" / "market_task_dry_run_result.json" if dry_run else RESULT_JSON
    result_md = ROOT / "tasks" / "market_task_dry_run_result.md" if dry_run else RESULT_MD
    created = [row for row in registered if row.get("action") in ("created", "selected")]
    updated = [row for row in registered if row.get("action") == "updated"]
    result = {
        "label": task.get("label"),
        "group": task.get("group"),
        "dry_run": dry_run,
        "candidates": candidates_count,
        "selected": len(selected),
        "registered": len(registered),
        "created": len(created),
        "updated": len(updated),
        "items": registered,
    }
    result_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# AIxEC Market Task Result",
        "",
        f"- label: {task.get('label')}",
        f"- group: {task.get('group')}",
        f"- dry_run: {dry_run}",
        f"- candidates: {candidates_count}",
        f"- selected: {len(selected)}",
        f"- registered: {len(registered)}",
        f"- created: {len(created)}",
        f"- updated: {len(updated)}",
        "",
        "## Registered / Selected",
    ]
    for row in registered[:100]:
        lines.append("- #{id} score={score} {name} | {reason}".format(**row))
    result_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(result_md)
    print(result_json)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default=str(TASK_DEFAULT))
    parser.add_argument("--limit", type=int, default=0, help="registration limit. default uses task target_count")
    parser.add_argument("--hits", type=int, default=30)
    parser.add_argument("--pages", type=int, default=10)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--max-candidates", type=int, default=0)
    parser.add_argument("--ollama-timeout", type=int, default=60)
    parser.add_argument("--min-score", type=int, default=45)
    parser.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", "gemma4:e4b"))
    parser.add_argument("--score-mode", choices=("ollama", "heuristic"), default="ollama")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env()
    task_path = Path(args.task)
    if not task_path.is_absolute():
        task_path = ROOT / task_path
    task = load_json(task_path)
    limit = args.limit or int(task.get("target_count") or 100)

    print("[TASK] label=%s group=%s keywords=%d limit=%d" % (
        task.get("label", ""), task.get("group", ""), len(task.get("keywords") or []), limit), flush=True)

    if args.max_candidates:
        max_candidates = args.max_candidates
    elif limit >= 400:
        max_candidates = limit + 100
    else:
        max_candidates = max(limit * 5, 150)
    candidates = collect_candidates(task, hits=args.hits, pages=args.pages, delay=args.delay, max_candidates=max_candidates)
    print("[FETCH] candidates=%d" % len(candidates), flush=True)

    selected = score_candidates(
        candidates,
        task,
        model=args.model,
        batch_size=args.batch_size,
        limit=limit,
        timeout=args.ollama_timeout,
        score_mode=args.score_mode,
        min_score=args.min_score,
    )
    selected = selected[:limit]
    print("[SCORE] selected_for_registration=%d" % len(selected), flush=True)
    print("[REGISTER] 登録開始 %d件" % len(selected), flush=True)

    category = {
        "label": task["label"],
        "group": task["group"],
        "genre_id": task.get("genre_id") or "",
        "affiliate_priority": task.get("affiliate_priority") or "",
    }
    registered = []
    for item in selected:
        selection = item.get("_selection") or {}
        if args.dry_run:
            product_id, action = "dry", "selected"
        else:
            product_id, action = market.upsert_product(item, category, upload=False)
            if product_id:
                upsert_selection_attrs(product_id, item)
        registered.append({
            "id": product_id,
            "action": action,
            "score": selection.get("score", 0),
            "name": compact_text(item.get("name"), 120),
            "reason": selection.get("reason", ""),
        })
        print("%s id=%s score=%s %s" % (action, product_id, selection.get("score", 0), item.get("name", "")[:80]), flush=True)

    write_report(task, len(candidates), selected, registered, args.dry_run)


if __name__ == "__main__":
    main()
