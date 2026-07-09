# CLAUDE.md — Regime Trading System

## Grounding
Multi-pair OANDA forex system (practice until Phase 11 gate). Regime-routed playbooks (trend_pullback, range_reversion, squeeze_breakout) + event-driven backtester with costs + risk layer with circuit breakers + Flask dashboard that displays the journal and remotely toggles active pairs. Bot = Always-On Task and dashboard = WSGI app on the same paid PythonAnywhere account, sharing one WAL-mode SQLite journal. Local dev = same two processes, two terminals. Bind all decisions to this. **Capital preservation > trade frequency. Validation > velocity. Observability is a feature.**

## Developer Context
Proficient Python scripter. Flask/SQLAlchemy patterns established (Laser Dashboard) — reuse them. Prior bot (TradingBotv3) failure modes are law in TRADING-RULES.md §1 — never reintroduce. Explain quant concepts on first use. Understanding matters as much as output.

## Prime Directives (violation = RED LINE; rationale in TRADING-RULES §1)
1. No secrets in source. Ever. `.env`/env vars only.
2. No live-trading path until Phase 11 gate: `environment="practice"` hardcoded until an explicit config flag AND a passing validation report exist.
3. Signals only from `complete==True` candles. No repainting.
4. All order prices rounded to instrument `displayPrecision` (fetched from OANDA at startup, never hardcoded).
5. Every order verified post-submit (filled/rejected/cancelled) and journaled with reason.
6. Position size from risk %: `units = f(equity, risk_pct, stop_distance, pip_value)`. Never fixed units.
7. Backtester and live loop share the same strategy code path.

## Stack
| Layer | Choice | Hard Constraint |
|---|---|---|
| Language | Python 3.10+ | Pinned requirements.txt |
| Broker | oandapyV20 | Practice env until Phase 11 |
| Compute | pandas+numpy vectorized | No per-row `.apply` over history |
| Journal | SQLite via SQLAlchemy, WAL ON | Bot writes trading tables; dashboard writes ONLY control/queue tables |
| Dashboard | Flask + Flask-SQLAlchemy + Jinja2 + Tailwind CDN | Laser Dashboard patterns. No build step, no JS frameworks. Chart.js CDN OK. |
| Migrations | Flask-Migrate | migrate+upgrade only |
| Config | YAML per instrument + .env secrets | Tuning = config change, never code |
| Scheduling | Bot local dev / PA Always-On Task prod; dashboard WSGI same account | Bot loop NEVER inside a web request; shared journal on same disk |
| Backtests | Queued via control table, drained by worker task | Never in a web request; watch PA CPU quota |

## Structure
```
regime_trader/
├── bot/
│   ├── config/       # instruments.yaml, strategy params, risk limits
│   ├── data/         # complete-candle fetch, cache, incremental update
│   ├── indicators/   # pure vectorized, unit-tested
│   ├── regime/       # classifier + hysteresis
│   ├── strategies/   # trend_pullback | range_reversion | squeeze_breakout
│   ├── risk/         # sizing, caps, breakers, cooldowns
│   ├── execution/    # OANDA adapter: precision, spread gate, verify, retry
│   ├── journal/      # SQLAlchemy models + writer (shared w/ dashboard)
│   ├── backtest/     # event-driven sim w/ spread+slippage costs
│   └── run_bot.py
├── dashboard/app/ + run.py
├── instance/journal.db   # never commit
├── tests/                # indicators, strategies, risk, backtest golden runs
├── .env (never commit) / .env.example (committed)
├── config.py
└── requirements.txt      # pinned only
```

## Core Interfaces (contracts — do not drift)
- `Strategy.generate_signal(window, regime) -> Signal|None`; Signal={strategy, instrument, direction, entry_ref, sl, tp, confidence_score, reasons[], vetoes[]}. **Near-misses journaled too** (score below threshold → written with vetoes).
- `RegimeClassifier.classify(htf_window) -> RegimeState` ∈ {TRENDING_UP, TRENDING_DOWN, RANGING, EXPANSION, COMPRESSION} + confidence + bars_in_regime.
- `RiskManager.size_and_approve(signal, account, open_positions) -> ApprovedOrder|Rejection(reason)`.
- `Executor.submit(approved_order) -> ExecutionResult` (verified, journaled).
- Control plane: dashboard writes `control_flags` + `instrument_control`; bot reads both each cycle, obeys within one cycle. Flags: trading_paused, kill_switch, per-pair enabled, backtest_requests.
- Active pairs/cycle = instruments.yaml (calibrated) ∩ enabled in instrument_control. Enabling an unconfigured pair → refused + journaled. Disabling → new entries stop; open positions managed to completion.

## Journal Models (abbrev.)
- **BotHeartbeat:** ts, active_pairs(json), cycle_ms, flags_seen(json), notes — 1/cycle; run status = latest age; active_pairs proves toggles took effect
- **RegimeSnapshot:** ts, instrument, regime, bars_in_regime, candles_fresh — 1/pair/cycle
- **SignalLog:** ts, instrument, strategy, direction, score, threshold, fired, vetoes(json), indicator_snapshot(json)
- **Order:** ts, signal_id, units, entry, sl, tp, oanda_order_id, status, reject_reason, spread_at_entry
- **Trade:** order_id, oanda_trade_id, open/close_ts, entry/exit_px, units, pnl, pnl_r, exit_reason, regime_at_entry
- **EquitySnapshot:** ts, balance, nav, open_pnl, margin_used
- **BacktestRun:** requested_ts, params(json), status, metrics(json incl. per-regime), equity_curve_path
- **ControlFlag:** key, value, updated_ts, updated_by
- **InstrumentControl:** instrument, enabled, max_positions_override, note, updated_ts, updated_by

## Dashboard Pages
All routes require login (credentials from .env; Flask-Login or HTTP Basic — pick simplest) — mandatory before Phase 10 deploy. This page set includes a kill switch; it is never exposed unauthenticated.
| Route | Shows |
|---|---|
| `/` | Heartbeat age, regime per pair, pause/kill state, equity sparkline, open trades, today's PnL |
| `/trades` | Open+historical, filter strategy/regime/date, per-trade R + exit reason |
| `/signals` | Signal log incl. near-misses w/ vetoes — the "why no trade" page |
| `/backtests` | Request (queue row), list runs, metrics + equity curve + per-regime attribution |
| `/controls` | Per-pair toggles (open-position count + calibration status shown), pause, kill switch (typed confirm), risk limits read-only |
| `/config` | Read-only active YAML + validation report status |

## Phases
| # | Scope | Status |
|---|---|---|
| 1 | Scaffold: repo, config loader, .env, pinned deps, journal models incl. InstrumentControl, migration init, WAL | [x] |
| 2 | Data layer: complete-candle fetch, cache, incremental update, precision registry | [x] |
| 3 | Indicators + regime classifier w/ hysteresis, per-pair calibration notes | [x] |
| 4 | Backtester: event-driven, spread/slippage/rollover, golden-run tests | [x] |
| 5 | trend_pullback + walk-forward validation | [x] |
| 6 | range_reversion, validated same way | [ ] |
| 7 | squeeze_breakout, validated same way | [ ] |
| 8 | Risk + execution layer; practice forward-test begins | [ ] |
| 9 | Dashboard (local), all pages, pair toggles end-to-end | [ ] |
| 10 | PA deploy: WSGI + Always-On bot + worker task, shared journal, env secrets both processes | [ ] |
| 11 | Live gate: 60+ day forward-test within tolerance of backtest + explicit user sign-off | [ ] |

## Always-On Rules
- No raw SQL. No hardcoded config/thresholds/credentials. Pin versions; flag packages <7 days old.
- Migrations for every schema change.
- Thresholds in ATR multiples or self-normalizing percentiles only — raw price-percent banned (TRADING-RULES §1.2).
- Strategy changes: unit tests → golden runs unchanged or deliberately re-baselined → walk-forward re-run noted.
- One strategy implementation, two drivers (backtest/live).
- Implied requirements: implement + flag at >80% confidence — never silently add or omit.
- Comments explain WHY, never narrate WHAT. Required: TRADING-RULES §-citations wherever
  code implements a law (anti-drift markers), and brief rationale on non-obvious quant
  logic. Banned: line narration, docstrings restating signatures, explanations of
  standard library/pandas idioms. Comments are read at every future file view — each
  one must earn permanent context cost.
- UTC only: `datetime.now(timezone.utc)`; bare `datetime.now()` banned.
- Per-pair config isolation: thresholds live under the instrument's yaml key with calibration note; shared defaults OK only if each pair's calibration confirms.
- Currency-level exposure caps aggregate across pairs (GBP/JPY+USD/JPY = one JPY bet).

## Companion Files
**Always active:** `AGENTS.md` (rules of engagement, Idea Protocol→ROADMAP), `TRADING-RULES.md` (domain law — contradicting code is a bug by definition).
**On demand:** `PROMPTS.md` (session loop, clear rules, kickoff/close-out prompts — every session starts/ends through it), `HANDOFF.md` (between-session baton), `AGENT.md`, `BRAIN.md`, `CODE-RECON.md`, `EXECUTION-MOMENTUM.md`, `ROADMAP.md`, `DEPLOY-PYTHONANYWHERE.md`.
