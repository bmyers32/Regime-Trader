"""
squeeze_breakout: COMPRESSION-only playbook (TRADING-RULES §3.3).

Spec-mapping decisions (approved 2026-07-10, recorded in HANDOFF.md before this file was
written; full reasoning there and in the approved plan doc):

DISPOSITION 1 (precondition): §3.3's "Precondition: BB width < own rolling 20th
percentile" is VERBATIM §2's own COMPRESSION regime definition -- it IS the regime gate,
not an independently-computed second check. Hard gate A (the ONLY hard gate this
strategy applies): generate_signal() returns None outright when regime != COMPRESSION,
same "not consulted" semantics as trend_pullback's only gate. Unlike range_reversion,
NO LTF-level defensive veto is added: RR's veto exists to protect against fading a fresh
breakout while still routed to a stale, dangerous regime; squeeze_breakout has no
analogous danger since it WANTS the breakout, and §2's own routing table forbids the
overlap anyway (EXPANSION routes to "reduce size/stand aside", a different instruction
entirely -- if this strategy also fired during EXPANSION that would contradict §2's
one-regime-one-playbook routing, not extend it).
KNOWN LIMITATION, explicitly not fixed this phase: because regime_confirm_bars=2 must be
satisfied on 2 CONSECUTIVE HTF closes before EXPANSION is confirmed, a genuine
slow-developing breakout can have the HTF regime already flip to EXPANSION before the LTF
trigger conditions actually fire here -- silently excluding an entry generate_signal()
never even evaluates (it returns None before reaching the trigger). This is a
missed-entry risk, not a safety risk (contrast RR's veto, built to prevent an UNSAFE
entry). Made measurable, not just documented: _evaluate_trigger below is factored out of
generate_signal specifically so scripts/run_validation_gates.py's hysteresis-excluded
diagnostic can replay the SAME scoring math on LTF bars where regime has just left
COMPRESSION, without duplicating the scoring logic. See that script for the
pre-registered decision rule on what a large hysteresis-excluded count implies.

Full TRADING-RULES §1.1 gate accounting for this playbook (2-3 hard gates + weighted
confluence):
  - Hard gate A: regime routing (COMPRESSION only) -- see above.
  - Hard gates B/C: spread gate + entry blackout -- ENGINE level
    (bot.backtest.costs.spread_gate_ok / entry_blackout_ok), same shared infrastructure
    the other two playbooks rely on. Not reimplemented here.
  - Weighted confluence (4 components, DISPOSITION 2/3): close_beyond_band,
    atr_expansion, body_pct (§3.3's three named "+"-joined trigger conditions) +
    tick_volume (§3.3's own "low-weight score component, never a hard gate" instruction
    -- included, not omitted, per disposition 3: the law is explicit, so silently
    dropping it would be a silent deletion, not a defensible simplification). All four
    are uniform (score, reason) 2-tuples, NEVER appended to vetoes -- same convention
    trend_pullback's 2026-07-09 law-drift fix established and range_reversion's scored
    components already follow. vetoes is structurally ALWAYS empty for this strategy
    (regime-routing is the only hard gate it applies), matching trend_pullback's shape,
    not range_reversion's (which carries one real veto for its own, unrelated reason).

DISPOSITION 2 (trigger scoring / AND-OR-N-of-M pre-registration): three of the four
scored components are BINARY (0/1) per §3.3's own literal conditions (a close either is
or is not beyond the band; body either does or does not clear 60%; §3.3 gives no
magnitude-based scoring instruction for any of them, so none is invented here). With
their weights summing to 1.0 across 4 components, confidence_score can only take one of
at most 2^4=16 discrete values -- richer than range_reversion's 2-component OR/
asymmetric/AND trichotomy but the same underlying phenomenon (Phase 6's AND/OR lesson).
scripts/run_validation_gates.py's classify_threshold_regime_general (new, additive --
does NOT touch range_reversion's existing 2-component classify_threshold_regime or its
registry entry) generalizes the classification to any component count by enumerating
minimal covering subsets. If a walk-forward window's IS selection lands on a subset that
does not require ALL of close_beyond_band/atr_expansion/body_pct together, that overrules
§3.3's literal "+" for that window and must be stated explicitly wherever this playbook's
calibration_note is written per pair -- not silently accepted, same standard as RR's
disposition 1.

DISPOSITION 3 (tick-volume): weight fixed low (0.1, at most 0.15 across the whole grid,
see instruments.yaml) so it can never single-handedly clear a meaningful threshold nor
substitute for a missing real trigger. Data source: OANDA's own `volume` column (tick
count) already flows through bot/data/fetcher.py into every cached candle -- this is
genuinely "OANDA tick-volume" per §3.3's own phrase, not a stand-in.

DISPOSITION 4 (optional false-break confirmation, §3.3's "next candle holds beyond
level, or enter on retest"): OUT this pass, deferred to ROADMAP.md as the pre-registered
revival-budget candidate (TRADING-RULES §6) -- building it now needs new engine
machinery (retest/N-bar-hold entry timing the engine doesn't support for any strategy
yet) and would collapse the pre-registered false-break-vs-insufficient-expansion
post-mortem split before the evidence exists to justify spending it.

DISPOSITION 5 (SL): min(compression-box opposite side, entry -+ sl_atr_mult*ATR),
whichever is FARTHER/more protective -- reuses trend_pullback's "whichever is farther"
convention (the one existing precedent for an unranked "X or Y" SL alternative in this
codebase), not range_reversion's fixed-ATR-mult-only convention (§3.2's text had no "or"
alternative to begin with). "Compression box" = the high/low extreme over
compression_box_lookback_bars immediately PRECEDING the trigger bar (excludes the
trigger bar itself -- including it could place the SL absurdly close for a strong
breakout candle). sl_atr_mult=1.5 is §3.3's own exact number (no range given, unlike
§3.1/§3.2, so no midpoint decision needed).

DISPOSITION 6 (exit/TP -- a real gap in §3.3's letter, not one of the original 5
dispositions, flagged Medium-ambiguity per AGENTS.md's Entry Protocol): tp=None, reusing
the EXISTING exit_cfg partial-at-1R + ATR/Chandelier trail machinery (bot/backtest/
engine.py._check_exit_with_trailing) rather than a fixed target. §3.3 says nothing about
targets at all -- unlike range_reversion's explicit middle-band TP and trend_pullback's
explicit partial+trail language. A squeeze-breakout's post-trigger price action is
directionally a nascent trend/expansion move -- the same character exit_cfg's trail was
built for -- and a fixed TP would cap the fat tail a trailed exit exists to keep,
contradicting the kickoff's own "cost-tolerant, larger-target" framing for this playbook.
Own squeeze_breakout_params.exit block (own partial_at_r/trail_atr_mult/
trail_atr_period), not copied from trend_pullback's numbers.

DISPOSITION 7 (§2 consultation-window experiment, TRADING-RULES §2/§3.3, dated
2026-07-11 -- addresses DISPOSITION 1's KNOWN LIMITATION above via §2 regime-routing,
not a trigger/revival-budget change): Hard gate A is amended. generate_signal now
consults when regime==COMPRESSION (unchanged) OR (regime==EXPANSION AND
regime.prior_regime==COMPRESSION AND regime.bars_in_regime<=regime_confirm_bars) --
this is the unit-correct HTF-bar-denominated equivalent of "N=htf_ltf_ratio x
regime_confirm_bars LTF bars past a confirmed COMPRESSION->EXPANSION transition"
(regime.bars_in_regime is HTF-denominated; N's own LTF-bar derivation collapses to
regime_confirm_bars once expressed in HTF-bar units -- see TRADING-RULES §2). The SL's
compression box FREEZES at the COMPRESSION-exit boundary for these consultation-window
entries (_stop_loss's box_offset, tracked via self._ltf_bars_since_compression, an
independent LTF-bar counter) rather than sliding with the live lookback -- a frozen box
mechanically widens the SL for later entries within the window, which biases the (a)/(b)
false-break split toward (b) on geometry alone; scripts/gross_vs_net.py's early/late
(bars_in_regime==1 vs ==2) stratification separates that from a genuine
confirmation-quality signal. No other playbook's routing changes.
"""

from __future__ import annotations

import pandas as pd

from bot.indicators.core import atr as _atr
from bot.indicators.core import bb_breakout_long as _bb_breakout_long
from bot.indicators.core import bb_breakout_short as _bb_breakout_short
from bot.indicators.core import bollinger_bands as _bollinger_bands
from bot.indicators.core import body_pct as _body_pct
from bot.regime.classifier import RegimeResult, RegimeState
from bot.strategies.base import Signal

# ATR14's 60-bar rolling mean (used by the atr_expansion trigger component) needs
# several multiples of 60 bars to stabilise -- same "accuracy improves after ~3x period"
# warmup convention ATR/ADX/EMA200 already use elsewhere in this codebase.
_EXPANSION_MEAN_WARMUP_BARS = 3 * 60

# §3.3's own literal "≥60% body" -- same inline convention trend_pullback already uses
# for this identical law text, not a new tunable param.
_MIN_BODY_PCT = 0.60


class SqueezeBreakout:
    """
    params: instruments.yaml's squeeze_breakout_params (defaults merged with any
    per-instrument squeeze_breakout_calibration override), PLUS regime_confirm_bars
    and htf_ltf_ratio injected at instantiation time from the SAME run's
    regime_params -- never duplicated in YAML (see scripts/run_validation_gates.py's
    _StrategySpec.extra_params / scripts/diagnose_gates.py's mirrored injection).
    One instance per instrument PER RUN. All indicator computation is still
    pure/recomputed from the window each call -- but as of the §2 consultation-
    window experiment (TRADING-RULES §2/§3.3, dated 2026-07-11), this class carries
    ONE piece of real instance state, self._ltf_bars_since_compression (an LTF-bar
    counter, NOT cached indicator output), used only to freeze the compression-box
    SL for entries taken during the extended consultation window. This is a real,
    documented deviation from the prior "stateless otherwise" claim -- it is safe
    only because a FRESH instance is constructed for every backtest run/window
    (the same registry instantiation pattern all three playbooks share, see
    scripts/run_validation_gates.py's _make_run_fn), so nothing leaks across runs
    and no explicit reset() method is needed (contrast RegimeClassifier, which IS
    reused across a run and does need reset()).
    """

    def __init__(self, params: dict, instrument: str) -> None:
        self._params = params
        self._instrument = instrument
        self._ltf_bars_since_compression: int | None = None
        # LTF-bar counter, reset to 0 on every COMPRESSION bar and incremented on
        # every other consulted bar -- used ONLY to freeze the compression-box SL
        # (see _stop_loss's box_offset). None until this instance has observed its
        # first COMPRESSION bar (see generate_signal's box_offset fallback).

    def generate_signal(self, window: pd.DataFrame, regime: RegimeResult) -> Signal | None:
        # Bookkeeping runs on every call this strategy is asked about (even ones
        # about to return None below), so the frozen-SL anchor stays accurate
        # whenever a later consultation-window bar needs it.
        if regime.regime == RegimeState.COMPRESSION:
            self._ltf_bars_since_compression = 0
        elif self._ltf_bars_since_compression is not None:
            self._ltf_bars_since_compression += 1

        p = self._params
        consult = regime.regime == RegimeState.COMPRESSION or (
            regime.regime == RegimeState.EXPANSION
            and regime.prior_regime == RegimeState.COMPRESSION
            and regime.bars_in_regime <= p["regime_confirm_bars"]
        )
        if not consult:
            return None  # not routed to this playbook this bar -> nothing to journal

        min_bars = max(
            p["bb_period"],
            p["compression_box_lookback_bars"] + 1,
            p["volume_lookback_bars"],
            _EXPANSION_MEAN_WARMUP_BARS,
        )
        if len(window) < min_bars:
            return None  # insufficient warmup -> not a real evaluation yet

        close = window["close"]
        last_close = close.iloc[-1]

        upper, _, lower = _bollinger_bands(close, p["bb_period"], p["bb_std"])
        upper_now, lower_now = upper.iloc[-1], lower.iloc[-1]
        atr_now = _atr(window["high"], window["low"], close, 14).iloc[-1]

        direction = self._derive_direction(last_close, upper_now, lower_now)

        confidence_score, reasons = self._evaluate_trigger(window, p, direction, upper, lower, atr_now)

        if regime.regime == RegimeState.EXPANSION and self._ltf_bars_since_compression is not None:
            # Consultation-window entry, with a real observed LTF count (the
            # documented fallback below covers the edge case where this instance
            # has never seen COMPRESSION in its own lifetime -- not this branch).
            # Consistency assertion (approved addition 1, 2026-07-11): the
            # strategy's own LTF counter and the classifier's HTF bars_in_regime
            # (converted via htf_ltf_ratio) must agree on the window bound. A trip
            # means the two clocks have drifted apart -- a semantic finding to
            # surface, not something to silently paper over.
            box_offset = self._ltf_bars_since_compression
            bound = p["htf_ltf_ratio"] * p["regime_confirm_bars"]
            assert 1 <= box_offset <= bound, (
                f"consultation-window clock mismatch: ltf_bars_since_compression="
                f"{box_offset} outside [1, {bound}] (htf_ltf_ratio={p['htf_ltf_ratio']}, "
                f"regime_confirm_bars={p['regime_confirm_bars']}, "
                f"bars_in_regime={regime.bars_in_regime})"
            )
        else:
            # Either COMPRESSION-routed (box_offset always 0, original behavior),
            # or the accepted "never observed COMPRESSION yet" edge case for a
            # consultation-window entry (module docstring) -- falls back to the
            # unfrozen sliding box rather than fabricating an anchor never seen.
            box_offset = 0
        sl = self._stop_loss(window, last_close, atr_now, direction, p, box_offset)

        return Signal(
            strategy="squeeze_breakout",
            instrument=self._instrument,
            direction=direction,
            entry_ref=last_close,
            sl=sl,
            tp=None,  # DISPOSITION 6 -- exit_cfg trail handles targets, see module docstring
            confidence_score=confidence_score,
            reasons=reasons,
            vetoes=[],  # structurally always empty -- regime-routing is the only hard gate
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_direction(last_close: float, upper_now: float, lower_now: float) -> str:
        """
        COMPRESSION carries no direction (like RANGING) -- candidate direction is
        cheap and always available: already-broken-out side if beyond a band, else
        the middle-band side (same fallback shape range_reversion uses; when price is
        still inside the bands the trigger components correctly score 0 regardless of
        which side this arbitrary tie-break picks, so it never inflates a score --
        only affects near-miss reporting readability). Exposed as its own staticmethod
        (not inlined into generate_signal) so scripts/run_validation_gates.py's
        hysteresis-excluded diagnostic can derive the SAME candidate direction on bars
        the regime gate excludes, without duplicating this tie-break logic.
        """
        if not pd.isna(upper_now) and last_close > upper_now:
            return "long"
        if not pd.isna(lower_now) and last_close < lower_now:
            return "short"
        middle_now = (
            (upper_now + lower_now) / 2.0 if not (pd.isna(upper_now) or pd.isna(lower_now)) else last_close
        )
        return "long" if last_close >= middle_now else "short"

    def _evaluate_trigger(
        self,
        window: pd.DataFrame,
        p: dict,
        direction: str,
        upper: pd.Series,
        lower: pd.Series,
        atr_now: float,
    ) -> tuple[float, list[str]]:
        """
        Factored out of generate_signal (DISPOSITION 1's "made measurable" note): the
        4-component weighted score, with NO regime gate applied. Shared by the real
        gated path above and scripts/run_validation_gates.py's hysteresis-excluded
        diagnostic, which calls this directly on bars where regime != COMPRESSION to
        measure how often the trigger alone would have fired had the regime gate not
        excluded it. Never invoke this as a substitute for the regime gate in the live
        or backtest trading path -- it is a scoring function only, not itself a signal.
        """
        close = window["close"]
        open_ = window["open"]
        high = window["high"]
        low = window["low"]
        volume = window["volume"]

        reasons: list[str] = []

        band_score, band_reason = self._close_beyond_band_score(close, upper, lower, direction)
        reasons.append(band_reason)

        expansion_score, expansion_reason = self._atr_expansion_score(high, low, close, p)
        reasons.append(expansion_reason)

        body_score, body_reason = self._body_score(open_, high, low, close, direction)
        reasons.append(body_reason)

        volume_score, volume_reason = self._tick_volume_score(volume, p)
        reasons.append(volume_reason)

        weights = p["score_weights"]
        confidence_score = (
            weights["close_beyond_band"] * band_score
            + weights["atr_expansion"] * expansion_score
            + weights["body_pct"] * body_score
            + weights["tick_volume"] * volume_score
        )
        return confidence_score, reasons

    @staticmethod
    def _close_beyond_band_score(
        close: pd.Series, upper: pd.Series, lower: pd.Series, direction: str
    ) -> tuple[float, str]:
        """§3.3 trigger component: close beyond band (bot.indicators.core.bb_breakout_
        long/short). Binary (score, reason) 2-tuple -- absence scores 0 via `reason`,
        NEVER required for the Signal to exist (that would be a hard gate wearing a
        score's clothing, the exact §1.1 anti-pattern this design prevents)."""
        if direction == "long":
            fired = bool(_bb_breakout_long(close, upper).iloc[-1])
        else:
            fired = bool(_bb_breakout_short(close, lower).iloc[-1])
        return (1.0, "close_beyond_band") if fired else (0.0, "no_band_breakout")

    @staticmethod
    def _atr_expansion_score(
        high: pd.Series, low: pd.Series, close: pd.Series, p: dict
    ) -> tuple[float, str]:
        """
        §3.3 trigger component: ATR expansion. Reuses the SAME dimensionless
        ratio/mean-mult thresholds as bot.regime.classifier's EXPANSION detection and
        range_reversion's _expansion_veto (regime_params.atr_expansion_ratio /
        atr_expansion_mean_mult) -- scale-invariant multipliers, not timeframe-bound
        periods, so this is a reuse of a validated dimensionless constant, not an
        untested new number. Deliberately reimplemented locally rather than imported
        from range_reversion.py or classifier.py -- same "local reuse, not a shared
        abstraction" precedent range_reversion's own docstring establishes for this
        identical formula. APPROVED CONTINGENT on a §1.7 pass-rate check on real H1
        history, same standard as range_reversion's veto.
        """
        atr10 = _atr(high, low, close, 10)
        atr50 = _atr(high, low, close, 50)
        atr14 = _atr(high, low, close, 14)

        atr10_last = atr10.iloc[-1]
        atr50_last = atr50.iloc[-1]
        atr14_last = atr14.iloc[-1]

        ratio_expansion = (
            not pd.isna(atr50_last)
            and atr50_last > 0
            and (atr10_last / atr50_last) > p["atr_expansion_ratio"]
        )
        atr_mean_60 = atr14.rolling(60).mean().iloc[-1]
        mean_expansion = (
            not pd.isna(atr_mean_60)
            and atr_mean_60 > 0
            and atr14_last > p["atr_expansion_mean_mult"] * atr_mean_60
        )

        if ratio_expansion or mean_expansion:
            return 1.0, "atr_expansion"
        return 0.0, "no_atr_expansion"

    @staticmethod
    def _body_score(
        open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, direction: str
    ) -> tuple[float, str]:
        """§3.3 trigger component: candle body >= 60% of range, in the breakout's own
        direction (a big-bodied candle against the breakout direction is not a
        confirming trigger). Binary (score, reason) 2-tuple, same style as
        trend_pullback's body>=60% sub-check inside _reversal_trigger_score."""
        body = _body_pct(open_, high, low, close).iloc[-1]
        candle_direction_ok = (
            close.iloc[-1] > open_.iloc[-1] if direction == "long" else close.iloc[-1] < open_.iloc[-1]
        )
        fired = bool(not pd.isna(body) and body >= _MIN_BODY_PCT and candle_direction_ok)
        return (1.0, f"body_pct={body:.2f}") if fired else (0.0, "body_below_threshold")

    @staticmethod
    def _tick_volume_score(volume: pd.Series, p: dict) -> tuple[float, str]:
        """
        §3.3: "OANDA tick-volume = weak evidence: low-weight score component, never a
        hard gate" (DISPOSITION 3). Binary (score, reason) 2-tuple: current bar's
        volume expanded relative to its own recent mean -- same "expansion vs own
        recent mean" shape as _atr_expansion_score, deliberately mirrored rather than
        inventing a differently-shaped check for weaker evidence.
        """
        mean_vol = volume.rolling(p["volume_lookback_bars"]).mean().iloc[-1]
        vol_now = volume.iloc[-1]
        fired = bool(
            not pd.isna(mean_vol) and mean_vol > 0 and vol_now > p["volume_expansion_mult"] * mean_vol
        )
        return (1.0, "tick_volume_expansion") if fired else (0.0, "no_tick_volume_expansion")

    @staticmethod
    def _stop_loss(
        window: pd.DataFrame,
        last_close: float,
        atr_now: float,
        direction: str,
        p: dict,
        box_offset: int = 0,
    ) -> float:
        """§3.3: SL = opposite side of the compression box, or 1.5x ATR -- whichever is
        FARTHER/more protective (DISPOSITION 5; trend_pullback's swing-extreme-vs-
        ATR-mult convention, the one existing precedent for an unranked SL "X or Y").
        Box excludes the trigger bar itself (window.iloc[-1]) -- a strong breakout
        candle's own extreme would otherwise place the SL absurdly close.

        box_offset (DISPOSITION 7, §2 consultation-window experiment, dated
        2026-07-11): 0 (default) reproduces the original sliding-window box exactly
        -- every COMPRESSION-routed entry, unmodified. >0 FREEZES the box at the
        COMPRESSION-exit boundary for a COMPRESSION-originated EXPANSION entry taken
        box_offset LTF bars into the consultation window (see generate_signal's
        self._ltf_bars_since_compression -- an exact, per-call-observed LTF count,
        not an HTF-ratio approximation). A wider (farther) SL is the mechanical,
        pre-registered consequence for later entries -- see scripts/gross_vs_net.py's
        early/late stratification."""
        lookback = p["compression_box_lookback_bars"]
        box = window.iloc[-(lookback + box_offset + 1) : -(box_offset + 1)]
        if direction == "long":
            sl_by_box = box["low"].min()
            sl_by_atr = last_close - p["sl_atr_mult"] * atr_now
            return min(sl_by_box, sl_by_atr)
        sl_by_box = box["high"].max()
        sl_by_atr = last_close + p["sl_atr_mult"] * atr_now
        return max(sl_by_box, sl_by_atr)
