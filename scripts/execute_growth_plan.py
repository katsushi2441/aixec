#!/usr/bin/env python3
"""Execute AIxEC growth plan actions."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "tasks" / "growth_plan.generated.json"
MEMORY = ROOT / "tasks" / "growth_memory.md"
RESULT = ROOT / "tasks" / "growth_execution_result.md"
API_BASE = "http://127.0.0.1:8081"


def post_to_sns(content, author="register"):
    payload = json.dumps({"author": author, "content": content}, ensure_ascii=False).encode("utf-8")
    req = Request(API_BASE + "/posts", data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=15) as res:
        return json.loads(res.read().decode("utf-8")).get("item", {}).get("id")


def run(cmd):
    result = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
    return {
        "cmd": " ".join(cmd),
        "returncode": result.returncode,
        "stdout": result.stdout[-3000:],
        "stderr": result.stderr[-3000:],
    }


def append_memory(plan, execution_lines):
    MEMORY.parent.mkdir(parents=True, exist_ok=True)
    with MEMORY.open("a", encoding="utf-8") as fh:
        fh.write("\n## Cycle %s\n\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        fh.write("- summary: %s\n" % plan.get("summary", ""))
        fh.write("- strategy: %s\n" % plan.get("strategy", ""))
        fh.write("- memory_note: %s\n\n" % plan.get("memory_note", ""))
        for line in execution_lines:
            fh.write("- %s\n" % line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default=str(PLAN))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--market-limit", type=int, default=20)
    parser.add_argument(
        "--allow-market-registration",
        action="store_true",
        help="allow growth actions to run autonomous_market_pipeline.py",
    )
    args = parser.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = ROOT / plan_path
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    lines = [
        "# AIxEC Growth Execution Result",
        "",
        f"- dry_run: {args.dry_run}",
        f"- summary: {plan.get('summary')}",
        f"- strategy: {plan.get('strategy')}",
        "",
    ]
    memory_lines = []
    market_registration_done = False
    for action in sorted(plan.get("actions") or [], key=lambda a: int(a.get("priority") or 9)):
        atype = action.get("type")
        lines.append("## Action: %s" % atype)
        if atype == "market_registration":
            if not args.allow_market_registration:
                lines.append("skipped: market_registration is managed by the dedicated market pipeline job")
                memory_lines.append("market_registration skipped separate pipeline")
                lines.append("")
                continue
            if market_registration_done:
                lines.append("skipped: market_registration already executed in this cycle")
                memory_lines.append("market_registration skipped duplicate")
                lines.append("")
                continue
            market_registration_done = True
            limit = min(int(action.get("limit") or args.market_limit), args.market_limit)
            cmd = [
                sys.executable,
                "scripts/autonomous_market_pipeline.py",
                "--skip-claude",
                "--limit",
                str(limit),
                "--hits",
                "10",
                "--pages",
                "1",
                "--max-candidates",
                str(max(limit * 3, 30)),
                "--score-mode",
                "heuristic",
            ]
            if args.dry_run:
                cmd.append("--dry-run")
            res = run(cmd)
            lines.append("```")
            lines.append(json.dumps(res, ensure_ascii=False, indent=2))
            lines.append("```")
            memory_lines.append("market_registration returncode=%s limit=%s" % (res["returncode"], limit))
        elif atype == "sns_post":
            msg = action.get("message") or action.get("reason") or plan.get("summary") or "AIxEC Growth Agent update"
            if args.dry_run:
                lines.append("dry-run SNS: " + msg)
                memory_lines.append("sns_post dry-run")
            else:
                post_id = post_to_sns(msg)
                lines.append("posted AIxSNS id=%s" % post_id)
                memory_lines.append("sns_post id=%s" % post_id)
        elif atype == "content_idea":
            topic = action.get("topic") or action.get("reason") or "AIxEC content idea"
            idea_path = ROOT / "tasks" / ("content_idea_%s.md" % time.strftime("%Y%m%d%H%M%S"))
            idea_path.write_text("# %s\n\n%s\n" % (topic, action.get("reason", "")), encoding="utf-8")
            lines.append("created " + str(idea_path))
            memory_lines.append("content_idea " + topic)
        else:
            lines.append("observe_only: " + (action.get("reason") or ""))
            memory_lines.append("observe_only")
        lines.append("")
    RESULT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    append_memory(plan, memory_lines)
    print(RESULT)


if __name__ == "__main__":
    main()
