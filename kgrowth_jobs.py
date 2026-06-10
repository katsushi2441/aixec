from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any


PROJECT_DIR = Path("/home/kojima/work/aixec")


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
    return {
        "ok": ok,
        "status": status,
        "items": int(items or 0),
        "note": note,
        "metrics": metrics or {},
        "artifacts": artifacts or [],
        "error": error,
        "created_at": _now(),
    }


def _read(relative_path: str) -> str:
    path = PROJECT_DIR / relative_path
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding="utf-8", errors="replace")


def _contains_in_order(text: str, first: str, second: str) -> bool:
    left = text.find(first)
    right = text.find(second)
    return left >= 0 and right >= 0 and left < right


def _amazon_cta_rebalance_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    checks = {
        "product_page_amazon_banner": False,
        "product_page_amazon_before_rakuten": False,
        "market_ranking_amazon_button": False,
        "aixtube_amazon_box": False,
        "books_ranking_amazon_button": False,
    }

    product = _read("webapps/index.php")
    checks["product_page_amazon_banner"] = "/images/amazon.png" in product and "to=amazon" in product
    checks["product_page_amazon_before_rakuten"] = _contains_in_order(product, "$amazon_click_url", "$rakuten_click_url")

    market = _read("webapps/market_ranking.php")
    checks["market_ranking_amazon_button"] = "Amazonで見る" in market and "amazon_click_url" in market

    aixtube = _read("webapps/aixtube.php")
    checks["aixtube_amazon_box"] = "Amazonを優先表示しています" in aixtube and "Amazonで探す" in aixtube

    books = _read("webapps/books_ranking.php")
    checks["books_ranking_amazon_button"] = "Amazonで見る" in books and "amazon_click_url" in books

    ok = all(checks.values())
    artifacts = [
        {"path": str(PROJECT_DIR / "webapps/index.php"), "kind": "php"},
        {"path": str(PROJECT_DIR / "webapps/market_ranking.php"), "kind": "php"},
        {"path": str(PROJECT_DIR / "webapps/aixtube.php"), "kind": "php"},
        {"path": str(PROJECT_DIR / "webapps/books_ranking.php"), "kind": "php"},
    ]
    title = str(improvement_job.get("title") or "Amazon CTA rebalance")
    if ok:
        return _result(
            ok=True,
            status="ok",
            items=1,
            note=f"{title}: Amazon優先CTAを確認しました",
            metrics={"checks_passed": sum(1 for value in checks.values() if value), "checks_total": len(checks), **checks},
            artifacts=artifacts,
        )
    return _result(
        ok=False,
        status="failed",
        items=0,
        note=f"{title}: Amazon優先CTAの検証に失敗しました",
        metrics={"checks_passed": sum(1 for value in checks.values() if value), "checks_total": len(checks), **checks},
        artifacts=artifacts,
        error=json.dumps({k: v for k, v in checks.items() if not v}, ensure_ascii=False),
    )


def _unsupported_job(improvement_job: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    kind = str(improvement_job.get("kind") or "unknown")
    title = str(improvement_job.get("title") or kind)
    return _result(
        ok=False,
        status="hold",
        items=0,
        note=f"{title}: kind={kind} はまだ実行関数未実装です",
        metrics={"unsupported": 1},
        error="unsupported improvement job kind",
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

    if kind in {"amazon_cta_rebalance", "aixtube_amazon_cta"}:
        return _amazon_cta_rebalance_job(job, dry_run)

    return _unsupported_job(job, dry_run)
