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
TASK_PATH = ROOT / "tasks" / "market_task.generated.json"


TOPIC_TASKS = {
    "security_cameras": {
        "label": "セキュリティ・監視カメラ",
        "group": "security_cameras",
        "target_count": 500,
        "genre_id": "",
        "keywords": [
            "防犯カメラ 屋外",
            "防犯カメラ ワイヤレス",
            "防犯カメラ PoE",
            "防犯カメラ ソーラー",
            "監視カメラ 屋外 防水",
            "ネットワークカメラ 屋外",
            "見守りカメラ",
            "ペットカメラ",
            "ベビーモニター カメラ",
            "防犯カメラセット",
            "録画機 防犯カメラ",
            "ドアホン カメラ",
            "スマートロック カメラ",
            "人感センサー カメラ",
            "AI検知 防犯カメラ",
            "暗視カメラ 屋外",
            "防犯ライト カメラ",
            "屋外カメラ wifi",
            "4K 防犯カメラ",
            "防犯カメラ 工事不要",
        ],
    },
    "ingredient_skincare": {
        "label": "成分美容・スキンケア",
        "group": "ingredient_skincare",
        "target_count": 500,
        "genre_id": "",
        "keywords": [
            "レチノール 美容液",
            "ナイアシンアミド 美容液",
            "ビタミンC 美容液",
            "セラミド 化粧水",
            "ヒアルロン酸 美容液",
            "CICA スキンケア",
            "アゼライン酸 美容液",
            "ペプチド 美容液",
            "グルタチオン 美容液",
            "敏感肌 スキンケア",
            "毛穴 美容液",
            "保湿クリーム セラミド",
            "日焼け止め 敏感肌",
            "クレンジングバーム",
            "フェイスパック 大容量",
            "導入美容液",
        ],
    },
    "kitchen_tools": {
        "label": "キッチン・調理器具",
        "group": "kitchen_tools",
        "target_count": 500,
        "genre_id": "",
        "keywords": [
            "フライパン IH",
            "鍋 セット",
            "包丁 三徳",
            "まな板 抗菌",
            "電気圧力鍋",
            "ノンフライヤー",
            "ホットプレート",
            "炊飯器 5合",
            "浄水器 カートリッジ",
            "保存容器 耐熱",
            "キッチンスケール",
            "ブレンダー",
            "コーヒーメーカー",
            "食洗機対応",
        ],
    },
    "pet_supplies": {
        "label": "ペット用品",
        "group": "pet_supplies",
        "target_count": 500,
        "genre_id": "",
        "keywords": [
            "ペットシーツ まとめ買い",
            "猫砂 まとめ買い",
            "ドッグフード 大容量",
            "キャットフード 大容量",
            "自動給餌器",
            "ペットカメラ",
            "犬 おやつ",
            "猫 おやつ",
            "ペット トイレ",
            "ペット キャリー",
            "犬 ハーネス",
            "猫 爪とぎ",
            "ペット 消臭",
            "ペット ブラシ",
        ],
    },
    "outdoor_camping": {
        "label": "アウトドア・キャンプ用品",
        "group": "outdoor_camping",
        "target_count": 500,
        "genre_id": "",
        "keywords": [
            "ポータブル電源",
            "ソーラーパネル ポータブル電源",
            "キャンプ テント",
            "キャンプ チェア",
            "アウトドア テーブル",
            "寝袋",
            "クーラーボックス",
            "LED ランタン",
            "焚き火台",
            "キャンプ マット",
            "タープ",
            "バーベキューコンロ",
            "アウトドア ワゴン",
            "防災 ポータブル電源",
        ],
    },
    "amazon_daily_consumables": {
        "label": "Amazon日用品・飲料・消耗品",
        "group": "amazon_daily_consumables",
        "target_count": 500,
        "genre_id": "",
        "affiliate_priority": "amazon",
        "keywords": [
            "洗濯洗剤 詰め替え 大容量",
            "柔軟剤 詰め替え 大容量",
            "食器用洗剤 詰め替え 大容量",
            "キッチンペーパー まとめ買い",
            "トイレットペーパー まとめ買い",
            "ティッシュペーパー まとめ買い",
            "除菌シート まとめ買い",
            "マスク まとめ買い",
            "歯ブラシ まとめ買い",
            "歯磨き粉 まとめ買い",
            "浄水器 カートリッジ 交換用",
            "プロテイン 1kg",
            "日焼け止め SPF50",
            "制汗剤 まとめ買い",
            "ゴミ袋 45L まとめ買い",
        ],
    },
}


def build_market_task(action, limit):
    topic = str(action.get("topic") or "").strip()
    task = dict(TOPIC_TASKS.get(topic) or {})
    if not task:
        group = topic.lower().replace("-", "_").replace(" ", "_") or "growth_selected_products"
        task = {
            "label": topic or "Growth選定商品",
            "group": group,
            "target_count": limit,
            "genre_id": "",
            "keywords": [topic] if topic else ["人気商品", "売れ筋", "ランキング"],
        }
    task["target_count"] = min(int(action.get("limit") or task.get("target_count") or limit), limit)
    task.setdefault("exclude_keywords", ["ふるさと納税", "中古", "ジャンク", "訳あり", "サンプル", "お試し"])
    task.setdefault(
        "description_policy",
        "検索需要とアフィリエイト送客を重視し、比較・選び方・用途が伝わる説明文にする。",
    )
    task["reason"] = action.get("reason") or task.get("reason") or "growth agent selected this market topic"
    task.setdefault("next_actions", ["登録結果の新規率を確認し、低ければ次回は別ジャンルへ切り替える"])
    return task


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
            task = build_market_task(action, limit)
            TASK_PATH.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            lines.append("generated task: %s (%s)" % (task.get("group"), task.get("label")))
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
