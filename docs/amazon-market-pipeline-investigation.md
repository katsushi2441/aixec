# Amazon Creators API for AIxEC Market Pipeline

## Goal

AIxECの `market-pipeline` は現在、楽天市場の商品検索APIから候補を集めている。
今後はAmazonで売れやすい商品も多く掲載したい。

このメモは、Amazon Creators APIを使ってAIxECの商品候補生成に使えるかを調査した結果。

## Conclusion

Creators APIはAIxECのAmazon商品候補収集に使える。

ただし、最初から「Amazon売れ筋ランキング全体を丸ごと取得するAPI」として扱うのではなく、
以下の用途で使うのが現実的。

- キーワード検索でAmazon商品候補を集める
- ASIN単位で商品詳細を補完する
- BrowseNodeを使ってカテゴリ単位の候補を広げる
- SalesRank / WebsiteSalesRank相当の情報が取れる場合は、候補スコアへ反映する

AIxECでは、楽天候補とAmazon候補を同じ候補JSONへ正規化して、既存の選定・登録フローへ渡すのがよい。

## Relevant API Operations

Amazon Creators APIの主な商品カタログ操作:

- `SearchItems`
  - キーワード、フィルタ、BrowseNodeで商品検索
  - AIxECの楽天 `fetch_items()` 相当
- `GetItems`
  - ASINなどから商品詳細を取得
  - JAN/ISBN/既存商品補完に使える
- `GetVariations`
  - 親ASINからバリエーションを取得
  - サイズ・色・容量違いの商品展開に使える
- `GetBrowseNodes`
  - カテゴリ階層を取得
  - 楽天genre_id相当のAmazon版として使える

## Current AIxEC Flow

現在の楽天market-pipeline:

```text
autonomous_market_pipeline.py
  -> register_market_task_worker.py
      -> import_rakuten_market_products.fetch_items()
      -> normalize_item()
      -> score_candidates()
      -> upsert_product()
```

楽天候補の正規化フィールド:

```text
keyword
name
catchcopy
caption
price
item_url
affiliate_url
image_url
shop_name
shop_code
item_code
genre_id
review_average
review_count
jan
raw
```

Amazon候補も同じような形へ寄せれば、既存のOllama/heuristic選定や登録結果レポートを流用できる。

## Proposed Amazon Candidate Schema

Amazon正規化アイテム案:

```json
{
  "source": "amazon_creators",
  "keyword": "生成AI 書籍",
  "name": "...",
  "catchcopy": "",
  "caption": "...",
  "price": 1980,
  "item_url": "https://www.amazon.co.jp/dp/ASIN",
  "affiliate_url": "https://www.amazon.co.jp/dp/ASIN?tag=bittensorman-22",
  "image_url": "...",
  "shop_name": "Amazon",
  "shop_code": "amazon",
  "item_code": "ASIN",
  "asin": "ASIN",
  "genre_id": "browse_node_id",
  "review_average": "",
  "review_count": "",
  "sales_rank": 123,
  "website_sales_rank": 456,
  "jan": "",
  "raw": {}
}
```

## Product Registration Mapping

Amazon商品登録時の `products` 値:

```text
internal_sku       amazon_creators:{asin}
asin               ASIN
jan                JAN/ISBNが取れる場合のみ
gtin               JAN/ISBNが取れる場合のみ
name               Amazon商品名
maker              ブランドまたはAmazon
model_number       ASINまたは型番
source_url         Amazon商品URL
sale_price         取得できる価格
amazon_url         AmazonアフィリエイトURLまたはgo.php導線
rakuten_url        null
affiliate_priority amazon
status             active
```

クリック計測を統一するため、表示側ではできるだけAIxEC `go.php` 経由を維持する。

## Where To Add Code

まずはAIxECリポジトリ側に追加する。
RQDB4AI本体にはAmazon固有コードを置かない。

候補:

```text
scripts/amazon_creators_client.py
scripts/import_amazon_market_products.py
```

`register_market_task_worker.py` には最小の変更で、候補ソースを選べるようにする。

例:

```bash
python3 scripts/register_market_task_worker.py --source rakuten
python3 scripts/register_market_task_worker.py --source amazon
python3 scripts/register_market_task_worker.py --source mixed
```

## Test Plan

### Phase 1: Read-only API test

Secretsをログに出さず、5件だけ取得する。

```bash
python3 scripts/amazon_creators_client.py search --keywords "生成AI 書籍" --limit 5
python3 scripts/amazon_creators_client.py get --asin "XXXXXXXXXX"
```

確認:

- 認証が通る
- 日本Amazon marketplaceで検索できる
- ASIN、title、URL、image、price、rank系情報が取れる
- affiliate tag付きURLを作れる

### Phase 2: Candidate JSON test

DB登録しない。

```bash
python3 scripts/import_amazon_market_products.py \
  --keywords "生成AI 書籍" \
  --hits 10 \
  --dry-run \
  --json-out /tmp/amazon_candidates.json
```

確認:

- `amazon_creators:{asin}` が一意キーになる
- 既存の楽天候補と同じ選定処理に渡せる
- SalesRankが取れる場合はscoreに反映できる

### Phase 3: Small registration

最初は5〜20件だけ登録。

```bash
python3 scripts/register_market_task_worker.py \
  --source amazon \
  --task tasks/market_task.generated.json \
  --limit 20 \
  --score-mode heuristic
```

確認:

- AIxEC商品ページにAmazon商品が表示される
- `affiliate_priority=amazon`
- Amazonボタンが出る
- AIxSNS告知に新規登録商品が出る

## Open Questions

- Creators APIで日本向けのBest Seller/BrowseNodeランキングがどの程度直接取れるか。
- `SearchItems` の `SortBy` とBrowseNode指定だけで、十分に「売れている商品」候補になるか。
- SalesRank系リソースがCreators API v3.3で安定して返るか。
- 価格・画像・レビュー情報の保存/表示条件をAmazon Associates規約に合わせる必要がある。

## Practical Recommendation

まずは楽天market-pipelineを置き換えない。

次の順番が安全。

1. Amazon Creators APIのread-only検索クライアントを作る。
2. 5件だけ検索して実レスポンスを保存せず確認する。
3. Amazon候補を楽天候補と同じJSONに正規化する。
4. `source=mixed` で楽天 + Amazon候補を混ぜてAI選定する。
5. AmazonのSalesRankやBrowseNodeが使えるなら、Amazon候補を優先スコアリングする。

大量掲載を狙う場合も、いきなり500件登録ではなく、カテゴリごとに20〜50件で開始する。

## 2026-06-05 Read-only Test Result

追加したread-onlyクライアント:

```text
scripts/amazon_creators_client.py
```

Python 3.12 + `creators` packageで、v3.3認証情報を使った検索リクエストまでは実行できた。

実行例:

```bash
uv run --python 3.12 --with creators \
  python scripts/amazon_creators_client.py search \
  --keywords "RTX 5090 グラフィックボード" \
  --limit 5 \
  --min-price 50000 \
  --sort-enum FEATURED
```

結果:

```text
AssociateNotEligible
```

これはキー形式やSDK呼び出し以前の問題ではなく、Amazon側が現在のアソシエイトアカウントをCreators API利用条件未達と判定している状態。

Amazon側でCreators API eligibilityが有効になったら、同じコマンドで再テストする。

## 2026-06-08 Read-only Retest Result

Amazon注文が30日内10件になったため再テストした。

実行:

```bash
uv run --python 3.12 --with creators \
  python scripts/amazon_creators_client.py search \
  --keywords "RTX 5090 グラフィックボード" \
  --limit 5 \
  --min-price 50000 \
  --sort-enum FEATURED
```

結果:

```text
AssociateNotEligible
```

軽い条件でも再確認:

```bash
uv run --python 3.12 --with creators \
  python scripts/amazon_creators_client.py search \
  --keywords "水 炭酸水" \
  --limit 1 \
  --min-price 1 \
  --sort-enum FEATURED
```

結果:

```text
AssociateNotEligible
```

確認できたこと:

- `docs/AIxEC-credentials.csv` は読み込めている。
- `Credential Id` は `amzn1.application-oa2-...` 形式。
- `Secret` は `amzn1.oa2-cs...` 形式。
- SDK呼び出しはAmazon側まで到達している。
- `creators` ラッパーではなく `creatorsapi_python_sdk.DefaultApi` 直呼びでも同じ403になる。
- `SearchItems` だけでなく `GetItems` でも同じ `AssociateNotEligible` になる。
- `version=3.3` + `marketplace=www.amazon.co.jp` が正しい組み合わせ。
  - `v3.3` はSDK側で非対応。
  - `2.3` はOAuthで `invalid_client` になり、今回の認証情報とは合わない。
  - `amazon.co.jp` はmarketplace形式として不正。`www.amazon.co.jp` が必要。
- ただしAmazon側は現在もこのアカウントをCreators API eligibleとして扱っていない。

考えられる原因:

- 10件が「注文」ではなく、Amazon側で「qualified / shipped / paid」になった売上としてまだ確定していない。
- 条件達成後、Creators API eligible反映まで時間差がある。
- Associates Central側でCreators API画面の状態がまだeligibleに更新されていない。
- Creators APIの前提である「approved creators account」状態がPA APIアクセス許可としてまだ反映されていない。

次回確認:

1. Amazon Associates CentralでCreators API欄が利用可能表示になっているか確認する。
2. 注文10件がキャンセル・返品ではなく発送済み/資格対象になっているか確認する。
3. 1〜2日後に同じコマンドで再テストする。

## 2026-06-09 New Credential Retest Result

別の認証情報 `docs/AIxEC-credentials (1).csv` で再テストした。

実行:

```bash
uv run --python 3.12 --with creators \
  python scripts/amazon_creators_client.py search \
  --credentials-csv 'docs/AIxEC-credentials (1).csv' \
  --keywords "RTX 5090 グラフィックボード" \
  --limit 5 \
  --min-price 50000 \
  --sort-enum FEATURED
```

軽い検索でも確認:

```bash
uv run --python 3.12 --with creators \
  python scripts/amazon_creators_client.py search \
  --credentials-csv 'docs/AIxEC-credentials (1).csv' \
  --keywords "水 炭酸水" \
  --limit 1 \
  --min-price 1 \
  --sort-enum FEATURED
```

結果:

```text
AssociateNotEligible
```

結論:

- 新しい認証情報でもOAuth認証とAPI到達はできている。
- ただしAmazon側がまだこのアカウントをCreators API eligibleとして扱っていない。
- API実装やcredential形式の問題ではなく、Amazon側の資格反映待ち、またはCreators API側の利用資格未達判定。
