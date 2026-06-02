# OpenClaw / Hermes Setup for AIxEC

## Current Status

- Claude Code OAuth: installed and authenticated.
  - Binary: `/home/kojima/.vscode-server/extensions/anthropic.claude-code-2.1.145-linux-x64/resources/native-binary/claude`
  - Auth directory: `/home/kojima/.claude`
- Ollama: configured through `.env`.
  - `OLLAMA_ENDPOINT`
  - `OLLAMA_BASE_URL`
- AIxEC automation entrypoint: implemented.
  - `/home/kojima/exdirect/aixec/scripts/hermes_autonomous_market.sh`
- OpenClaw: not installed yet.
- Hermes: not installed yet.

## AIxEC Pipeline

OpenClaw/Hermes should run:

```bash
/home/kojima/exdirect/aixec/scripts/hermes_autonomous_market.sh
```

## AIxEC Growth Agent

The stronger OpenClaw/Hermes use case is the growth loop, not only product registration.

Growth loop:

1. Observe AIxEC logs, valid go.php clicks, AIxSNS reactions, product groups, and memory.
2. Ask Claude Code OAuth to make a strategic growth plan.
3. Execute the selected action: market registration, SNS post, content idea, or observe only.
4. Use Ollama gemma4:e4b inside workers for bulk product scoring.
5. Save memory for the next cycle.

Hermes/OpenClaw should run:

```bash
/home/kojima/exdirect/aixec/scripts/hermes_growth_agent.sh
```

Small dry-run:

```bash
/home/kojima/exdirect/aixec/scripts/hermes_growth_agent.sh --dry-run --market-limit 1
```

Generated files:

- `tasks/growth_observation.md`
- `tasks/growth_plan.generated.json`
- `tasks/growth_execution_result.md`
- `tasks/growth_memory.md`

Small dry-run:

```bash
/home/kojima/exdirect/aixec/scripts/hermes_autonomous_market.sh \
  --skip-claude --dry-run --limit 5 --hits 3 --pages 1 --max-candidates 12
```

Full run:

```bash
/home/kojima/exdirect/aixec/scripts/hermes_autonomous_market.sh
```

## OpenClaw Role

Use `openclaw_aixec_market_prompt.md` as the OpenClaw task prompt.

Expected behavior:

1. Start AIxEC autonomous pipeline.
2. Let Claude Code OAuth create `tasks/market_task.generated.json`.
3. Let worker use Ollama `gemma4:e4b` to select products.
4. Register selected products into AIxEC.
5. Post the result to AIxSNS.

## Hermes Role

Hermes should be the scheduler / job runner.

Command:

```bash
cd /home/kojima/exdirect/aixec
python3 scripts/autonomous_market_pipeline.py
```

## systemd Fallback

If Hermes is not ready, use systemd timer as a safe scheduler:

```bash
sudo cp /home/kojima/exdirect/aixec/scripts/systemd/aixec-autonomous-market.service /etc/systemd/system/
sudo cp /home/kojima/exdirect/aixec/scripts/systemd/aixec-autonomous-market.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aixec-autonomous-market.timer
systemctl status aixec-autonomous-market.timer
```

Manual run:

```bash
sudo systemctl start aixec-autonomous-market.service
journalctl -u aixec-autonomous-market.service -n 100 --no-pager
```

## Install Note

Do not install random OpenClaw/Hermes packages from search results.

Before installation, confirm the official repository or installer URL. These tools receive broad access to files, shell, OAuth sessions, and DB/FTP workflows.
