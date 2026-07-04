# ROADMAP.md — Regime Trading System
Future work + ideas outside current phase scope. Phase status lives in CLAUDE.md.

## Deferred (known, intentionally outside Phases 1–11)
- **Cross-pair correlation-aware sizing** — v1 handles multi-pair risk via per-currency exposure caps (TRADING-RULES §4.2): blunt but safe. Correlation matrix that downsizes when enabled pairs are highly correlated (GBP/JPY+EUR/JPY) needs real multi-pair trade history first.
- **Postgres migration** — SQLite+WAL suffices for one writer + one reader. Revisit only if concurrency or PA disk I/O becomes a measured problem.
- **Live economic-calendar API** — Phase 8 ships blackout windows from a manually maintained weekly config table; §4.6 defines behavior when calendar data is absent.

## Feature Proposals
(Idea Processing Protocol appends here. Format per entry: Idea / Reasoning / Design questions / Why deferred.)

### Telegram/email alerting
**Idea:** Push on breaker trip, rejection streak, heartbeat gap >N min, daily PnL summary.
**Reasoning:** Dashboard is pull-based; a stalled Always-On Task fails silently until someone looks. Alerting closes the loop for an unattended system.
**Design questions:** Channel (Telegram bot vs SMTP); dedup/rate-limit; sender lives in bot vs a watchdog task reading heartbeats (watchdog survives bot death — likely correct).
**Why deferred:** Needs journal+heartbeat schema stable (Phases 1–2). Fits right after Phase 10.

### Signal replay viewer
**Idea:** Click a SignalLog row → render candle window + indicator_snapshot overlay: exactly what the strategy saw.
**Reasoning:** Turns "why did/didn't it trade" from CSV archaeology into a glance. Chart.js on existing stack; snapshot JSON already captured.
**Design questions:** Cached candles vs refetch; window size (~50); default overlays.
**Why deferred:** Needs Phases 2 + 9. Purely additive; no schema change.

### Walk-forward automation harness
**Idea:** One CLI command running the full §5 chain (backtest → WFO → stability sweep → per-regime attribution) emitting a single validation-report artifact the Phase 11 gate consumes.
**Reasoning:** Gates are only as strong as their friction is low; one-command revalidation actually gets run after every tweak.
**Why deferred:** Needs Phases 4–5. Build immediately after — before playbooks 2–3 so they're validated with it from birth.
