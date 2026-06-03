from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


DEFAULT_PROJECT_DIR = "/home/kojima/work/aixec"
DEFAULT_AIXEC_API = "https://aixec.exbridge.jp/api.php"
DEFAULT_MARKET_REGISTER_TASK_API = "https://aixec.exbridge.jp/api.php?path=market/register-task"
DEFAULT_MARKET_TIMEOUT = 3600
DEFAULT_GROWTH_TIMEOUT = 1800
DEFAULT_REGISTER_TIMEOUT = 1800


def _standard_result(
    *,
    ok: bool,
    status: str,
    items: int = 0,
    metrics: dict[str, Any] | None = None,
    note: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    error: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "ok": bool(ok),
        "status": status,
        "items": int(items or 0),
        "metrics": metrics or {},
        "note": note,
        "artifacts": artifacts or [],
        "error": error,
    }
    result.update(extra)
    return result


def _tail(value: str, limit: int = 4000) -> str:
    if not value:
        return ""
    return value[-limit:]


def _project_dir() -> Path:
    path = Path(os.environ.get("AIXEC_DIR", DEFAULT_PROJECT_DIR)).expanduser()
    if not path.is_dir():
        raise RuntimeError(f"AIxEC project directory not found: {path}")
    return path


def _run(
    command: list[str],
    *,
    dry_run: bool,
    timeout: int,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    project_dir = cwd or _project_dir()
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    started_at = dt.datetime.now(dt.timezone.utc)
    result = subprocess.run(
        command,
        cwd=str(project_dir),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    finished_at = dt.datetime.now(dt.timezone.utc)

    response = {
        "status": "ok" if result.returncode == 0 else "failed",
        "created_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "dry_run": bool(dry_run),
        "cwd": str(project_dir),
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": _tail(result.stdout),
        "stderr_tail": _tail(result.stderr),
    }
    if result.returncode != 0:
        raise RuntimeError(
            "AIxEC market job failed "
            f"returncode={result.returncode}\n"
            f"command={command}\n"
            f"stdout tail:\n{response['stdout_tail']}\n"
            f"stderr tail:\n{response['stderr_tail']}"
        )
    return response


def _env_from_kwargs(kwargs: dict[str, Any]) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("AIXEC_DB", "AIXEC_API_BASE", "CLAUDE_BIN"):
        value = kwargs.get(key) or kwargs.get(key.lower())
        if value:
            env[key] = str(value)
    if "CLAUDE_BIN" not in env and not os.environ.get("CLAUDE_BIN"):
        claude_bin = shutil.which("claude")
        if not claude_bin:
            candidates = sorted(
                Path("/home/kojima/.vscode-server/extensions").glob(
                    "anthropic.claude-code-*/resources/native-binary/claude"
                ),
                reverse=True,
            )
            if candidates:
                claude_bin = str(candidates[0])
        if claude_bin:
            env["CLAUDE_BIN"] = claude_bin
    return env


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _load_task(kwargs: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    project_dir = _project_dir()
    task = kwargs.get("task")
    if isinstance(task, dict):
        return task

    task_json = kwargs.get("task_json")
    if isinstance(task_json, str) and task_json.strip():
        return json.loads(task_json)

    task_path = kwargs.get("task_path")
    if task_path:
        path = Path(str(task_path))
        if not path.is_absolute():
            path = project_dir / path
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))

    generated = project_dir / "tasks" / "market_task.generated.json"
    if generated.is_file():
        return json.loads(generated.read_text(encoding="utf-8"))

    if dry_run:
        return {
            "label": str(kwargs.get("label") or "AI PC・ゲーミング"),
            "group": str(kwargs.get("group") or "ai_pc_gaming"),
            "genre_id": str(kwargs.get("genre_id") or ""),
            "keywords": kwargs.get("keywords") or ["ゲーミングPC", "ミニPC", "GPU"],
            "exclude_keywords": kwargs.get("exclude_keywords") or [],
            "target_count": int(kwargs.get("target_count") or kwargs.get("limit") or 3),
            "description_policy": "RQDB4AI dry-run default task",
            "reason": "dry-run default task because market_task.generated.json was not found",
        }

    raise RuntimeError(
        "market task is required. Provide task/task_json/task_path or create "
        "/home/kojima/work/aixec/tasks/market_task.generated.json"
    )


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 60) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json", "User-Agent": "rqdb4ai-aixec/0.1"}
    if headers:
        request_headers.update(headers)
    req = Request(url, data=data, headers=request_headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8", errors="replace")
            status_code = getattr(res, "status", None)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {raw[:1000]}") from exc
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {"raw": raw}
    return {"status_code": status_code, "response": parsed}


def _api_base(kwargs: dict[str, Any]) -> str:
    return str(
        kwargs.get("aixec_api_url")
        or kwargs.get("api_url")
        or os.environ.get("AIXEC_PUBLIC_API_URL")
        or os.environ.get("AIXEC_API_URL")
        or DEFAULT_AIXEC_API
    ).rstrip("/")


def _api_url(path: str, kwargs: dict[str, Any], query: dict[str, Any] | None = None) -> str:
    base = _api_base(kwargs)
    clean_path = path.strip("/")
    query = {k: v for k, v in (query or {}).items() if v is not None and v != ""}
    if base.endswith("api.php"):
        url = base + "?path=" + quote(clean_path, safe="/")
        if query:
            url += "&" + urlencode(query, doseq=True)
        return url
    url = base + "/" + "/".join(quote(part, safe="") for part in clean_path.split("/"))
    if query:
        url += "?" + urlencode(query, doseq=True)
    return url


def _api_get(path: str, kwargs: dict[str, Any], query: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    req = Request(_api_url(path, kwargs, query), headers={"User-Agent": "rqdb4ai-aixec/0.1"})
    with urlopen(req, timeout=timeout) as res:
        raw = res.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _api_post(path: str, payload: dict[str, Any], kwargs: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    token = (
        kwargs.get("api_token")
        or kwargs.get("AIXEC_API_TOKEN")
        or kwargs.get("aixec_api_token")
        or os.environ.get("AIXEC_MARKET_REGISTER_TOKEN")
        or os.environ.get("AIXEC_API_TOKEN")
    )
    request_payload = dict(payload)
    if token and "api_token" not in request_payload:
        request_payload["api_token"] = str(token)
    return _post_json(_api_url(path, kwargs), request_payload, timeout=timeout)


def _worker_status(name: str, kwargs: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    try:
        payload = _api_get("worker/status", kwargs, timeout=timeout)
    except Exception as exc:
        return {"status": "unknown", "items": 0, "note": f"worker/status unavailable: {exc}"}
    workers = payload.get("workers") if isinstance(payload, dict) else None
    if isinstance(workers, dict) and isinstance(workers.get(name), dict):
        return dict(workers.get(name) or {})
    return {"status": "unknown", "items": 0, "note": f"{name} not found"}


def _metrics_from_worker_status(record: dict[str, Any]) -> dict[str, int]:
    note = str(record.get("note") or "")
    items = int(record.get("items") or 0)
    metrics = {"created": items}
    for key in ("created", "updated", "skipped", "failed", "market", "books"):
        match = re.search(rf"\b{re.escape(key)}=(\d+)", note)
        if match:
            metrics[key] = int(match.group(1))
    if "market" in metrics and "created" not in metrics:
        metrics["created"] = metrics["market"]
    return metrics


def _report_register_worker(kwargs: dict[str, Any], status: str, items: int, note: str) -> None:
    try:
        _api_post(
            "worker/report",
            {"name": "aixec-register-market-worker-enqueue", "status": status, "items": int(items), "note": note[:200]},
            kwargs,
            timeout=20,
        )
    except Exception:
        # The RQ result is still the source of truth if the dashboard report endpoint is temporarily unavailable.
        pass


def _product_exists_by_key(product_key: str, kwargs: dict[str, Any]) -> bool:
    if not product_key:
        return False
    try:
        payload = _api_get("products/" + product_key, kwargs, timeout=20)
        return bool(payload.get("ok") and payload.get("item"))
    except Exception:
        return False


def _book_product_payload(book: dict[str, Any], description_html: str) -> dict[str, Any]:
    isbn = "".join(ch for ch in str(book.get("isbn") or "") if ch.isdigit())
    return {
        "name": book.get("title") or "",
        "maker": book.get("publisher_name") or "楽天ブックス",
        "model_number": isbn or None,
        "jan": isbn or None,
        "gtin": isbn or None,
        "internal_sku": "rakuten_books:" + isbn if isbn else None,
        "description": description_html,
        "sale_price": book.get("item_price"),
        "source_url": book.get("item_url"),
        "rakuten_url": book.get("affiliate_url") or book.get("item_url"),
        "affiliate_priority": "rakuten",
        "status": "active",
        "image_url": book.get("image_url") or "",
    }


def _post_register_sns(kwargs: dict[str, Any], title: str, lines: list[str], url: str) -> Any:
    content = title + "\n\n" + "".join("・%s\n" % line for line in lines[:10])
    if len(lines) > 10:
        content += "\nほか%d件\n" % (len(lines) - 10)
    content += "\n" + url
    result = _api_post("posts", {"author": "register", "content": content}, kwargs, timeout=30)
    response = result.get("response") or {}
    item = response.get("item") or {}
    return item.get("id")


def _limit_text(value: Any, limit: int = 3000) -> str:
    text = str(value or "")
    return text[:limit]


def _chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    size = max(1, int(size))
    return [items[index : index + size] for index in range(0, len(items), size)]


def _book_candidate_payload(book: dict[str, Any], tab: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _limit_text(book.get("title"), 500),
        "author": _limit_text(book.get("author"), 500),
        "publisher_name": _limit_text(book.get("publisher_name"), 300),
        "isbn": _limit_text(book.get("isbn"), 32),
        "item_caption": _limit_text(book.get("item_caption"), 3000),
        "item_price": book.get("item_price"),
        "item_url": _limit_text(book.get("item_url"), 1000),
        "affiliate_url": _limit_text(book.get("affiliate_url"), 1000),
        "image_url": _limit_text(book.get("image_url"), 1000),
        "tab_label": _limit_text(tab.get("label"), 100),
        "tab_group": _limit_text(tab.get("group"), 100),
    }


def _market_candidate_payload(item: dict[str, Any], category: dict[str, Any]) -> dict[str, Any]:
    return {
        "keyword": _limit_text(item.get("keyword"), 200),
        "name": _limit_text(item.get("name"), 800),
        "catchcopy": _limit_text(item.get("catchcopy"), 1000),
        "caption": _limit_text(item.get("caption"), 3000),
        "price": item.get("price"),
        "item_url": _limit_text(item.get("item_url"), 1000),
        "affiliate_url": _limit_text(item.get("affiliate_url"), 1000),
        "image_url": _limit_text(item.get("image_url"), 1000),
        "shop_name": _limit_text(item.get("shop_name"), 300),
        "shop_code": _limit_text(item.get("shop_code"), 200),
        "item_code": _limit_text(item.get("item_code"), 300),
        "genre_id": _limit_text(item.get("genre_id"), 100),
        "review_average": _limit_text(item.get("review_average"), 50),
        "review_count": _limit_text(item.get("review_count"), 50),
        "jan": _limit_text(item.get("jan"), 32),
        "category_label": _limit_text(category.get("label"), 100),
        "category_group": _limit_text(category.get("group"), 100),
    }


def _submit_market_candidates(payload: dict[str, Any], kwargs: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    if dry_run or kwargs.get("skip_submit") or kwargs.get("skip_post"):
        return {"submitted": False, "reason": "dry_run_or_skip_submit"}

    url = str(
        kwargs.get("submit_url")
        or kwargs.get("register_task_url")
        or os.environ.get("AIXEC_MARKET_REGISTER_TASK_API")
        or DEFAULT_MARKET_REGISTER_TASK_API
    )
    token = (
        kwargs.get("api_token")
        or kwargs.get("AIXEC_API_TOKEN")
        or kwargs.get("aixec_api_token")
        or os.environ.get("AIXEC_MARKET_REGISTER_TOKEN")
        or os.environ.get("AIXEC_API_TOKEN")
    )
    request_payload = dict(payload)
    if token:
        request_payload["api_token"] = str(token)

    result = _post_json(url, request_payload, timeout=int(kwargs.get("submit_timeout") or 120))
    return {"submitted": True, "url": url, **result}


def _generate_market_candidates(task: dict[str, Any], dry_run: bool, kwargs: dict[str, Any]) -> dict[str, Any]:
    project_dir = _project_dir()
    import sys

    scripts_dir = project_dir / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        import register_market_task_worker as worker  # type: ignore
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass

    # RQDB4AI worker must not inspect or update the production SQLite DB.
    worker.exists_in_db = lambda _item: False

    env = _env_from_kwargs(kwargs)
    old_env = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        worker.load_env()
        limit = int(kwargs.get("limit") or task.get("target_count") or (3 if dry_run else 500))
        hits = int(kwargs.get("hits") or (3 if dry_run else 20))
        pages = int(kwargs.get("pages") or (1 if dry_run else 3))
        max_candidates = int(
            kwargs.get("max_candidates")
            or kwargs.get("max-candidates")
            or max(limit * (3 if dry_run else 2), 20 if dry_run else 600)
        )
        delay = float(kwargs.get("delay") or (0.2 if dry_run else 1.5))
        batch_size = int(kwargs.get("batch_size") or kwargs.get("batch-size") or 20)
        min_score = int(kwargs.get("min_score") or kwargs.get("min-score") or 45)
        score_mode = str(kwargs.get("score_mode") or kwargs.get("score-mode") or "heuristic")
        ollama_timeout = int(kwargs.get("ollama_timeout") or kwargs.get("ollama-timeout") or 60)
        model = str(kwargs.get("model") or os.environ.get("OLLAMA_MODEL") or "gemma4:e4b")

        candidates = worker.collect_candidates(
            task,
            hits=hits,
            pages=pages,
            delay=delay,
            max_candidates=max_candidates,
        )
        selected = worker.score_candidates(
            candidates,
            task,
            model=model,
            batch_size=batch_size,
            limit=limit,
            timeout=ollama_timeout,
            score_mode=score_mode,
            min_score=min_score,
        )[:limit]
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    output = {
        "project": "aixec",
        "app": "market",
        "dry_run": dry_run,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "task": task,
        "counts": {
            "candidates": len(candidates),
            "selected": len(selected),
        },
        "items": selected,
    }
    output_path = project_dir / "tasks" / ("market_register_task_dry_run.json" if dry_run else "market_register_task.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"payload": output, "output_path": str(output_path)}


def market_pipeline_job(dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
    started_at = dt.datetime.now(dt.timezone.utc)
    try:
        task = _load_task(kwargs, dry_run)
    except RuntimeError as exc:
        finished_at = dt.datetime.now(dt.timezone.utc)
        return _standard_result(
            ok=False,
            status="warn",
            items=0,
            metrics={"created": 0, "updated": 0, "skipped": 0, "failed": 0},
            note="market_pipeline skipped: market_task_required",
            error=str(exc),
            **{
                "created_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "dry_run": bool(dry_run),
                "cwd": str(_project_dir()),
                "command": [
                "python3",
                "scripts/register_market_task_worker.py",
                "--candidate-json-only",
                ],
                "returncode": 0,
                "stdout_tail": "",
                "stderr_tail": str(exc),
            },
        )
    generated = _generate_market_candidates(task, dry_run, kwargs)
    submit = _submit_market_candidates(generated["payload"], kwargs, dry_run)
    finished_at = dt.datetime.now(dt.timezone.utc)
    submit_response = submit.get("response") if isinstance(submit, dict) else {}
    submit_result = submit_response.get("result") if isinstance(submit_response, dict) else {}
    registered = int(submit_result.get("registered") or submit_result.get("items") or 0) if isinstance(submit_result, dict) else 0
    created = int(submit_result.get("created") or 0) if isinstance(submit_result, dict) else 0
    updated = int(submit_result.get("updated") or 0) if isinstance(submit_result, dict) else 0
    selected = int(generated["payload"]["counts"].get("selected") or 0)
    items = selected if dry_run or not submit.get("submitted") else registered
    return _standard_result(
        ok=True,
        status="ok",
        items=items,
        metrics={
            "selected": selected,
            "candidates": int(generated["payload"]["counts"].get("candidates") or 0),
            "registered": registered,
            "created": created,
            "updated": updated,
        },
        note=f"market_pipeline selected={selected} registered={registered} created={created} updated={updated}",
        artifacts=[{"type": "file", "label": "candidate_json", "path": generated["output_path"]}],
        **{
            "created_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "dry_run": bool(dry_run),
            "cwd": str(_project_dir()),
            "command": [
                "python3",
                "scripts/register_market_task_worker.py",
                "--candidate-json-only",
            ],
            "output_path": generated["output_path"],
            "counts": generated["payload"]["counts"],
            "submit": submit,
            "stdout_tail": json.dumps(
                {
                    "output_path": generated["output_path"],
                    "counts": generated["payload"]["counts"],
                    "submitted": submit.get("submitted"),
                },
                ensure_ascii=False,
            ),
            "stderr_tail": "",
        },
    )


def growth_agent_job(dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
    started_at = dt.datetime.now(dt.timezone.utc)
    market_limit = int(kwargs.get("market_limit") or kwargs.get("market-limit") or (5 if dry_run else 20))
    skip_claude = bool(kwargs.get("skip_claude") or kwargs.get("skip-claude") or False)
    payload = {
        "dry_run": bool(dry_run),
        "skip_claude": skip_claude,
        "market_limit": market_limit,
        "source": str(kwargs.get("source") or "rqdb4ai"),
    }
    if kwargs.get("check_only"):
        payload["check_only"] = True

    response = _api_post("growth/run-agent", payload, kwargs, timeout=int(kwargs.get("submit_timeout") or 120))
    body = response.get("response") or {}
    if not body.get("ok"):
        raise RuntimeError(f"growth/run-agent failed: {body}")
    result = dict(body.get("result") or {})
    finished_at = dt.datetime.now(dt.timezone.utc)
    started = bool(result.get("started") or result.get("running") or result.get("pid"))
    status = str(result.get("status") or ("ok" if dry_run or started else "warn"))
    items = int(result.get("items") or (1 if started and not dry_run else 0))
    return _standard_result(
        ok=status in {"ok", "warn", "warning"},
        status="warn" if status in {"warn", "warning"} else status,
        items=items,
        metrics={"created": items, "market_limit": market_limit},
        note=f"growth_agent status={status} items={items} market_limit={market_limit}",
        **{
            "created_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "dry_run": bool(dry_run),
            "cwd": str(_project_dir()),
            "endpoint": _api_url("growth/run-agent", kwargs),
            "returncode": 0,
            "created": items,
            "market_limit": market_limit,
            "skip_claude": skip_claude,
            "api_result": result,
            "stdout_tail": json.dumps(result, ensure_ascii=False)[-4000:],
            "stderr_tail": "",
        },
    )


def register_market_worker_job(dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
    """Trigger the WEB/API-side register_market worker.

    RQDB4AI must not rebuild AIxEC's ranking or DB registration logic. The
    existing AIxEC WEB/API server owns that work and reports the real result.
    """
    started_at = dt.datetime.now(dt.timezone.utc)
    project_dir = _project_dir()
    payload = {
        "dry_run": bool(dry_run),
        "check_only": bool(kwargs.get("check_only")),
        "source": str(kwargs.get("source") or "rqdb4ai"),
    }
    response = _api_post("register-market/run-worker", payload, kwargs, timeout=int(kwargs.get("submit_timeout") or 120))
    body = response.get("response") or {}
    if not body.get("ok"):
        raise RuntimeError(f"register-market/run-worker failed: {body}")
    api_result = dict(body.get("result") or {})
    trigger_started = bool(api_result.get("started") or api_result.get("already_running") or api_result.get("running"))
    if not trigger_started and not dry_run:
        status = str(api_result.get("status") or "warn")
        total = int(api_result.get("items") or 0)
        finished_at = dt.datetime.now(dt.timezone.utc)
        return _standard_result(
            ok=status in {"ok", "warn", "warning"},
            status="warn" if status in {"warn", "warning"} else status,
            items=total,
            metrics={"created": total},
            note=str(api_result.get("note") or f"register_market_worker not started status={status}")[:200],
            **{
                "created_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "dry_run": bool(dry_run),
                "cwd": str(project_dir),
                "endpoint": _api_url("register-market/run-worker", kwargs),
                "trigger_started": trigger_started,
                "api_result": api_result,
            },
        )

    if dry_run:
        status = str(api_result.get("status") or "ok")
        total = int(api_result.get("items") or 0)
        worker_status = dict(api_result)
    else:
        worker_name = "aixec-register-market-worker-enqueue"
        wait_timeout = int(kwargs.get("wait_timeout") or kwargs.get("register_wait_timeout") or DEFAULT_REGISTER_TIMEOUT)
        poll_interval = int(kwargs.get("poll_interval") or kwargs.get("register_poll_interval") or 15)
        deadline = time.monotonic() + max(1, wait_timeout)
        worker_status: dict[str, Any] = {}
        while time.monotonic() < deadline:
            worker_status = _worker_status(worker_name, kwargs)
            worker_state = str(worker_status.get("status") or "").lower()
            if worker_state not in {"running", "queued", "starting"}:
                break
            time.sleep(max(1, poll_interval))
        else:
            raise TimeoutError(f"register_market_worker still running after {wait_timeout} seconds: {worker_status}")

        status = str(worker_status.get("status") or "unknown")
        total = int(worker_status.get("items") or 0)

    finished_at = dt.datetime.now(dt.timezone.utc)
    metrics = _metrics_from_worker_status(worker_status)
    if status not in {"ok", "warn", "warning"}:
        return _standard_result(
            ok=False,
            status="down",
            items=total,
            metrics=metrics,
            note=str(worker_status.get("note") or f"register_market_worker failed status={status}")[:200],
            error=worker_status.get("note") or status,
            **{
                "created_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "dry_run": bool(dry_run),
                "cwd": str(project_dir),
                "endpoint": _api_url("register-market/run-worker", kwargs),
                "trigger_started": trigger_started,
                "api_result": api_result,
                "worker_status": worker_status,
            },
        )

    return _standard_result(
        ok=status in {"ok", "warn", "warning"},
        status="warn" if status in {"warn", "warning"} else status,
        items=total,
        metrics=metrics,
        note=str(worker_status.get("note") or f"register_market_worker status={status} items={total}")[:200],
        **{
            "created_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "dry_run": bool(dry_run),
            "cwd": str(project_dir),
            "endpoint": _api_url("register-market/run-worker", kwargs),
            "created": total,
            "trigger_started": trigger_started,
            "api_result": api_result,
            "worker_status": worker_status,
        },
    )
