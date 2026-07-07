# HANDOFF — 2026-07-07T00:00Z (Session B close-out, blocked)
Phase: 5 — trend_pullback   Status: IN-PROGRESS, BLOCKED on Track 1 data sufficiency

## Session B: blocked before gates ran — do not skip ahead
Session B was kicked off believing Track 1 (spread sampling) had landed. It had not.
Checked instance/spread_samples.csv on PA: only the ny_overlap bucket has any rows
(sampler started 2026-07-07 17:01 UTC; asian/london buckets are empty because no
UTC-asian/london hours have elapsed yet since start). Separately, the task was
running on an HOURLY cadence (17:01/18:01/19:01), not the intended 2-3min cadence —
diagnosed and fixed this session (see below). **No gates were run. No cost_model
PENDING values were filled. TRADING-RULES §5 steps 1-6 from the Session B kickoff
prompt are all still outstanding.**

**Root cause of the cadence bug:** scripts/sample_spreads.py had no internal loop —
`sample_once()` fired once and the script exited; cadence was 100% delegated to
whatever invoked it. PythonAnywhere's Tasks-tab scheduled tasks only support daily
or hourly recurrence in the UI — there is no minute-level cron there, so "hourly"
was the finest granularity that mechanism could ever produce, not a misconfiguration
of an otherwise-capable scheduler.

**Fix applied this session:** scripts/sample_spreads.py now runs as a long-lived
loop (`run_loop`, `_SAMPLE_INTERVAL_SECONDS=150`) that samples every ~2.5min and
sleeps between; a `--once` flag preserves the old single-shot behavior for manual
checks. Per-iteration exceptions are caught and logged (traceback to stdout) so one
failed OANDA request doesn't kill the whole run. **Not yet deployed** — needs to be
re-run on PA as an Always-On Task (not a Tasks-tab scheduled task) tonight:
  1. Kill/delete the existing hourly Tasks-tab entry for sample_spreads.py.
  2. Create a PA Always-On Task running `python scripts/sample_spreads.py` (no
     `--once`) from the project's venv/working dir.
  3. Confirm rows are landing every ~2-3min via `wc -l instance/spread_samples.csv`
     a few minutes after start, and again the next morning to confirm session-bucket
     coverage is actually filling in (not just ny_overlap).

**Session B verdict rule for next session:** do not consider Track 1 "landed" on a
trade/observation-count technicality. Calibration data sufficiency = at least ~100
observations per session bucket (asian/london/ny_overlap) per pair, across all three
buckets, before aggregating median spread_pips into instruments.yaml. No synthetic
or placeholder spread values are an acceptable substitute (TRADING-RULES §1.7) —
if a bucket is thin when next picked up, wait longer; do not estimate around it.

## Where things stand
trend_pullback strategy + BacktestEngine partial/trail exit + near-miss signal funnel
are code-complete, tested (133/133), committed, and pushed to origin/master (commits
acb93bc, 47b7204, d4d4742). TRADING-RULES §5 gates 2-6 are NOT-RUN — cost_model is
only partially calibrated (see below). Phase 5 is NOT ticked complete in CLAUDE.md.

cost_model calibration status (bot/config/instruments.yaml, all 6 pairs):
  - rollover_pips_per_day: DONE — real OANDA-published rates via
    scripts/fetch_financing_rates.py, run from a PythonAnywhere console (dated
    2026-07-07 in each pair's cost_model.calibration_note).
  - spread_pips / max_spread_pips: BLOCKED, restarted this session — see "Session B:
    blocked" above. scripts/sample_spreads.py now supports a proper ~2-3min Always-On
    Task loop (fix landed, not yet deployed to PA). Needs redeploy tonight, then 2-3
    full weekdays to cover all three session buckets (asian/london/ny_overlap) with
    ≥100 observations each. Check progress from a PA Bash console:
    `wc -l instance/spread_samples.csv`.
  - slippage_pips: NOT DERIVABLE from sample_spreads.py at all — that script measures
    quoted bid/ask spread, not real fill slippage. Needs its own decision once there's
    real fill data (Phase 8's Order.spread_at_entry) or an explicitly-flagged interim
    approach — do not silently pick a number when that time comes.

Standing rule: run OANDA-credentialed scripts from PA, not the local machine — a TLS
cert-verification failure recurred here across two different networks and was never
root-caused (see BRAIN.md's "Verification failing closed is the system succeeding").

## Architecture decisions from Session A (still governing, reference only)
1. **Partial-at-1R + ATR/Chandelier trail** (TRADING-RULES §3.1): BacktestEngine's
   optional `exit_cfg` dict (partial_fraction, partial_at_r, breakeven_after_partial,
   trail_atr_period, trail_atr_mult). `exit_cfg=None` reproduces exact Phase 4
   behavior. `BacktestTrade` carries partial_exit_ts/px/units/pnl (all None when no
   partial fired). Rollover is charged on units actually held per calendar-day
   segment, not a flat full-size calc. Phase 8 open item: the live Order/Trade
   journal has no representation yet for one-entry-two-closes (ROADMAP.md).
2. **Near-miss journaling** (engine-level): `BacktestEngine(signal_threshold=,
   record_signals=)` — a Signal fires only when vetoes is empty AND
   confidence_score >= threshold; every consulted evaluation (generate_signal()
   returned non-None) lands in `BacktestResult.signal_log` regardless of fire/no-fire,
   plus a computed funnel (consulted/gates_passed/threshold_cleared/fired + score
   distribution) — this is the §1.7 empirical pass-rate evidence.
3. **EMA200 pullback depth is a scored component, not a veto** (score_weights.
   ema200_side=0.2) — an unconditional veto would be a 4th hard gate, reintroducing
   the AND-stack anti-pattern TRADING-RULES §1.1 exists to prevent. This playbook's
   only hard gate is regime-routing.

CLAUDE.md's Always-On Rules comment convention was also refined this phase: WHY not
WHAT, required TRADING-RULES §-citations wherever code implements a law, banned line
narration / signature-restating docstrings / stdlib-idiom explanations.

## Not done / next action
Two independent, parallelizable tracks:

**Track 1 (blocked on time, not on work — redeploy required first, see Session B
close-out note at top of file):** scripts/sample_spreads.py's cadence bug is fixed
in code but the Always-On Task redeploy on PA has NOT happened yet — do that first.
Once redeployed and 2-3 full weekdays have accumulated with ≥100 observations per
session bucket per pair (not just the 20-trade-count floor logic from Track 2 —
this is a separate, stricter sufficiency bar for raw spread samples): aggregate
instance/spread_samples.csv (median spread_pips per instrument/session), show
per-pair/per-bucket values with sample counts and flag any thin/anomalous bucket
BEFORE writing into instruments.yaml, decide slippage_pips, run the RE-BASELINE RULE
ceremony already written in instruments.yaml (fill -> re-run existing goldens ->
expect the shift -> re-baseline deliberately with a dated note), then run
TRADING-RULES §5 gates 1-6 per pair and report a verdict. Only then is Phase 5's
exit criteria row satisfiable.

**Session B verdict rule (evidence thickness, not just the trade-count floor):**
`default_gate3_pass_fn`'s `min_trade_count=20` is a hard floor, not evidence that a
sample just above it is thick enough to trust. If real trend_pullback's stitched OOS
trade count comes back thin (passes the floor but is small in absolute terms, or the
run is otherwise data-starved), the correct response is NOT to ship on a technical
pass, extend the backtest window, or loosen the entry threshold — it is to trigger
TRADING-RULES §2's timeframe-comparison run (4H/1H vs 1H/15M as competing
configurations, winner = best net-of-cost OOS expectancy subject to the same
minimum-trade-count guard) BEFORE any ship decision, not after one has already been
implied. A thin sample on the default timeframe pair is itself evidence the
anchor:execution ratio may be wrong for this pair, not just evidence to gather more
of the same.

**Track 2 — DONE this session (2026-07-07):** TRADING-RULES §5 gates 3/4/6 harness
built as pure infrastructure, validated on synthetic data, no dependency on Track 1's
real cost_model:
  - `bot/backtest/param_sweep.py` — generic grid search (`select_best_params`), the
    shared building block gate 3's IS optimization and any future overfit-scenario
    test both use.
  - `bot/backtest/walk_forward.py` (gate 3) — rolling IS/OOS windows, structural
    IS/OOS isolation (an assert tripwire, not just convention — see design
    dispositions below), OOS evaluation with real-history warmup + entry-ts trim,
    a separately-tested pure `stitch_oos_results` function.
  - `bot/backtest/stability.py` (gate 4) — ±10% one-at-a-time for independent
    params, pairwise compensating perturbation for simplex-constrained groups
    (score_weights), sharp-peak/no-profitable-peak rejection logic.
  - `bot/backtest/monte_carlo.py` (gate 6) — permutation-based drawdown-path CI
    PLUS bootstrap-with-replacement P(net_pnl<=0), explicit pass rule (see
    dispositions below).
  - `bot/backtest/gate_report.py` — `GateReport` assembling gates 3/4/6, explicit
    Gate-5-deferred note, JSON-safe `gate_report_to_dict`.
  - Tests: `test_param_sweep.py`, `test_walk_forward.py` (incl. a known-answer
    stitching test and an IS/OOS-isolation spy test), `test_stability.py`,
    `test_monte_carlo.py`, `test_gate_report.py`, and
    `test_validation_defendants.py` — four "known-guilt" end-to-end scenarios (real
    edge passes all gates; coin-flip fails gate 3; overfit-by-construction via a
    wide threshold grid searched on zero-cost noise fails gates 3 AND 4 with a
    genuine winner's-curse sharp peak; a cherry-picked lucky zero-edge seed passes
    gate 3 but is convicted by gate 6's bootstrap check).
  - Post-review refinements (same session, after initial accept): every gate's pass
    reason now states its own numbers and thresholds inline (e.g. "stitched OOS
    net_pnl=30087.89 > 0 with trade_count=183 >= min_trade_count=20"), never a bare
    boolean; `GateReport.limitations` aggregates StabilityResult's perturbation-
    scoping note AND a new MonteCarloResult.limitations note (both MC methods
    assume trade independence — serially correlated trades, e.g. trailing exits in
    a persistent regime, mean gate 6 understates real drawdown clustering and is
    slightly lenient on trend-following strategies; block bootstrap is the known
    upgrade, not implemented); `gate_report.render_text()` added for human-readable
    CLI/session output. 175/175 tests pass (133 pre-existing + 42 new).
  - Real trend_pullback runs plug into `run_fn(params, ltf_slice, htf_slice)` once
    Track 1's cost_model lands — the harness itself has zero dependency on real
    costs and needs no changes to consume them.
  - Matches ROADMAP.md's "Walk-forward automation harness" feature proposal
    (updated there with delivered-status + remaining CLI-wiring scope).
  - PROMPTS.md §5.3 verification gate run against this session's diff: state
    ownership clear (pure in-memory, no journal/DB/OANDA touched), blast radius
    confirmed zero (wraps BacktestEngine via injected run_fn, doesn't modify
    engine.py or any live path), TRADING-RULES §1 laws N/A (no market thresholds,
    no new production strategy — synthetic test doubles only) or satisfied
    (synthetic data carries complete=True, UTC timestamps). PASS.

## Track 2 validation-harness design dispositions (recorded pre-code, per session request)
1. Gate 6 (Monte Carlo) pass/fail criterion — TRADING-RULES §5.6 says "trade-order
   shuffles -> drawdown confidence intervals" but pure order-permutation cannot flag
   a lucky-seed zero-edge result: permuting order leaves the SUM of trade PnLs
   unchanged, so a positive total survives every permutation trivially. Extended
   gate 6 beyond literal permutation to include bootstrap resampling WITH
   replacement (composition varies, sum does not) alongside the literal
   order-permutation drawdown-path CI. Explicit pass rule (not "a CI exists"):
     passed = observed_net_pnl > 0
              AND P(bootstrap resample net_pnl <= 0) <= max_prob_nonpositive (default 0.05)
              AND permutation-path drawdown p95 <= max_acceptable_drawdown (default 0.30)
   All three thresholds are constructor args, not hardcoded law — provisional
   defaults only, same spirit as TRADING-RULES §1.7's calibration-note requirement.
   Rationale/test: defendant (d) (zero-edge strategy, cherry-picked lucky seed with
   positive stitched OOS net_pnl) exists specifically to prove gate 3's raw net_pnl
   check alone would rubber-stamp this defendant, and gate 6's bootstrap
   prob_nonpositive check is what convicts it.
2. Stitching correctness — a dedicated known-answer test (test_walk_forward.py)
   feeds 3 hand-built fake per-window OOS results (trades + equity Series, incl.
   one trade sitting exactly on a window boundary) directly into the stitching
   function (bypassing the engine) and asserts the exact expected concatenated
   equity curve/trade list. Windows are bar-index-defined half-open ranges
   [oos_start, oos_end) over the SAME shared timestamp index, so boundary
   assignment is exact (no rounding/duplication ambiguity) as long as OOS windows
   are non-overlapping (step_bars defaults to oos_bars; overlapping OOS windows are
   out of scope, not handled).
3. ±10% one-at-a-time (§5.4) vs. compensating-pair ridges — one-at-a-time is kept
   as the default for general independent numeric params (sl_atr_mult,
   pullback_zone_atr_min/max, entry_threshold, trail_atr_mult, partial_at_r): full
   pairwise/combinatorial sweep across all of them is deferred, out of scope for
   this session. ADDED: pairwise compensating perturbation specifically for
   simplex-constrained groups (score_weights, which must sum to 1.0) — raise one
   weight by pct*value, lower another by the same absolute amount, all C(n,2)
   pairs both directions. This is the one place a "compensating pair" ridge is
   both cheap to test (4 weights = 6 pairs) and structurally guaranteed to exist
   (the sum-to-1 constraint IS a compensating relationship). GateReport/
   StabilityResult carries a `limitations` field stating the general
   one-at-a-time scoping explicitly, so it is visible at read time, not just here.
4. Gate 6 independence assumption (raised after initial accept) — both permutation
   and bootstrap treat trade PnLs as i.i.d. draws. Real trades from a trailing-exit
   strategy in a persistent regime are serially correlated, so real drawdown
   clustering is understated and gate 6 is slightly lenient specifically for
   trend-following strategies (trend_pullback is exactly this shape). Recorded as a
   MonteCarloResult.limitations string, surfaced on every GateReport via the
   aggregated `limitations` list (not buried in a code comment only). Block
   bootstrap (resample contiguous trade blocks, not single trades) is the known fix
   if/when a real trend_pullback run shows this mattering — not implemented this
   session.

**Phase 9 breadcrumb:** `gate_report.render_text()`'s `§` characters (TRADING-RULES
citations in gate reasons/notes/limitations) render as a mangled byte in a Windows
git-bash/cmd console — confirmed this session to be a console-codepage display quirk
only, NOT source or string corruption (the underlying string is correct UTF-8,
`b'\xc2\xa7'`). No action needed for Flask/file output (both handle UTF-8 natively);
this note exists so nobody burns time chasing a phantom encoding bug in report text
when wiring the /backtests dashboard page.

## Files touched (Session B close-out, this pass)
  - `scripts/sample_spreads.py` (fixed: added `run_loop`/`_SAMPLE_INTERVAL_SECONDS`
    for Always-On Task use; `--once` flag preserves prior single-shot behavior;
    not yet redeployed to PA)
  - `HANDOFF.md` (this file — blocked status, cadence-bug diagnosis, redeploy steps)

## Files touched (Track 2 session, prior pass)
  - `bot/backtest/param_sweep.py` (new)
  - `bot/backtest/walk_forward.py` (new)
  - `bot/backtest/stability.py` (new)
  - `bot/backtest/monte_carlo.py` (new)
  - `bot/backtest/gate_report.py` (new)
  - `tests/test_param_sweep.py` (new)
  - `tests/test_walk_forward.py` (new)
  - `tests/test_stability.py` (new)
  - `tests/test_monte_carlo.py` (new)
  - `tests/test_gate_report.py` (new)
  - `tests/test_validation_defendants.py` (new)
  - `HANDOFF.md` (this file)
  - `ROADMAP.md` (Walk-forward automation harness entry updated to delivered-status)
  - `BRAIN.md` (new Wisdom entry: "Test the judge with defendants of known guilt")

## Open tensions
  - trend_pullback_params (entry_threshold, score_weights, sl_atr_mult,
    trail_atr_mult, pullback_zone_atr bounds) are PROVISIONAL defaults implementing
    §3.1's prose spec — not yet empirically validated. Do not treat as ship-ready
    until the walk-forward harness runs against real costs.
  - breakeven_after_partial defaults False (absent from §3.1) — only flip it if the
    parameter-stability sweep shows it helps, with a dated re-baseline note.

## Do NOT redo
  - Do not run OANDA-credentialed scripts from this local machine — use PA.
  - Do not disable/bypass TLS certificate verification anywhere.
  - Do not silently fill cost_model with published-typical or placeholder numbers.
  - Do not report any TRADING-RULES §5 gate as PASS/FAIL until real costs are in.
  - Do not add breakeven_after_partial=True as a default without a validated reason.
  - Do not treat Track 1 as "landed" on the presence of a file or a nonzero row
    count alone — require ≥100 observations per session bucket per pair across all
    three buckets (asian/london/ny_overlap) before aggregating into instruments.yaml.
  - Do not schedule sample_spreads.py (or any sub-hourly-cadence script) via PA's
    Tasks tab — that UI's finest recurrence is hourly. Use an Always-On Task with
    an internal sleep loop instead (see run_loop in the script).
