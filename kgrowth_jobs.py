from __future__ import annotations

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_DIR = Path("/home/kojima/work/aixec")
ARTIFACT_DIR = PROJECT_DIR / "storage" / "kgrowth"
SITE_BASE = "https://aixec.exbridge.jp"
SNS_POST_URL = SITE_BASE + "/api.php?path=posts"
KURAGE_BASE = "https://kurage.exbridge.jp"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _result(
    *,
    ok: bool,
    status: str,
    items: int = 0,
    note: str = "",
    metrics: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    error: str = "",
) -> dict[str, Any]:
    result = {
        "ok": ok,
        "status": status,
        "items": int(items or 0),
        "note": note,
        "metrics": metrics or {},
        "artifacts": artifacts or [],
        "error": error,
        "created_at": _now(),
    }
    return result


def _http_post_json(url: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "kgrowth-jobs/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            text = res.read().decode("utf-8", errors="replace")
            status = int(getattr(res, "status", 200))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        status = int(exc.code)
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {"raw": text[:1000]}
    if isinstance(data, dict):
        data.setdefault("status_code", status)
        return data
    return {"ok": status < 400, "status_code": status, "data": data}


def _post_aixsns_if_needed(improvement_job: dict[str, Any], result: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    if result.get("sns_post"):
        return result
    if dry_run or not result.get("ok") or int(result.get("items") or 0) < 1:
        return result
    job_id = str(improvement_job.get("id") or "").strip()
    marker = f"kgrowth:{job_id}" if job_id else ""
    title = str(improvement_job.get("title") or improvement_job.get("kind") or "kgrowth改善ジョブ")
    kind = str(improvement_job.get("kind") or "")
    note = str(result.get("note") or "")
    artifact_lines = []
    for artifact in (result.get("artifacts") or [])[:2]:
        path = artifact.get("path") if isinstance(artifact, dict) else ""
        if path:
            artifact_lines.append(f"成果物: {path}")
    content = "\n".join(
        line
        for line in [
            f"kgrowth改善ジョブ完了: {title}",
            f"kind: {kind}",
            note,
            *artifact_lines,
            "GSCとsimpletrackの分析から作った改善ジョブを実行しました。",
            marker,
        ]
        if line
    )
    post = _http_post_json(SNS_POST_URL, {"author": "kgrowth", "content": content})
    result = dict(result)
    result["sns_post"] = {
        "ok": bool(post.get("ok")),
        "id": (post.get("item") or {}).get("id") if isinstance(post.get("item"), dict) else None,
        "status_code": post.get("status_code"),
    }
    return result


def _read(relative_path: str) -> str:
    path = PROJECT_DIR / relative_path
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding="utf-8", errors="replace")


def _contains_in_order(text: str, first: str, second: str) -> bool:
    left = text.find(first)
    right = text.find(second)
    return left >= 0 and right >= 0 and left < right


def _write_artifact(kind: str, job_id: str, suffix: str, content: str) -> dict[str, Any]:
    safe_kind = re.sub(r"[^a-zA-Z0-9_.-]", "-", kind).strip("-") or "job"
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]", "-", job_id).strip("-") or "latest"
    path = ARTIFACT_DIR / safe_kind / f"{safe_id}.{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "kind": suffix}


def _http_get(url: str, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "kgrowth-jobs/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return int(getattr(res, "status", 200)), res.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")


def _api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = {"path": path.lstrip("/")}
    if params:
        query.update({k: v for k, v in params.items() if v is not None and v != ""})
    url = SITE_BASE + "/api.php?" + urllib.parse.urlencode(query)
    status, text = _http_get(url)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {"ok": False, "raw": text[:1000]}
    data.setdefault("status_code", status)
    return data


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9ぁ-んァ-ン一-龥]+", "-", value.lower()).strip("-")
    return slug[:80] or "topic"


def _file_contains(relative_path: str, patterns: list[str]) -> dict[str, bool]:
    text = _read(relative_path)
    return {pattern: pattern in text for pattern in patterns}


def _amazon_cta_rebalance_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    checks = {
        "go_php_has_amazon": all(_file_contains("webapps/go.php", ["function amazon_url", "tag=bittensorman-22"]).values()),
        "books_amazon_first": _contains_in_order(_read("webapps/books_ranking.php"), "Amazonで見る", "楽天ブックスで見る"),
        "sns_related_amazon_first": _contains_in_order(_read("webapps/sns.php"), "Amazonで探す", "楽天でも見る"),
        "aixtube_amazon_first": _contains_in_order(_read("webapps/aixtube.php"), "Amazonで探す", "楽天市場でも見る"),
    }
    ok = all(checks.values())
    artifact = _write_artifact(
        "amazon_cta_rebalance",
        str(improvement_job.get("id") or "latest"),
        "json",
        json.dumps({"checks": checks, "checked_at": _now()}, ensure_ascii=False, indent=2),
    )
    return _result(
        ok=ok,
        status="ok" if ok else "failed",
        items=1 if ok else 0,
        note="Amazon優先CTA共通テンプレート確認" + ("完了" if ok else "失敗"),
        metrics=checks,
        artifacts=[artifact],
        error="" if ok else "Amazon-first CTA template checks failed",
    )


def _amazon_product_growth_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    payload = dict(improvement_job.get("payload") or {})
    product_id = str(payload.get("product_id") or payload.get("id") or "").strip()
    query = str(payload.get("name") or payload.get("query") or payload.get("keyword") or "").strip()
    product = _api_get(f"products/{product_id}") if product_id else (_api_get("products", {"q": query, "limit": 1}) if query else {})
    item = product.get("item") if isinstance(product.get("item"), dict) else None
    if item is None and isinstance(product.get("items"), list) and product["items"]:
        item = product["items"][0]
    name = str((item or {}).get("name") or query or product_id)
    target_id = str((item or {}).get("id") or product_id)
    amazon_url = SITE_BASE + "/go.php?" + urllib.parse.urlencode({"to": "amazon", "kw": name, "from": "kgrowth-product", "pid": target_id})
    checks = {
        "has_product_or_query": bool(name),
        "go_php_has_amazon": "function amazon_url" in _read("webapps/go.php"),
        "amazon_url_created": "to=amazon" in amazon_url,
    }
    artifact = _write_artifact(
        "amazon_product_growth",
        str(improvement_job.get("id") or target_id or "latest"),
        "json",
        json.dumps({"product": item or {}, "amazon_url": amazon_url, "checks": checks, "checked_at": _now()}, ensure_ascii=False, indent=2),
    )
    ok = all(checks.values())
    return _result(
        ok=ok,
        status="ok" if ok else "failed",
        items=1 if ok else 0,
        note=f"{name}: Amazon導線生成確認" + ("完了" if ok else "失敗"),
        metrics=checks,
        artifacts=[artifact],
        error="" if ok else "Amazon product growth checks failed",
    )


def _amazon_hub_article_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    payload = dict(improvement_job.get("payload") or {})
    topic = str(payload.get("topic") or "").strip()
    title = f"{topic}の選び方とAmazonで探すポイント" if topic else str(improvement_job.get("title") or "Amazon hub article")
    slug = _slugify(topic or title)
    products = _api_get("products", {"q": topic, "limit": 6}) if topic else {"items": []}
    items = products.get("items") if isinstance(products.get("items"), list) else []
    lines = [
        f"# {title}",
        "",
        f"{topic}について検索している人が比較しやすいように、AIxECの商品データとAmazon導線を前提に整理します。",
        "",
        "## 選び方",
        "- 用途を先に決め、必要な性能やサイズを絞ります。",
        "- 価格だけでなくレビュー、発売時期、関連アクセサリも確認します。",
        "- AIxECの商品ページで概要を確認し、Amazonでも在庫や価格を比較します。",
        "",
        "## 関連商品候補",
    ]
    for item in items[:6]:
        name = str(item.get("name") or "")
        pid = str(item.get("id") or "")
        lines.append(f"- {name} ({SITE_BASE}/product/{urllib.parse.quote(name) if name else pid})")
    if not items:
        lines.append("- 現時点では関連商品候補が少ないため、次回の分析で候補を再探索します。")
    lines += [
        "",
        "## Amazon導線",
        f"{SITE_BASE}/go.php?to=amazon&kw={urllib.parse.quote(topic or title)}&from=kgrowth-hub",
        "",
    ]
    artifact = _write_artifact("amazon_hub_article", str(improvement_job.get("id") or slug), "md", "\n".join(lines))
    ok = bool(topic)
    post = _publish_sns_article(
        author="kgrowth",
        title=title,
        description=f"{topic}の選び方、比較ポイント、Amazonで探す導線をAIxECの商品データから整理します。" if topic else title,
        content="\n".join(lines),
        slug="kgrowth-hub-" + slug,
        kind="kgrowth-amazon-hub",
        source_url="",
        dry_run=dry_run,
    ) if ok else {"ok": False}
    ok = ok and bool(post.get("ok"))
    result = _result(
        ok=ok,
        status="ok" if ok else "failed",
        items=1 if ok else 0,
        note=f"{title}: ハブ記事ドラフト生成完了",
        metrics={"topic": topic, "slug": slug, "related_products": len(items)},
        artifacts=[artifact, {"path": post.get("url", ""), "kind": "url"}],
        error="" if ok else "topic is empty or AIxSNS post failed",
    )
    result["sns_post"] = post
    return result


def _publish_sns_article(
    *,
    author: str,
    title: str,
    description: str,
    content: str,
    slug: str,
    kind: str,
    source_url: str = "",
    dry_run: bool,
) -> dict[str, Any]:
    article_url = SITE_BASE + "/sns.php?" + urllib.parse.urlencode({"slug": slug})
    if dry_run:
        return {"ok": True, "dry_run": True, "id": None, "slug": slug, "url": article_url, "status_code": 0}
    payload = {
        "author": author,
        "title": title,
        "description": description,
        "content": content,
        "slug": slug,
        "kind": kind,
        "source_url": source_url,
    }
    post = _http_post_json(SNS_POST_URL, payload, timeout=30)
    item = post.get("item") if isinstance(post.get("item"), dict) else {}
    return {
        "ok": bool(post.get("ok")),
        "id": item.get("id"),
        "slug": item.get("slug") or slug,
        "url": SITE_BASE + "/sns.php?" + urllib.parse.urlencode({"slug": item.get("slug") or slug}),
        "status_code": post.get("status_code"),
        "raw": post,
    }


def _search_query_answer_article_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    payload = dict(improvement_job.get("payload") or {})
    query = str(payload.get("query") or "").strip()
    page = str(payload.get("page") or "").strip()
    if not query or not page:
        return _result(ok=False, status="failed", items=0, note="query and page are required", error="missing query/page")
    amazon_url = SITE_BASE + "/go.php?" + urllib.parse.urlencode({"to": "amazon", "kw": query, "from": "kgrowth-search-query"})
    title = f"{query}を探している人へ"
    slug = "kgrowth-" + _slugify(query)
    description = f"{query}で検索した人向けに、AIxECの関連ページとAmazonで比較する導線をまとめます。"
    content = "\n".join(
        [
            title,
            "",
            f"Google Search Consoleで「{query}」の表示が確認できました。検索している人は、概要だけでなく、関連する商品・書籍・動画をすぐ比較したい状態だと考えられます。",
            "",
            "AIxECでは、このテーマに関連する商品ページやAIxTube動画を確認できます。まず元ページで内容を確認し、購入候補はAmazonでも価格・在庫・レビューを比較してください。",
            "",
            f"元ページ: {page}",
            f"Amazonで探す: {amazon_url}",
            "",
            f"kgrowth:{improvement_job.get('id','')}",
        ]
    )
    artifact = _write_artifact("search_query_answer_article", str(improvement_job.get("id") or ""), "md", content)
    post = _publish_sns_article(
        author="kgrowth",
        title=title,
        description=description,
        content=content,
        slug=slug,
        kind="kgrowth-search-query",
        source_url=page,
        dry_run=dry_run,
    )
    ok = bool(post.get("ok"))
    result = _result(
        ok=ok,
        status="ok" if ok else "failed",
        items=1 if ok else 0,
        note=f"{query}: 検索意図回答記事{'dry-run生成' if dry_run else '投稿'}完了",
        metrics={"query": query, "page": page, "position": payload.get("position"), "impressions": payload.get("impressions")},
        artifacts=[artifact, {"path": post.get("url", ""), "kind": "url"}],
        error="" if ok else "AIxSNS post failed",
    )
    result["sns_post"] = post
    return result


def _affiliate_product_article_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    payload = dict(improvement_job.get("payload") or {})
    product = str(payload.get("product") or "").strip()
    if not product:
        return _result(ok=False, status="failed", items=0, note="product is required", error="missing product")
    pid = str(payload.get("pid") or "").strip()
    jan = str(payload.get("jan") or "").strip()
    model = str(payload.get("model") or "").strip()
    source = str(payload.get("source") or "").strip()
    params = {"to": "amazon", "kw": product, "from": "kgrowth-affiliate-product"}
    if pid:
        params["pid"] = pid
    if jan:
        params["jan"] = jan
    if model:
        params["model"] = model
    amazon_url = SITE_BASE + "/go.php?" + urllib.parse.urlencode(params)
    internal_url = source if source.startswith("http") else (SITE_BASE + source if source.startswith("/") else "")
    title = f"{product}を比較する"
    slug = "kgrowth-product-" + _slugify(product)
    description = f"実クリックがある商品「{product}」について、AIxEC内ページとAmazon比較導線を整理します。"
    content = "\n".join(
        [
            title,
            "",
            "simpletrackのbot除外済み実クリックで反応が出ている商品です。購入検討者は型番・JAN・商品名で探している可能性が高いため、AIxEC内の関連ページとAmazon導線をまとめます。",
            "",
            f"商品名: {product}",
            f"型番: {model}" if model else "",
            f"JAN/ISBN: {jan}" if jan else "",
            f"AIxEC内の流入元: {internal_url}" if internal_url else "",
            f"Amazonで探す: {amazon_url}",
            "",
            f"kgrowth:{improvement_job.get('id','')}",
        ]
    )
    content = "\n".join(line for line in content.splitlines() if line != "")
    artifact = _write_artifact("affiliate_product_article", str(improvement_job.get("id") or ""), "md", content)
    post = _publish_sns_article(
        author="kgrowth",
        title=title,
        description=description,
        content=content,
        slug=slug,
        kind="kgrowth-affiliate-product",
        source_url=internal_url,
        dry_run=dry_run,
    )
    ok = bool(post.get("ok"))
    result = _result(
        ok=ok,
        status="ok" if ok else "failed",
        items=1 if ok else 0,
        note=f"{product}: 実クリック商品記事{'dry-run生成' if dry_run else '投稿'}完了",
        metrics={"product": product, "pid": pid, "jan": jan, "model": model, "clicks": payload.get("clicks", 0)},
        artifacts=[artifact, {"path": post.get("url", ""), "kind": "url"}],
        error="" if ok else "AIxSNS post failed",
    )
    result["sns_post"] = post
    return result


def _aixtube_amazon_cta_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    text = _read("webapps/aixtube.php")
    body = text.split("<body>", 1)[-1]
    checks = {
        "has_amazon_click_url": "function amazon_click_url" in text,
        "has_rakuten_click_url": "function rakuten_click_url" in text,
        "top_nav_amazon_before_rakuten": _contains_in_order(body, "nav-amazon", "nav-rakuten"),
        "body_cta_amazon_before_rakuten": _contains_in_order(body, "Amazonで探す", "楽天市場でも見る"),
        "description_meta_exists": 'name="description"' in text,
    }
    artifact = _write_artifact(
        "aixtube_amazon_cta",
        str(improvement_job.get("id") or "latest"),
        "json",
        json.dumps({"checks": checks, "checked_at": _now()}, ensure_ascii=False, indent=2),
    )
    ok = all(checks.values())
    return _result(
        ok=ok,
        status="ok" if ok else "failed",
        items=1 if ok else 0,
        note="AIxTube Amazon優先CTA確認" + ("完了" if ok else "失敗"),
        metrics=checks,
        artifacts=[artifact],
        error="" if ok else "AIxTube Amazon CTA checks failed",
    )


def _aixtube_search_snippet_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    payload = dict(improvement_job.get("payload") or {})
    query = str(payload.get("query") or "").strip()
    page = str(payload.get("page") or "").strip()
    status_code, html = _http_get(page) if page else (0, "")
    lower = html.lower()
    checks = {
        "status_code": status_code,
        "has_title": "<title>" in lower,
        "has_description": 'name="description"' in lower,
        "has_og_description": 'property="og:description"' in lower,
        "has_amazon": "to=amazon" in lower or "amazon" in lower,
        "query_seen": bool(query and query.lower() in lower),
    }
    artifact = _write_artifact(
        "aixtube_search_snippet",
        str(improvement_job.get("id") or "latest"),
        "json",
        json.dumps({"query": query, "page": page, "checks": checks, "checked_at": _now()}, ensure_ascii=False, indent=2),
    )
    ok = status_code == 200 and checks["has_title"] and checks["has_description"] and checks["has_og_description"] and checks["has_amazon"]
    return _result(
        ok=ok,
        status="ok" if ok else "failed",
        items=1 if ok else 0,
        note=f"{query or page}: AIxTube検索スニペット確認" + ("完了" if ok else "失敗"),
        metrics=checks,
        artifacts=[artifact],
        error="" if ok else "AIxTube page snippet check failed",
    )


def _buzblogger_search_intent_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    root = Path("/home/kojima/work/buzblogger")
    checks = {
        "schema_has_search_query": False,
        "skill_mentions_query": False,
        "product_search_uses_title": False,
        "post_uses_search_query": False,
    }
    schema = (root / "tasks" / "buzblog_post.schema.json").read_text(encoding="utf-8", errors="replace")
    skill = (root / "skills" / "buzblogger" / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    finder = (root / "scripts" / "find_related_products.py").read_text(encoding="utf-8", errors="replace")
    poster = (root / "scripts" / "post_buzblog.py").read_text(encoding="utf-8", errors="replace")
    checks["schema_has_search_query"] = '"search_query"' in schema
    checks["skill_mentions_query"] = "検索クエリ" in skill or "search_query" in skill
    checks["product_search_uses_title"] = (
        "search_query =" in finder
        and ("search_products(keyword" in finder or "search_products(search_query" in finder or "search_products(title" in finder)
    )
    checks["post_uses_search_query"] = "search_query" in poster
    ok = all(checks.values())
    artifact = _write_artifact("buzblogger_search_intent", str(improvement_job.get("id") or ""), "json", json.dumps(checks, ensure_ascii=False, indent=2))
    return _result(
        ok=ok,
        status="ok" if ok else "failed",
        items=1 if ok else 0,
        note="BuzBlogger検索意図対応チェック" + ("完了" if ok else "未完了"),
        metrics=checks,
        artifacts=[artifact],
        error="" if ok else "buzblogger search intent implementation is incomplete",
    )


def _aixsns_register_noindex_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    sns = _read("webapps/sns.php")
    checks = {
        "has_noindex": "noindex,follow" in sns,
        "checks_register_author": "register" in sns and "author" in sns,
        "detail_only": "$detail_post" in sns,
    }
    ok = all(checks.values())
    return _result(
        ok=ok,
        status="ok" if ok else "failed",
        items=1 if ok else 0,
        note="AIxSNS register noindex確認" + ("完了" if ok else "失敗"),
        metrics=checks,
        artifacts=[{"path": str(PROJECT_DIR / "webapps/sns.php"), "kind": "php"}],
        error="" if ok else "register detail noindex rule not found",
    )


def _kurage_page_url(path: str) -> str:
    path = str(path or "").strip()
    if path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return KURAGE_BASE + path


def _http_get_text(url: str, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "kgrowth-kurage/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return int(getattr(res, "status", 200)), res.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return 0, str(exc)


def _kurage_video_detail_seo_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    payload = improvement_job.get("payload") if isinstance(improvement_job.get("payload"), dict) else {}
    page = str(payload.get("page") or "")
    url = _kurage_page_url(page)
    status, html = _http_get_text(url)
    checks = {
        "http_ok": 200 <= status < 300,
        "has_title": "<title>" in html.lower(),
        "has_description": 'name="description"' in html.lower(),
        "has_canonical": 'rel="canonical"' in html.lower(),
        "has_video_object": "VideoObject" in html,
        "has_thumbnail": "proxy=thumbnail" in html,
        "has_video_player": "proxy=video" in html,
    }
    artifact = _write_artifact(
        "kurage_video_detail_seo",
        str(improvement_job.get("id") or ""),
        "json",
        json.dumps({"url": url, "checks": checks, "dry_run": dry_run}, ensure_ascii=False, indent=2),
    )
    ok = checks["http_ok"] and checks["has_title"] and checks["has_description"] and checks["has_canonical"]
    return _result(
        ok=ok,
        status="ok" if ok else "failed",
        items=1 if ok else 0,
        note="Kurage動画詳細SEO確認" + ("完了" if ok else "失敗"),
        metrics=checks,
        artifacts=[artifact],
        error="" if ok else "Kurage video detail page SEO metadata is incomplete",
    )


def _kurage_amazon_cta_from_clicks_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    payload = improvement_job.get("payload") if isinstance(improvement_job.get("payload"), dict) else {}
    keyword = str(payload.get("keyword") or "AI動画生成").strip()
    asin = str(payload.get("asin") or "").strip()
    source_page = str(payload.get("source_page") or "/kuragev.php").strip()
    cta_url = "/go.php?to=amazon&kw=" + urllib.parse.quote(keyword)
    if asin:
        cta_url += "&asin=" + urllib.parse.quote(asin)
    cta_url += "&from=" + urllib.parse.quote(source_page)
    artifact_payload = {
        "source_page": source_page,
        "keyword": keyword,
        "asin": asin,
        "cta_url": cta_url,
        "html": f'<a href="{cta_url}" rel="nofollow sponsored">Amazonで関連商品を見る</a>',
        "dry_run": dry_run,
    }
    artifact = _write_artifact(
        "kurage_amazon_cta_from_clicks",
        str(improvement_job.get("id") or ""),
        "json",
        json.dumps(artifact_payload, ensure_ascii=False, indent=2),
    )
    status, _ = _http_get_text(KURAGE_BASE + "/go.php?to=amazon&kw=" + urllib.parse.quote(keyword) + "&from=" + urllib.parse.quote(source_page), timeout=10)
    ok = status in {204, 302} or 300 <= status < 400
    return _result(
        ok=ok,
        status="ok" if ok else "failed",
        items=1 if ok else 0,
        note="Kurage Amazon CTA案生成" + ("完了" if ok else "失敗"),
        metrics={"go_php_status": status, "has_keyword": bool(keyword), "has_source_page": bool(source_page)},
        artifacts=[artifact],
        error="" if ok else "Kurage go.php did not respond as expected",
    )


def _kurage_search_intent_video_page_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    payload = improvement_job.get("payload") if isinstance(improvement_job.get("payload"), dict) else {}
    query = str(payload.get("query") or "").strip()
    page = str(payload.get("page") or "").strip()
    artifact_payload = {
        "query": query,
        "page": page,
        "recommended_changes": [
            "Align title and meta description with the search query.",
            "Add related Kurage/Horizon video links for the same intent.",
            "Add an Amazon CTA through /go.php only when the query has buying or learning-resource intent.",
        ],
        "dry_run": dry_run,
    }
    artifact = _write_artifact(
        "kurage_search_intent_video_page",
        str(improvement_job.get("id") or ""),
        "json",
        json.dumps(artifact_payload, ensure_ascii=False, indent=2),
    )
    return _result(
        ok=bool(query and page),
        status="ok" if query and page else "failed",
        items=1 if query and page else 0,
        note="Kurage検索意図動画ページ改善案生成" + ("完了" if query and page else "失敗"),
        metrics={"has_query": bool(query), "has_page": bool(page)},
        artifacts=[artifact],
        error="" if query and page else "query/page is missing",
    )


def execute_improvement_job(
    dry_run: bool = False,
    improvement_job: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute one kgrowth improvement proposal.

    This module lives in the AIxEC repo because the concrete implementation is
    AIxEC-specific. kdeck only decides which goal to run; rqdb4ai only executes
    this generic function name from the app repo.
    """
    job = dict(improvement_job or kwargs.get("job") or {})
    kind = re.sub(r"[^a-zA-Z0-9_.-]", "-", str(job.get("kind") or "")).strip("-")
    if not kind:
        return _result(ok=False, status="failed", items=0, note="improvement_job.kind is required", error="missing kind")

    if kind == "search_query_answer_article":
        result = _search_query_answer_article_job(job, dry_run)
    elif kind == "affiliate_product_article":
        result = _affiliate_product_article_job(job, dry_run)
    elif kind == "amazon_cta_rebalance":
        result = _amazon_cta_rebalance_job(job, dry_run)
    elif kind == "amazon_product_growth":
        result = _amazon_product_growth_job(job, dry_run)
    elif kind == "amazon_hub_article":
        result = _amazon_hub_article_job(job, dry_run)
    elif kind == "aixtube_amazon_cta":
        result = _aixtube_amazon_cta_job(job, dry_run)
    elif kind == "aixtube_search_snippet":
        result = _aixtube_search_snippet_job(job, dry_run)
    elif kind == "buzblogger_search_intent":
        result = _buzblogger_search_intent_job(job, dry_run)
    elif kind == "aixsns_register_noindex":
        result = _aixsns_register_noindex_job(job, dry_run)
    elif kind == "kurage_video_detail_seo":
        result = _kurage_video_detail_seo_job(job, dry_run)
    elif kind == "kurage_amazon_cta_from_clicks":
        result = _kurage_amazon_cta_from_clicks_job(job, dry_run)
    elif kind == "kurage_search_intent_video_page":
        result = _kurage_search_intent_video_page_job(job, dry_run)
    else:
        return _result(
            ok=False,
            status="failed",
            items=0,
            note=f"unsupported kgrowth improvement kind: {kind}",
            metrics={"kind": kind},
            artifacts=[],
            error=f"kgrowth job kind is not implemented: {kind}",
        )
    if str(job.get("target_app") or "") == "kurage":
        return result
    return _post_aixsns_if_needed(job, result, dry_run)
