# HANDOFF — 2026-07-13T03:20Z
Phase: carry-with-regime-conditioning (§6 slot 2 of 3)   Status: COMPLETE — FAIL, slot 2 SPENT

Done this session: Full spec-mapping proposal for slot 2 resolved and approved,
including the signal-source resolution (FRED, the project's first non-OANDA data
dependency) and four user-approved amendments, recorded in HANDOFF.md before any
strategy code existed. During the build, the user added three further riders (tracked
`calibration/rates/` not gitignored — a caught internal contradiction; real-data
recompute of the sign-stability exhibit before any gate ran, with a HALT criterion
scoped to sign/classification only; gate-4-scope and C.6-divergence-direction framing
requirements for the eventual report) — all four original amendments plus all riders
were folded into the build. Built `bot/data/rates.py` (`PolicyRateCache`,
`apply_effective_date_shift`, `rate_asof`), `scripts/fetch_policy_rates.py` (JPY
series corrected mid-build: `IRSTCB01JPM156N` returned zero live observations,
switched to `IRSTCI01JPM156N`), fetched and pinned the real 5-currency snapshot to
`calibration/rates/` (from PA — local hit the anticipated TLS interception), recomputed
the sign-stability exhibit from real data (no HALT triggered — confirmed both target
pairs static-positive, GBP_USD/AUD_USD dynamic), built `bot/strategies/carry.py` +
`carry_params`/`carry_calibration` config, `tests/{test_rates,test_carry}.py` (22 new
tests, full suite 275 passed throughout), registered `carry` in
`scripts/{run_validation_gates,diagnose_gates}.py` with two new diagnostics
(`compute_carry_expansion_diagnostic`, generalized `expansion_veto_pass_rate`). Ran
TRADING-RULES §5 gates on both target pairs. **Verdict: FAIL, both pairs, via a novel
failure signature — see archive/POST-MORTEMS.md §7 for the complete numbers.**
TRADING-RULES.md §6 amended twice (spec resolution, then closure). ROADMAP.md's Closed
Dispositions updated. `bot/config/instruments.yaml`'s USD_JPY/GBP_JPY `carry_calibration`
blocks updated with full TESTED results.

**Key findings, in case this hearing is ever revisited (§6's renewal clause, ≥12mo new
candles):**
- NOVEL FAILURE SIGNATURE — first in this codebase's history: gate 3 (walk-forward net
  PnL) genuinely PASSES on BOTH pairs (USD_JPY net_pnl=+414.84/104 trades, GBP_JPY
  net_pnl=+386.45/101 trades) — a real, positive edge existed. FAILS via gate 6
  (bootstrap) at nearly IDENTICAL probabilities on both pairs (P(net_pnl≤0)=22.5%/
  22.3%, both far above the ≤5% bar) — the positive result isn't statistically robust.
  Every prior FAIL (trend_pullback, range_reversion, squeeze_breakout, momentum) had
  negative gross and/or net PnL outright; carry is the first strategy where the edge
  was real but not distinguishable from noise.
- Gate 4 split (USD_JPY FAIL on `sl_atr_mult` sensitivity, 58.4% deviation; GBP_JPY
  PASS, 31.0% worst deviation) does NOT rescue or complicate the verdict once its
  scope is read correctly: carry has ZERO free signal parameters this hearing (the
  differential's sign is fixed, no threshold searched), so gate 4 only measured
  exit-parameter stability — neither result speaks to the carry SIGNAL's robustness,
  unlike momentum's gate 4 which independently caught its own signal parameter (N) as
  fragile. Gate 6's shared, near-identical signature across both pairs is decisive.
- Gross-vs-net is a genuinely new shape: BOTH pairs have gross>0 AND net>0 (neither
  "no-edge" nor traditional "cost-dominated" — those categories assume net≤0). USD_JPY
  net (+414.84) actually EXCEEDS gross (+364.20, 106 trades) — rollover credit more
  than fully offsets spread/slippage. GBP_JPY gross (+437.90, 100 trades) slightly
  exceeds net (+386.45) but rollover_cost=+145.96 still dwarfs the small remaining
  drag (total_cost=51.45).
- A5(d)-equivalent duty cycle + rollover-share (PRIMARY exhibit for this thesis, per
  pre-registration 5): USD_JPY 81.0% (472.1d/582.6d), rollover_cost=+146.21. GBP_JPY
  80.1% (466.3d/582.0d), rollover_cost=+145.96 — both pairs land within half a point
  of each other on duty cycle and within $0.25 on total rollover credit, an unplanned
  convergence.
- C.6 rollover reconciliation CONFIRMED on real numbers: both pairs' signal says long
  throughout (static-positive differential); OANDA's snapshot credits the long side
  for both (GBP_JPY long=+1.063, USD_JPY long=+0.803 pips/day) — the engine's real
  charges (+146.21/+145.96) confirm this reconciles cleanly. Divergence direction
  confirmed conservative, not generous: both pairs' real differentials NARROWED over
  the window (Fed cut, BOJ hiked), so the constant present-day snapshot UNDERSTATES
  early-window rollover credit relative to true history — a PASS would have survived
  this bias; the actual FAIL cannot be attributed to an unfairly generous assumption
  either.
- EXPANSION-veto pass-rate (§1.7, C.2 rider 3, BINDING): USD_JPY 21.4% (33/154), GBP_JPY
  37.9% (72/190) — both comfortably inside 1%-95%, the centerpiece regime-gate is
  genuinely binding, NOT decorative, on both pairs.
- EXPANSION-during-hold diagnostic (C.2 rider 1) — a CLEAN NULL RESULT on both pairs:
  USD_JPY 0/49 losing trades (all -2425.69) coincided with EXPANSION during the hold.
  GBP_JPY only 1/46 (-53.08 of -2309.52). The centerpiece regime-conditioning mechanic
  is real and binding on entries but does NOT explain the losses — a future revival
  targeting "strengthen the EXPANSION response" (e.g. mid-hold forced flatten) inherits
  this null result, not an obvious target. Same standing as momentum's own A3/A7 null.
- Per-regime attribution (informational): both pairs' best regime was RANGING
  (USD_JPY +533.98/50/60.0%; GBP_JPY +323.06/43/62.8%); both pairs' worst was
  TRENDING_UP (USD_JPY -96.00/2/0%, thin; GBP_JPY -205.17/11/36.4%, real sample) — an
  echo of momentum's own irony (losing money specifically in classified TRENDING
  states), not acted on.
- Verdict-combination reading (pre-registered before either pair's gates ran): both
  FAILED — carry is closed at its own JPY-funded home terrain, not "one strong result."
  The correlation caveat that motivated this reading held exactly: both pairs moved
  together on the decisive gate (6).
- Sign-stability exhibit (recomputed from the real pinned FRED data, not just the
  research-derived first pass): confirms USD_JPY/GBP_JPY are STATIC-POSITIVE the whole
  window (0 sign flips each) — this hearing tested a regime-conditioned STATIC
  short-JPY position, never a dynamically-switching signal. GBP_USD (5 flips) and
  AUD_USD (3 flips) are the confirmed dynamic-differential pairs, untested, recorded
  as the lawful §6-renewal candidates for actually testing signal dynamics.

**Architecture left behind (reusable by future strategies, not carry-specific):**
- `bot/data/rates.py` (`PolicyRateCache`, `apply_effective_date_shift`, `rate_asof`) —
  the project's first non-OANDA, non-candle data-cache pattern (currency-keyed, not
  instrument+granularity-keyed), TRACKED in git under `calibration/` rather than
  gitignored `instance/` — a new precedent for small, audit-worthy calibration data
  that must survive a fresh clone, distinct from large per-machine OANDA caches.
- `scripts/fetch_policy_rates.py` — first fetcher in this repo hitting a non-OANDA
  external API (FRED), auto-writing its output (unlike `fetch_financing_rates.py`'s
  manual-paste convention) since the object is a full time series, not a handful of
  scalars for review.
- `expansion_veto_pass_rate(signals, veto_name=...)` in `diagnose_gates.py` —
  generalized past its original range_reversion-only caller via a parameter (same move
  `classify_threshold_regime_general` made), available to any future strategy with its
  own named EXPANSION-style veto.
- `compute_carry_expansion_diagnostic` in `run_validation_gates.py` — a reusable
  pattern (classify the D-anchor regime timeline once, check whether a named regime
  state was ever active during a losing trade's hold) for any future regime-conditioned
  strategy's own "did the regime gate matter" diagnostic.

Not done / next action — one hearing remains in the §6 budget:
1. **Slot 3: failed-breakout re-entry, continuation direction.** Cached H1 only, no
   new fetch needed. Must specify the CONTINUATION thesis (census correction, see
   archive/CENSUS-PIVOT-CYCLE.md) not the fade convention the census script used
   internally for signing. Not yet started. Needs its own spec-mapping proposal before
   any code, same PROMPTS.md §5.7 discipline slots 1-2 used.

Open tensions: TRADING-RULES §6's hearings budget now has 2 of 3 spent, 0 passes.
Slot 3 is the LAST hearing in this budget — per §6's own text, exhausting the budget
without any pass ends strategy search on this data window (until it materially renews,
≥12mo new candles). Worth flagging to the user before slot 3 starts: this is the final
shot in the current budget, not one of several remaining options. Do not reopen
trend_pullback, range_reversion, squeeze_breakout, the momentum hearing, or this carry
hearing — all closed permanently. Do not retry carry on GBP_USD/AUD_USD under this same
slot (spent) — those are §6-renewal candidates for a FUTURE data window, not a
same-window re-try. The EXPANSION-during-hold null result is not optional framing to
re-litigate — it is what the numbers say, same standing as every other archived
diagnostic in this codebase.

Files touched this session: `HANDOFF.md` (this rewrite, superseding the pre-code
version), `config.py`/`.env.example` (`FRED_API_KEY`), `bot/data/rates.py` (new),
`scripts/fetch_policy_rates.py` (new), `calibration/rates/*.parquet` + `fetched_at.txt`
(new, tracked), `bot/strategies/carry.py` (new), `bot/config/instruments.yaml`
(`carry_params` + `carry_calibration` for USD_JPY/GBP_JPY, TESTED), `scripts/
run_validation_gates.py` (carry registry entry, `_build_param_grid_carry`,
`compute_carry_expansion_diagnostic`), `scripts/diagnose_gates.py` (generalized
`expansion_veto_pass_rate`, carry diagnostic block), `tests/{test_rates,test_carry}.py`
(new), `TRADING-RULES.md` (two new §6 rows), `ROADMAP.md` (Closed Dispositions),
`archive/POST-MORTEMS.md` (§7, new).

Do NOT redo: this hearing (fixed real-data run, archived numbers final for this data
window) or slot 1's momentum hearing (unrelated, already closed). The sign-stability
exhibit's real-data recompute and the EXPANSION-during-hold diagnostic's null result
are not optional framing to re-litigate — they are what the numbers say, same standing
as every other archived diagnostic in this codebase.
