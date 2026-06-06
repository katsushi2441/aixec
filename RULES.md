# AIxEC RULES

AIxECでClaude/Codexが作業する時の共通ルール。細かい作業メモを増やさず、このファイルに集約する。

## 基本

- WEB公開ファイルは `webapps/` が本体。
- WEBサーバの公開先は `/web/aixec_exbridge_jp/`。
- FTP接続情報はMarkdownに書かず、`/home/kojima/exdirect/aixec/.env` を使う。
- `webapps/` を編集したら、必ずFTPアップロードまで行う。
- CodexからGitHubへpushする時は、このファイルの「Codex git push手順」を使う。
- 既存商品の説明文、画像、URLなどを上書きする処理は、実行前にユーザーへ確認する。
- API、FTP、AIxSNS投稿の接続先は、必ずルートの `SERVERS.md` を確認する。

## Codex git push手順

このサーバのCodexからGitHubへpushする時は、毎回まずSSH agentを確認する。
失敗してからやり直すのではなく、以下の成功手順を使う。

### 使えるSSH agentを探す

```bash
for s in /tmp/ssh-*/agent.*; do
  echo "-- $s"
  SSH_AUTH_SOCK="$s" ssh-add -L 2>&1 | head -2
  SSH_AUTH_SOCK="$s" ssh -o BatchMode=yes -T git@github.com 2>&1 | head -3
done
```

成功例:

```text
Hi katsushi2441! You've successfully authenticated, but GitHub does not provide shell access.
```

この表示が出た `SSH_AUTH_SOCK` を使う。

2026-06-07時点で成功した例:

```bash
SSH_AUTH_SOCK=/tmp/ssh-XXXXXX1CDlcM/agent.3865478 git push origin main
```

`Permission denied (publickey)` が出たら、`SSH_AUTH_SOCK` 未指定か、使えないagentを使っている。
`ssh-add -L` が `The agent has no identities.` なら、そのagentは使わない。

pullだけなら、SSH認証なしでも公開HTTPSで取得できる。

```bash
git fetch https://github.com/katsushi2441/aixec.git main
git rebase FETCH_HEAD
```

## 書籍データ追加

楽天ブックスからAIxECへ書籍を登録する時は、`scripts/register_ranking_books.py` を使う。

### 仕組み

- 登録対象ジャンルは `scripts/register_ranking_books.py` の `TABS` に定義する。
- `label` は画面表示や `book_genres.json` に残る表示名。
- `group` はAIxTubeやリールで関連書籍を絞り込む内部分類名。
- `genre_id` が分かる場合は楽天ブックスジャンルIDを入れる。
- ジャンルIDが曖昧な場合は空にして、`keyword` にタイトル検索語を入れる。
- 画像は `webapps/images/products/books/` にローカル保存し、FTPでWEBサーバへアップロードする。
- 登録後、`enrich_books_metadata.py` でopenBD/Google Books由来の基本情報・解説を補完する。
- 登録後、`webapps/data/book_genres.json` をWEBサーバへFTPアップロードする。

## 楽天市場の商品画像

楽天市場APIから取得した商品画像は、原則として楽天APIが返す画像URLをそのまま表示に使う。

- 楽天アフィリエイトの商品紹介・送客用途では、楽天API由来の画像URL表示を優先する。
- 新規の楽天市場商品取り込みでは、画像ファイルをローカル保存する実装を増やさない。
- DBには楽天APIの `image_url` を保存し、画面側はそのURLを表示する。
- 画像の加工、再配布目的の保存、大量コピーは避ける。
- 既存のローカル保存済み画像を変更・削除する場合は、実行前にユーザーへ確認する。

例外:

- 書籍画像やメーカー公式画像など、すでにローカル保存前提で運用している既存処理は、その処理のルールに従う。
- ただし、新しく楽天市場APIから商品を取り込む場合は、Claude/Codexともに「楽天API画像URLを表示」を標準方針にする。

## 楽天市場商品データ追加

書籍以外の楽天市場商品をAIxECへ登録する時は、`scripts/import_rakuten_market_products.py` を使う。
常駐巡回する場合は、書籍の `register_worker.py` と同じ考え方で `scripts/register_market_worker.py` を使う。

### 仕組み

- 登録対象ジャンルは `scripts/import_rakuten_market_products.py` の `CATEGORIES` に定義する。
- `label` は画面表示名、`group` は `market_ranking.php` のタブや商品属性で使う内部分類名。
- 登録時は `product_attributes` に `rakuten_genre_label` / `rakuten_genre_group` / `rakuten_genre_id` を保存する。
- ランキングページ `webapps/market_ranking.php` は `rakuten_genre_group` で商品を絞り込む。
- 既存判定は `jan` または `internal_sku = rakuten_market:{item_code}` で行う。
- 楽天市場商品画像はローカル保存ではなく、楽天APIの画像URLを `product_image` として使う。
- `ふるさと納税` を含む商品名は登録対象外にする。

### 手動実行

```bash
cd /home/kojima/exdirect/aixec
RAKUTEN_MARKET_IMPORT_DELAY=6 python3 scripts/import_rakuten_market_products.py \
  --category trading_cards \
  --hits 10
```

### 常駐ワーカー

```bash
cd /home/kojima/exdirect/aixec
REGISTER_MARKET_WORKER_INTERVAL=21600 \
REGISTER_MARKET_WORKER_HITS=10 \
REGISTER_MARKET_WORKER_DELAY=6 \
python3 scripts/register_market_worker.py
```

常駐ワーカーは新規登録があった場合、AIxSNSへ `register` 名義で投稿する。

### 実行前確認

```bash
curl -sS http://localhost:8081/health
pgrep -af "scripts/api_server.py|register_worker.py|register_market_worker.py"
```

AIxEC APIは `http://localhost:8081` で起動している必要がある。

### 指定ジャンルだけ実行

```bash
cd /home/kojima/exdirect/aixec
RAKUTEN_BOOKS_TAB_DELAY=15 python3 scripts/register_ranking_books.py \
  --groups side_business,sole_proprietor_tax,investment_nisa,stock_investment
```

楽天API制限を避けるため、`RAKUTEN_BOOKS_TAB_DELAY` は10秒以上、エラーが出る場合は15秒以上にする。

### 全ジャンル実行

```bash
cd /home/kojima/exdirect/aixec
RAKUTEN_BOOKS_TAB_DELAY=15 python3 scripts/register_ranking_books.py
```

## 書籍ジャンル追加時に必ず反映する場所

書籍ジャンルを追加した時は、データ登録だけで終わらせない。

- `scripts/register_ranking_books.py` の `TABS`
- `webapps/data/book_genres.json`
- `webapps/index.php` の「ジャンルから選ぶ」
- `webapps/reels.php` のタブ
- 必要に応じて `webapps/books_ranking.php`
- AIxSNS告知投稿

## 楽天市場商品ジャンル追加時に必ず反映する場所

楽天市場商品ジャンルを追加した時は、商品登録だけで終わらせない。

- `scripts/import_rakuten_market_products.py` の `CATEGORIES`
- `webapps/market_ranking.php` の `$tabs`
- `webapps/market_ranking.php` の `description` 文言
- `webapps/index.php` の「ジャンルから探す」
- `scripts/register_market_worker.py` の `CATEGORY_URLS`
- `webapps/index.php` と `webapps/market_ranking.php` をFTPアップロード
- 登録件数をDBで確認する
- 必要に応じてAIxSNS告知投稿

## Claude Code OAuth / OpenClawによる商品ジャンル選定

AIxECの商品登録を自動化する時は、いきなりworkerで登録せず、先にマーケティング文脈から `task.json` を作る。

構成:

- `skills/aixec-product-registration/SKILL.md`: 商品登録スキル。判断基準、禁止事項、出力形式。
- `scripts/build_marketing_context.py`: DBとaccess.logから `tasks/marketing_context.md` を生成する。
- `scripts/claude_select_market_task.py`: Claude Code OAuthの非対話実行で `tasks/market_task.generated.json` を作る。
- OpenClaw/Hermesから呼ぶ場合も、この2本を順に実行する。

実行:

```bash
cd /home/kojima/exdirect/aixec
python3 scripts/build_marketing_context.py
python3 scripts/claude_select_market_task.py
```

注意:

- Claude Codeは `/home/kojima/.vscode-server/extensions/anthropic.claude-code-2.1.145-linux-x64/resources/native-binary/claude` を使う。
- OAuthセッションを使うため、実行環境から `/home/kojima/.claude` が読める必要がある。
- Codexサンドボックス内のネットワーク制限では失敗することがある。その場合は外側のOpenClaw/Hermes/systemdから実行する。
- 2026-05-23時点の試験では、Claude Code OAuthで `structured_output` として `market_task.generated.json` を生成できた。
- 生成されたtaskは登録前に件数、重複、既存ジャンルとの競合を確認する。

## Ollama gemma4:e4bによる商品選定・登録worker

Claude Code/OpenClawが作った `tasks/market_task.generated.json` を実行する時は、`scripts/register_market_task_worker.py` を使う。

処理:

- 楽天市場APIから候補商品を取得する
- 既存商品と除外語を先に落とす
- Ollama `gemma4:e4b` でAIxECに合う商品を選定する
- score 60以上の商品だけ登録対象にする
- 登録処理は既存の `scripts/import_rakuten_market_products.py` の `upsert_product()` を使う
- 楽天市場商品画像は保存しない。楽天API画像URLを使う
- 結果は `tasks/market_task_result.md` に残す

実行:

```bash
cd /home/kojima/exdirect/aixec
python3 scripts/register_market_task_worker.py --task tasks/market_task.generated.json --dry-run --limit 10
python3 scripts/register_market_task_worker.py --task tasks/market_task.generated.json --limit 500
```

環境:

- Ollama接続先は `.env` の `OLLAMA_ENDPOINT` または `OLLAMA_BASE_URL` を使う
- 標準モデルは `gemma4:e4b`
- Ollamaが失敗した場合は簡易ヒューリスティックで暫定評価するが、本登録前はdry-run結果を確認する

## Hermes / OpenClaw 完全自動パイプライン

Hermesから定期実行し、OpenClawの司令塔タスクとして動かす場合は、`scripts/autonomous_market_pipeline.py` を使う。

処理:

1. `scripts/build_marketing_context.py` でマーケティング文脈を作る。
2. `scripts/claude_select_market_task.py` でClaude Code OAuthを呼び、ジャンル・キーワード・商品登録taskを作る。
3. `scripts/register_market_task_worker.py` で楽天API候補取得、Ollama gemma4:e4b選定、AIxEC登録を行う。
4. 登録結果を `tasks/market_task_result.json` / `.md` に残す。
5. 新規登録があればAIxSNSへ `register` 名義で告知する。

実行:

```bash
cd /home/kojima/exdirect/aixec
python3 scripts/autonomous_market_pipeline.py
```

Hermesから呼ぶ入口:

```bash
/home/kojima/exdirect/aixec/scripts/hermes_autonomous_market.sh
```

OpenClawに渡す司令塔プロンプト:

- `openclaw_aixec_market_prompt.md`

少量テスト:

```bash
cd /home/kojima/exdirect/aixec
python3 scripts/autonomous_market_pipeline.py --skip-claude --dry-run --limit 5 --hits 3 --pages 1 --max-candidates 12
```

確認コマンド:

```bash
cd /home/kojima/exdirect/aixec
python3 scripts/import_rakuten_market_products.py --category ai_pc_gaming --hits 30 --delay 3
php -l webapps/index.php
php -l webapps/market_ranking.php
python3 - <<'PY'
import sqlite3
conn=sqlite3.connect('/home/kojima/exdirect/aixec/storage/aixec.sqlite')
group='ai_pc_gaming'
print(conn.execute("""
select count(distinct product_id) from product_attributes
where attr_name='rakuten_genre_group' and attr_value=?
""", (group,)).fetchone()[0])
conn.close()
PY
```

FTP公開先:

- `webapps/index.php` -> `/web/aixec_exbridge_jp/index.php`
- `webapps/market_ranking.php` -> `/web/aixec_exbridge_jp/market_ranking.php`

公開確認:

```bash
curl -L -s 'https://aixec.exbridge.jp/' | rg -n 'AI PC・ゲーミング|ゲーミングPC|RTX|ミニPC'
curl -L -s 'https://aixec.exbridge.jp/market_ranking.php?tab=ai_pc_gaming' | rg -n 'AI PC・ゲーミング|商品がありません'
```

## 2026-05-21 楽天市場商品ジャンル追加実績

追加ジャンル:

| 表示名 | group | 主な取得キーワード | 登録件数 |
| --- | --- | --- | ---: |
| AI PC・ゲーミング | `ai_pc_gaming` | RTX ゲーミングPC、ゲーミングPC RTX、AI PC、ミニPC 32GB、GPU グラフィックボード、4K モニター、ウルトラワイドモニター、メカニカルキーボード、USB マイク 配信、Webカメラ 4K、外付けSSD 2TB、NVMe SSD 2TB、キャプチャーボード | 363件 |

実行結果:

- 初回 `--hits 3 --delay 2`: 新規35件
- 追加 `--hits 30 --delay 3`: 新規328件、更新35件、スキップ27件
- 合計363件

反映済み:

- `scripts/import_rakuten_market_products.py` に `ai_pc_gaming` を追加
- `webapps/market_ranking.php` に `AI PC・ゲーミング` タブを追加
- `scripts/register_market_worker.py` の `CATEGORY_URLS` に `AI PC・ゲーミング` を追加
- `webapps/index.php` の「ジャンルから探す」に次を追加
  - AI PC・ゲーミング
  - ゲーミングPC
  - RTX
  - ミニPC
  - 4Kモニター
  - メカニカルキーボード
  - USBマイク
  - Webカメラ
  - 外付けSSD
  - キャプチャーボード

注意:

- `GPU グラフィックボード` はグラボ本体だけでなくGPUサポート・グラボステーも混ざりやすい。
- 次回精度を上げる場合は、除外語に `サポート`、`ステー`、`ホルダー`、`ブラケット` を追加することを検討する。

## AI PC・ゲーミング商品のAI説明文生成

`AI PC・ゲーミング` の商品説明を追加・再生成する時は、対象を必ず `rakuten_genre_group = ai_pc_gaming` に絞る。

実行スクリプト:

```bash
cd /home/kojima/exdirect/aixec
python3 scripts/generate_ai_pc_descriptions.py --template-only --workers 4
```

この処理は次を行う。

- `products.description` の先頭に `AIによる商品説明` ブロックを追加する
- 既存の商品説明、楽天リンク、画像、元説明は削除せず後ろに残す
- 再実行時は `<!-- aixec-ai-description:start -->` から `<!-- aixec-ai-description:end -->` の既存AI説明ブロックだけ差し替える
- `product_attributes` に `market_description_ai` と `market_description_ai_generated_at` を保存する

確認コマンド:

```bash
sqlite3 /home/kojima/exdirect/aixec/storage/aixec.sqlite "
select count(*) from products p
join product_attributes g on g.product_id=p.id
 and g.attr_name='rakuten_genre_group'
 and g.attr_value='ai_pc_gaming'
where p.description like '%aixec-ai-description:start%';
"

curl -s 'https://aixec.exbridge.jp/product.php?id=61831' | rg -n 'AIによる商品説明|詳細説明をAI生成する'
```

注意:

- Ollamaで自由生成すると、未確認スペックを盛ることがある。
- 商品説明の一括生成では、事実誤認を避けるため `--template-only` を標準にする。
- 商品ページにAI説明文が入っている場合、`webapps/index.php` 側で `詳細説明をAI生成する` ボタンは表示しない。
- `webapps/index.php` を編集したらFTPアップロードする。
- AIxECは現状 `/home/kojima/exdirect/aixec` 単体ではGitリポジトリではないため、DB更新とFTP反映を確認する。

2026-05-21実績:

- `AI PC・ゲーミング` 363件にAI説明文を生成
- 確認件数: 363件
- 表示確認: `https://aixec.exbridge.jp/product.php?id=61831`

## go.php アフィリエイトクリックのbot対策

`go.php` は楽天/Amazonの外部アフィリエイトURLへ302リダイレクトするため、botに踏まれると楽天・Amazon側のクリック計測とAIxECのログが大きくずれる。

方針:

- `go.php` 側でbot判定する
- botの場合は楽天/Amazonへリダイレクトしない
- botの場合は `204 No Content` を返す
- `X-Robots-Tag: noindex, nofollow, noarchive` を返す
- 人間の通常ブラウザだけ302リダイレクトする

確認コマンド:

```bash
curl -sI -A 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)' \
  'https://aixec.exbridge.jp/go.php?to=rakuten&kw=test&pid=61831' \
  | rg -i 'HTTP/|location|x-robots|cache-control'

curl -sI -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139.0.0.0 Safari/537.36' \
  'https://aixec.exbridge.jp/go.php?to=rakuten&kw=test&pid=61831' \
  | rg -i 'HTTP/|location|x-robots|cache-control'
```

期待値:

- Googlebot UA: `HTTP/2 204`、`x-robots-tag: noindex, nofollow, noarchive`
- 通常ブラウザUA: `HTTP/2 302`、`location: https://hb.afl.rakuten.co.jp/...`

2026-05-21実績:

- 2026-05-20の楽天クリックrawログ `14,533` の大半がGooglebot系だった
- bot除外後の楽天クリックは `23` まで減少
- 実際の楽天アフィリエイトクリック数 `6` との差が出たため、`webapps/go.php` にbot遮断を追加
- `webapps/go.php` をFTPアップロード済み

## go.php 呼び出し元ページの計測

`go.php` のクリックは、どのページから呼ばれたかを `simpletrack.php` で見えるようにする。

実装方針:

- `go.php` のログ用URLに `from` を追加する
- リンク生成側は可能な限り `from` を明示する
- `from` が無い古いリンクは `HTTP_REFERER` から補完する
- `simpletrack.php?dashboard=1` に `go.php 呼び出し元ページ` 表を表示する
- `go.php 商品別クリック` 表にも `呼び出し元` 列を表示する

主な `from` の形式:

- 商品ページ: `product:{product_id}`
- AIxSNS記事: `sns:{post_id}`
- AIxTube動画: `aixtube:{product_id}`
- 楽天市場ランキング: `market_ranking:{tab}`
- 書籍ランキング: `books_ranking:{tab}`
- リール: `reels`

確認例:

```bash
curl -s 'https://aixec.exbridge.jp/sns.php?id=588' | rg -n 'from=sns'
curl -s 'https://aixec.exbridge.jp/product.php?id=61831' | rg -n 'from=product'
curl -s 'https://aixec.exbridge.jp/simpletrack.php?dashboard=1&range=1d' | rg -n 'go.php 呼び出し元ページ|sns:588|product:61831'
```

2026-05-21実績:

- `webapps/go.php`
- `webapps/simpletrack.php`
- `webapps/index.php`
- `webapps/market_ranking.php`
- `webapps/reels.php`
- `webapps/books_ranking.php`
- `webapps/sns.php`
- `webapps/aixtube.php`

を更新し、FTPアップロード済み。

## 2026-05-16 書籍ジャンル追加実績

追加ジャンル:

| 表示名 | group | 取得キーワード | 新規登録 |
| --- | --- | --- | ---: |
| 副業 | `side_business` | 副業 | 19件 |
| 個人事業・確定申告 | `sole_proprietor_tax` | 確定申告 | 20件 |
| 投資・新NISA | `investment_nisa` | 新NISA | 20件 |
| 株式投資 | `stock_investment` | 株式投資 | 20件 |

合計79件を登録。登録ID範囲は `61265` から `61343`。

反映済み:

- `webapps/data/book_genres.json` をFTPアップロード
- `webapps/index.php` にジャンルリンク追加
- `webapps/reels.php` にタブ追加
- AIxSNSへ `codex` 名義で投稿

AIxSNS投稿:

```text
https://aixec.exbridge.jp/sns.php?id=284
```

## AIxSNS告知

AIxSNS投稿は公開プロキシを使う。詳しい接続先はルートの `SERVERS.md` を確認する。

```bash
curl -sS -X POST "https://aixec.exbridge.jp/api.php?path=posts" \
  -H "Content-Type: application/json" \
  -d '{"author":"codex","content":"投稿本文"}'
```

Codexが投稿する場合、`author` は `codex`。

## 2026-05-21 AI PC・ゲーミング追加拡張

目的:

- AIxECで、ゲーミングPC、GPU、GPUサーバー、AIワークステーション、DDR5メモリなど「AIに活かせるコンピュータ機器」を増やす。

実施内容:

- `scripts/import_rakuten_market_products.py` の `AI PC・ゲーミング` キーワードを拡張。
- 取り込み後、明確な混入データを削除。
- 過去登録分のGPUサポート金具など、AI機器として邪魔な商品もカテゴリ全体から削除。
- `scripts/generate_ai_pc_descriptions.py --template-only --workers 4` で商品説明を再生成。
- `webapps/index.php` の「ジャンルから探す」に GPU / GPUサーバー / AIワークステーション / RTX 5090 / RTX 5080 / RTX 5070 / DDR5メモリを追加。
- `webapps/index.php` はFTPアップロード済み。

重要な注意:

- `CUDA PC` は `Barracuda` HDDを拾うので使わない。
- `AI サーバー` はコーヒーサーバー、ケーキサーバーを拾うので使わない。
- 除外語に単独の `本` を入れない。`本体のみ` など正常なPC商品まで除外してしまう。
- 書籍除外は `単行本` / `電子書籍` など具体語にする。
- 追加後は必ず混入確認をする。

確認コマンド:

```bash
cd /home/kojima/exdirect/aixec
sqlite3 storage/aixec.sqlite "select count(distinct p.id) from products p join product_attributes a on a.product_id=p.id where a.attr_name='rakuten_genre_group' and a.attr_value='ai_pc_gaming';"
curl -L -s 'https://aixec.exbridge.jp/' | rg -n 'GPUサーバー|AIワークステーション|RTX 5090|DDR5メモリ'
curl -L -s 'https://aixec.exbridge.jp/index.php?q=RTX5090' | rg -n '検索結果|RTX5090|商品が見つかりません'
```

今回の結果:

- `AI PC・ゲーミング` は 622件。
- AI説明文は 622件すべて生成済み。

## simpletrack ダッシュボードの unknown 除外

2026-05-22対応。

- `go.php` の `from` が空、かつ `ref` も空のアクセスは、ダッシュボード集計から除外する。
- 理由: 直近24時間の `from=(unknown)` の大半が Googlebot / GoogleOther などのクローラーだったため。
- ログ自体は残す。表示集計だけから外す。
- 対象ファイル: `webapps/simpletrack.php`
- 編集後は `php -l webapps/simpletrack.php` を実行し、FTPアップロードする。

確認:

```bash
curl -L -s 'https://aixec.exbridge.jp/simpletrack.php?dashboard=1&range=1d' | rg -c '\(unknown\)'
```

2026-05-22時点で `0` 件確認済み。

## 2026-05-22 型番商品・工具機器カテゴリ追加

目的:

- 型番検索で流入を取りやすい商品をAIxECに増やす。
- 工具、測定器、ネットワーク機器、NAS/UPS、プリンター、PC周辺機器など、商品名に型番が入るものを優先する。

追加した場所:

- `scripts/import_rakuten_market_products.py`
  - `model_number_products` / `型番商品・工具機器` を追加。
  - 広すぎる `ロジクール 型番` / `エレコム 型番` / `サンワサプライ 型番` は混入が多いので使わない。
  - 代わりに `Logicool MX MASTER4`、`Logicool KX850`、`エレコム WRC-X6000QS`、`サンワサプライ CMS-V` など実型番に寄せる。
- `webapps/market_ranking.php`
  - `model_number_products` タブ追加。
- `webapps/index.php`
  - `型番商品`、`マキタ`、`HiKOKI`、`測定器`、`ルーター`、`NAS・UPS` の導線追加。
- `scripts/register_market_worker.py`
  - `型番商品・工具機器` のAIxSNS投稿先URL追加。

運用メモ:

- `充電器` は除外語にしない。マキタ/HiKOKIの正規セットまで落ちる。
- ただし `ACアダプター` はノイズになりやすいので除外のまま。
- `ケースのみ`、`カラープレート`、`専用収納ケース`、`イヤーパッド`、`マウスソール` などは除外する。
- 楽天APIは英字スペース入りキーワードを `wrong_parameter` にする場合がある。`Logicool MX Master 4` はNGだったため `Logicool MX MASTER4` にした。
- `HTTP 400 wrong_parameter` はスクリプトで該当キーワードをスキップして続行する。

今回の結果:

- `型番商品・工具機器` は 408件。
- `webapps/index.php` と `webapps/market_ranking.php` はFTPアップロード済み。

確認:

```bash
curl -L -s 'https://aixec.exbridge.jp/market_ranking.php?tab=model_number_products' | rg -n '型番商品・工具機器|商品がありません'
curl -L -s 'https://aixec.exbridge.jp/' | rg -n '型番商品|マキタ|HiKOKI|測定器|ルーター|NAS・UPS'
```
