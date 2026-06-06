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
