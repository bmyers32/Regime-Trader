---
Purpose: Domain law. Code contradicting this file is a bug by definition — fix the code or amend this file deliberately via the Change Log. Always active with CLAUDE.md.
---

# TRADING-RULES.md

## §1 Failure Catalog → Law (from TradingBotv3; never reintroduce)
1. 7-condition AND-stack ≈ zero signal probability → Entries = 2–3 hard gates + weighted confluence score w/ tunable threshold. Every evaluation journaled, incl. non-fires w/ vetoes.
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
