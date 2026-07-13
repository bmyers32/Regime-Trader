---
Purpose: Domain law. Code contradicting this file is a bug by definition — fix the code or amend this file deliberately via the Change Log. Always active with CLAUDE.md.
---

# TRADING-RULES.md

## §1 Failure Catalog → Law (from TradingBotv3; never reintroduce)
1. 7-condition AND-stack ≈ zero signal probability → Entries = 2–3 hard gates + weighted confluence score w/ tunable threshold. Every evaluation journaled, incl. non-fires w/ vetoes. EXEMPTION (§6, 2026-07-12): a strategy with exactly ONE scoreable component has no OR/AND arbitration to weight — it may be signal-only (confidence_score fixed, no score_weights/entry_threshold search), stated explicitly in that strategy's own spec-mapping, not silently omitted. Hard gates (regime/spread/blackout etc.) still apply in full; only the weighted-confluence machinery is exempted, and only when a second component would be decorative.
2. Raw-percent distance filters (EMA200±0.5% ≈ 95 pips GBP/JPY) vetoed fresh trends → All distance/width thresholds in ATR multiples or rolling percentiles. Raw price-percent banned.
3. Operator-precedence bug → negative TP → silent rejection of ALL bearish TF trades → SL/TP math unit-tested both directions per strategy. Rejections journaled loudly + dashboard-visible; N consecutive rejections trips breaker.
4. Unrounded floats → precision rejections → Precision registry from OANDA at startup; one rounding function for all outgoing prices; SL/TP validated on correct side of bid/ask.
5. Signals on forming candle → repainting → `complete==True` filter at data layer, everywhere incl. backtests.
6. Computed-but-unused indicators (dynamic RSI, ADX) → Every computed indicator is consumed or deleted. CODE-RECON flags unused as defect.
7. Always-true filter (`bb_width<0.05`) → Every threshold ships with a calibration note: empirical pass-rate on 6mo of target-pair data. Pass-rate >95% or <1% must be justified or rebuilt.
8. Timeframe identity confusion (said 30m/4h, fetched M15/H1) → Timeframes exist once, in config, by name. No literals in strategy code.
9. Re-entry spam + 15 correlated positions → Per-strategy/direction cooldown; dedup vs open positions within X×ATR; caps per pair AND per currency.
10. Fixed 5000 units → Risk-based sizing only (§4.1).
11. Mid-price signals, spread ignored → Backtester charges spread+slippage; live max-spread gate; spread journaled at entry.
12. Full 6-month refetch+recompute every 15min → Candle cache + incremental; a cycle touches only new closed candles.
13. "Backtest" = signal CSV, no PnL → Nothing is validated without event-driven PnL sim w/ costs + §5 gates.
14. Secrets in source → .env only; pre-commit grep for token patterns (`[0-9a-f]{32}-[0-9a-f]{32}`, account IDs) from Phase 1. Leak = revoke first, investigate second.

## §2 Regime Classifier
Anchor (higher) TF classifies; strategies execute on lower TF.
| State | Definition (calibrate per pair; note pass-rates) | Routes to |
|---|---|---|
| TRENDING_UP/DOWN | ADX(14)>25 AND EMA20/50/200 aligned AND MA slope persistent N bars | trend_pullback |
| RANGING | ADX<20 AND flat MA slope | range_reversion |
| EXPANSION | ATR(10)/ATR(50)>1.25 or ATR>1.3×60-bar mean | reduce size / stand aside |
| COMPRESSION | BB width < own 20th rolling percentile | arm squeeze_breakout |

Hysteresis mandatory: 2 consecutive closed anchor candles to switch; min hold M bars; regime+bars journaled every cycle. ADX 25–40 tradeable; >50 possible exhaustion → trend playbook takes no NEW entries.

**Timeframe selection law:** anchor:execution ratio 4–6:1. The TF pair is per-instrument, per-playbook config (§1.8) — never assumed. Candidates (default 4H/1H and 1H/15M) are validated as competing configurations through §5; winner = best net-of-cost OOS expectancy subject to a minimum trade count (a thin sample cannot win by luck). Expected biases to verify, not assume: higher TF → better spread-to-ATR efficiency + regime stability (suits trend_pullback, squeeze_breakout); lower TF → more trades, faster statistical significance, intraday session ranges (may suit range_reversion if middle-band targets clear ATR:spread ≥ 4:1).

## §3 Playbooks

### 3.1 trend_pullback (TRENDING only)
- Direction: HTF EMA alignment via merge_asof(direction='backward').
- Hard gates: regime matches direction; spread ≤ max; no blackout (§4.6).
- Score: price within 0.25–0.5×ATR of EMA20–EMA50 zone; ONE reversal trigger (engulfing OR ≥60%-body close OR HA flip); RSI>50 long/<50 short; pullback not beyond EMA200 zone.
- Exits: SL 1.5–2×ATR or beyond swing extreme; partial at 1R; trail remainder (ATR/Chandelier). No fixed far targets — trail harvests the fat tail that pays for ~40% win rate.
- Stand down: ADX<~20 or regime flip.

### 3.2 range_reversion (RANGING only — module v3 lacked)
- Long: close back INSIDE lower BB (re-entry close, not pierce) + RSI<30 turning up. Short mirrored at upper band.
- Targets: middle band (20 SMA) first; optional runner toward opposite band. Never hold for full traversal.
- SL: beyond rejection-candle extreme, ~1–1.5×ATR.
- Hard veto: any EXPANSION/ATR-spike signal instantly disables new entries (fading fresh breakouts = this playbook's death).
- Session: prefer London/NY; Asian-session behavior is per-pair calibration, not assumption.

### 3.3 squeeze_breakout (COMPRESSION→EXPANSION)
- Precondition: BB width < own rolling 20th percentile.
- Trigger: close beyond band + ATR expansion + ≥60% body.
- Optional false-break cut: next candle holds beyond level, or enter on retest.
- SL: opposite side of compression box or 1.5×ATR — NEVER opposite BB band.
- OANDA tick-volume = weak evidence: low-weight score component, never a hard gate.

## §4 Risk Invariants (risk layer enforces; strategies cannot override)
1. Risk/trade: fixed equity % (default 0.5–1.0%); units from actual SL distance + pip value.
2. Max positions per pair; aggregate exposure per currency (JPY legs across pairs count together).
3. Daily loss breaker (default 3R or 3%): pause until next UTC day + dashboard flag.
4. Rejection breaker: N consecutive rejections → pause + alert.
5. Cooldown per strategy/direction; dedup vs open positions within X×ATR.
6. Blackout: no new entries ±15–30min around high-impact events for the pair's currencies (BoE/BoJ/Fed/NFP/CPI). Calendar absent → trade normally, journal the gap.
7. Weekend/market-hours aware; no cycles vs closed market.
8. Kill switch: halt new entries immediately; close-all requires typed confirmation.
9. Instrument control: remote enable/disable via dashboard. Disable = no new entries, open positions managed (flatten = separate confirmed action). Enable requires instruments.yaml entry with calibration notes (§1.7); bot refuses + journals uncalibrated pairs. §5 validation is PER PAIR — validated on GBP/JPY ≠ validated on EUR/USD.

## §5 Validation Gates (order mandatory; no skipping)
1. Unit tests: indicators vs known-good values; SL/TP both directions; sizing math.
2. Backtest w/ costs (spread, slippage, rollover), ≥2yr per pair per playbook.
3. IS/OOS split (~70/30) then walk-forward (optimize rolling window → test next unseen segment → roll); judge stitched OOS equity curve only.
4. Parameter stability: ±10% neighbors perform similarly; sharp peak = overfit = reject.
5. Per-regime attribution: expectancy, win%, maxDD per playbook per regime. Negative in home regime → does not ship.
6. Monte Carlo trade-order shuffles → drawdown confidence intervals.
7. Practice forward-test ≥60 days, identical code path; live gate = forward expectancy within tolerance of backtest + explicit user sign-off (Phase 11).

## §6 Change Log
| Date | § | Change | Reason |
|---|---|---|---|
| (seed) | all | Initial law: v3 post-mortem + regime research | Rebuild baseline |
| 2026-07-10 | 5 (new) | Revival budget: a CLOSED playbook (§5 gates FAILED, verdict rendered and recorded) gets exactly ONE revival attempt per data window. The attempt must enter via PROMPTS.md §5.7's required sequence and name a genuinely new edge-thesis mechanism (different trigger/zone/exit definition, different regime-routing dependency, etc.) — not a parameter retune on the same spec. Budget is per (playbook, data window) pair; status as of this entry: none spent (trend_pullback and range_reversion are both closed, zero revival attempts used by either). | Prevent unbounded FAIL-revival churn: a closed, evidenced verdict (BRAIN.md: "A clean FAIL with reasons is a deliverable") must stay closed absent a genuinely new mechanism, or the FAIL-then-retry cycle degrades into parameter-hunting with extra ceremony — the exact outcome §1.7's always-true-filter law and §5's gates exist to prevent. |
| 2026-07-12 | 6 (new) | Pivot-cycle hearings budget: THREE full §5 hearings for the current data window. Slots 1–2 pre-claimed on external-evidence grounds: D1/H4 time-series momentum; carry-with-regime-conditioning. Slot 3 awarded only by census evidence, to at most ONE candidate; all others recorded and closed. The cap governs hearings, not winners: every hearing that passes gates proceeds to §5 sign-off and ships — multiple passes all ship, routing per §2. The Phase 11 forward test (≥60 days, unseen data) is the final arbiter for every pass. Exhausting the budget without any pass ends strategy search on this window. Renews only when the data window materially renews (≥12 months of new candles). | All three playbooks closed FAILED with zero revival spent (§6 entry above); squeeze_breakout's §2 post-mortem (archive/POST-MORTEMS.md §5) surfaced "trend inception from compression" as an untested population distinct from either dead thesis — a structured, budgeted pivot replaces unbounded re-tries against closed theses, per BRAIN.md "decide which diagnostic wins before either diagnostic exists." |
| 2026-07-12 | 1.1 (amend) | §1.1 exemption: a single-scoreable-component strategy may be signal-only (no weighted confluence, no score_weights/entry_threshold search) — hard gates unaffected. See §1.1's own text for the exact wording. | D1/H4 time-series momentum (slot 1) has exactly one component (sign of trailing N-day return); a second decorative score component would repeat the exact always-true-filter/padded-AND-stack failure mode §1.1 itself exists to prevent, just inverted (padding for its own sake rather than over-gating). Recorded as law before momentum's spec-mapping proceeds, not as an unstated implementation shortcut. |
| 2026-07-12 | 6 (amend) | Slot 1 (D1/H4 momentum) hearing spec-mapping resolved, pre-code: signal-only per the 1.1 exemption above; `RegimeResult` gains an optional `htf_window` field (read-only convention, no-lookahead-tested) so a strategy can consult raw anchor-TF price history without changing `generate_signal`'s contracted signature; ATR/Chandelier trail is the exit (no new engine surface); EUR_USD + GBP_JPY are the two target pairs; a gate-3 floor-miss ("structurally too thin at D1") SPENDS the slot exactly like an evaluated FAIL and licenses no downward-timeframe search; scope is short-horizon momentum only (effective N∈{20,60}, N=120 kept in the grid but flagged near-untestable under this window's IS sizing, literature's 12-month lookback untestable on this data window at all — §6's renewal clause is the lawful path to testing it later); gate 4's stability sweep includes N via int-aware rounded perturbation rather than repeating the rejection_lookback_bars-style exclusion precedent. Full amendment record (A1–A8): HANDOFF.md this date. | Every prior FAIL (trend_pullback, range_reversion, squeeze_breakout) was diagnosed on H1 execution data (archive/POST-MORTEMS.md gross-vs-net table) — this is the first hearing at D1 anchor granularity, and the spec-mapping questions it raises (signal-vs-score structure, anchor-data access, exit mechanics, rollover at multi-week spacing, honest thin-sample accounting) are load-bearing enough to resolve and record before any strategy code exists, per PROMPTS.md §5.7. |
| 2026-07-12 | 6 (slot 1 SPENT) | D1/H4 momentum hearing executed and CLOSED: FAIL §5 gates 3/4/6, EUR_USD/GBP_JPY, decisively — not a floor-miss (109/105 stitched OOS trades). Gate 4 independently flags N as the sharpest, sign-flipping stability dimension in BOTH pairs regardless of which N each pair's search actually used — the fragility is not confined to N=120's known handicap, so the short-horizon scope (A6) does not rescue the verdict. Pre-registered A3/A7 sign-flip diagnostic found a null result on signal-flip exit as a revival mechanism (balanced, not flip-dominated split) — no obvious revival target handed forward. 2 of 3 hearings remain in the budget (carry-with-regime-conditioning, slot 2; failed-breakout re-entry continuation, slot 3). | Full numbers, both pairs' gross-vs-net/duty-cycle/rollover-share/per-regime/per-session exhibits, and the complete A3/A7 diagnostic: archive/POST-MORTEMS.md §6. |
| 2026-07-13 | 6 (amend) | Slot 2 (carry-with-regime-conditioning) hearing spec-mapping resolved, pre-code: signal = sign of a real historical policy-rate differential fetched from FRED (the project's first non-OANDA data dependency, `calibration/rates/`, TRACKED not gitignored), no minimum-differential threshold searched (zero free signal parameters this hearing); EXPANSION on the D-anchor vetoes NEW entries only (journaled, no mid-hold flatten — the hearing's own centerpiece regime-conditioning mechanic, the first strategy to gate directly on the classifier's confirmed `regime.regime`); same ATR/Chandelier trail exit every playbook uses; USD_JPY + GBP_JPY are the two target pairs (confirmed static-positive-differential, JPY-funded, "home terrain," per a real-data sign-stability exhibit); rollover cost (constant present-day OANDA snapshot) and the signal (time-varying historical FRED differential) are explicitly different conventions, stated not reconciled. Full amendment + build-rider record: HANDOFF.md this date. | The signal-source problem (a constant financing-rate snapshot is a valid cost model but a degenerate signal) had to be resolved before any spec existed — the first hearing needing an external, non-broker data source, raising genuinely new questions (no-lookahead convention for a non-candle data type, tracked-vs-gitignored calibration data, sign-stability as a pair-selection gate) load-bearing enough to resolve and record before any strategy code exists, per PROMPTS.md §5.7. |
| 2026-07-13 | 6 (slot 2 SPENT) | Carry-with-regime-conditioning hearing executed and CLOSED: FAIL §5 gates, USD_JPY/GBP_JPY, via a failure signature never seen in this codebase before — gate 3 (walk-forward net PnL) genuinely PASSES on BOTH pairs (net_pnl=+414.84/104 trades, +386.45/101 trades), not a floor-miss, but gate 6 (bootstrap) decisively rejects both at nearly identical probabilities (P(net_pnl≤0)=22.5%/22.3%, both far above the ≤5% bar) — a real edge existed over this stitched OOS record but is not statistically distinguishable from noise. Gate 4 splits (USD_JPY FAIL on exit-parameter sensitivity, GBP_JPY PASS) but per this hearing's own pre-registered scope caveat measures exit-parameter stability only (zero signal parameters existed to sweep), so neither result speaks to the signal's own robustness — gate 6's shared signature across both pairs is decisive. Pre-registered EXPANSION-during-hold diagnostic returns a clean null on both pairs (essentially 0% of losing-trade PnL coincided with EXPANSION during the hold, despite the veto genuinely binding 21.4%/37.9% of consulted entries) — the hearing's own centerpiece regime-gate does not explain the losses, so no revival target is handed forward. Verdict-combination reading (pre-registered): both FAIL means carry is closed at its own home terrain, not one strong result needing a second look. Scope: confined to a regime-conditioned STATIC short-JPY position (both target pairs' real differentials never changed sign this window) — GBP_USD/AUD_USD (confirmed dynamic-differential pairs) remain untested and are the lawful renewal candidates for actually testing a switching signal. 3 of 3 hearings now spent (0 passes); TRADING-RULES §6's own text: exhausting the budget without any pass ends strategy search on this window, pending only slot 3 (failed-breakout re-entry) which remains unrun. | Full numbers, both pairs' gate 3/4/6/gross-vs-net/duty-cycle/rollover-share/per-regime exhibits, the real-data sign-stability recompute, and the complete EXPANSION-during-hold + EXPANSION-veto-rate diagnostics: archive/POST-MORTEMS.md §7. |
