# OpenClawを司令塔として活かすAIxEC Market Pipeline設計

## Summary

現在のmarket pipelineは、HermesがRQDB4AIへ既存 `market_task.generated.json` を渡しているだけで、OpenClawの司令塔性を活かしていない。

これを次の構成に変える。

```text
Hermes → OpenClaw/Claude OAuthで市場判断 → task生成 → RQDB4AIで候補取得・選定 → AIxEC APIでDB登録 → dashboard/AIxSNS反映
```

OpenClawの役割は「マーケティング判断とtask生成」。RQDB4AIの役割は「重い候補処理」。AIxEC WEB/APIの役割は「本番DB登録」。

## Key Changes

- Hermesの `aixec-market-pipeline-enqueue` は、RQDB4AIへ即enqueueしない。
- 先にAIxEC側でOpenClaw経由Claude OAuthを呼び、最新のDB・アクセスログ・登録状況から `tasks/market_task.generated.json` を再生成する。
- task生成が成功した場合だけ、そのtaskをRQDB4AIの `aixec_market_jobs.market_pipeline_job` に渡す。
- task生成失敗時は、古いtaskを勝手に使わず `down` としてdashboardへ報告する。
- AIxSNS投稿文も「OpenClawがマーケティング判断した」と書くのは、OpenClaw task生成が成功した時だけにする。

## Implementation Design

- AIxEC側にOpenClaw司令塔スクリプトを作る。
  - `scripts/openclaw_select_market_task.py`
  - 入力: `tasks/marketing_context.md`, `skills/aixec-product-registration/SKILL.md`, `tasks/task.schema.json`
  - 出力: `tasks/market_task.generated.json`, `tasks/market_task.openclaw_raw.json`
  - 実行: `openclaw capability model run --model claude-cli/claude-sonnet-4-6 --local --json`
  - OpenClaw失敗時のClaude直呼びfallbackは入れない。OpenClaw活用を保証するため。

- Hermes側のmarket enqueueスクリプトを変更する。
  - `scripts/build_marketing_context.py` を実行
  - `scripts/openclaw_select_market_task.py` を実行
  - 生成されたtask JSONを読み込み、RQDB4AIへenqueue
  - dashboard noteに `openclaw_task=<group>` `job=<rq_job_id>` を入れる

- RQDB4AI側は今まで通り。
  - `aixec_market_jobs.market_pipeline_job`
  - 受け取った `task` で楽天候補取得・Ollama/heuristic選定
  - AIxEC API `market/register-task` にPOST
  - 本番DBは触らない

- dashboard/status syncを整理する。
  - enqueue成功は `queued items=0`
  - OpenClaw task生成成功はnoteに明記
  - 実登録件数はRQDB4AI job結果またはAIxEC API登録結果から反映
  - 古いtask再利用は禁止。

## Test Plan

- OpenClaw単体テスト:
  - `build_marketing_context.py` 実行後、OpenClawでJSON schema準拠taskが生成されること。
  - `market_task.openclaw_raw.json` にOpenClaw出力が保存されること。
  - `market_task.generated.json` の `label/group/keywords/target_count/reason` が存在すること。

- Hermes dry-run:
  - market enqueueスクリプトをdry-run相当で実行し、OpenClaw task生成までは行う。
  - RQDB4AIへは `dry_run=true` または `skip_submit=true` で投入確認。
  - dashboardに `queued` とOpenClaw task情報が出ること。

- Failure tests:
  - OpenClawコマンドを無効化した場合、RQDB4AIへenqueueされないこと。
  - task JSONがschema不正ならenqueueされないこと。
  - `rqdb4ai_status_sync.sh` 実行後にゾンビ名や古いworker名が復活しないこと。

- Production acceptance:
  - Hermes定時実行でOpenClaw taskが毎回更新される。
  - RQDB4AI jobに渡されたtaskが、その回のOpenClaw生成taskと一致する。
  - AIxSNS告知文にOpenClaw利用を書くのは、OpenClaw生成taskで登録した回だけ。

## Assumptions

- OpenClaw/Claude OAuthはこのサーバ側で使う。RQDB4AIサーバ側にはOAuth判断を移さない。
- RQDB4AIは引き続き別サーバで、重い処理とOllama選定を担当する。
- 本番DB登録はAIxEC WEB/API側のみが担当する。
- 既存のClaude直呼び `claude_select_market_task.py` は残してもよいが、market pipeline本流では使わない。
- 既存ブログの表現は、実装後に「OpenClawが実際に司令塔としてtask生成する構成」に合わせて修正する。
