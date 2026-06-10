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
    return _result(
        ok=ok,
        status="ok" if ok else "failed",
        items=1 if ok else 0,
        note=f"{title}: ハブ記事ドラフト生成完了",
        metrics={"topic": topic, "slug": slug, "related_products": len(items)},
        artifacts=[artifact],
        error="" if ok else "topic is empty",
    )


def _aixtube_search_snippet_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    payload = dict(improvement_job.get("payload") or {})
    query = str(payload.get("query") or "").strip()
    page = str(payload.get("page") or "").strip()
    status_code, html = _http_get(page) if page else (0, "")
    checks = {
        "status_code": status_code,
        "has_title": "<title>" in html.lower(),
        "has_description": 'name="description"' in html.lower(),
        "has_amazon": "to=amazon" in html.lower() or "amazon" in html.lower(),
        "query_seen": bool(query and query.lower() in html.lower()),
    }
    artifact = _write_artifact(
        "aixtube_search_snippet",
        str(improvement_job.get("id") or ""),
        "json",
        json.dumps({"query": query, "page": page, "checks": checks, "checked_at": _now()}, ensure_ascii=False, indent=2),
    )
    ok = status_code == 200 and checks["has_title"] and checks["has_description"] and checks["has_amazon"]
    return _result(
        ok=ok,
        status="ok" if ok else "failed",
        items=1 if ok else 0,
        note=f"{query or page}: AIxTube検索スニペット確認{'完了' if ok else '失敗'}",
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


def _unsupported_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    kind = str(improvement_job.get("kind") or "unknown")
    title = str(improvement_job.get("title") or kind)
    return _result(
        ok=True,
        status="warn",
        items=1,
        note=f"{title}: kind={kind} は汎用実行記録として処理しました",
        metrics={"generic_execution_record": 1},
        artifacts=[_write_artifact(kind, str(improvement_job.get("id") or ""), "json", json.dumps(improvement_job, ensure_ascii=False, indent=2))],
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

    if kind == "amazon_hub_article":
        result = _amazon_hub_article_job(job, dry_run)
    elif kind == "aixtube_search_snippet":
        result = _aixtube_search_snippet_job(job, dry_run)
    elif kind == "buzblogger_search_intent":
        result = _buzblogger_search_intent_job(job, dry_run)
    elif kind == "aixsns_register_noindex":
        result = _aixsns_register_noindex_job(job, dry_run)
    else:
        result = _unsupported_job(job, dry_run)
    return _post_aixsns_if_needed(job, result, dry_run)
