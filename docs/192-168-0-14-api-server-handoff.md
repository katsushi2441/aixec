# 192.168.0.14 AIxEC API Server Handoff

目的:
`api_server.py` を `192.168.0.14` で正しく稼働させる。
Hermesは `192.168.0.2` に残す。

## 正しい構成

```text
192.168.0.2
- Hermes
- RQDB4AI enqueue
- status sync
- スケジュール管理

192.168.0.14
- AIxEC api_server.py
- AIxEC DB
- /worker/report
- /market/register-task
- /register-market/run-worker
- /horizon/run-worker
```

`192.168.0.14` でHermesを本番稼働させない。
APIだけを稼働させる。

## 作業ディレクトリ

```bash
cd /home/kojima/bittensorman/aidexx/aixec
```

## 起動確認

```bash
systemctl --user status aixec-api.service --no-pager
ss -ltnp | grep ':8081'
curl -sS http://127.0.0.1:8081/health
curl -sS http://192.168.0.14:8081/health
```

期待:

```json
{"ok":true,"name":"AIxEC","runtime":"python","db":"storage/aixec.sqlite"}
```

## DB確認

```bash
ls -lh storage/aixec.sqlite

python3 - <<'PY'
import sqlite3
con = sqlite3.connect("storage/aixec.sqlite")
for t in ["products", "posts"]:
    print(t, con.execute(f"select count(*) from {t}").fetchone()[0])
PY
```

目安:

```text
products 約79351
posts    約7594
```

## API機能確認

```bash
curl -sS http://127.0.0.1:8081/products?limit=1 | jq '.ok'
curl -sS http://127.0.0.1:8081/posts?limit=1 | jq '.ok'
curl -sS http://127.0.0.1:8081/worker/status | jq '.ok'
curl -sS http://127.0.0.1:8081/ollama/status | jq '.ok'
curl -sS http://127.0.0.1:8081/market/pipeline/status | jq '.ok'
```

全部 `true` が期待値。

## systemd user service

AIxEC APIはsystemd user serviceで稼働させる。

確認:

```bash
systemctl --user cat aixec-api.service
```

期待する要点:

```ini
[Service]
WorkingDirectory=/home/kojima/bittensorman/aidexx/aixec
Environment=AIXEC_DB=storage/aixec.sqlite
Environment=AIXEC_PORT=8081
ExecStart=/home/kojima/bittensorman/aidexx/aixec/scripts/run_api.sh
Restart=always
RestartSec=5
```

再起動:

```bash
systemctl --user daemon-reload
systemctl --user restart aixec-api.service
sleep 2
systemctl --user status aixec-api.service --no-pager
curl -sS http://127.0.0.1:8081/health
```

## Hermesは014で動かさない

確認:

```bash
pgrep -af hermes || true
pgrep -af rqdb4ai_status_sync || true
```

Hermesやstatus syncが014で動いていたら止める。

```bash
pkill -f hermes || true
pkill -f rqdb4ai_status_sync || true
```

ただし、以下は止めない。

```text
python3 scripts/api_server.py
```

## /scheduleについて

`/schedule` はHermes表示用。
Hermesは `192.168.0.2` で動かすため、014側の `/schedule` がfallbackでもAPI本体の異常ではない。

014側でHermesを動かして解決しようとしない。
必要なら `jobs.json` だけを表示用に同期する。

## 192.168.0.2から呼ばれるAPI

Hermesは002側で動く。
002側Hermesから014側APIへPOSTされる。

014側で受ける必要がある主なendpoint:

```text
GET  /health
GET  /products
GET  /posts
GET  /worker/status
POST /worker/report
POST /market/register-task
POST /register-market/run-worker
POST /horizon/run-worker
POST /growth/run-agent
```

`worker/report` の受信テスト:

```bash
curl -sS -X POST http://127.0.0.1:8081/worker/report \
  -H 'Content-Type: application/json' \
  -d '{"name":"migration-test","status":"ok","items":0,"note":"api migration test"}' | jq .
```

期待:

```json
{"ok":true}
```

## 002側で変更すべき参照

002側HermesのAIxEC API参照は、014へ向ける。

変更前の例:

```text
http://127.0.0.1:8081
http://localhost:8081
http://192.168.0.2:8081
```

変更後:

```text
http://192.168.0.14:8081
```

014側Codexは、002側Hermesの本番起動までは触らない。
必要な修正点だけ002側Codexへ伝える。

## 絶対にやらないこと

- 014でHermesを本番稼働させない
- 014でRQDB4AI workerを起動しない
- 014でジョブスケジュールを二重化しない
- 002と014の両方でHermesを動かさない
- API移行のためにRQDB4AI job本体を014へ作らない

## 最終確認

```bash
curl -sS http://192.168.0.14:8081/health
curl -sS http://192.168.0.14:8081/products?limit=1 | jq '.ok'
curl -sS http://192.168.0.14:8081/posts?limit=1 | jq '.ok'
curl -sS http://192.168.0.14:8081/worker/status | jq '.ok'
```

全部OKなら、014側のAIxEC API稼働は完了。
