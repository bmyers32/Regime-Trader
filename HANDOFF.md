# HANDOFF — 2026-07-07T00:00Z
Phase: 5 — trend_pullback   Status: IN-PROGRESS

## Where things stand
trend_pullback strategy + BacktestEngine partial/trail exit + near-miss signal funnel
are code-complete, tested (133/133), committed, and pushed to origin/master (commits
acb93bc, 47b7204, d4d4742). TRADING-RULES §5 gates 2-6 are NOT-RUN — cost_model is
only partially calibrated (see below). Phase 5 is NOT ticked complete in CLAUDE.md.

cost_model calibration status (bot/config/instruments.yaml, all 6 pairs):
  - rollover_pips_per_day: DONE — real OANDA-published rates via
    scripts/fetch_financing_rates.py, run from a PythonAnywhere console (dated
    2026-07-07 in each pair's cost_model.calibration_note).
  - spread_pips / max_spread_pips: IN PROGRESS — scripts/sample_spreads.py is
    scheduled hourly on PA (Tasks tab), started 2026-07-07. Needs 2-3 full weekdays
    to cover all three session buckets (asian/london/ny_overlap) with enough density.
    Check progress from a PA Bash console: `wc -l instance/spread_samples.csv`.
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

**Track 1 (blocked on time, not on work):** spread sampling keeps running hourly on
PA unattended. Once 2-3 weekdays have accumulated: aggregate instance/
spread_samples.csv (median spread_pips per instrument/session), paste into
instruments.yaml, decide slippage_pips, run the RE-BASELINE RULE ceremony already
written in instruments.yaml (fill -> re-run existing goldens -> expect the shift ->
re-baseline deliberately with a dated note), then run TRADING-RULES §5 gates 1-6 per
pair and report a verdict. Only then is Phase 5's exit criteria row satisfiable.

**Track 2 (can start now, chosen next):** build the TRADING-RULES §5 walk-forward/
validation harness — IS/OOS split, rolling walk-forward, parameter-stability sweep
(±10% neighbor comparison), Monte Carlo trade-order shuffles for drawdown confidence
intervals (§5 gates 3, 4, 6). This is pure infrastructure, buildable and testable now
with synthetic data (same pattern Phase 4's backtester used before real strategies
existed) — real trend_pullback runs plug into it once Track 1 lands. Matches
ROADMAP.md's "Walk-forward automation harness" feature proposal, which was originally
sequenced to land right after Phase 4 and didn't. This is a genuine new scope of work
— start it as its own fresh-context session (PROMPTS.md: `/clear` when switching
session type), not a continuation of this one.

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
