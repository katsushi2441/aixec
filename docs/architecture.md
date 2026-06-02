# AIxEC Architecture

## Decision

SQLite runs on this Linux server only. Heteml does not connect to SQLite directly.

Reason: SQLite is a local file database, not a network database server. Remote access must go through an application layer.

## Runtime shape

```text
Browser
  -> https://aixec.exbridge.jp/          heteml PHP 8.2 frontend/proxy
  -> http://exbridge.ddns.net:8022      AIxEC API on this Linux server
  -> storage/aixec.sqlite                local SQLite file
```

## Responsibilities

- Linux server: API, SQLite, AI/Ollama, Playwright, CSV generation.
- Heteml: public frontend, thin PHP proxy, no DB secrets.

## Initial local API

```bash
cd /home/kojima/exdirect/aixec
sqlite3 storage/aixec.sqlite < database/schema.sql
./scripts/run_api.sh
```
