# HANDOFF — 2026-07-10T13:15Z
Phase: 7 — squeeze_breakout   Status: NOT STARTED (Phase 6 CLOSED this session)

Done this session: Phase 6 (range_reversion) closed. Spec-mapping plan approved
with 5 dispositions (AND/OR pre-registration for the two-binary confluence score,
full §1.1 gate accounting incl. engine-level spread/blackout gates, static
middle-band TP as a documented approximation, LTF expansion-veto threshold reuse
contingent on a §1.7 pass-rate check, in-place script generalization with a
byte-identical trend_pullback proof) — all five recorded in HANDOFF before code,
then built: bot/indicators/core.py (bb_reentry_long/short), bot/strategies/
range_reversion.py, bot/config/instruments.yaml (range_reversion_params +
per-pair calibration), bot/backtest/results.py (per-session attribution, general-
purpose), scripts/run_validation_gates.py + diagnose_gates.py (generalized to a
strategy registry, trend_pullback rerun confirmed byte-identical: EUR_USD
trade_count=127 net_pnl=-1437.53 FAIL, matching the archived Phase 5 commit
exactly), tests/test_range_reversion.py (15 tests incl. the expansion-veto-IS-a-
real-veto asymmetry vs. trend_pullback). 204/204 tests pass.

TRADING-RULES §5 gates 3/4/6 run on real >=2yr H1/H4 OANDA history + real
cost_model for EUR_USD and EUR_GBP (kickoff's target pair order) — FAILED
decisively, both pairs: EUR_USD 40 stitched OOS trades net_pnl=-354.20, gate 4
base_metric=-483.43 (already negative pre-perturbation, no profitable neighborhood),
gate 6 bootstrap P(net_pnl<=0)=86.2%. EUR_GBP 64 trades net_pnl=-163.13, gate 4
base_metric=-219.19, gate 6 P(net_pnl<=0)=72.5%. Expansion-veto pass-rate
(disposition 4) cleared both pairs (10.9% / 8.9%, inside the 1%-95% band, no
recalibration needed). AND/OR/asymmetric window breakdown (disposition 1):
EUR_USD mostly AND (6/10), EUR_GBP mostly ASYMMETRIC (6/10) — i.e. EUR_GBP's own
walk-forward selection overruled §3.2's conjunctive letter more often than it
honored it. Full numbers in bot/config/instruments.yaml's per-pair
range_reversion_calibration notes and ROADMAP.md's "range_reversion H1
post-mortem". AUD_USD/GBP_USD/USD_JPY/GBP_JPY deliberately NOT run — the FAIL was
decisive on both target pairs, same disposition logic as Phase 5's post-mortem.
CLAUDE.md's Phase 6 row is ticked (exit criteria are about gates running+reporting
per pair + the expansion-veto test, not the strategy passing — same pre-committed
rule Phase 5 used).

Infra fix discovered mid-phase (not range_reversion-specific): EUR_GBP was the
first pair either strategy's gate scripts ever ran that needs cross-currency
position sizing (quote=GBP, account=USD, neither leg direct/self-convertible) —
scripts/run_validation_gates.py/diagnose_gates.py never built a conversion_series
before now because EUR_USD/USD_JPY (Phase 5's only real runs) didn't need one.
Added run_validation_gates.load_conversion_series() (sources GBP_USD from the same
local candle cache, no new fetch) and wired it through both scripts' run_fn
closures. Re-verified the byte-identical trend_pullback proof AFTER this fix too
(EUR_USD is direct-conversion, quote==account_currency, so conversion_series={}
either way — confirmed no behavior change). See BRAIN.md's new wisdom entry.

TWO PRE-REGISTERED CLOSE-OUT EXHIBITS run before committing (neither a rescue of
the accepted FAIL verdict — both decision rules stated before seeing the data):
(1) Per-session attribution (scripts/gross_vs_net.py) for both range_reversion
target pairs, completing the kickoff's own empirical question about session
preference. EUR_USD's losses were concentrated in the Asian session (asian
net_pnl=-434.33 vs. london+ny_overlap combined +80.13) — met the pre-registered
trigger, so scripts/session_followup_eurusd.py ran ONE follow-up (Asian UTC hours
added to entry_blackout_hours_utc, reusing that existing mechanism — no strategy
or param change): gate 3 flipped to PASS (76 trades, net_pnl=+82.34) but gates 4
(base_metric=-34.12) and 6 (bootstrap P(net_pnl<=0)=42.3%) both still FAILED —
overall verdict unchanged, informative but not a rescue. EUR_GBP's losses were
concentrated in ny_overlap instead (not Asian; asian net_pnl=-25.05 vs. ny_overlap
-485.68) — did NOT meet the trigger, so no follow-up ran for that pair; its FAIL
stands exactly as originally recorded.
(2) Gross-vs-net PnL (scripts/gross_vs_net.py, re-costs each accepted run's
ALREADY-SELECTED per-window params at cost_cfg=ZERO_COST_MODEL, no re-
optimization) for all four accepted final runs, to classify failure mode:
trend_pullback EUR_USD gross=-654.11/net=-1437.53 (no-edge), trend_pullback
USD_JPY gross=-631.78/net=-700.08 (no-edge), range_reversion EUR_USD
gross=-352.08/net=-354.20 (no-edge), range_reversion EUR_GBP
gross=+340.09/net=-163.13 (COST-DOMINATED — the one cost-dominated result found
across both playbooks; a real pre-cost edge existed and costs erased it entirely).
Both classifications now live in ROADMAP.md's two post-mortems and in
instruments.yaml's EUR_USD/EUR_GBP range_reversion_calibration notes.

Not done / next action: Phase 7 kickoff — squeeze_breakout per TRADING-RULES §3.3
(COMPRESSION-only playbook: BB-width-percentile precondition, breakout trigger =
close beyond band + ATR expansion + >=60% body, optional false-break retest cut,
SL opposite side of compression box or 1.5xATR, tick-volume as weak/low-weight
score only never a hard gate). Use PROMPTS.md §5.2's kickoff template. Same
harness (scripts/run_validation_gates.py, add a "squeeze_breakout" entry to its
_STRATEGIES registry) and same discipline established across Phases 5-6: resolve
the §1.1 gate/score mapping explicitly before coding, propose + wait for approval,
audit against the letter before trusting any borrowed structure from the prior two
playbooks. All 6 pairs' H1/H4 candle cache already exists locally — no PA fetch
needed to start.
KICKOFF CONTEXT (from this session's gross-vs-net exhibit): 3 of the 4 prior-
playbook runs so far are NO-EDGE (gross<=0) — the signal itself has nothing, costs
are not the story. Only range_reversion/EUR_GBP was cost-dominated (real gross
edge, erased by spread/slippage/rollover). squeeze_breakout's larger-target exit
thesis (§3.3: breakout + ATR expansion, presumably wider stops/targets than
range_reversion's middle-band scalp or trend_pullback's trailed pullback) is
explicitly the COST-TOLERANT design — it's betting that a bigger per-trade target
survives cost drag better. If squeeze_breakout ALSO comes back no-edge gross, that
would point at a deeper problem (regime detection, timeframe choice, or the
breakout-trigger definition itself) rather than a costs problem — read that
distinction before assuming which failure mode a squeeze_breakout FAIL belongs to.
Re-run scripts/gross_vs_net.py's pattern (frozen per-window params, ZERO_COST_MODEL
re-cost) for squeeze_breakout's own gate runs too, once they exist.
REVIVAL BUDGET (TRADING-RULES §6, 2026-07-10 row, new law): a closed playbook gets
exactly ONE revival attempt per data window, entering via PROMPTS.md §5.7 with a
named new edge-thesis mechanism — not a parameter retune. Status: none spent yet
(trend_pullback, range_reversion both closed, zero attempts used by either). This
means squeeze_breakout is now THE LAST UNTESTED PLAYBOOK — if it also fails, all
three playbooks are closed with zero revival budget spent, a materially different
state than "one closed, two untested." Weigh that when deciding how much scrutiny
to give squeeze_breakout's own spec-mapping before coding.
FIRST IN-THE-WILD DEFENDANT-(D) CONVICTION: EUR_USD's Asian-exclusion follow-up
(gate 3 PASS, gates 4/6 FAIL) is the first time on REAL data that the exact pattern
tests/test_validation_defendants.py's defendant (d) was built to catch (a lucky,
non-representative positive walk-forward result that gate 6's bootstrap overturns)
actually occurred and was correctly caught. See BRAIN.md: "A green equity curve is
one gate of three." Read this before treating any single-gate PASS on
squeeze_breakout as a signal to stop looking.

Open tensions:
  - range_reversion is CLOSED but its code/tests/config remain in the repo
    (not deleted) — enabled: false is the only gate preventing it from trading;
    do not flip without a redefined playbook per ROADMAP's re-entry condition.
  - scripts/run_validation_gates.py's stability keys exclude any integer bar-count
    param (rejection_lookback_bars here, swing_lookback_bars for trend_pullback) —
    perturb_one_at_a_time's +/-10% sweep produces non-integer values a bar-slicing
    op can't accept. Follow this precedent for squeeze_breakout's own bar-count
    params (compression lookback, retest confirmation bars, etc.) — do not
    rediscover this the hard way.
  - Per-session attribution (bot/backtest/results.py) is now general-purpose
    infrastructure, available to squeeze_breakout without further work.

Files touched (Phase 6, this session — see "Phase 6 complete" commit for the full
diff): bot/indicators/core.py, bot/strategies/range_reversion.py (new),
bot/config/instruments.yaml, bot/backtest/results.py, scripts/{run_validation_gates,
diagnose_gates}.py, scripts/{gross_vs_net,session_followup_eurusd}.py (new,
close-out exhibits), tests/{test_indicators,test_range_reversion,test_walk_forward}.py,
CLAUDE.md, ROADMAP.md, BRAIN.md.

Do NOT redo:
  - Do not run TRADING-RULES §5 gates for range_reversion on AUD_USD/GBP_USD/
    USD_JPY/GBP_JPY under the current spec — decisive FAIL on both target pairs,
    see ROADMAP.md's post-mortem for why.
  - Do not re-open range_reversion's FAIL with a wider param_grid or a third
    parameter attempt — closed per ROADMAP.md; revival needs a new edge thesis,
    entering via PROMPTS.md §5.7.
  - Do not add rejection_lookback_bars (or any future strategy's analogous bar-
    count param) to a stability-sweep keys list — same precedent as trend_pullback.
  - Do not run OANDA-credentialed scripts from this local machine — not needed
    for squeeze_breakout's kickoff either (candle cache already complete).
  - Do not run a SECOND EUR_USD session follow-up or any follow-up for EUR_GBP —
    the pre-registered exhibit protocol was one follow-up per pair, contingent on
    the Asian-concentration trigger; EUR_GBP didn't meet it, EUR_USD's follow-up
    already ran and didn't change the verdict. Re-opening either is a rescue
    attempt, not a completion of the pre-registered experiment.
