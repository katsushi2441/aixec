# AIxEC Product Registration Skill

AIxECで楽天市場商品を追加するための共通手順。

## 役割

- Claude Code / OpenClaw: マーケティング判断、ジャンル選定、登録タスク作成。
- worker.py: task.jsonに従って楽天API取得、未登録判定、DB登録、ログ出力。
- Ollama: 商品説明、分類、除外判定の補助。

## タスク作成ルール

Claude Codeは `tasks/marketing_context.md` を読み、次に攻める楽天市場ジャンルを1つ選ぶ。

判断基準:

- 検索需要が強く、商品ページや解説記事へ展開しやすいことを最優先する。
- 1回で500件程度に広げられるキーワード群であること。
- AIxECらしさがあること。AI、PC、業務効率化、専門知識、経営、医療、介護、学習、開発者向けを優先するが、アクセス拡大のため美容健康、生活家電、防災、季節商品、仕事道具も対象にする。
- アフィリエイト送客に向くこと。
- 既存ジャンルと重複しすぎないこと。ただし検索需要が大きく、切り口が違うなら隣接ジャンルも選んでよい。
- 書籍だけに逃げない。商品母数が大きい楽天市場ジャンルを積極的に選ぶ。

避けるもの:

- ふるさと納税
- 権利面や真贋リスクが高い高額中古品
- 一過性すぎる商品
- AIxECの文脈と弱い日用品だけのジャンル

## 出力

Claude CodeはJSONだけを出力する。

```json
{
  "label": "表示名",
  "group": "snake_case_group",
  "target_count": 500,
  "genre_id": "",
  "keywords": ["楽天検索キーワード25〜40個"],
  "exclude_keywords": ["除外語"],
  "description_policy": "商品説明生成方針",
  "reason": "選定理由",
  "next_actions": ["worker.pyで実行すること"]
}
```

## 登録ルール

- 楽天市場商品画像はローカル保存しない。楽天APIの画像URLを使う。
- 既存判定は `jan` または `internal_sku = rakuten_market:{item_code}` を使う。
- `product_attributes` に `rakuten_genre_label` / `rakuten_genre_group` / `rakuten_genre_id` を保存する。
- 登録後は件数を確認し、必要なら `webapps/index.php` と `webapps/market_ranking.php` に導線を追加する。
- AIxSNS告知は登録完了後に行う。

## worker.py実行ルール

`scripts/register_market_task_worker.py` は、Claude Code/OpenClawが作った `tasks/market_task.generated.json` を読む。

処理:

1. `keywords` を順に楽天市場APIへ投げて候補商品を集める。
2. `exclude_keywords` と共通除外語で候補を除外する。
3. DBの既存商品を除外する。
4. Ollama `gemma4:e4b` に候補を10件程度ずつ渡し、AIxECに合う商品か判定させる。
5. scoreが高い順に `target_count` まで登録する。
6. 登録結果を `tasks/market_task_result.md` に残す。

Ollamaの役割:

- 商品名、キャッチコピー、説明、価格、レビューから、AIxECの文脈に合うか評価する。
- 明らかなノイズ商品、無関係商品、ふるさと納税、中古リスクが高い商品を落とす。
- description生成方針に沿った短い選定理由を返す。

Ollamaに任せないこと:

- DB登録
- 価格やJANなどの事実値の改変
- 楽天URL生成
- 画像保存
- FTPアップロード

実行例:

```bash
cd /home/kojima/exdirect/aixec
python3 scripts/register_market_task_worker.py --task tasks/market_task.generated.json --dry-run --limit 10
python3 scripts/register_market_task_worker.py --task tasks/market_task.generated.json --limit 500 --pages 10 --batch-size 10
```
