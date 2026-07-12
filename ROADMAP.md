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

### squeeze_breakout optional false-break confirmation (retest / next-candle-holds entry)
**STATUS UPDATE (2026-07-11, Phase 7 close-out): NOT licensed by squeeze_breakout's own
FAIL.** The pre-registered false-break split DID find 100% of losses were false-break-
type on both target pairs — the surface-level trigger condition for this entry — but the
ALSO-pre-registered hysteresis-excluded diagnostic found the false-break signature is
better explained by the regime-routing gate excluding valid trigger-clearing bars near a
COMPRESSION exit, not by a missing confirmation step. Per that decision rule (stated
before the data existed specifically to prevent this scenario), this mechanism is NOT
the next move. See the squeeze_breakout H1 post-mortem below for the full reasoning.
Retained for the record, but no longer an open candidate absent a change to the
regime-routing finding itself.
**Idea:** §3.3's optional clause: "next candle holds beyond level, or enter on retest" —
either require the LTF trigger bar's breakout level to still hold on the FOLLOWING closed
candle before entering, or wait for price to pull back and retest the broken level as a
limit-style entry, instead of entering unconditionally at the next bar's open the moment
the trigger fires.
**Reasoning:** squeeze_breakout's own named failure mode is false breaks (stopped out
before the expansion materializes). This clause is the law's own pre-registered lever for
exactly that failure mode — but only for it. Building it now would require genuinely new
engine machinery (bot/backtest/engine.py's BacktestEngine currently fills every fired
Signal unconditionally at the very next bar's open, for every strategy — no
retest-limit or N-bar-confirmation entry model exists yet) and, more importantly, would
collapse Phase 7's own pre-registered diagnostic split (false-break losses vs.
expansion-materialized-but-insufficient losses, see HANDOFF.md/the Phase 7 plan doc)
before the evidence exists to justify spending effort on it.
**Design questions:** Retest-limit (wait for price to return to the broken level, enter
there) vs. next-candle-holds (require one more closed candle beyond the level before
entering at ITS close/next open) — these have different engine implications (a limit
order that may never fill vs. a delayed but still-market entry). Does this apply
symmetrically to the SL/compression-box math, or does a retest entry warrant a tighter
SL (price is now closer to the level)? Does the deferred exit_cfg partial/trail math
need to shift its reference point (entry_px) accordingly?
**Why deferred:** THIS IS SQUEEZE_BREAKOUT'S PRE-REGISTERED REVIVAL-BUDGET CANDIDATE
(TRADING-RULES §6, "a genuinely new edge-thesis mechanism — a different entry-timing
model, not a parameter retune"). Contingent, not automatic: only licensed if squeeze_
breakout's own Phase 7 post-mortem attributes a FAIL primarily to false-break losses
(case (a) in the pre-registered split), not to expansion-materialized-but-insufficient
losses (case (b), which this mechanism cannot fix) or to the separately-tracked
hysteresis-excluded finding (which routes to §2 regime-routing territory instead, per
the same pre-registered decision rule). See ROADMAP's squeeze_breakout post-mortem
(once written) for the actual attribution before spending this budget.

### squeeze_breakout H1 post-mortem (CLOSED 2026-07-11 — do not revive with a parameter change; revival-budget lever explicitly NOT licensed by this result, see below)
**Verdict:** FAILED TRADING-RULES §5 gates 3/4/6 on both target pairs (GBP_USD, USD_JPY),
decisively. GBP_USD: 53 stitched OOS trades, net_pnl=-691.75, gate 4 sharp-peak
(entry_threshold +10% deviates 93.1% from base_metric=56.68), gate 6 bootstrap
P(net_pnl<=0)=96.8%. USD_JPY: 50 trades, net_pnl=-113.13, gate 4 sharp-peak
(atr_expansion_mean_mult -10% deviates 88.6% from base_metric=301.09), gate 6 bootstrap
P(net_pnl<=0)=61.9%. Both pairs' base_metric was positive pre-perturbation (unlike
trend_pullback/range_reversion's post-mortems) — the FAIL here is a stability/overfit
failure (a sharp, non-robust peak), not the "no profitable neighborhood at all" signature
the other two playbooks showed.

**Trigger-region breakdown (DISPOSITION 2, classify_threshold_regime_general):** windows
mostly landed in genuine N-of-4 territory (a specific 3-of-4 or other partial subset,
not a clean OR or full-AND), with 4/10 GBP_USD windows and 3/10 USD_JPY windows landing on
the provisional default's own "3 real triggers, tick_volume excluded from the minimal
subset" reading — see instruments.yaml's per-pair calibration_note for the full per-window
list. Compression-regime pass-rate (§1.7 note): 29.3% of H4 bars (GBP_USD), 29.9%
(USD_JPY) — comfortably non-degenerate (nowhere near the <1%/>95% always-true-filter
failure mode), so the precondition itself is not implicated.

**HYSTERESIS-EXCLUDED FINDING (approved addition 1, the decisive diagnostic this
post-mortem turns on):** GBP_USD: 52 hysteresis-excluded evaluations vs. 53 fired
(~98%) — for essentially every trade that fired, another LTF bar existed within 8 bars
of leaving COMPRESSION where the SAME frozen per-window params would have cleared
threshold had the regime gate not excluded it. USD_JPY: 35 vs. 50 fired (70%) — same
shape, less extreme. **Per the PRE-REGISTERED decision rule (HANDOFF.md / Phase 7 plan
doc, stated before any data was seen): this routes the finding to §2 regime-routing
territory — NOT the trigger, NOT the revival budget, NOT an M15 comparison — and that
rule is honored here even though the (a)/(b) split below would, taken alone, suggest
the opposite conclusion.**

**False-break split + R-distribution non-degeneracy check (pre-registered protocol,
scripts/gross_vs_net.py EXHIBIT 3):** R-multiple distribution shows genuine spread, not
a degenerate single cluster — GBP_USD min=-1.061/median=-1.025/p75=+0.815/max=+2.760;
USD_JPY min=-1.147/median=+0.199/p75=+0.893/max=+1.310 — so the split below is treated as
informative. Result: **100% of losing trades in BOTH pairs are case (a), false-break**
(GBP_USD: 33/33 losers, pnl=-1736.63; USD_JPY: 24/24 losers, pnl=-1260.79) — case (b),
expansion-materialized-but-insufficient, is EMPTY in both pairs (0 trades). Taken in
isolation, this is exactly the signature ROADMAP's "squeeze_breakout optional false-break
confirmation" entry names as the revival-budget candidate's trigger condition. **It is
NOT being treated as licensing that revival here** — the pre-registered hysteresis-
excluded decision rule above takes precedence by design (stated before this data existed,
specifically to prevent this exact convenient-post-hoc-reasoning trap): a false-break-
dominated result caused primarily by the regime gate excluding valid trigger-clearing
bars near a COMPRESSION exit is a §2 regime-routing problem wearing a false-break
costume, not genuine evidence that a next-candle-holds/retest filter would have saved
these specific trades.

**STRUCTURAL SYNTHESIS (post-verdict analysis, 2026-07-11): the two diagnostics are not
two competing explanations — they are two views of ONE structural fact.** The
COMPRESSION-only regime gate (DISPOSITION 1) means squeeze_breakout can only ever open a
trade on a bar still formally labeled COMPRESSION. The instant the HTF classifier
confirms EXPANSION (2 consecutive HTF closes, §2's hysteresis law), the gate closes to
new entries — regardless of whether the trigger conditions are still clearing on the
LTF. This has one unavoidable consequence: every trade this playbook is STRUCTURALLY
ABLE to take is taken at the LEAST-confirmed possible moment of a breakout attempt — the
first bar(s) the trigger fires, before the move has had any chance to prove it isn't
reverting. The hysteresis-excluded count is literally counting the bars where the SAME
breakout, a few bars further along and having survived without reverting (i.e. more
confirmed), would ALSO have cleared the trigger — those are exactly the bars the gate
throws away. The false-break split is what happens on the bars the gate lets through
instead: entries confined to the least-confirmed edge of each attempt are, definitionally,
the entries most likely to be false breaks. **The routing question (§2) and the
false-break diagnosis are not alternative culprits; they converge on the same directional
fix — the playbook needs to be allowed to enter LATER, not to filter its earliest entries
more aggressively.** This is also why the false-break confirmation filter (ROADMAP entry
above, next-candle-holds/retest) was correctly not licensed: that mechanism would make
the earliest-only entries pickier without ever reaching the more-confirmed bars currently
excluded by construction — treating a symptom of the gate's timing, not the gate's timing
itself. The pre-registered decision rule was written before this connection was
understood — it named the correct structural culprit anyway, by design, before either
number existed to tempt a different conclusion.

**Gross-vs-net classification (STANDARD EXHIBIT — carries more weight than in either
prior phase, see why below):** GBP_USD gross=-447.86 (54 trades) vs. net=-691.75 —
**no-edge** (gross<=0). USD_JPY gross=+0.35 (51 trades) vs. net=-113.13 — mechanically
gross>0 so the classifier's own rule labels it COST-DOMINATED, but $0.35 gross across 51
trades over a 766-day, ~13,000-H1-bar history is not a real edge by any practical
standard — **treat this as an ESSENTIALLY-ZERO-EDGE case, not a genuine cost-dominated
finding like range_reversion/EUR_GBP's +340.09.** Both pairs are therefore consistent
with "the signal itself has nothing," continuing the 5-of-6-runs no-edge pattern (only
range_reversion/EUR_GBP was a real cost-dominated result) started in Phases 5-6 — see
HANDOFF.md's Phase 7 kickoff framing.
**Why this classification matters more here than in trend_pullback/range_reversion's
post-mortems:** both prior playbooks' gate 4 base_metric was already negative
pre-perturbation — a full-history backtest at the representative config couldn't clear
breakeven even before costs were the question, so "no edge" was close to foregone. Here
gate 4's base_metric was POSITIVE pre-perturbation on both pairs (+56.68 GBP_USD,
+301.09 USD_JPY) — a real, if fragile, profitable peak existed somewhere in the full
history under ONE specific parameter setting. Gross-vs-net answers the question that
positive number leaves open: does that peak's profitability show up in the ACTUAL
rolling-OOS trades the walk-forward's own per-window parameter selection produced, before
costs? It does not — gross is deeply negative (GBP_USD) or indistinguishable from zero
(USD_JPY). This means gate 4's positive base_metric and the gross-vs-net finding are
CONSISTENT, not in tension: the full-history representative-config peak was itself a
hindsight-selected artifact (exactly what gate 4's own instability finding already
diagnosed) that never manifested as a genuine pre-cost edge in the trades actually fired
across rolling out-of-sample windows. Costs are not, and were never going to be, the
story for either pair.

**Per-session attribution (informational only — no pre-registered follow-up trigger was
defined for squeeze_breakout this phase, unlike range_reversion's Asian-session
question; NOT acted on):** GBP_USD losses concentrated in london (-387.24, 15 trades,
win_rate 0.267) and ny_overlap (-326.60, 31 trades, win_rate 0.387), asian slightly
positive (+22.09, 7 trades). USD_JPY losses concentrated in london (-158.95, 11 trades),
ny_overlap and asian both mildly positive. No follow-up run for either pair.

**Reasoning it's closed, not iterated:** decisive stability failure (sharp, non-robust
peaks) on both target pairs plus a large, pre-registered-decisive hysteresis-excluded
finding that specifically forecloses the most tempting revival path (the confirmation
filter) for this data window. Trade counts (53, 50) clear gate 3's min_trade_count=20
floor.
**Untested pairs:** EUR_USD, EUR_GBP, AUD_USD, GBP_JPY never run under this spec — same
"others follow only on evidence" discipline as Phases 5-6; both target pairs' FAILs were
decisive enough that running more pairs against the identical spec is not expected to be
informative.
**Re-entry condition (DECIDED 2026-07-11, EXECUTED 2026-07-11/12, VERDICT: FAIL,
CLOSED PERMANENTLY): the §2 consultation-window experiment.** NOT the deferred
false-break confirmation filter (foreclosed by the structural synthesis above) and NOT
a TRADING-RULES §6 revival attempt at all — a regime-routing LAW question, not an
edge-thesis retune, so it drew on no revival budget in either direction, and none was
spent. Full spec, execution, reconciliation, and the corrected epitaph: see the
"squeeze_breakout §2 consultation-window experiment" entry below (now marked CLOSED
with its full POST-MORTEM). Both target pairs FAILED gates 3/4/6 bit-for-bit identically
to this post-mortem's own numbers above — the amendment produced zero incremental
trades in either pair. squeeze_breakout and this specific §2 question are both now
closed permanently, per the pre-registered rule.
**Where the detail lives:** full gate numbers, per-window trigger-region breakdown, and
the hysteresis-excluded diagnostic are archived in the "Phase 7 complete" commit message
and in bot/config/instruments.yaml's GBP_USD/USD_JPY squeeze_breakout_calibration notes.

**PHASE 7 CLOSES ALL THREE PLAYBOOKS WITH ZERO REVIVAL BUDGET SPENT** (trend_pullback,
range_reversion, squeeze_breakout all FAILED and closed; TRADING-RULES §6's revival
budget remains fully unspent across all three). This is the state HANDOFF.md's Phase 7
kickoff flagged as materially different from "one closed, two untested" — it is now the
actual outcome. See HANDOFF.md's close-out for what this implies for the system's next
move (Phase 8 risk/execution layer has no playbook cleared to trade; the practice
forward-test in Phase 8's own exit criteria has nothing validated to forward-test yet).

### squeeze_breakout §2 consultation-window experiment (CLOSED 2026-07-11 — FAIL, permanently, both target pairs; do not revisit this specific mechanism)
**Idea:** Extend squeeze_breakout's consultation window N LTF bars past a confirmed
COMPRESSION→EXPANSION transition (only that specific transition — not general EXPANSION,
not a change to any other playbook's routing), where
`N = htf_ltf_ratio × regime_confirm_bars` — the SAME formula and value (8 LTF bars for
the default H4/H1 pairing) `compute_hysteresis_excluded` already used to measure the
problem, now proposed as the fix. This is the direct, minimal-arbitrary-choice
"enter later" mechanism the structural synthesis in the post-mortem above converges on.

**Draft law amendment (NOT yet written into TRADING-RULES.md — draft only, to be applied
at the start of the experiment session per its own Verification Gate, then either kept
[dated Change-Log entry, PASS] or reverted [FAIL, entry never added]):**
- §2 regime table, COMPRESSION row: append "— squeeze_breakout MAY additionally consult
  for N = htf_ltf_ratio × regime_confirm_bars LTF bars after confirming EXPANSION,
  IF that EXPANSION was entered directly from COMPRESSION (see §3.3). No other playbook's
  routing changes."
- §3.3, Precondition bullet: append "EXPERIMENTAL (dated, pending re-validation): the
  consultation window additionally includes the first N bars of an EXPANSION regime that
  was entered directly from COMPRESSION, N = htf_ltf_ratio × regime_confirm_bars — see
  §2 and the Change Log."
- §6 Change Log row (to be added ONLY if the experiment PASSES): date | §2/§3.3 |
  "squeeze_breakout's consultation window extended N=8 (H4/H1) LTF bars into a
  COMPRESSION-originated EXPANSION" | "GBP_USD/USD_JPY re-run under the amended gate
  passed TRADING-RULES §5 gates 3/4/6; the hysteresis-excluded diagnostic (Phase 7)
  showed the strict COMPRESSION-only gate was excluding the majority of would-fire,
  more-confirmed continuation bars."

**Required implementation (blast-radius question next session's Verification Gate must
resolve FIRST, before any strategy code changes):** `generate_signal()` only receives the
CURRENT bar's `RegimeResult` — it has no path to "what regime preceded this one," so the
amended gate needs that as a new, explicit field. Proposed: add
`prior_regime: RegimeState | None = None` to `RegimeResult` (bot/regime/classifier.py) —
default-valued, appended after the existing three fields, so every existing call site
that constructs `RegimeResult(...)` (tests across trend_pullback/range_reversion/
squeeze_breakout/regime/walk_forward/validation_defendants) keeps working unmodified.
`RegimeClassifier` already tracks `self._current_regime`/`self._bars_in_regime`
internally; add `self._prior_regime`, set it to the OLD `self._current_regime` at the
exact moment a switch is confirmed (mirroring how `bars_in_regime` resets to 1 there),
and report it on every `RegimeResult` until the next switch. This touches shared
classifier code used by ALL THREE playbooks + the eventual live loop — needs the SAME
"generalization proof" discipline this phase used for scripts/run_validation_gates.py
(re-run trend_pullback and range_reversion's own gate numbers after the change, confirm
byte-identical, before trusting squeeze_breakout's own re-run).
squeeze_breakout's own gate becomes: fire when `regime==COMPRESSION` OR
(`regime==EXPANSION AND prior_regime==COMPRESSION AND bars_in_regime<=N`).

**Design questions left open for next session:** does `prior_regime` need to survive
gray-zone (`_INDETERMINATE`) holds without being cleared? (current classify() logic
holds `self._current_regime` through gray zones without touching it — `prior_regime`
should follow the same hold-through-gray-zone convention, not reset.) Does the SL
(compression-box lookback) still make sense computed the same way N bars into EXPANSION,
or does the box need to freeze at the COMPRESSION-exit point rather than keep sliding?
Does exit_cfg's trail need any adjustment for entries that start later/closer to the move
already having partly happened?

**Pre-registered rule (restated from the post-mortem above):** re-run GBP_USD and
USD_JPY ONLY, same harness, same param grids, only the consultation gate changed. FAIL →
squeeze_breakout closes permanently AND this specific §2 question closes permanently
(not to be reopened later on a hunch) — no TRADING-RULES §6 revival budget consumed
either way, since this was never a revival attempt. PASS → proceeds to full TRADING-RULES
§5 sign-off (all gates, including the still-deferred gate 5 per-regime attribution)
before any enablement is considered — a walk-forward/stability/Monte-Carlo PASS alone is
not a ship decision (BRAIN.md: "A green equity curve is one gate of three").
**Why scheduled, not built now:** amending shared regime-classifier code and re-running
real gates is its own bounded unit of work, deserving its own session's Verification Gate
and generalization proof — same "one phase/bounded task per session" discipline
PROMPTS.md §1 states as the default.

---

**POST-MORTEM (session executed 2026-07-11, verdict rendered 2026-07-12): FAIL, both
target pairs, decisively — closes squeeze_breakout AND this §2 question PERMANENTLY,
per the pre-registered rule above. No TRADING-RULES §6 revival budget consumed (never a
revival attempt).**

**Implementation, exactly as drafted above:** `prior_regime` added to `RegimeResult`
(trailing default field, all 15 pre-existing direct construction sites unaffected),
`RegimeClassifier` sets it at the confirmed-switch instant, mirrors `bars_in_regime`'s
reset-to-1, holds through gray-zone/same-regime bars automatically (no special-casing
needed — nothing but the confirmed-switch branch ever touches it). **Generalization
proof: byte-identical**, confirmed by re-running and diffing against archived numbers —
EUR_USD/trend_pullback (127 trades, net_pnl=-1437.53), USD_JPY/trend_pullback (115
trades, net_pnl=-700.08 — corrects a "117" transcription slip from this session's own
planning notes), EUR_USD/range_reversion (40 trades, net_pnl=-354.20), EUR_GBP/
range_reversion (64 trades, net_pnl=-163.13) — all exact, all FAIL verdicts unchanged.
squeeze_breakout's gate implemented as `regime.bars_in_regime <= regime_confirm_bars`
(HTF-bar units), NOT `<= 8` (LTF-bar units) — a real units mismatch caught before
implementation: `bars_in_regime` increments once per HTF close, while N=8 was derived
as an LTF-bar quantity. Using `regime_confirm_bars` directly (2, for H4/H1) is the
unit-correct equivalent and holds by construction (no second constant to drift out of
sync). Compression-box SL frozen at the COMPRESSION-exit boundary for consultation-
window entries via a new, explicitly-documented instance-state counter
(`self._ltf_bars_since_compression`) — a real, flagged deviation from the class's prior
"stateless otherwise" contract, safe only because a fresh instance is built per run/
window. A consistency assertion (the strategy's own LTF counter vs. the HTF-derived
bound, converted via `htf_ltf_ratio`) ran on every real consultation-window evaluation
in both live gate runs and never tripped.

**Gate 3/4/6 verdict: bit-for-bit identical to Phase 7's pre-amendment numbers, both
pairs.** GBP_USD: 53 trades, net_pnl=-691.75, gate 4 sharp-peak (entry_threshold+10%
deviates 93.1% from base_metric=56.68), gate 6 bootstrap P(net_pnl<=0)=96.8%. USD_JPY:
50 trades, net_pnl=-113.13, gate 4 sharp-peak (atr_expansion_mean_mult-10% deviates
88.6% from base_metric=301.09), gate 6 bootstrap P(net_pnl<=0)=61.9%. Gross-vs-net,
R-multiple distribution, and the (a)/(b) false-break split (100% false-break, both
pairs, case (b) empty in both) are ALSO bit-for-bit identical to Phase 7's archived
exhibits. The new early/late (bars_in_regime==1 vs ==2) stratification added this
session shows **0/0 in both buckets, both pairs** — the amendment produced literally
zero incremental trades. Confirmed independently via per-regime attribution
(diagnose_gates.py): all 53 GBP_USD and all 50 USD_JPY fired trades have
`regime_at_entry=="COMPRESSION"` — zero `"EXPANSION"`-routed trades in either pair.

**The pre-registered parity check (admitted population must be >=50% of Phase 7's
excluded baseline, else halt interpretation) tripped at its most extreme value: 0%
admitted against baselines of 52 (GBP_USD) and 35 (USD_JPY).** Per the rule, this
halted interpretation pending explanation — investigated directly rather than accepted
or dismissed (see BRAIN.md, "A tripped guardrail is a demand for evidence, not a
verdict").

**RECONCILIATION (the investigation, and the standalone finding it produced):** the
original hysteresis-excluded diagnostic counts ANY non-COMPRESSION regime within N
bars of a COMPRESSION exit — RANGING and TRENDING included, not just EXPANSION. Cross-
tabulating the exact same candidate population (400 GBP_USD / 464 USD_JPY LTF bars,
matching the Phase 7 counts precisely) against the real, continuously-classified regime
state at each bar:

| | GBP_USD | USD_JPY |
|---|---|---|
| Phase 7 candidate bars (any non-COMPRESSION regime within N) | 400 | 464 |
| ...classified EXPANSION | 16 (4.0%) | 8 (1.7%) |
| ...classified RANGING/TRENDING | 384 (96.0%) | 456 (98.3%) |
| ...of the EXPANSION bars, correctly admitted (prior=COMPRESSION, bars_in_regime<=confirm_bars) | 16 (100%) | 8 (100%) |
| ...of the admitted bars, actually fired a trade | 0 | 0 |

Also verified: the per-window walk-forward classifier reset (a fresh `RegimeClassifier`
per window, per `_make_run_fn`) does NOT explain the null result — replaying the full-
history continuous transition timestamps against each window's own bounded re-
bootstrap showed most windows (6 of 10 for GBP_USD) still observe the same rare
transitions within their own slice. The gate is reachable, was reached, and admitted
exactly the population it was designed to admit — with zero loss to windowing, timing,
or bug (no assertion ever tripped across either live run).

**The corrected epitaph — more precise than either of the two pre-registered options
from the kickoff (neither applies: zero consultation-window trades occurred in either
pair, so no false-break-share measurement was even possible on that population):** two
independent conditions were required for this amendment to rescue squeeze_breakout, and
both failed. (1) The targeted transition type — COMPRESSION resolving DIRECTLY into a
confirmed EXPANSION — is rare: only 4.0% (GBP_USD) and 1.7% (USD_JPY) of Phase 7's
originally-diagnosed excluded population was ever this specific transition type; the
other 96-98% was COMPRESSION exiting into RANGING or TRENDING, a population this
amendment's own correctly-scoped letter (COMPRESSION→EXPANSION *specifically*, per
TRADING-RULES §2/§3.3's exact wording) cannot and should not reach. (2) Even within the
small, genuinely-eligible population that DOES exist (16 and 8 bars respectively, 100%
correctly captured), not one trigger evaluation ever cleared any walk-forward window's
own selected entry_threshold on real price/indicator data. The amendment is not a bug;
the population it targets is real but vanishingly rare, and even its rare real
instances carry no signal.

**STANDALONE FINDING, beyond the verdict itself — record for future regime-routing
work, not just this playbook:** under this classifier's real behavior on both target
pairs' 766-day H4 history, COMPRESSION resolves to a confirmed EXPANSION only ~2-4% of
the time. §2's "COMPRESSION arms squeeze_breakout... implying a coiled market about to
break out" narrative describes a near-nonexistent sequence in practice — most
COMPRESSION regimes in this data resolve into a directional TRENDING move or fizzle
back into RANGING, not a confirmed volatility EXPANSION. This is not itself a §2 law
defect (COMPRESSION's own definition — narrow BB width — is unrelated to what regime
follows it, and EXPANSION's ATR-ratio definition is a different, independent
statistical claim) but it is a load-bearing empirical fact any future regime-routing
work on either pair should carry forward rather than re-derive.

**PIVOT-SESSION CANDIDATE surfaced by the above (untested, not a Phase 7 reopening —
a new, distinct hypothesis for the next playbook-selection deliberation):**
COMPRESSION→TRENDING is the dominant compression-exit path in this data (~60%+, per the
regime breakdown table above: RANGING+TRENDING_UP+TRENDING_DOWN account for 384/400 and
456/464 of all COMPRESSION-exit candidates). "Trend inception from compression" as an
entry population — entering AT or shortly after the moment a compressed range resolves
into a confirmed trend — is distinct from both of this system's dead theses: it is not
squeeze_breakout's thesis (which specifically wanted the EXPANSION/volatility-breakout
resolution, now shown to be the rare minority outcome), and it is not trend_pullback's
tested structure either (trend_pullback's own FAIL was tested on trending-in-general,
via EMA-pullback-zone entries deep into an already-established trend — not on the
inception moment itself). This is recorded here as one candidate among others for the
next pivot-session's ranked deliberation (alongside D1/H4 time-series momentum and
carry-with-regime-conditioning) — to be evaluated on its own merits there, not built on
the strength of this note alone.

**Files touched this session (see the two-commit pair — "squeeze_breakout §2
consultation-window experiment: FAIL" followed by its revert — for the exact diff):**
`TRADING-RULES.md`, `bot/regime/classifier.py`, `bot/strategies/squeeze_breakout.py`,
`bot/backtest/{engine,results}.py`, `scripts/{run_validation_gates,diagnose_gates,
gross_vs_net}.py`, `tests/{test_regime,test_squeeze_breakout}.py`. The functional code
and the TRADING-RULES.md EXPERIMENTAL clauses were reverted to Phase-7-closed state
after the verdict (code must not contradict law, and law does not carry this mechanism
now that it FAILED) — this ROADMAP entry, BRAIN.md's two new wisdom entries, and
HANDOFF.md's close-out are the permanent record of what was tried and why it failed.

### Compression-within-trend signal flag
**Idea:** When TRENDING regime fires and BB width is simultaneously below its rolling percentile, pass a `compression_flag=True` into the SignalLog indicator_snapshot. The trend_pullback strategy can optionally tighten its score threshold when the flag is set, favouring only the highest-confidence pullback entries.
**Reasoning:** During Phase 3, the classifier priority debate revealed that TRENDING and COMPRESSION can be simultaneously true — the classifier resolves the conflict by picking TRENDING, but the compression state carries information. A pullback within a compressed trend tends to resolve sharply in the trend direction, making it a potentially tighter entry.
**Design questions:** Flag belongs in indicator_snapshot (no schema change) or as a dedicated SignalLog column? Does tighter score threshold need its own walk-forward arm, or does it fall out of the existing one? What is the Phase 4 hit rate of simultaneous TRENDING + sub-P20 BB?
**Why deferred:** No strategy code until Phase 5. Phase 4 pass-rates will first reveal how often the overlap occurs per pair; if rare (<5% of TRENDING bars), the signal adds noise not signal.
