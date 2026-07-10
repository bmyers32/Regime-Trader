# ROADMAP.md — Regime Trading System
Future work + ideas outside current phase scope. Phase status lives in CLAUDE.md.

## Deferred (known, intentionally outside Phases 1–11)
- **Historical bid/ask candles** — Phase 4 backtester costs spread via session-bucketed
  config values (instruments.yaml cost_model, seeded from scripts/sample_spreads.py
  live-sampling) rather than historical bid/ask series, since Phase 2's CandleFetcher
  only pulls mid-price ("M") candles. Only worth the added fetch/cache/storage scope
  (roughly doubling per-pair data volume) if Phase 11's forward-vs-backtest divergence
  report specifically implicates cost modeling as the gap — not a default upgrade.
- **Wednesday triple-charge rollover** — OANDA triples financing on Wednesdays to cover
  weekend rollover (T+2 settlement). scripts/fetch_financing_rates.py emits a uniform
  annual_rate/365 daily figure and bot.backtest.costs.rollover_crossings() counts
  calendar-day boundaries uniformly — Wednesday's 3x multiplier is not modeled. Revisit
  together with the bid/ask item above if Phase 11 divergence implicates rollover cost
  specifically; low priority alone (small $ impact vs spread/slippage for short-hold
  playbooks; larger for trend_pullback's multi-day trail-to-exit holds — watch that one).
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
**Status: gates 3/4/6 DELIVERED 2026-07-07** (Track 2, HANDOFF.md) —
`bot/backtest/{param_sweep,walk_forward,stability,monte_carlo,gate_report}.py`,
validated on synthetic data via `tests/test_validation_defendants.py`'s four
known-guilt scenarios. Gate 5 (per-regime attribution) intentionally NOT built —
deferred to Session B reporting per HANDOFF.md. Real per-pair runs still need
Track 1's cost_model (spread/slippage calibration) before a §5 verdict can be
reported; the harness itself has no dependency on that data landing. Remaining
scope for "done": wire a CLI entrypoint (one command: pull real pair data → run
`run_walk_forward`/`run_stability_sweep`/`run_monte_carlo` → `build_gate_report` →
`render_text`/persist) once real data exists — the pieces exist, only the wiring
doesn't yet.
**Idea:** One CLI command running the full §5 chain (backtest → WFO → stability sweep → per-regime attribution) emitting a single validation-report artifact the Phase 11 gate consumes.
**Reasoning:** Gates are only as strong as their friction is low; one-command revalidation actually gets run after every tweak.
**Why deferred:** Needs Phases 4–5. Build immediately after — before playbooks 2–3 so they're validated with it from birth.

### Partial-close representation in the live Order/Trade journal
**Idea:** bot/backtest/engine.py's exit_cfg now models trend_pullback's "partial at 1R,
trail remainder" as one entry producing two priced legs (BacktestTrade.partial_exit_*
fields alongside the terminal exit) while staying one row per entry. Phase 8's live
executor will submit a REAL OANDA partial-close order for the first leg and a second
close for the remainder — the current Order/Trade journal schema (bot/journal/models.py)
assumes one Order -> one Trade -> one open/close pair.
**Reasoning:** Prime Directive 7 requires backtest and live to share the same strategy
code path; if Phase 8 doesn't also model two closes per entry, backtest-vs-live parity
breaks exactly in the dimension Phase 11's forward-test divergence report measures.
**Design questions:** A second Trade row linked to the same Order (partial_of_trade_id
FK)? Or extend Trade with its own partial_exit_* columns mirroring BacktestTrade's?
Does SignalLog/Order need a "partial" status distinct from "filled"?
**Why deferred:** Needs Phase 8's execution/journal design session — surfaced here
during Phase 5 (HANDOFF.md 2026-07-06 Session A, Decision 1e) so it isn't rediscovered
cold when Phase 8 starts.

### trend_pullback H1 post-mortem (CLOSED 2026-07-09 — do not revive with a parameter change)
**Verdict:** FAILED TRADING-RULES §5 gates 3/4/6 on both tested pairs (EUR_USD,
USD_JPY), TWICE — once on the as-shipped code (which had an undetected law drift:
3 of 4 §3.1 score components were wired as hard vetoes, reintroducing the §1.1
AND-stack anti-pattern), and again after that drift was fixed and the corrected,
spec-compliant structure was evaluated on its own real merits (entry_threshold/
score_weights searched inside the walk-forward per window, real >=2yr H1/H4 OANDA
data, real cost_model). Trade count roughly doubled post-fix (61->127 EUR_USD,
48->115 USD_JPY) but net_pnl got WORSE, not better — the AND-stack was genuinely
suppressing volume as hypothesized, and the larger, honestly-scored sample still
shows no edge net of costs.
**Reasoning it's closed, not iterated:** gate 4 found no profitable parameter
neighborhood in either pair post-fix (base_metric negative across all 24 stability
perturbations, both pairs); gate 6's bootstrap found the negative result robust,
not a resampling artifact (P(net_pnl<=0) 86.8%-100% across all four pair/structure
combinations run this session). This is a decisive structural failure, not a
marginal or cost-sensitive one.
**Re-entry condition:** any future revival MUST propose a DIFFERENT edge thesis —
new trigger/zone definitions, a different regime-routing dependency, a different
exit model, etc. — not a parameter change on the existing §3.1 spec (entry_threshold/
score_weights/sl_atr_mult retuning was already effectively explored via this
session's per-window grid search and did not help). Enters via PROMPTS.md §5.7
(hypothesis stated up front, blast radius, implementation, re-validation) like any
other strategy change.
**Untested pairs:** GBP_USD, AUD_USD, EUR_GBP, GBP_JPY were never run under this
spec (see HANDOFF.md's 2026-07-09 disposition for why, incl. a correction to the
initial cost-ranking rationale — AUD_USD/EUR_GBP are actually cheaper than the two
tested pairs, not more expensive; the skip rests on the FAIL's decisiveness, not on
their cost economics). Revisit only alongside a redefined playbook, not standalone.
**Gross-vs-net failure-mode classification (Phase 6 close-out exhibit, 2026-07-10,
scripts/gross_vs_net.py — re-costs the SAME already-selected per-window params at
cost_cfg=ZERO_COST_MODEL, no re-optimization):** EUR_USD gross=-654.11 (128 trades)
vs. net=-1437.53 — **no-edge** (gross<=0: the strategy has no edge even before any
cost is applied). USD_JPY gross=-631.78 (117 trades) vs. net=-700.08 — **no-edge**
as well. Costs roughly double the loss in both cases but are not the reason either
pair failed; the underlying signal itself has no edge. Contrast with range_reversion
EUR_GBP below, which IS cost-dominated — this distinguishes "the edge thesis is
wrong" from "the edge thesis is right but too expensive to trade," a distinction
squeeze_breakout's kickoff should read before assuming either failure mode.
**Where the detail lives:** full gate numbers, veto breakdown, funnel diagnostics,
and the law-drift audit are archived in the "Phase 5 complete" commit message
(2026-07-09) — `git log --grep "Phase 5 complete"` — not reproduced here.

### range_reversion H1 post-mortem (CLOSED 2026-07-10 — do not revive with a parameter change)
**Verdict:** FAILED TRADING-RULES §5 gates 3/4/6 on both target pairs (EUR_USD,
EUR_GBP), decisively. EUR_USD: 40 stitched OOS trades, net_pnl=-354.20. EUR_GBP: 64
trades, net_pnl=-163.13. Both pairs' gate 4 stability sweep found the
REPRESENTATIVE config's base_metric already negative over the full history (no
profitable peak to even test stability of) — the same "no profitable neighborhood"
signature trend_pullback's post-mortem found. Gate 6 bootstrap: P(net_pnl<=0) =
86.2% (EUR_USD), 72.5% (EUR_GBP).
**AND/OR/asymmetric finding (disposition 1):** the entry_threshold/score_weights
walk-forward search did NOT consistently select §3.2's literal AND (conjunctive)
region. EUR_USD: 6/10 windows AND, 2/10 OR, 2/10 asymmetric. EUR_GBP: 2/10 AND,
2/10 OR, 6/10 ASYMMETRIC (majority). For EUR_GBP specifically, the walk-forward's
own IS selection MORE OFTEN preferred a single component firing alone over
requiring both — overruling §3.2's conjunctive letter more often than honoring it.
Recorded per disposition 1's explicit requirement, not silently absorbed into "the
search found a good threshold."
**Expansion-veto pass-rate (disposition 4):** cleared for both pairs — EUR_USD
10.9%, EUR_GBP 8.9% fire-rate among consulted bars, both comfortably inside the
1%-95% band. No recalibration triggered; the LTF-reused regime_params thresholds
were valid for both pairs.

**Per-session attribution (Phase 6 close-out exhibit, 2026-07-10,
scripts/gross_vs_net.py — the kickoff's explicit empirical question, "Asian-session
behavior is per-pair calibration, not assumption," answered by measurement instead
of a coded-in preference). Decision rule pre-registered before seeing the data:
roughly uniform losses across sessions -> FAIL fully closed as recorded; losses
materially concentrated in Asian entries -> one follow-up run per pair with
London/NY-only entry, as the completion of the pre-registered experiment (§3.2's
own preference clause), not a parameter retune.**
- EUR_USD: asian n=10 net_pnl=-434.33 win_rate=0.100; london n=11 net_pnl=-6.50
  win_rate=0.636; ny_overlap n=19 net_pnl=+86.63 win_rate=0.579. Non-Asian
  (london+ny_overlap) combined net_pnl=+80.13 — POSITIVE — against an Asian-only
  net_pnl of -434.33, out of an overall net_pnl=-354.20. This MEETS the
  pre-registered trigger: losses are materially concentrated in the Asian session.
- EUR_GBP: asian n=7 net_pnl=-25.05 win_rate=0.571; london n=21 net_pnl=+347.61
  win_rate=0.857; ny_overlap n=36 net_pnl=-485.68 win_rate=0.556. The loss is
  concentrated in ny_overlap, NOT Asian (Asian's own contribution is a small
  -25.05 against London's large +347.61 and ny_overlap's large -485.68). This does
  NOT meet the pre-registered trigger — the trigger was specifically about Asian
  concentration (§3.2's own preference clause is London/NY vs. Asian, not a general
  best-session filter) — so EUR_GBP gets no follow-up; its FAIL stays closed exactly
  as originally recorded above.

**Session follow-up, EUR_USD only, as pre-registered (2026-07-10,
scripts/session_followup_eurusd.py — reuses the EXISTING entry_blackout_hours_utc
mechanism, bot.backtest.costs.entry_blackout_ok, to exclude all Asian UTC hours for
this run only; instruments.yaml's cost_model on disk is untouched; no strategy code
or entry_threshold/score_weights/sl_atr_mult changed):** gate 3 walk-forward FLIPS
to PASS — 76 stitched OOS trades, net_pnl=+82.34. But gate 4 (representative
config's base_metric=-34.12, no profitable peak) and gate 6 (bootstrap
P(net_pnl<=0)=42.3%, far above the 5% robustness bar — the positive result is not
statistically distinguishable from noise) both still FAIL. **OVERALL VERDICT
UNCHANGED: FAIL.** The follow-up completed the pre-registered experiment honestly
and is genuinely informative (excluding Asian entries measurably helps, both in
direction and magnitude) but does not rescue the pair — a walk-forward PASS without
a stable parameter neighborhood or a bootstrap-robust result is exactly the
"positive result indistinguishable from noise" case gates 4/6 exist to catch. Also
notable: even in this follow-up, AND-region windows were a minority (2/10 AND,
3/10 OR, 5/10 asymmetric) — §3.2's conjunctive letter was overruled even more often
here than in the original run.

**Gross-vs-net failure-mode classification (same close-out exhibit,
scripts/gross_vs_net.py, original accepted runs before the session follow-up):**
EUR_USD gross=-352.08 (43 trades) vs. net=-354.20 — **no-edge** (gross<=0; costs
contributed almost nothing to this pair's loss, the "no edge" is overwhelming and
cost-independent). EUR_GBP gross=+340.09 (65 trades) vs. net=-163.13 — **COST-
DOMINATED** (gross>0, net<0): a genuine pre-cost edge existed and spread/slippage/
rollover erased it entirely, a >500-unit swing from costs alone. This is the one
cost-dominated result found across both playbooks so far (contrast trend_pullback's
post-mortem above, both no-edge) — worth flagging for squeeze_breakout's kickoff,
whose larger-target thesis is explicitly the cost-tolerant design.

**Reasoning it's closed, not iterated:** decisive on both target pairs, same
standard as trend_pullback's post-mortem (gate 4's base_metric negative BEFORE any
perturbation is the strongest possible stability-sweep signal — there is no peak to
be near). Trade counts are thin in absolute terms (40, 64) but both clear gate 3's
min_trade_count=20 floor, so this isn't a "too few trades to judge" case — a real,
if modest, sample showing no edge net of costs. The pre-registered session
follow-up (above) was run for EUR_USD and did not change this: gate 3 alone passing
is not a verdict.
**Untested pairs:** AUD_USD, GBP_USD, USD_JPY, GBP_JPY never run under this spec —
per the kickoff instruction ("others follow only on evidence") and the same
discipline as trend_pullback's post-mortem: EUR_USD/EUR_GBP's FAIL was decisive
enough that running more pairs against the identical spec is not expected to be
informative. Revisit only alongside a redefined playbook (different entry-condition
mapping, different exit model), not a parameter change.
**Re-entry condition:** any future revival MUST propose a DIFFERENT edge thesis, not
a parameter change on the existing §3.2 spec (entry_threshold/score_weights
retuning was already explored via the per-window grid search and did not help —
gate 4's stability sweep additionally shows no nearby profitable neighborhood).
Enters via PROMPTS.md §5.7.
**Where the detail lives:** full gate numbers, funnel/veto breakdown, and per-pair
expansion-veto pass-rates are archived in the "Phase 6 complete" commit message
(not reproduced here) and in bot/config/instruments.yaml's per-pair
range_reversion_calibration notes.

### Compression-within-trend signal flag
**Idea:** When TRENDING regime fires and BB width is simultaneously below its rolling percentile, pass a `compression_flag=True` into the SignalLog indicator_snapshot. The trend_pullback strategy can optionally tighten its score threshold when the flag is set, favouring only the highest-confidence pullback entries.
**Reasoning:** During Phase 3, the classifier priority debate revealed that TRENDING and COMPRESSION can be simultaneously true — the classifier resolves the conflict by picking TRENDING, but the compression state carries information. A pullback within a compressed trend tends to resolve sharply in the trend direction, making it a potentially tighter entry.
**Design questions:** Flag belongs in indicator_snapshot (no schema change) or as a dedicated SignalLog column? Does tighter score threshold need its own walk-forward arm, or does it fall out of the existing one? What is the Phase 4 hit rate of simultaneous TRENDING + sub-P20 BB?
**Why deferred:** No strategy code until Phase 5. Phase 4 pass-rates will first reveal how often the overlap occurs per pair; if rare (<5% of TRENDING bars), the signal adds noise not signal.
