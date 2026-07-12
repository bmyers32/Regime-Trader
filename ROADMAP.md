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

## Next session: Pivot cycle — census + hearings-budget (drafted, not executed)
Drafted 2026-07-12 (external review conversation) — not yet in TRADING-RULES.md, not
executed; this is the plan the next session runs. Surfaced by squeeze_breakout's §2
post-mortem (archive/POST-MORTEMS.md §5): COMPRESSION resolves to confirmed EXPANSION
only ~2-4% of the time but to TRENDING/RANGING ~60%+ — "trend inception from
compression" is an untested, distinct entry population from either dead thesis.

**Deliverable 1 — Law (add to TRADING-RULES §6, dated, when this session runs):**
> Pivot-cycle hearings budget: THREE full §5 hearings for the current data window.
> Slots 1–2 pre-claimed on external-evidence grounds: D1/H4 time-series momentum;
> carry-with-regime-conditioning. Slot 3 awarded only by census evidence, to at most
> ONE candidate; all others recorded and closed. The cap governs hearings, not
> winners: every hearing that passes gates proceeds to §5 sign-off and ships —
> multiple passes all ship, routing per §2. The Phase 11 forward test (≥60 days,
> unseen data) is the final arbiter for every pass. Exhausting the budget without any
> pass ends strategy search on this window. Renews only when the data window
> materially renews (≥12 months of new candles).

**Deliverable 2 — Moments census, measurement only** (no strategies, no parameters, no
gates, cached data only), all six pairs, per closed-list candidate: (a) population
count over the full window; (b) event study — forward returns at +4/+8/+24 LTF bars
vs. matched random same-regime baseline; (c) cost context — median session spread at
event hour vs. forward-move magnitude.

**Candidates (closed list):** (i) COMPRESSION→TRENDING confirmed transitions ("trend
inception," surfaced by §5's post-mortem); (ii) TRENDING→RANGING→TRENDING
resumptions; (iii) EXPANSION→RANGING aftermath; (iv) London-open after a defined
Asian range; (v) failed-breakout re-entry into the compression box; (vi) TRENDING
death (ADX rollover <20); (vii) Monday open gaps; (viii) month-end final two
sessions.

**Award rule (pre-registered):** slot 3 goes to the single candidate whose
event-study distribution is most distinguishable from baseline AND whose cost ratio
clears 4:1 at realistic horizons — only if at least one clears both; none do → slot 3
forfeited, budget is two. Borderline forfeits; ties go to fewer hearings.
Momentum/carry are already in (external evidence), not competing for a slot — the
census counts and measures, it doesn't rank on narrative appeal. See BRAIN.md
"Decide which diagnostic wins before either diagnostic exists" and "A tripped
guardrail is a demand for evidence, not a verdict."
