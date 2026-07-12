# HANDOFF — 2026-07-12T23:15Z
Phase: D1/H4 time-series momentum (§6 slot 1 of 3)   Status: COMPLETE — FAIL, slot 1 SPENT

Done this session: `scripts/fetch_history.py` parameterized (`--granularity` flag,
commit `0a38fe6`) and D-granularity cache verified for all 6 pairs. Full
spec-mapping proposal for slot 1 resolved and approved, including 8 user-approved
pre-code amendments (A1–A8) — all recorded in the prior version of this file and
now superseded by this close-out (full amendment text: `git log` this file's
history, or archive/POST-MORTEMS.md §6's summary). Built the momentum playbook
end-to-end and ran TRADING-RULES §5 gates 3/4/6 on both target pairs. **Verdict:
FAIL, decisively, both pairs — see archive/POST-MORTEMS.md §6 for the complete
numbers.** TRADING-RULES.md §1.1 amended (signal-only exemption) and §6 amended
twice (spec resolution, then closure). ROADMAP.md's Closed Dispositions updated.
`bot/config/instruments.yaml`'s EUR_USD/GBP_JPY `momentum_calibration` blocks
updated with full TESTED results.

**Key findings, in case this hearing is ever revisited (§6's renewal clause,
≥12mo new candles):**
- NOT a floor-miss (amendment A4) — 109/105 stitched OOS trades, well clear of
  the 20-trade floor. Trail-exit re-entry chains inflated count above the raw
  sign-flip floor exactly as amendment A7 predicted before any number existed.
- Gate 4's stability sweep independently found N (the signal itself) to be the
  single sharpest, sign-flipping dimension in BOTH pairs' stability neighbors —
  at whichever N each pair's search actually used (EUR_USD's representative was
  N=20, not N=120). Amendment A6's scoping caveat (short-horizon-only,
  N=120 near-untestable) does NOT rescue this verdict — the fragility is not
  confined to N=120.
- Gross-vs-net: EUR_USD no-edge (gross=-349.23), GBP_JPY COST-DOMINATED
  (gross=+203.80, net=-108.27) — the two target pairs failed in different modes.
- A3/A7 pre-registered sign-flip diagnostic: a genuine NULL result on
  signal-flip exit as a revival mechanism. After removing re-entry-chain losses
  (sign-intact by construction), "fresh" sign-intact losses are close in both
  count and magnitude to sign-flipped losses in both pairs — the split does not
  point at the exit mechanism as the fix. Any future revival attempt inherits
  this null result, not a clean target.
- A5(d) duty cycle ~85% both pairs; rollover was 46.5% of EUR_USD's total cost
  (a drag) but a net CREDIT for GBP_JPY (-17.8% reported share, sign is the
  honest signal) — confirms rollover is genuinely first-order at D1 hold
  lengths, in both directions.
- A5(a) funnel confirmed exactly as predicted: consulted==fired both pairs,
  confidence_score constant 1.0 — the honest shape of a signal-only strategy,
  not the v3 always-true-filter failure (no threshold exists here to calibrate).

**Architecture left behind (reusable by future strategies, not momentum-specific):**
- `RegimeResult.htf_window` (bot/regime/classifier.py) — optional, defaulted,
  backward-compatible field carrying the anchor-TF window as of each classify()
  call. No-lookahead-tested (tests/test_backtest.py). Read-only convention
  documented on the field itself.
- `bot/backtest/stability.py::perturb_one_at_a_time` now rounds int-typed
  perturbations to int instead of crashing/requiring exclusion — available to
  any future strategy with an int-typed parameter that actually matters to gate 4.
- `scripts/{run_validation_gates,diagnose_gates,gross_vs_net}.py` generalized
  per-strategy TF pair + walk-forward window sizing (`_StrategySpec.htf_gran/
  ltf_gran/is_bars/oos_bars`, defaulted None = unchanged H4/H1 + 3000/1000 for
  the three original playbooks) and per-strategy params grouping/description
  (`params_key_fn`/`describe_params`, defaulted to the score_weights-based
  helpers) — momentum is the first strategy to use either override; both are
  now real registry-level capabilities, not one-off hacks.

Not done / next action — two hearings remain in the §6 budget, in this order:
1. **Carry-with-regime-conditioning (slot 2, pre-claimed).** Reuses this
   session's D1 fetch — no second fetch needed. Not yet started; needs its own
   spec-mapping proposal (signal definition, regime-conditioning mechanism,
   pairs) before any code, same PROMPTS.md §5.7 discipline this hearing used.
2. **Slot 3: failed-breakout re-entry, continuation direction.** Cached H1
   only, no new fetch needed. Must specify the CONTINUATION thesis (census
   correction from the prior session, see archive/CENSUS-PIVOT-CYCLE.md) not
   the fade convention the census script used internally for signing. Not yet
   started.

Open tensions: TRADING-RULES §6's hearings budget now has 1 of 3 spent, 0
passes. Exhausting the budget without any pass ends strategy search on this
data window (§6's own text) — worth flagging to the user before slot 2 starts,
not deciding unilaterally. Do not reopen trend_pullback, range_reversion,
squeeze_breakout, or this momentum hearing — all closed permanently. Do not
retry momentum on a different anchor TF (amendment A4, still binding) — the
FAIL stands until the data window renews.

Files touched this session: `scripts/fetch_history.py` (commit `0a38fe6`),
`TRADING-RULES.md` (§1.1 exemption, two new §6 rows), `bot/indicators/core.py`
(`trailing_return`), `bot/regime/classifier.py` (`RegimeResult.htf_window`),
`bot/backtest/stability.py` (A8 int-aware perturbation), `bot/strategies/
momentum.py` (new), `bot/config/instruments.yaml` (`momentum_params` +
`momentum_calibration` for EUR_USD/GBP_JPY), `scripts/{run_validation_gates,
diagnose_gates,gross_vs_net}.py` (momentum registry + generalization + A3/A5/A6
diagnostics), `tests/{test_indicators,test_regime,test_backtest,test_stability,
test_momentum}.py`, `archive/POST-MORTEMS.md` (§6, new), `ROADMAP.md` (Closed
Dispositions), `HANDOFF.md` (this rewrite).

Do NOT redo: this hearing (fixed real-data run, archived numbers final for this
data window) or the pivot-cycle census (archive/CENSUS-PIVOT-CYCLE.md, unrelated,
already closed). The A3/A7 diagnostic's null result on signal-flip exit is not
optional framing to re-litigate — it is what the numbers say, same standing as
every other archived diagnostic in this codebase.
