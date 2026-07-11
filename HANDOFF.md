# HANDOFF — 2026-07-11T05:40Z
Phase: 7 — squeeze_breakout   Status: COMPLETE (Phase 7 CLOSED this session; one bounded follow-up experiment SCHEDULED next session, see below — this is NOT a Phase 8 kickoff)

Done this session: Phase 7 (squeeze_breakout) closed. Spec-mapping plan approved with
6 dispositions + 2 approved additions (hysteresis-excluded diagnostic using each
walk-forward window's own frozen per-window params, realized-R-distribution
non-degeneracy check) + 1 process note (manual review on run_validation_gates.py) — all
recorded in HANDOFF before code, then built: bot/indicators/core.py (bb_breakout_long/
short), bot/strategies/squeeze_breakout.py (new, 4-component scored trigger:
close_beyond_band/atr_expansion/body_pct/tick_volume, no strategy-level veto, SL=
min(compression-box opposite side, entry-+1.5xATR), tp=None + own exit_cfg block reusing
trend_pullback's partial+trail machinery), bot/config/instruments.yaml
(squeeze_breakout_params + per-pair calibration blocks, all 6 pairs), scripts/
run_validation_gates.py (generalized: new _StrategySpec registry entry, new
classify_threshold_regime_general — additive N-ary subset-cover classifier, does NOT
touch range_reversion's existing 2-component classify_threshold_regime — plus the new
compute_hysteresis_excluded diagnostic, wired into __main__ only for squeeze_breakout),
scripts/gross_vs_net.py (generalized: new false_break_vs_insufficient_expansion/
r_multiple_distribution functions + EXHIBIT 3), tests/{test_indicators,
test_squeeze_breakout,test_run_validation_gates}.py (new coverage: bb_breakout_* both
directions, regime-routing hard gate, SL both directions, all 4 components scored never
vetoed, tick-volume-cannot-rescue-a-missing-trigger proof, classify_threshold_regime_
general parity + N-ary scenarios). 236/236 tests pass (204 baseline + 32 new). Byte-
identical trend_pullback/EUR_USD re-run confirmed after the harness generalization
(trade_count=127, net_pnl=-1437.53, exact match to the archived Phase 5/6 numbers) --
same generalization-proof discipline Phase 6 established.

One mid-build fix: the provisional entry_threshold=0.9 (intended as the exact
3-real-trigger-AND boundary, 0.3+0.3+0.3) landed exactly on a float boundary --
0.3+0.3+0.3 evaluates to 0.8999999999999999 in Python, strictly less than the literal
0.9 -- caught by the test suite (two tests failed on `>=` at the boundary). Fixed at the
source (instruments.yaml default changed to entry_threshold=0.85, a safe margin below
the float-realized sum and comfortably above any 2-real+volume combination), not papered
over in the tests.

TRADING-RULES §5 gates 3/4/6 run on real >=2yr H1/H4 OANDA history + real cost_model for
GBP_USD and USD_JPY (kickoff's target pair order, chosen for breakout/trending character
over Phase 5-6's range/trend-suited pairs) -- FAILED decisively, both pairs. GBP_USD: 53
stitched OOS trades, net_pnl=-691.75, gate 4 sharp-peak/overfit (entry_threshold+10%
deviates 93.1% from base_metric=+56.68 -- POSITIVE pre-perturbation, unlike trend_
pullback/range_reversion's "no profitable neighborhood at all" signature), gate 6
bootstrap P(net_pnl<=0)=96.8%. USD_JPY: 50 trades, net_pnl=-113.13, gate 4 same
sharp-peak shape (base_metric=+301.09, atr_expansion_mean_mult-10% deviates 88.6%), gate
6 bootstrap P(net_pnl<=0)=61.9%. Compression-regime pass-rate (§1.7 note): 29.3% H4 bars
(GBP_USD), 29.9% (USD_JPY) -- comfortably non-degenerate, precondition not implicated.

GROSS-VS-NET (standard exhibit, carries more evidentiary weight than in either prior
phase -- see why below): GBP_USD gross=-447.86 (54 trades) vs net=-691.75 -- no-edge.
USD_JPY gross=+0.35 (51 trades) vs net=-113.13 -- mechanically gross>0 (COST-DOMINATED
by the literal classification rule) but flagged explicitly as an ESSENTIALLY-ZERO-EDGE
case ($0.35 across 51 trades over 766 days is not a real edge by any practical
standard), not a genuine cost-dominated result like range_reversion/EUR_GBP's +340.09.
WHY IT MATTERS MORE THIS PHASE: unlike trend_pullback/range_reversion, gate 4's
base_metric was POSITIVE pre-perturbation on both pairs (a real, if fragile, profitable
peak existed in the full-history representative-config backtest) -- gross-vs-net answers
whether that profitability shows up pre-cost in the trades the walk-forward's own
per-window parameter selection ACTUALLY fired, and it does not. This means gate 4's
positive base_metric and the gross-vs-net finding are CONSISTENT: the full-history peak
was a hindsight-selected artifact (exactly what gate 4's instability finding already
diagnosed) that never manifested as a genuine pre-cost edge in real rolling-OOS trades.
Costs were never going to be the story for either pair. Per-session attribution also
computed (informational only, no pre-registered follow-up trigger existed for this
playbook, unlike range_reversion's Asian-session question) -- not acted on.

THE DECISIVE FINDING (approved addition 1, hysteresis-excluded diagnostic): GBP_USD 52
hysteresis-excluded evaluations vs. 53 fired (~98%, per-window frozen params); USD_JPY 35
vs. 50 fired (70%). For essentially every trade that fired, another LTF bar existed
within 8 bars of a COMPRESSION exit where the SAME frozen params would also have cleared
threshold, had the regime gate not excluded it. Per the pre-registered decision rule
(stated before any data existed), this routes the finding to §2 regime-routing territory
-- NOT the trigger, NOT the revival budget, NOT an M15 comparison.

THE TEMPTING FINDING THAT WAS DELIBERATELY NOT ACTED ON (approved addition 2,
false-break split + R-distribution non-degeneracy check, scripts/gross_vs_net.py
EXHIBIT 3): R-distributions confirmed genuine spread (not degenerate) on both pairs.
100% of losing trades on BOTH pairs (33/33 GBP_USD, 24/24 USD_JPY) are case (a),
false-break type (never reached partial_at_r) -- case (b) is EMPTY in both pairs. This
is exactly the signature that would license spending TRADING-RULES §6's revival budget
on the deferred false-break-confirmation filter (ROADMAP.md). It was NOT treated as
licensing that revival -- the pre-registered hysteresis-excluded rule above takes
precedence by design, specifically to prevent this exact convenient-post-hoc-reasoning
trap. See BRAIN.md's new wisdom entry ("Decide which diagnostic wins before either
diagnostic exists") -- this is the first real instance of that discipline actually
mattering, not just being stated.

STRUCTURAL SYNTHESIS (post-verdict analysis -- read this before touching squeeze_
breakout again): the hysteresis-excluded and false-break findings are NOT two competing
explanations. They are two views of ONE fact. The COMPRESSION-only regime gate means
every trade squeeze_breakout can structurally take is taken at the LEAST-confirmed
possible moment of a breakout attempt -- the instant the trigger first clears, before
the HTF classifier has even confirmed the regime has moved on, because the gate slams
shut the moment it does. The hysteresis-excluded count is literally the bars where the
SAME breakout, a few bars further along and having survived without reverting (i.e.
MORE confirmed), would also have cleared the trigger -- exactly the bars the gate
excludes. The false-break split is simply what happens on the only bars the gate lets
through instead: entries confined to the least-confirmed edge of every attempt are, by
construction, the ones most likely to be false breaks. The routing question and the
false-break diagnosis converge on the SAME directional fix: let the playbook enter
LATER, not filter its earliest entries harder. This is also why the confirmation filter
was correctly not licensed -- it would make the earliest-only entries pickier without
ever reaching the more-confirmed bars currently excluded by construction. The
pre-registered decision rule named the correct structural culprit before this
connection was even understood.

CLAUDE.md's Phase 7 row is ticked (exit criteria are about gates running+reporting per
pair + the BB-width pass-rate documentation, not the strategy passing -- same
pre-committed rule Phases 5-6 used). Full numbers in bot/config/instruments.yaml's
GBP_USD/USD_JPY squeeze_breakout_calibration notes and ROADMAP.md's "squeeze_breakout H1
post-mortem" (now includes the gross-vs-net weighting note and the structural synthesis
above, both recorded permanently there, not just here). EUR_USD/EUR_GBP/AUD_USD/GBP_JPY
deliberately NOT run -- same "others follow only on evidence" discipline as Phases 5-6.
ROADMAP.md's "squeeze_breakout optional false-break confirmation" entry updated in place
with a STATUS UPDATE marking it NOT licensed (retained for the record, not deleted).

***PHASE 7 CLOSES ALL THREE PLAYBOOKS WITH ZERO REVIVAL BUDGET SPENT.*** trend_pullback,
range_reversion, AND squeeze_breakout have now all FAILED TRADING-RULES §5 gates and are
closed; TRADING-RULES §6's revival budget remains fully unspent across all three.

Not done / next action: ONE BOUNDED §2 EXPERIMENT, DECIDED 2026-07-11, SCHEDULED FOR THE
NEXT SESSION. NOT a Phase 8 kickoff, NOT a TRADING-RULES §6 revival attempt (this is a
regime-routing LAW question, draws on no revival budget in either direction). Full spec
lives in ROADMAP.md's "squeeze_breakout §2 consultation-window experiment" entry
(new this session) -- summary below, read the ROADMAP entry for the complete draft
amendment text and design questions before starting.

THE EXPERIMENT: extend squeeze_breakout's consultation window N = htf_ltf_ratio x
regime_confirm_bars LTF bars (8, for the default H4/H1 pairing -- same formula
compute_hysteresis_excluded already used) past a CONFIRMED COMPRESSION-to-EXPANSION
transition specifically (not general EXPANSION, not any other playbook's routing).
Gate becomes: fire when regime==COMPRESSION OR (regime==EXPANSION AND
prior_regime==COMPRESSION AND bars_in_regime<=N).

REQUIRED FIRST STEP, BEFORE ANY STRATEGY CODE CHANGES: resolve the blast-radius question
-- generate_signal() only sees the current bar's RegimeResult, which has no "what regime
preceded this one" field today. Proposed (drafted, not yet built): add
`prior_regime: RegimeState | None = None` to RegimeResult (bot/regime/classifier.py,
default-valued and appended last so every existing RegimeResult(...) call site across
the test suite keeps working unmodified); RegimeClassifier gets a new
`self._prior_regime` set to the OLD `self._current_regime` at the exact moment a switch
is confirmed (mirrors how bars_in_regime already resets to 1 there), held through
gray-zone (_INDETERMINATE) bars the same way current_regime already is. This touches
shared classifier code used by ALL THREE playbooks -- run the SAME generalization proof
this phase used for run_validation_gates.py (re-run trend_pullback/range_reversion's own
gate numbers after the change, confirm byte-identical, BEFORE trusting squeeze_
breakout's own re-run). Design questions still open (see ROADMAP entry): whether the
compression-box SL should keep sliding or freeze at the COMPRESSION-exit point for
bars evaluated in the extended window; whether exit_cfg's trail needs adjustment for
entries that start later/closer to the move already underway.

PRE-REGISTERED RULE (stated now, before the experiment runs): re-run GBP_USD and
USD_JPY ONLY, same harness, same param grids, only the consultation gate changed.
FAIL -> squeeze_breakout closes PERMANENTLY and this specific §2 question closes
PERMANENTLY too (not reopened later on a hunch) -- zero revival budget consumed either
way. PASS -> proceeds to FULL TRADING-RULES §5 sign-off (all gates, including the
still-deferred gate 5 per-regime attribution) before any enablement is considered -- a
gates-3/4/6 PASS alone is not a ship decision (BRAIN.md: "A green equity curve is one
gate of three").

Open tensions:
  - The prior_regime design questions above (compression-box SL freeze-vs-slide;
    exit_cfg trail adjustment) are NOT resolved -- next session's Verification Gate must
    resolve them before implementation, not discover them mid-build.
  - scripts/run_validation_gates.py's compute_hysteresis_excluded is squeeze_breakout-
    specific by design (not part of the _StrategySpec registry surface) -- it is
    meaningless for trend_pullback/range_reversion, which have no regime-lag failure
    mode of this shape. Do not try to generalize it to the other two playbooks. Once
    prior_regime exists on RegimeResult, this diagnostic's own hand-rolled
    bars-since-compression computation becomes a redundant (but already-working,
    don't touch) alternate path to the same quantity the live strategy gate will use
    natively.
  - Same integer-bar-count-excluded-from-stability-sweep precedent now applies to
    squeeze_breakout's compression_box_lookback_bars and volume_lookback_bars, carried
    forward correctly this phase -- continue honoring it for any future playbook's
    analogous params, including whatever the experiment's own new params turn out to be.

Files touched (Phase 7, this session -- see "Phase 7 complete" commit for the full
diff): bot/indicators/core.py, bot/strategies/squeeze_breakout.py (new),
bot/config/instruments.yaml, scripts/{run_validation_gates,gross_vs_net}.py,
tests/{test_indicators,test_squeeze_breakout,test_run_validation_gates}.py (last one
new), CLAUDE.md, ROADMAP.md, BRAIN.md.

Do NOT redo:
  - Do not run TRADING-RULES §5 gates for squeeze_breakout on EUR_USD/EUR_GBP/AUD_USD/
    GBP_JPY under the CURRENT (strict COMPRESSION-only) spec -- decisive FAIL on both
    target pairs, see ROADMAP.md's post-mortem for why. The scheduled experiment changes
    the gate itself, so this restriction is about the OLD spec, not a blanket freeze.
  - Do not build the deferred false-break confirmation filter (ROADMAP.md) as a
    response to this phase's FAIL -- explicitly NOT licensed, per the pre-registered
    hysteresis-excluded decision rule and the structural synthesis above.
  - Do not re-open trend_pullback or range_reversion's FAILs with a wider param_grid or
    a third parameter attempt -- both closed per their own ROADMAP post-mortems.
  - Do not add compression_box_lookback_bars/volume_lookback_bars (or the experiment's
    own new params) to a stability-sweep keys list -- same precedent as the other two
    playbooks' integer bar-count params.
  - Do not run OANDA-credentialed scripts from this local machine -- not needed for the
    experiment either (candle cache already complete for all 6 pairs).
  - Do not start Phase 8 as literally scoped before the experiment resolves -- CLAUDE.md's
    Phase 8 wording assumes a validated playbook exists; that's still false until the
    experiment's PASS/FAIL is in.
  - Do not skip the prior_regime generalization proof (trend_pullback/range_reversion
    byte-identical re-run) before trusting squeeze_breakout's own experiment re-run --
    same discipline this phase already used once for run_validation_gates.py.
