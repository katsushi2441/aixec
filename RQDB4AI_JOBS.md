# AIxEC RQDB4AI Jobs

AIxEC固有のjobコードはAIxECリポジトリ配下に置く。

RQDB4AI本体にはAIxEC固有のPythonファイル、設定、説明を書かない。

## Job code

- `/home/kojima/work/aixec/aixec_market_jobs.py`

## 方針

- RQDB4AIはキュー管理とPython callable実行だけを担当する。
- AIxECの業務ロジックはAIxEC側が持つ。
- AIxECの本番DBはWEBサーバ側の資産。
- RQDB4AI側でAIxEC本番DBを直接触らない。
- enqueue成功をAIxEC実処理成功として扱わない。
- 実登録件数はAIxEC側の処理結果またはreportを正とする。

## register_market_worker

`register_market_worker` は `market_pipeline` とは別物。

- `market_pipeline`: taskに基づく市場選定・候補登録
- `register_market_worker`: 既存ジャンルの楽天ランキング巡回・未登録商品の登録

この2つを流用・混同しない。
