#!/usr/bin/env python3
"""Ask Claude Code OAuth to choose the next AIxEC market category task."""
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
SKILL = ROOT / "skills" / "aixec-product-registration" / "SKILL.md"
CONTEXT = ROOT / "tasks" / "marketing_context.md"
SCHEMA = ROOT / "tasks" / "task.schema.json"
OUT = ROOT / "tasks" / "market_task.generated.json"
RAW_OUT = ROOT / "tasks" / "market_task.claude_raw.json"


def main():
    prompt = f"""以下を読んで、AIxECで次に登録する楽天市場商品ジャンルを1つ選んでください。

必ずJSONだけを出力してください。Markdownや説明文は不要です。

目的:
- 1回の実行で500件前後の商品登録を狙う。
- 既存ジャンルの周辺に寄りすぎず、検索流入が増える人気ジャンルを選ぶ。
- AIxECらしさは大事だが、狭い専門性より「検索需要」「商品数」「記事化しやすさ」「アフィリエイト送客」を優先する。

選定ルール:
- target_countは原則500。
- keywordsは25〜40個。狭いキーワードだけでなく、人気商品名、用途、悩み、比較軸、型番系を混ぜる。
- 既存ジャンルと近い場合でも、検索需要が強く、切り口が別なら選んでよい。
- 書籍だけに逃げない。PC機器、家電、美容健康、防災、季節商品、仕事道具、生活改善商品も候補に入れる。
- reasonには、検索需要・500件集められる根拠・AIxECで解説記事化する切り口を必ず入れる。

マーケティング評価配点:
- 検索需要・トレンド性: 45点
- 商品数と500件登録しやすさ: 20点
- アフィリエイト送客しやすさ: 15点
- AIxECの記事・SNS・動画展開しやすさ: 15点
- 既存ジャンルとの差別化: 5点

SKILL:
{SKILL.read_text(encoding='utf-8')}

MARKETING_CONTEXT:
{CONTEXT.read_text(encoding='utf-8')}
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
    result = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=600)
    if result.returncode != 0:
        RAW_OUT.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
        raise SystemExit(result.stderr or result.stdout)
    RAW_OUT.write_text(result.stdout, encoding="utf-8")
    payload = json.loads(result.stdout)
    if isinstance(payload, dict) and isinstance(payload.get("structured_output"), dict):
        task = payload["structured_output"]
    else:
        text = payload.get("result") if isinstance(payload, dict) else payload
        task = json.loads(text) if isinstance(text, str) else text
    OUT.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
