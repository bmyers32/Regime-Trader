# HANDOFF — 2026-07-06T00:00Z (Session A)
Phase: 5 — trend_pullback   Status: IN-PROGRESS

## Session A: architecture decisions recorded BEFORE code (per user direction)

These three decisions came out of the Phase 5 kickoff's ambiguity pass (AGENTS.md
Entry Protocol — engine changes are never trivial). Recorded here first so a context
wipe mid-build doesn't lose the reasoning.

### Decision 1 — Partial-at-1R + trailing exit (TRADING-RULES §3.1)
REJECTED: trail-only-no-partial (validates a different exit policy than §3.1 specifies;
breaks backtest/live parity in exactly the dimension Phase 11 measures) and the
breakeven-at-1R assumption embedded in that option (not in §3.1 — must earn its way in
via walk-forward, not ship as a silent default).

ADOPTED: single BacktestTrade row per entry (preserves trade_count/win_rate semantics),
amended with full partial-leg visibility:
  (a) BacktestTrade gains partial_exit_ts/px/units/pnl fields, all None when no partial
      fired (backward compatible with every existing Phase 4 trade/test).
  (b) New engine-level `exit_cfg` dict (optional; None = exact Phase 4 behavior, zero
      regression): partial_fraction (0.5), partial_at_r (1.0), breakeven_after_partial
      (bool, default False — absent from §3.1, not assumed), trail_atr_period (22),
      trail_atr_mult (3.0, Chandelier convention).
  (c) Partial fill is limit-style: priced via apply_exit_cost(..., exit_reason="tp", ...)
      — half-spread only, no slippage (resting-order economics, same rule TP already
      gets). The remainder's eventual trail/SL exit keeps the asymmetric slippage rule.
  (d) Rollover charges on ACTUAL units held per calendar-day segment: full initial_units
      for [entry_ts, partial_exit_ts), reduced remaining_units for [partial_exit_ts,
      exit_ts] — two rollover_cost_pips() calls summed, not one flat calc on stale units.
  (e) Phase 8 flag: one entry -> two OANDA closes in live. The live Order/Trade journal
      schema will need to mirror this leg pattern (a second linked Trade row, or a
      partial-close extension) — not solved now, do not let Phase 8 silently assume
      one-entry-one-exit.
  Signal/Strategy Core Interface is UNCHANGED — exit_cfg lives on BacktestEngine's
  constructor, not on Signal. The engine computes its own ATR internally (once per
  run(), vectorized, not recomputed per-bar) for the Chandelier calc. This keeps the
  partial/trail capability generic (any future strategy could opt in via exit_cfg)
  rather than bolted onto trend_pullback specifically.

### Decision 2 — cost_model calibration (spread/slippage/rollover still PENDING)
Both calibration scripts deferred out of Session A, for two DIFFERENT reasons: sample_
spreads.py was deferred BY DESIGN regardless of network (it must sample continuously
across a day+ spanning all three UTC session buckets — that can't happen in one
sitting, TLS or not; never attempted this session). fetch_financing_rates.py's single
in-session attempt was separately blocked by the employer-network TLS issue below —
that failure is TLS-specific and does not explain the spread-sampling deferral.
trend_pullback + its tests are built
against an explicit, clearly-labeled PROVISIONAL cost_cfg (same inline-dict pattern as
tests/test_backtest.py's existing `_COST_CFG`) — instruments.yaml's cost_model stays
untouched (still null).
Consequence: every TRADING-RULES §5 validation gate (backtest-with-costs through
Monte Carlo) is marked NOT-RUN this session. No walk-forward verdict, no re-baseline,
no per-pair gate report — those require real cost numbers per the RE-BASELINE RULE
already written in instruments.yaml, and running them on placeholders would produce a
number that looks like a verdict but isn't one.

### Decision 3 — near-miss journaling visibility (engine-level, scoped)
ADOPTED (engine-level, not just unit-test level):
  (a) BacktestEngine records every CONSULTED evaluation — meaning every bar where
      generate_signal() returns a non-None Signal (trend_pullback returns None outright
      when regime doesn't route to it at all; returns a Signal, vetoed or not, for every
      bar regime DOES route) — into BacktestResult.signal_log using a SignalEvaluation
      shape mirroring the real SignalLog journal columns (ts, instrument, strategy,
      direction, score, threshold, fired, vetoes, reasons). Phase 8's real journal writer
      persists the same shape — that's the forward-compat point.
  (b) Fire contract: non-empty vetoes -> never fires regardless of score. Empty vetoes
      but score < threshold -> recorded, fired=False (the near-miss case). Empty vetoes
      and score >= threshold -> fired=True, position opened.
  (c) BacktestResult exposes a computed funnel (consulted -> gates_passed ->
      threshold_cleared -> fired) plus score distribution (min/max/mean/median) — this
      IS the §1.7 empirical pass-rate note for the confluence threshold; it's also the
      reason a unit-test-only approach was rejected (a unit test can't produce an
      empirical pass-rate across 2yr of real data, only a real engine run can).
  (d) `record_signals: bool = True` on BacktestEngine, `signal_threshold: float = 1.0`
      default — chosen specifically so every existing Phase 4 test (whose test-double
      strategy always returns confidence_score=1.0, vetoes=[]) still fires identically;
      zero behavior change unless a real threshold is passed.
  (e) Unit tests on trend_pullback.generate_signal() directly (pullback-without-trigger
      asserting vetoes populate) are kept too, as the fast/cheap check.

## TLS blocker — RESOLVED, standing rule recorded
fetch_financing_rates.py failed TLS to OANDA (cert chain rejected by both Python/
certifi and Windows schannel) when run from this machine mid-session. Initial theory:
employer wireless network TLS inspection at the network edge. CORRECTION (see Session
A post-session update below): the identical failure recurred on this same machine
after switching to the home network, so the network-edge theory is NOT confirmed —
this looks like a local machine-level issue (persistent agent or cert store) that was
never actually root-caused. No machine-level fix applied or wanted regardless (no CA
bundle changes, no proxy config, no disabling verification, anywhere, ever) — the
correct response to an unexplained TLS failure is to route the credentialed call
through a known-good path (PA), not to weaken verification to make the symptom
disappear. STANDING RULE: run OANDA-credentialed scripts from PA, not this local
machine, until the local TLS issue is separately investigated.

## Session A — DONE (code complete, 133/133 tests pass)
Built, in order: RSI + candle-pattern indicators (engulfing, body%, Heikin-Ashi flip)
in bot/indicators/core.py (40 tests); bot/strategies/trend_pullback.py implementing
TRADING-RULES §3.1 (regime-routing hard gate, pullback-zone/reversal-trigger/RSI-side
weighted score, EMA200 hard veto, ATR-vs-swing-extreme SL, tp=None); instruments.yaml
trend_pullback_params block (provisional, dated 2026-07-06) + per-pair
trend_pullback_calibration stub deferring to Session B; BacktestTrade + BacktestEngine
partial/trail/signal_log extensions per Decisions 1 & 3; full test coverage (11
strategy tests incl. both-direction SL + 4 distinct veto reasons + regime-routing
None-vs-vetoed distinction; 12 engine tests incl. partial-fires-at-exact-1R,
trail-exit-above-original-SL, split-rollover-by-segment, signal-funnel counts,
record_signals toggle; confirmed all 101 original Phase 4 tests still pass byte-for-
byte with exit_cfg=None/signal_threshold=1.0 defaults — zero regression).

Pre-commit review correction: EMA200 pullback depth was initially implemented as an
unconditional veto (vetoes.append("beyond_ema200")) — caught before commit as
contradicting §3.1, which lists it under the same "Score:" bullet as pullback-zone/
trigger/RSI, not under "Hard gates:". Refactored to a 4th weighted score component
(_ema200_side_score, score_weights.ema200_side=0.2, rebalanced from 0.4/0.3/0.3 to
0.3/0.25/0.25/0.2) that reduces confidence_score without forcing a no-fire — the
veto version was functionally a 4th hard gate, reintroducing the exact AND-stack shape
TRADING-RULES §1.1 exists to prevent. See BRAIN.md's new "Grouped spec conditions are
one score, not gates in disguise" entry.

Mid-session Verification Gate (PROMPTS §5.3): PASS for everything built this session
(AGENTS.md gate checklist + TRADING-RULES §1 spot-check: ATR/score-space thresholds
only, complete-candles-only preserved, SL tested both directions, no computed-but-
unused indicators, no bare datetime.now(), no per-row .apply()). Note: EXECUTION-
MOMENTUM.md is referenced by CLAUDE.md/PROMPTS.md but does not exist in this repo —
gate was run against AGENTS.md's Verification Gate directly instead.

## Not done / next action
Session A ends at: code complete, §5 gates NOT-RUN pending real cost values — Phase 5
is NOT ticked complete in CLAUDE.md (exit criteria require §5 gates 1-6 reported per
pair; only gate 1 — unit tests — is done).

## Post-session update (2026-07-07) — rollover values landed
`origin/master` was found 6 commits behind local (Phases 1-4 never pushed) while
setting up PA for this — pushed (already-reviewed commits only; this session's
Phase 5 diff was NOT included). Confirmed PA's system image only had Python 3.10
until the user upgraded it; re-ran with 3.13.1 to match local dev's pin exactly.
`fetch_financing_rates.py` ran successfully from the PA console. Correction to the
earlier TLS diagnosis: the identical cert-verification failure recurred on the local
machine even after switching to the home network, which points away from "employer
network TLS inspection" as the sole/confirmed cause and toward a local machine-level
issue (persistent agent or cert store) that was never actually root-caused — running
from PA sidestepped the problem rather than diagnosing it. Standing rule updated:
run OANDA-credentialed scripts from PA, not this local machine, until/unless the
local TLS issue is separately investigated and fixed. rollover_pips_per_day is now filled for
all 6 pairs in instruments.yaml with real OANDA-published rates (dated 2026-07-07
in each pair's cost_model.calibration_note); spread_pips/max_spread_pips/
slippage_pips remain PENDING — sample_spreads.py has still NOT been run (needs a
multi-day sample spanning all three UTC sessions, unrelated to the TLS issue).
No re-baseline ceremony triggered yet — existing goldens read inline cost dicts,
not instruments.yaml, so filling rollover alone didn't shift any test (confirmed:
133/133 still pass). The RE-BASELINE RULE only fires once real strategies start
reading instruments.yaml's cost_model directly, which hasn't happened yet either.

Session B (next) opens with:
  1. Run sample_spreads.py repeatedly across a day+ (all three UTC session buckets)
     from PA — the one calibration step still outstanding. Aggregate the CSV (e.g.
     median per instrument/session) and paste into instruments.yaml's spread_pips/
     max_spread_pips/slippage_pips blocks (rollover is already done — see above).
  2. RE-BASELINE RULE ceremony per instruments.yaml's existing comment block: fill ->
     re-run existing goldens/walk-forward -> expect the shift -> re-baseline
     deliberately with a dated note in both the yaml calibration_note and the relevant
     test file.
  3. Run TRADING-RULES §5 gates 1-6 for trend_pullback per pair (unit tests already
     done in Session A; backtest-with-real-costs, IS/OOS + walk-forward, parameter
     stability on entry_threshold/score_weights/sl_atr_mult/trail_atr_mult, per-regime
     attribution, Monte Carlo shuffles).
  4. Report verdict per pair; only then is Phase 5's exit criteria row satisfiable.

## Open tensions
  - trend_pullback_params (entry_threshold, score_weights, sl_atr_mult, trail_atr_mult,
    pullback_zone_atr bounds) are PROVISIONAL — reasonable defaults implementing §3.1's
    prose spec, not yet empirically validated. Calibration_note in instruments.yaml says
    this explicitly; do not treat as ship-ready until Session B's walk-forward runs.
  - Phase 8's Order/Trade journal schema does not yet have a representation for a
    partial-close (one entry -> two OANDA closes). Flagged, not solved — must be
    addressed when Phase 8 designs the live execution path, or backtest/live will
    diverge exactly where Phase 11 measures divergence.
  - breakeven_after_partial defaults False (absent from §3.1). If Session B's parameter
    stability sweep shows it helps, it earns its way in with a dated re-baseline note —
    never flip silently.

## Do NOT redo
  - Do not run OANDA-credentialed scripts (fetch_financing_rates.py, sample_spreads.py)
    from this local machine — its TLS failure recurred on both employer and home
    networks and was never root-caused; run them from PA instead until it is.
  - Do not disable/bypass TLS certificate verification anywhere to route around this —
    an unexplained failure is a reason to use a known-good path, not to weaken the check.
  - Do not attempt sample_spreads.py in a single sitting regardless of network — it is
    a multi-session, multi-day sampler by design (TLS was never the blocker for this
    one; don't conflate the two deferrals).
  - Do not disable/bypass TLS certificate verification anywhere to route around the
    above — the failure is correct behavior, not a bug to patch around.
  - Do not silently fill instruments.yaml's cost_model with published-typical or
    placeholder numbers (carried over from Phase 4 — still binding).
  - Do not report any TRADING-RULES §5 gate as PASS/FAIL this session — they are
    NOT-RUN, pending Session B's real cost values. A number computed on placeholder
    costs is not a verdict.
  - Do not add breakeven_after_partial=True as a default — it's an unvalidated addition
    to §3.1's spec, not a documented requirement.

## Files touched this session
  bot/indicators/core.py (rsi, body_pct, bullish/bearish_engulfing, heikin_ashi +
    bullish/bearish flip helpers), bot/strategies/trend_pullback.py (new),
  bot/backtest/results.py (BacktestTrade partial-leg fields, SignalEvaluation,
    compute_signal_funnel, BacktestResult.signal_log), bot/backtest/engine.py
    (exit_cfg, signal_threshold, record_signals + _check_exit_with_trailing/
    _execute_partial + _close_position segment-aware rollover),
  bot/config/instruments.yaml (defaults.trend_pullback_params + per-pair
    trend_pullback_calibration stub, all 6 pairs),
  tests/test_indicators.py (+40 new: RSI, body_pct, engulfing, Heikin-Ashi),
  tests/test_trend_pullback.py (new, 11 tests), tests/test_backtest.py (+12 new:
    partial/trail, split-rollover, signal funnel), HANDOFF.md.
