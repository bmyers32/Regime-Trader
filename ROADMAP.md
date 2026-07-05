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

### Compression-within-trend signal flag
**Idea:** When TRENDING regime fires and BB width is simultaneously below its rolling percentile, pass a `compression_flag=True` into the SignalLog indicator_snapshot. The trend_pullback strategy can optionally tighten its score threshold when the flag is set, favouring only the highest-confidence pullback entries.
**Reasoning:** During Phase 3, the classifier priority debate revealed that TRENDING and COMPRESSION can be simultaneously true — the classifier resolves the conflict by picking TRENDING, but the compression state carries information. A pullback within a compressed trend tends to resolve sharply in the trend direction, making it a potentially tighter entry.
**Design questions:** Flag belongs in indicator_snapshot (no schema change) or as a dedicated SignalLog column? Does tighter score threshold need its own walk-forward arm, or does it fall out of the existing one? What is the Phase 4 hit rate of simultaneous TRENDING + sub-P20 BB?
**Why deferred:** No strategy code until Phase 5. Phase 4 pass-rates will first reveal how often the overlap occurs per pair; if rare (<5% of TRENDING bars), the signal adds noise not signal.
