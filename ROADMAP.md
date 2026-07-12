# ROADMAP.md — Regime Trading System
Future work + ideas outside current phase scope. Phase status lives in CLAUDE.md.
Closed verdicts: two lines here (verdict + pointer), full text in archive/.

## Deferred (known, intentionally outside Phases 1–11)
- **Historical bid/ask candles** — costs spread via session-bucketed config values
  (instruments.yaml cost_model) rather than historical bid/ask series, since Phase 2's
  CandleFetcher only pulls mid-price candles. Only worth the added fetch/cache/storage
  scope if Phase 11's forward-vs-backtest divergence implicates cost modeling.
- **Wednesday triple-charge rollover** — OANDA triples financing Wednesdays (T+2);
  scripts/fetch_financing_rates.py models a uniform daily rate instead. Revisit with
  the bid/ask item if Phase 11 divergence implicates rollover; low priority alone.
- **Cross-pair correlation-aware sizing** — v1 uses per-currency exposure caps
  (TRADING-RULES §4.2): blunt but safe. A correlation matrix needs real multi-pair
  trade history first.
- **Postgres migration** — SQLite+WAL suffices for one writer + one reader; revisit
  only if concurrency or PA disk I/O becomes a measured problem.
- **Live economic-calendar API** — Phase 8 ships blackout windows from a manually
  maintained weekly config table; §4.6 defines behavior when calendar data is absent.

## Feature Proposals
(Idea Processing Protocol appends here. Format per entry: Idea / Reasoning / Design questions / Why deferred.)

### Telegram/email alerting
Push on breaker trip, rejection streak, heartbeat gap >N min, daily PnL summary —
closes the loop for an unattended system (dashboard is pull-based). Channel TBD
(Telegram bot vs SMTP); sender likely a watchdog task reading heartbeats (survives
bot death, unlike a bot-internal sender). Needs journal+heartbeat schema stable;
fits right after Phase 10.

### Signal replay viewer
Click a SignalLog row → render candle window + indicator_snapshot overlay: exactly
what the strategy saw. Turns "why did/didn't it trade" from CSV archaeology into a
glance (Chart.js on existing stack, snapshot JSON already captured). Needs Phases
2+9; purely additive, no schema change.

### Walk-forward automation harness
Gates 3/4/6 DELIVERED 2026-07-07 (commit f57a032):
`bot/backtest/{param_sweep,walk_forward,stability,monte_carlo,gate_report}.py`,
validated against `tests/test_validation_defendants.py`'s four known-guilt
scenarios. Gate 5 (per-regime attribution) not built. Remaining scope: one CLI
entrypoint wiring pull-data → run gates → `build_gate_report` → persist — pieces
exist, only the wiring doesn't. Needs Phases 4-5; build before playbooks 2-3 so
they're validated with it from birth.

### Partial-close representation in the live Order/Trade journal
bot/backtest/engine.py already models trend_pullback's "partial at 1R, trail
remainder" as two priced legs in one BacktestTrade row. Phase 8's live executor
will submit two real OANDA closes per entry — the current Order/Trade schema
(bot/journal/models.py) assumes one Order→one Trade→one open/close pair. Prime
Directive 7 requires backtest/live parity here, or Phase 11's divergence report
breaks on exactly this dimension. Open question: second Trade row
(partial_of_trade_id FK) vs. extending Trade with its own partial_exit_* columns.
Needs Phase 8's execution/journal design session.

### Compression-within-trend signal flag
When TRENDING fires and BB width is simultaneously sub-percentile, pass
`compression_flag=True` into indicator_snapshot; trend_pullback could optionally
tighten its score threshold when set. Surfaced by Phase 3's classifier-priority
debate (TRENDING/COMPRESSION can be simultaneously true; classifier picks TRENDING
but the compression state carries information). Needs Phase 4 pass-rate data first
— if the overlap is rare (<5% of TRENDING bars) the signal adds noise, not edge.

## Closed Dispositions (pointer only — full text + numbers in archive/POST-MORTEMS.md)

**trend_pullback H1 (CLOSED 2026-07-09):** FAIL §5 gates 3/4/6, EUR_USD/USD_JPY —
no-edge gross even after fixing an AND-stack law drift; needs a new edge thesis.
→ archive/POST-MORTEMS.md §1, commit aa2b57d.

**range_reversion H1 (CLOSED 2026-07-10):** FAIL §5 gates 3/4/6, EUR_USD/EUR_GBP —
EUR_GBP cost-dominated, EUR_USD no-edge; Asian-session follow-up flipped gate 3 only.
→ archive/POST-MORTEMS.md §2, commit 0cb3633.

**squeeze_breakout false-break confirmation:** NOT licensed — false-break split was
real but hysteresis-excluded diagnostic showed it's a §2 routing artifact; record only.
→ archive/POST-MORTEMS.md §3, commit ded3b2b.

**squeeze_breakout H1 (CLOSED 2026-07-11):** FAIL §5 gates 3/4/6, GBP_USD/USD_JPY —
sharp non-robust peaks; hysteresis-excluded finding routed the fix to §2, not the
trigger or revival budget. → archive/POST-MORTEMS.md §4, commit ded3b2b.

**squeeze_breakout §2 consultation-window experiment (CLOSED 2026-07-12):** FAIL,
bit-for-bit identical to Phase 7 — eligible population vanishingly rare (16/8 bars)
and signal-free; permanently closes squeeze_breakout and this §2 question.
→ archive/POST-MORTEMS.md §5, commits bde494e (FAIL) / fd70f4c (revert).

**All three playbooks now FAILED and closed, zero TRADING-RULES §6 revival budget
spent** — Phase 8 (risk/execution layer) has no playbook cleared to forward-test.

**Pivot-cycle census + hearings-budget (EXECUTED 2026-07-12):** Law live in
TRADING-RULES.md §6 — three-hearing budget, slots 1–2 pre-claimed (momentum,
carry-with-regime-conditioning), slot 3 by census evidence only. **Slot 3 AWARDED
to (v) failed-breakout re-entry into compression box, hearing to be specified as
SECOND-ATTEMPT CONTINUATION in the original breakout direction** — the census
signing tested a fade hypothesis and refuted it (CI negative under fade-sign at
all 3 horizons); (iii) EXPANSION→RANGING and (iv) London-open after Asian range
also cleared both bars but are recorded and closed, not awarded (cap = one
winner), lawfully re-census-eligible once the data window renews (≥12mo).
→ archive/CENSUS-PIVOT-CYCLE.md.

**D1/H4 time-series momentum (CLOSED 2026-07-12, §6 slot 1 of 3 SPENT):** FAIL §5
gates 3/4/6, EUR_USD/GBP_JPY, decisively — NOT a floor-miss (109/105 stitched OOS
trades, well clear of the 20-trade floor). Gross-vs-net split across failure modes
(EUR_USD no-edge, GBP_JPY cost-dominated); gate 4 independently flags N itself as
the sharpest, sign-flipping stability dimension in both pairs, at whichever N each
pair actually used — not confined to N=120's known warmup handicap. Pre-registered
A3/A7 sign-flip diagnostic found a genuine null result on signal-flip exit as a
revival mechanism (the split is balanced, not flip-dominated) — this FAIL does not
hand a future revival attempt an obvious target. Scoped to short-horizon momentum
(effective N∈{20,60}); the literature's ~12-month lookback was never tested
(untestable on this data window) — TRADING-RULES §6's renewal clause (≥12mo new
candles) is the lawful path later, not a re-try now.
→ archive/POST-MORTEMS.md §6.
