---
Purpose: Phase 10 companion. PythonAnywhere's process model shapes the architecture from Phase 1.
---

# DEPLOY-PYTHONANYWHERE.md

## The shaping constraint
PA web apps are WSGI request/response workers — no long-running loops. Therefore TWO processes, ONE SQLite journal:
```
┌────────────────────┐      journal.db (WAL)      ┌─────────────────────┐
│ BOT: Always-On Task│ writes ────────────────▶   │ DASHBOARD: WSGI app │
│ run_bot.py loop    │ ◀──── reads control_flags/ │ read-mostly; writes │
└────────────────────┘       instrument_control   │ flags + BT queue    │
        ▲ worker task drains BacktestRun queue    └─────────────────────┘
```

## Account facts (paid account active — verify limits at deploy; they change)
- Always-On Tasks host bot + backtest worker. Both auto-restart on crash — journal a BotHeartbeat on startup so restarts are visible.
- CPU-seconds are metered even paid. Backtests are the budget risk, not the bot loop. Worker drains the queue as a task — NEVER in a web request (web timeout would kill it anyway).
- Outbound HTTPS to api-fxpractice/api-fxtrade.oanda.com unrestricted on paid.

## SQLite discipline (two processes)
- `PRAGMA journal_mode=WAL` at engine creation; set `busy_timeout`; short write transactions.
- Bot = ONLY writer to trading tables; dashboard writes ONLY control_flags, instrument_control, BacktestRun queue.
- DB in the project directory (shared disk both processes see). Never /tmp.

## Deploy checklist (Phase 10)
1. Push repo; virtualenv; `pip install -r requirements.txt` (pinned).
2. Secrets: web-app "Environment variables" panel for dashboard; Always-On task sources `~/.env` at top of launch command (env vars don't auto-propagate to tasks).
3. WSGI file → dashboard app factory; static mapped for /static/.
4. Always-On Task: `python /home/USER/regime_trader/bot/run_bot.py`.
5. Second task: backtest worker.
6. Daily backup task: `sqlite3 journal.db ".backup backups/journal-$(date +%F).db"`, keep 14 days, prune older. The journal holds the Phase 11 forward-test evidence — losing it resets the live-gate clock. Periodically pull a copy off PA to local disk.
7. Code lives on a **private** GitHub/GitLab remote (repo contains strategy params and account structure even with .env excluded). Push at every close-out.
8. Smoke-test order of proof: heartbeat rows appear → `/` shows fresh heartbeat (after login — unauthenticated requests rejected) → pause flag observed within one cycle → **disable a pair on /controls, next heartbeat's active-pair list excludes it, re-enable restores** → queued backtest completes and renders → backup file appears next day.
9. PA servers are UTC — the only timezone this project speaks (CLAUDE.md rules).

## Local-first parity
run_bot.py, dashboard, worker run identically on dev machine (three terminals) and PA (task + web app + task). Needing an `if on_pythonanywhere:` branch = design smell — stop and flag.
