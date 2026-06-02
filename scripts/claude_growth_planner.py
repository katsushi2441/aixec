#!/usr/bin/env python3
"""Ask Claude Code OAuth to create a growth plan for AIxEC."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_BIN = os.environ.get(
    "CLAUDE_BIN",
    "/home/kojima/.vscode-server/extensions/anthropic.claude-code-2.1.145-linux-x64/resources/native-binary/claude",
)
OBS = ROOT / "tasks" / "growth_observation.md"
SCHEMA = ROOT / "tasks" / "growth_plan.schema.json"
OUT = ROOT / "tasks" / "growth_plan.generated.json"
RAW = ROOT / "tasks" / "growth_plan.claude_raw.json"


def main():
    prompt = f"""AIxEC Growth Agentとして、次の1サイクルで何をするべきか判断してください。

目的:
- 商品数を増やすだけでなく、検索流入、AIxSNS発信、アフィリエイト送客、AIxECらしい専門性を伸ばす。
- botノイズではなく、有効クリック・投稿反応・登録済みジャンルを見て方針を変える。
- 実行可能なactionsをJSONで返す。

制約:
- APIキー課金ではなくClaude Code OAuthを使う。
- 商品登録は worker.py が行う。
- 大量処理の一次判断は Ollama gemma4:e4b が行う。
- 画像保存はしない。
- 無理に商品登録しなくてよい。SNS投稿やcontent_ideaでもよい。

OBSERVATION:
{OBS.read_text(encoding='utf-8')}
"""
    cmd = [
        CLAUDE_BIN,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        SCHEMA.read_text(encoding="utf-8"),
        prompt,
    ]
    result = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=900)
    if result.returncode != 0:
        RAW.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
        raise SystemExit(result.stderr or result.stdout)
    RAW.write_text(result.stdout, encoding="utf-8")
    payload = json.loads(result.stdout)
    plan = payload.get("structured_output")
    if not isinstance(plan, dict):
        text = payload.get("result", "")
        plan = json.loads(text)
    OUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()

