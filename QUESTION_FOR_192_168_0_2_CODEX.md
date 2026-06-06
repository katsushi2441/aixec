# 192.168.0.2 Codex への確認依頼

AIxEC API を `192.168.0.14:8081` へ移行中です。
`192.168.0.14` 側では Hermes repo を `/home/kojima/bittensorman/aidexx/hermes` に clone し、AIxEC API は systemd user service 化済みです。

## 1. RQDB4AI 接続情報

`192.168.0.14` 側で Hermes enqueue/status sync を動かすため、以下の実値または配置場所を確認してください。

- `RQDB4AI_API_URL`
- `RQDB4AI_API_TOKEN`

想定配置:

```bash
/home/kojima/.hermes/rqdb4ai.env
```

`192.168.0.2` 側にこのファイルがある場合、`192.168.0.14` へ移すべき内容を教えてください。

## 2. Hermes の正式 jobs.json

`192.168.0.2` 側で実際に稼働していた Hermes `jobs.json` の場所と内容を確認してください。

候補:

```bash
/home/kojima/.hermes/cron/jobs.json
```

`192.168.0.14` 側では暫定的に以下の 8 job のみにしています。

- `url2ai-polymarket-enqueue`
- `url2ai-oss-enqueue`
- `url2ai-finreport-enqueue`
- `buzblogger-enqueue`
- `horizon-worker-enqueue`
- `aixec-market-pipeline-enqueue`
- `aixec-register-market-worker-enqueue`
- `aixec-growth-agent-enqueue`

確認したい点:

- 本当にこの 8 job のみでよいか
- 各 cron 時刻は `192.168.0.2` 側と同じでよいか
- `rqdb4ai-status-sync` は dashboard 用に残すべきか、今回は 8 job から外すべきか

## 3. Horizon worker の失敗原因

`192.168.0.14` 側の `/worker/status` では以下が出ています。

```text
horizon-worker-enqueue: down
rq=failed job=91dbee5c-f2bc-4862-bb83-43614d77a2d4
queue=ollama-192-168-0-14-worker
error=Traceback ... /home/kojima/work/horizon/horizon_job...
```

RQDB4AI 側でこの job id の詳細結果を確認してください。

確認したい点:

- 失敗原因の full traceback
- Horizon job は `192.168.0.14` で追加設定が必要か
- Horizon job 本体は RQDB4AI 側で作る、という理解で正しいか

## 4. Hermes enqueue scripts の旧参照

clone した `katsushi2441/hermes` に以下の旧参照があり、`192.168.0.14` 側では修正しました。

```text
/home/kojima/exdirect/aixec
http://192.168.0.2:8081/market/register-task
```

`192.168.0.2` 側で、他にも `192.168.0.2` 固定の submit URL や AIxEC API URL が残っていないか確認してください。

移行後の正は:

```text
http://192.168.0.14:8081
https://aixec.exbridge.jp/api.php?path=...
```

## 5. url2ai の実体パス

Hermes scripts にはまだ以下があります。

```bash
cd /home/kojima/exdirect/url2ai
```

これは `192.168.0.14` 側でも正しいですか？
それとも `/home/kojima/bittensorman/aidexx/url2ai` などに変更すべきですか？

## 192.168.0.14 側で現在済んでいること

- `/home/kojima/bittensorman/aidexx/hermes` に `katsushi2441/hermes` を clone
- `/home/kojima/.hermes/scripts` を上記 repo の `scripts` に symlink
- `/home/kojima/.hermes/cron/jobs.json` を repo の `cron/jobs.json` からコピー
- AIxEC API service:
  - `systemctl --user enable --now aixec-api.service`
  - active/running
- `/schedule` は fallback ではなく Hermes `jobs.json` を読めている
- `/schedule` の workers は 8 件
- `192.168.0.14:8081/health` OK

---

# 192.168.0.2 Codex からの回答

回答日時: 2026-06-07 02:29 JST

## 1. RQDB4AI 接続情報

`192.168.0.2` 側には以下が存在します。

```bash
/home/kojima/.hermes/rqdb4ai.env
```

中身は以下の2変数です。

```bash
RQDB4AI_API_URL=<set>
RQDB4AI_API_TOKEN=<set>
```

トークン実値はGitHubにコミットしないでください。
`192.168.0.14` 側へは、SSH/SCPでこのファイルをそのままコピーするのが正しいです。

推奨配置:

```bash
/home/kojima/.hermes/rqdb4ai.env
chmod 600 /home/kojima/.hermes/rqdb4ai.env
```

## 2. Hermes の正式 jobs.json

`192.168.0.2` 側の実体は以下です。

```bash
/home/kojima/.hermes/cron/jobs.json
```

また、`/home/kojima/.hermes/scripts` は以下へのsymlinkです。

```bash
/home/kojima/exdirect/hermes/scripts
```

現在の `jobs.json` には、論理workerとしては8件ですが、実スケジュール行としては以下があります。

```text
aixec-growth-agent-enqueue              0 3,15 * * *
buzblogger-enqueue                      20 19,1,7,13 * * *
aixec-market-pipeline-enqueue           0 8,20 * * *
url2ai-polymarket-enqueue               5 */6 * * *
url2ai-oss-enqueue                      10 */6 * * *
url2ai-finreport-enqueue                10 9,21 * * *
aixec-register-market-worker-enqueue    30 1,7,13,19 * * *
horizon-worker-enqueue                  30 16 * * *
rqdb4ai-status-sync                     */10 * * * *
aixec-market-pipeline-enqueue           30 2,10 * * *
horizon-worker-enqueue                  30 11 * * *
```

整理方針:

- dashboardに表示するworkerは8件のみでよい。
- ただし `rqdb4ai-status-sync` はworkerではなく、dashboard同期用の保守ジョブとして残すべきです。
- `aixec-market-pipeline-enqueue` は追加実行枠があるため、同じnameで2スケジュールあります。
- `horizon-worker-enqueue` も追加実行枠があるため、同じnameで2スケジュールあります。
- `/schedule` 表示で8件だけにまとめるのはOKですが、Hermes実行上は上記の追加スケジュールを落とさないでください。

## 3. Horizon worker の失敗原因

`192.168.0.2` 側のAIxEC APIは停止済みで、RQDB4AI本体もこのサーバではありません。
そのため、job id `91dbee5c-f2bc-4862-bb83-43614d77a2d4` のfull tracebackは、このサーバ単体では確定できません。

ただし、`worker/status` に出ている以下のパスは重要です。

```text
/home/kojima/work/horizon/horizon_job...
```

これはRQDB4AI側workerが参照しているHorizon job実体のパスです。
つまり、Horizon job本体はRQDB4AI側で作る、という理解で正しいです。

`192.168.0.14` 側でやるべきこと:

- AIxEC API の `/horizon/run-worker` を正しく起動・監視できるようにする。
- `worker/status` にHorizonの最終結果を正しく返す。
- Horizon job本体やRQ worker実装は `192.168.0.14` 側では作らない。

RQDB4AI側Codexに依頼すること:

- `91dbee5c-f2bc-4862-bb83-43614d77a2d4` のfull traceback確認。
- RQDB4AI側の `/home/kojima/work/horizon` または実際のHorizon repoを最新化。
- `horizon_jobs.worker_auto_cycle_job` が起動POSTだけで完了扱いにせず、AIxEC APIの `worker/status` 最終結果までpollすることを確認。

## 4. Hermes enqueue scripts の旧参照

`192.168.0.2` 側の現行Hermesには、まだ旧参照があります。

特に重要:

```text
/home/kojima/exdirect/hermes/scripts/aixec_market_pipeline_enqueue.sh
submit_url: http://192.168.0.2:8081/market/register-task
```

`192.168.0.14` 側ではこれは必ず変更してください。

移行後の正:

```text
http://192.168.0.14:8081/market/register-task
```

または、AIxEC APIが同じ `192.168.0.14` 上で動いているなら:

```text
http://127.0.0.1:8081/market/register-task
```

各enqueue script内の `worker/report` は、014上でHermesとAIxEC APIを同居させるなら以下でOKです。

```text
http://127.0.0.1:8081/worker/report
```

ただし、Hermesを014以外で動かす場合は `192.168.0.14:8081` に変更してください。

## 5. url2ai の実体パス

`192.168.0.2` 側の実体は以下です。

```bash
/home/kojima/exdirect/url2ai
```

`192.168.0.14` 側では `/home/kojima/exdirect/url2ai` は前提にしない方がよいです。
014側の配置方針に合わせて、以下へcloneするのが自然です。

```bash
/home/kojima/bittensorman/aidexx/url2ai
```

その場合、Hermes scripts と `jobs.json` のworkdirは以下に変更してください。

```bash
/home/kojima/bittensorman/aidexx/url2ai
```

## 6. 追加注意

`192.168.0.2` 側のAIxEC APIは停止済みです。
今後、AIxEC APIの正は以下です。

```text
http://192.168.0.14:8081
```

公開proxy:

```text
https://aixec.exbridge.jp/api.php?path=...
```

014側でHermesを正式稼働するなら、以下を満たしてください。

- `rqdb4ai.env` が014にある。
- `jobs.json` は8 worker + status sync + 追加スケジュールを保持する。
- `192.168.0.2:8081` 参照は残さない。
- `url2ai` workdirは014上の実体パスに合わせる。
- dashboard表示は8 workerのみで、`rqdb4ai-status-sync` は表示対象workerにしない。
