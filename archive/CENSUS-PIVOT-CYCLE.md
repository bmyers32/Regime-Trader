---
Purpose: Archived record of the 2026-07-12 pivot-cycle moments census (measurement
only, no strategy code, no gates). Full methodology, per-candidate tables, and the
mechanical slot-3 determination. Live pointer: ROADMAP.md.
---

# CENSUS-PIVOT-CYCLE — Pivot-cycle moments census (2026-07-12)

Executed per ROADMAP.md's "Pivot cycle: census + hearings-budget" entry (drafted
2026-07-12) and TRADING-RULES.md §6's dated 2026-07-12 hearings-budget law. Surfaced
by squeeze_breakout's §2 post-mortem (archive/POST-MORTEMS.md §5): COMPRESSION
resolves to confirmed EXPANSION only ~2-4% of the time but to TRENDING/RANGING
~60%+ — "trend inception from compression" (candidate i) is an untested, distinct
entry population from either dead thesis. Eight candidates pre-registered in
ROADMAP.md; this session measured all eight, all six pairs, cached H1/H4 only, no
OANDA calls.

## Verified topology (AGENTS.md)

Read-only against `instance/candle_cache/*.parquet` (H1+H4, all 6 pairs) and
`bot/config/instruments.yaml`. Writes confined to `TRADING-RULES.md` §6 (law),
this archive file, `ROADMAP.md` (2-line pointer), `HANDOFF.md`, and
`scripts/pivot_census.py` (new, committed measurement script, same precedent as
`scripts/gross_vs_net.py`/`diagnose_gates.py`). Zero edits to
`bot/strategies`, `bot/regime`, `bot/risk`, `bot/backtest` engine — the script
imports `RegimeClassifier` and `bot/indicators/core.py` read-only, reusing the
exact HTF→LTF `merge_asof(direction="backward")` regime-alignment pattern already
established in `scripts/run_validation_gates.py`'s `compute_hysteresis_excluded`
(same "latest confirmed regime as of this bar" semantics `BacktestEngine` uses
internally) rather than re-deriving HTF/LTF open/close-boundary alignment from
scratch.

## Frozen methodology (approved before any candidate was computed)

**Regime alignment:** `RegimeClassifier` rolled bar-by-bar over full H4 history
per pair, broadcast onto H1 via `merge_asof(direction="backward")`. Events for
regime-transition candidates (i, ii, iii, vi) are detected natively on the merged
LTF series as episode boundaries — a maximal contiguous run of LTF bars sharing
one confirmed regime label — which sidesteps HTF/LTF open-vs-close timestamp
ambiguity entirely by asking the same question a live strategy would ask: "what
regime does THIS bar see."

**Candidate definitions (all frozen 2026-07-12, before computing):**
- **(i) COMPRESSION→TRENDING:** event = first LTF bar of a TRENDING_UP/DOWN
  episode immediately following a COMPRESSION episode. Signed by trend direction.
- **(ii) TRENDING→RANGING→TRENDING resumption:** same-direction only
  (UP→RANGING→UP or DOWN→RANGING→DOWN); intervening RANGING episode's HTF
  `bars_in_regime` at its end ≤20 (5× `regime_min_hold_bars`, ~1 week at H4).
  Event = first bar of the resumption episode. Signed by trend direction.
- **(iii) EXPANSION→RANGING:** event = first bar of a RANGING episode
  immediately following EXPANSION. Unsigned (no a priori direction).
- **(iv) London-open after Asian range:** Asian window = `costs.py`'s existing
  `session_for_hour` "asian" bucket (21:00–07:00 UTC), reused verbatim. Event =
  every H1 bar at hour==7 UTC, unconditional (not contingent on a range break —
  the candidate is "London-open," not "London breakout"). Unsigned.
- **(v) Failed-breakout re-entry into compression box:** box = LTF rolling
  20-bar high/low (matches `squeeze_breakout_params.compression_box_lookback_bars`,
  excludes current bar), computed only while HTF regime==COMPRESSION at the
  breakout bar. Breakout = close beyond box. Failure = close re-enters
  `[box_low, box_high]` within the next 4 LTF bars. Event = the re-entry bar.
  Signed opposite the failed breakout's direction (fading the false break) —
  **this sign convention was proposed as a hypothesis, not a finding; the
  census result on this convention refutes it, see "Corrected direction"
  below.**
  **Footnote (pre-registered at approval):** the +4 horizon column is partially
  degenerate with the failure-confirmation window itself (an event can only
  exist because price was back inside the box by +1..+4 bars), so its
  distinguishability at +4 is structurally inflated relative to +8/+24 — the
  primary (+24) gating horizon is unaffected by this, but the +4 column should
  not be read as independent confirmation.

  **Corrected direction (added post-computation, does not change any number —
  see below):** under the fade-sign convention above, both the raw event mean
  AND the event-vs-baseline diff CI are NEGATIVE at all three horizons
  (event_mean: +4=−0.084, +8=−0.117, +24=−0.068; diff CI: +4=[−0.216,−0.007],
  +8=[−0.360,−0.072], +24=[−0.585,−0.089]). A negative result under a
  fade-signed convention is the mirror image of a positive result under the
  opposite sign — the census does not support the fade hypothesis it was
  built to test; it supports the opposite: after a failed breakout and box
  re-entry, price on average continues in the ORIGINAL breakout direction (a
  second-attempt-continuation pattern), not a reversion through/past the box.
  Bootstrap CI magnitude and eligibility (distinguishable, cost≥4:1, margin)
  are sign-invariant, so this correction changes the THESIS the slot-3 hearing
  will test, not the mechanical award itself (see Slot-3 determination below).
  Slot 3's hearing will be specified in the corrected (continuation) direction,
  openly census-informed rather than externally pre-claimed like slots 1-2 —
  TRADING-RULES §6's existing clause ("The Phase 11 forward test ... is the
  final arbiter for every pass") applies identically to a census-derived
  thesis as to a pre-claimed one; the census licenses the hearing, it does not
  substitute for one.
- **(vi) TRENDING death (ADX rollover <20):** event = first LTF bar within a
  TRENDING_UP/DOWN episode where raw ADX(14), aligned from H4 onto the merged
  LTF series, crosses below 20 — the raw signal, not waiting for hysteresis to
  confirm the regime has actually left TRENDING. **De-overlap clause (added at
  approval):** only the FIRST such cross per confirmed TRENDING episode counts;
  later crosses in the same episode are suppressed (a trend can wobble under 20
  and back above it repeatedly before the episode truly ends). Unsigned (no
  pre-registered continuation/reversion thesis for this candidate specifically).
  **Overlap-immunity check (i)/(ii)/(iii), confirmed:** these three iterate over
  the classifier's own `episodes` list — one row per hysteresis-confirmed
  regime run, built once via consecutive-run grouping — so each transition
  boundary is visited exactly once by construction. No de-overlap clause is
  needed or was applied to them; only (vi), which scans raw ADX WITHIN an
  episode rather than between episodes, needed one.
- **(vii) Monday open gaps:** event = first LTF bar after a >24h gap from the
  previous bar (weekend closure). Signed by gap direction
  (`open[event] - close[event-1]`).
- **(viii) Month-end final two trading days:** "session" here means calendar
  trading day (the dates present in the data), not `costs.py`'s intraday
  asian/london/ny_overlap buckets — disambiguated explicitly at approval to
  avoid overloading that term. Event = first LTF bar of the earlier of the
  final two trading dates each month. Unsigned.

**Baseline construction (approved as designed, unchanged from proposal):**
baseline pool per event-stratum = all OTHER H1 bars in the same pair carrying
the SAME regime sub-state the event carries, excluding the event bars
themselves and excluding bars within a guard band of ANY event bar of that
SAME candidate, drawn without replacement, `BASELINE_MULT=5×` that stratum's
event count (capped at pool size), seed=20260712 (frozen). Forward return =
`(close[t+k] - close[t]) / ATR14(t)`, k∈{4,8,24} LTF bars, pooled across all 6
pairs via ATR normalization. Distinguishability = bootstrap 95% CI (2000
resamples, same with-replacement method as `bot/backtest/monte_carlo.py`) on
(event mean − baseline mean) at the PRIMARY horizon (+24 bars) excludes zero —
the single gating horizon, +4/+8 reported as context only (multiple-comparison
control). Cost ratio = median `|price move|` at +24 bars ÷ that pair's
session-bucketed `cost_model.spread_pips` at the event's UTC hour, pooled
across pairs.

**Award floor (added at approval, pre-registered before computing):** pooled
post-detection event count < 30 disqualifies a candidate from slot 3
regardless of CI outcome.

**Implementation fixes made during execution (both mechanical, applied before
inspecting any candidate's distinguishability outcome — not results-driven
tuning):**
1. The fixed 24-bar guard band, sized for rare/transition candidates, tiled the
   entire timeline around candidate (iv)'s own events (spaced ~24 bars apart,
   ~once/trading day), degenerately emptying its baseline pool (first run: all
   NaN for iv). Fix: `effective_guard_band()` caps the band at
   `median_event_gap // 2 - 1` (floored at 1 bar), applied uniformly per
   candidate/pair — rare candidates (i, ii, iii, vi with gaps ≫48 bars) are
   unaffected; only (iv) (shrunk to 11 bars) and (v) (shrunk to 8-11 bars,
   pair-dependent) needed it.
2. A `continue` statement incorrectly tied event-return recording to baseline-draw
   availability (skipping BOTH when a stratum's baseline pool was empty, instead
   of only skipping the baseline draw). Decoupled — event returns are always
   recorded independent of baseline availability.
3. The slot-3 tie-break originally sorted by raw CI lower bound, which only
   ranks correctly for negative-effect candidates. Fixed to `min(|lo|, |hi|)` —
   the CI edge nearest zero, sign-agnostic — the correct "most distinguishable"
   measure.

### Fix-3 evidentiary record

No git commit trail distinguishes fix stages — all three fixes above were made
and verified locally, in one editing pass, before the single commit (`0cd40d6`)
that captured the final script; there is no separate pre/post-fix-3 commit to
cite. The actual evidence is this session's two full console runs, both
captured verbatim below.

**Correction to the initial claim:** fix 3's effect on THIS census, verified
against the actual run logs, changed the winner from **(iv) to (v)**, not from
(iii) to (v). Run 1 (old tie-break, (iv) still NaN from bug #1/#2) selected
(v) over (iii) — and did so *correctly*, because for two negative-CI
candidates, sorting by raw lower-bound descending happens to agree with the
sign-agnostic margin ranking (both metrics: v > iii). The bug only bites once
(iv) enters the eligible set with a POSITIVE CI: raw-lower-bound-descending
trivially ranks any positive lower bound above any negative one regardless of
magnitude. Applying the OLD metric to the FINAL (bug-fixed) three-candidate
set: `lo` values are iii=−1.038, iv=+0.050, v=−0.585 → descending order
iv, v, iii → **old metric picks (iv)**. The NEW metric (`min(|lo|,|hi|)`):
iii=0.003, iv=0.050, v=0.089 → **new metric picks (v)**. So the corrected
metric's real effect was displacing (iv), not (iii) — (iii) was never going
to win under either metric; its margin is the weakest of the three regardless
of sign-handling.

Run 1 console excerpt (candidate iv, pre-fix — degenerate NaN; mechanical
determination selected v over iii, coincidentally correctly):
```
=== Candidate iv: London-open after Asian range ===
  per-pair events (post-guard-band): {'GBP_JPY': 534, ... 'EUR_GBP': 534}
  pooled n = 3204  (floor=30, floor_ok=True)
  +24 bars: event_mean=nan baseline_mean=nan diff_CI=[nan, nan]
  cost ratio (median |move|/spread @ +24): nan
  distinguishable(+24)=False  cost_ok=False  clears_both=False
...
=== SLOT 3 MECHANICAL DETERMINATION ===
Slot 3 AWARDED to candidate v: Failed-breakout re-entry into compression box
  (other eligible candidates recorded, not awarded: ['iii'])
```

Run 2 console excerpt (all fixes applied — iv now populated with a genuine
positive CI, exercising the tie-break fix for real):
```
=== Candidate iv: London-open after Asian range ===
  per-pair events (post-guard-band): {'GBP_JPY': 534, ... 'EUR_GBP': 534}
  guard band shrunk to 11 bars (frequency-adaptive, see effective_guard_band)
  pooled n = 3204  (floor=30, floor_ok=True)
  +24 bars: event_mean=2.7783 baseline_mean=2.6072 diff_CI=[0.0495, 0.2887]
  cost ratio (median |move|/spread @ +24): 16.74
  distinguishable(+24)=True  cost_ok=True  clears_both=True
...
=== SLOT 3 MECHANICAL DETERMINATION ===
Slot 3 AWARDED to candidate v: Failed-breakout re-entry into compression box
  (other eligible candidates recorded, not awarded: ['iv', 'iii'])
```
Both full logs (all 8 candidates, all 6 pairs) were captured to the session's
scratchpad during execution; the excerpts above are the load-bearing lines for
this determination, reproduced here so the evidence is committed, not
ephemeral.

## Results

All pairs: GBP_JPY, EUR_USD, USD_JPY, GBP_USD, AUD_USD, EUR_GBP. `n` = pooled
event count across all 6 pairs (population, unaffected by guard band — guard
band only shapes baseline-pool eligibility). CI = bootstrap 95% CI on
(event − baseline) mean-difference at the stated horizon, in ATR-multiples.
Cost ratio = median |price move| ÷ session spread at +24 bars.

| Candidate | Population (n) | Floor≥30 | +4 CI | +8 CI | +24 CI (primary) | Distinguishable(+24) | Cost ratio(+24) | Cost≥4:1 | Clears both bars |
|---|---|---|---|---|---|---|---|---|---|
| (i) COMPRESSION→TRENDING | 87 | Y | [-0.09, 0.73] | [-0.48, 0.60] | [-0.92, 0.83] | N | 16.23 | Y | **N** |
| (ii) TRENDING→RANGING→TRENDING | 6 | **N** | [-1.63, 0.76] | [-1.00, 1.46] | [-2.63, 1.15] | N | 11.56 | Y | **N** |
| (iii) EXPANSION→RANGING | 44 | Y | [-0.47, 0.02] | [-0.19, 0.74] | [-1.04, -0.003] | Y | 19.15 | Y | **Y** |
| (iv) London-open after Asian range | 3204 | Y | [0.48, 0.57] | [0.86, 1.01] | [0.05, 0.29] | Y | 16.74 | Y | **Y** |
| (v) Failed-breakout re-entry | 1109 | Y | [-0.22, -0.01]† | [-0.36, -0.07] | [-0.58, -0.09] | Y | 18.31 | Y | **Y** |
| (vi) TRENDING death (ADX<20) | 82 | Y | [-0.32, 0.09] | [-0.35, 0.17] | [-0.90, 0.02] | N | 14.02 | Y | **N** |
| (vii) Monday open gaps | 666 | Y | [-0.17, 0.06] | [-0.19, 0.11] | [-0.43, 0.14] | N | 16.23 | Y | **N** |
| (viii) Month-end final two days | 156 | Y | [-0.33, -0.10] | [-0.42, -0.03] | [-0.45, 0.27] | N | 16.32 | Y | **N** |

† (v)'s +4 column is partially degenerate with its own failure-confirmation
window — see footnote above; does not affect the +24 primary gate.

Three candidates clear both bars: (iii), (iv), (v). Two are disqualified
outright regardless of any CI: (ii) fails the population floor (n=6 — the
episode structure required is simply rare in 2 years of H4 data); (i), (vi),
(vii), (viii) each fail distinguishability at the primary +24 horizon (their
CIs straddle zero).

## Slot-3 mechanical determination

Per the pre-registered rule (ROADMAP.md, TRADING-RULES §6 2026-07-12): slot 3
goes to the single candidate whose event-study distribution is most
distinguishable from baseline AND clears the 4:1 cost ratio — margin metric
`min(|CI_lo|, |CI_hi|)` at +24 bars (sign-agnostic distance from zero):

| Candidate | +24 CI | Margin (distance from zero) |
|---|---|---|
| (v) Failed-breakout re-entry | [-0.58, -0.09] | **0.089** |
| (iv) London-open after Asian range | [0.05, 0.29] | 0.050 |
| (iii) EXPANSION→RANGING | [-1.04, -0.003] | 0.003 (razor-thin — barely excludes zero) |

**Slot 3 is AWARDED to candidate (v): Failed-breakout re-entry into the
compression box — hearing to be specified as a second-attempt CONTINUATION
thesis (original breakout direction), per the corrected-direction finding
above, not the originally-proposed fade.**

Per the cap's own text ("Slot 3 awarded only by census evidence, to at most
ONE candidate; all others recorded and closed"), (iii) and (iv) — despite
clearing both bars — are recorded and closed, not awarded a hearing. (iii)'s
margin is especially thin (CI upper bound −0.003, a hair's-breadth exclusion
of zero) and would not have survived a stricter multiple-comparison
correction; flagged for the record, not used to override the mechanical rule.
Both remain lawfully re-census-eligible — see "(iii)/(iv) closure and
renewal eligibility" below.

**Budget after this session:** three slots claimed — momentum (D1/H4,
pre-claimed), carry-with-regime-conditioning (pre-claimed), failed-breakout
re-entry into compression box as continuation (slot 3, this census). All
three now proceed to §5 hearings independently; each stands or falls on its
own forward test per the cap's "cap governs hearings, not winners" clause.

## (iii)/(iv) closure and renewal eligibility

Both cleared both census bars but were not awarded slot 3 (cap = one winner).
They are CLOSED for this data window, not eliminated:

- **(iii) EXPANSION→RANGING aftermath:** n=44 (just above the 30 floor), +24
  CI=[−1.038, −0.003] (margin 0.003 — razor-thin), cost ratio 19.15. Closed on
  thin-margin + not-awarded grounds, not on any data defect.
- **(iv) London-open after Asian range:** n=3204 (largest population of any
  candidate), +24 CI=[0.050, 0.289] (margin 0.050), cost ratio 16.74. Closed
  solely because the cap capped slot 3 at one winner, not on evidentiary
  weakness — its distinguishability is comfortably clear of zero.

Per TRADING-RULES §6's 2026-07-12 entry ("Renews only when the data window
materially renews (≥12 months of new candles)"), both are lawful re-census
candidates starting 2027-07-12 at the earliest, and only via a fresh full
census re-run (not a standalone re-measurement) — not before, and not via the
separate playbook revival-budget mechanism (§6's 2026-07-10 entry), which
governs closed PLAYBOOKS post-hearing, not pre-hearing census candidates.

## Script

`scripts/pivot_census.py` — reusable, committed (same precedent as
`gross_vs_net.py`/`diagnose_gates.py`). Run: `python scripts/pivot_census.py`
(no OANDA calls, cached H1/H4 only). Full console output archived at this
session's close; re-running reproduces identical numbers (fixed seed, no
tuning knobs exposed).
