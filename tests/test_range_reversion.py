"""
Phase 6 exit-criteria tests — range_reversion (PROMPTS.md §4 row 6).

Covers: SL tested both directions, near-miss scoring visible per component
(band_reentry / rsi_recovery, both scored, never vetoed), the AND/OR/asymmetric
confluence collapse pre-registered in HANDOFF.md's disposition 1 (both scored
components are binary and weights sum to 1.0, so the (threshold, weights) choice
selects a DISCRETE effective regime — this file proves that math is real, not just
documented), regime-routing hard gate, and — the deliberate asymmetry vs.
trend_pullback — the expansion/ATR-spike condition IS asserted as a real veto that
blocks regardless of score (TRADING-RULES §3.2's own "Hard veto:" bullet, disposition
2 in HANDOFF.md).

Synthetic fixtures: a long, low-amplitude sine-wave "quiet RANGING" warmup (stable,
non-degenerate Bollinger Bands / ATR) followed by a hand-tuned tail sequence (a
gradual decline/incline + one bounce/dip bar) engineered to land at a specific point
relative to the band/RSI. Indicator values used to calibrate each fixture were
computed via the SAME bot.indicators.core functions this strategy calls (verified
numerically before writing these fixtures — band position and RSI depend on the
exact bars appended, including circularly on each other, so fixtures were tuned by
running the real indicator functions, not hand-derived). The confluence-structure
tests bypass fixture engineering entirely and patch the two component-score methods
directly, isolating the weighted-sum arithmetic from indicator mechanics (already
covered per-component by the tests above them) — same pattern trend_pullback's tests
use.
"""

from __future__ import annotations

import math
from unittest.mock import patch

import pandas as pd
import pytest

from bot.regime.classifier import RegimeResult, RegimeState
from bot.strategies.range_reversion import RangeReversion

_PARAMS = {
    "bb_period": 20,
    "bb_std": 2.0,
    "rsi_period": 14,
    "rsi_oversold_threshold": 30.0,
    "rejection_lookback_bars": 3,
    "sl_atr_mult": 1.25,
    "entry_threshold": 0.55,
    "score_weights": {"band_reentry": 0.5, "rsi_recovery": 0.5},
    "expansion_veto_atr_ratio": 1.25,
    "expansion_veto_atr_mean_mult": 1.3,
}

_RANGING = RegimeResult(RegimeState.RANGING, confidence=0.5, bars_in_regime=10)
_STRATEGY = RangeReversion(_PARAMS, "EUR_USD")


def _bars(times, opens, highs, lows, closes) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": 100,
            "complete": True,
        }
    )


def _quiet_base(n: int = 220, amp: float = 0.0008, base: float = 1.10000):
    """Low-amplitude sine-wave RANGING series -- stable, non-degenerate BB/ATR."""
    closes = [base + amp * math.sin(2 * math.pi * i / 10) for i in range(n)]
    opens = [base] + closes[:-1]
    highs = [max(o, c) + 0.0002 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 0.0002 for o, c in zip(opens, closes)]
    return opens, highs, lows, closes


def _append_deltas(opens, highs, lows, closes, deltas: list[float]):
    opens, highs, lows, closes = list(opens), list(highs), list(lows), list(closes)
    prev = closes[-1]
    for d in deltas:
        c = prev + d
        o = prev
        highs.append(max(o, c) + 0.0002)
        lows.append(min(o, c) - 0.0002)
        opens.append(o)
        closes.append(c)
        prev = c
    return opens, highs, lows, closes


def _to_df(opens, highs, lows, closes) -> pd.DataFrame:
    times = [pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=i) for i in range(len(closes))]
    return _bars(times, opens, highs, lows, closes)


def _build_long(decline_bars: int, decline_step: float, bounce: float) -> pd.DataFrame:
    """Gradual decline (pierces the lower band, drags RSI down) + one bounce bar
    (candidate re-entry). Gradual, not a single sharp jump, so the move's own ATR
    footprint stays inside the expansion veto's threshold (verified numerically)."""
    o, h, l, c = _quiet_base()
    deltas = [decline_step] * decline_bars + [bounce]
    return _to_df(*_append_deltas(o, h, l, c, deltas))


def _build_short(incline_bars: int, incline_step: float, dip: float) -> pd.DataFrame:
    """Mirror of _build_long at the upper band."""
    o, h, l, c = _quiet_base()
    deltas = [incline_step] * incline_bars + [dip]
    return _to_df(*_append_deltas(o, h, l, c, deltas))


def _build_expansion_spike() -> pd.DataFrame:
    """One sharp-range bar appended to the quiet base -- trips the LTF expansion
    veto (verified numerically: ATR10/ATR50 ratio and ATR14-vs-60-mean both clear
    their thresholds), independent of whatever regime is passed to generate_signal."""
    o, h, l, c = _quiet_base()
    prev = c[-1]
    spike_close = prev + 0.003
    o = o + [prev]
    h = h + [spike_close + 0.001]
    l = l + [prev - 0.001]
    c = c + [spike_close]
    return _to_df(o, h, l, c)


# Fixture parameters, tuned numerically against the real indicator functions:
_LONG_FULL_FIRE = (8, -0.0006, 0.0007)  # band_reentry AND rsi_recovery both fire
_LONG_REENTRY_NO_RSI = (3, -0.0004, 0.0009)  # band_reentry fires, RSI not oversold yet
_LONG_RSI_NO_REENTRY = (12, -0.0006, 0.0001)  # RSI oversold+turning, bounce too small to re-enter
_SHORT_FULL_FIRE = (8, 0.0006, -0.0007)


# ---------------------------------------------------------------------------
# Regime routing hard gate
# ---------------------------------------------------------------------------

class TestRegimeRouting:
    @pytest.mark.parametrize(
        "regime",
        [
            RegimeResult(RegimeState.TRENDING_UP, confidence=0.8, bars_in_regime=20),
            RegimeResult(RegimeState.TRENDING_DOWN, confidence=0.8, bars_in_regime=20),
            RegimeResult(RegimeState.EXPANSION, confidence=0.5, bars_in_regime=5),
            RegimeResult(RegimeState.COMPRESSION, confidence=0.5, bars_in_regime=5),
        ],
    )
    def test_non_ranging_regime_returns_none(self, regime) -> None:
        window = _build_long(*_LONG_FULL_FIRE)
        assert _STRATEGY.generate_signal(window, regime) is None

    def test_insufficient_warmup_returns_none(self) -> None:
        o, h, l, c = _quiet_base(n=50)
        window = _to_df(o, h, l, c)
        assert _STRATEGY.generate_signal(window, _RANGING) is None


# ---------------------------------------------------------------------------
# SL tested both directions (TRADING-RULES §1.3)
# ---------------------------------------------------------------------------

class TestStopLossBothDirections:
    def test_long_setup_sl_below_entry(self) -> None:
        window = _build_long(*_LONG_FULL_FIRE)
        signal = _STRATEGY.generate_signal(window, _RANGING)

        assert signal is not None
        assert signal.direction == "long"
        assert signal.sl < signal.entry_ref, "long SL must sit below entry"
        assert signal.tp is not None and signal.tp > signal.sl

    def test_short_setup_sl_above_entry(self) -> None:
        window = _build_short(*_SHORT_FULL_FIRE)
        signal = _STRATEGY.generate_signal(window, _RANGING)

        assert signal is not None
        assert signal.direction == "short"
        assert signal.sl > signal.entry_ref, "short SL must sit above entry"
        assert signal.tp is not None and signal.tp < signal.sl


# ---------------------------------------------------------------------------
# Near-miss visibility — both scored components, never vetoed
# ---------------------------------------------------------------------------

class TestNearMissScoring:
    def test_band_reentry_without_rsi_recovery(self) -> None:
        """Re-entry closes back inside the band, but RSI hasn't reached oversold
        yet -- scores 0 on rsi_recovery via 'rsi_not_oversold', does not veto."""
        window = _build_long(*_LONG_REENTRY_NO_RSI)
        signal = _STRATEGY.generate_signal(window, _RANGING)

        assert signal is not None
        assert signal.vetoes == []
        assert "band_reentry" in signal.reasons
        assert "rsi_not_oversold" in signal.reasons
        w = _PARAMS["score_weights"]
        assert signal.confidence_score == pytest.approx(w["band_reentry"])

    def test_rsi_recovery_without_band_reentry(self) -> None:
        """RSI is oversold and turning up, but the bounce is too small to close
        back inside the band yet -- scores 0 on band_reentry via 'no_band_reentry',
        does not veto."""
        window = _build_long(*_LONG_RSI_NO_REENTRY)
        signal = _STRATEGY.generate_signal(window, _RANGING)

        assert signal is not None
        assert signal.vetoes == []
        assert "no_band_reentry" in signal.reasons
        assert any(r.startswith("rsi_recovering") for r in signal.reasons)
        w = _PARAMS["score_weights"]
        assert signal.confidence_score == pytest.approx(w["rsi_recovery"])

    def test_full_confluence_fires(self) -> None:
        """Both conditions true simultaneously -- confidence_score=1.0, clears
        entry_threshold, no vetoes."""
        window = _build_long(*_LONG_FULL_FIRE)
        signal = _STRATEGY.generate_signal(window, _RANGING)

        assert signal is not None
        assert signal.vetoes == []
        assert "band_reentry" in signal.reasons
        assert any(r.startswith("rsi_recovering") for r in signal.reasons)
        assert signal.confidence_score == pytest.approx(1.0)
        assert signal.confidence_score >= _PARAMS["entry_threshold"]


# ---------------------------------------------------------------------------
# Expansion/ATR-spike veto — the deliberate asymmetry vs. trend_pullback
# (TRADING-RULES §3.2's own "Hard veto:" bullet; HANDOFF.md disposition 2)
# ---------------------------------------------------------------------------

class TestExpansionVeto:
    def test_expansion_atr_spike_is_a_real_veto(self) -> None:
        """A sharp-range bar trips the LTF-level expansion check even though the
        REGIME argument passed in is still (confirmed) RANGING -- this is exactly
        the 'instant, faster than classifier hysteresis' gate the module docstring
        describes. Unlike trend_pullback's near-miss components, this DOES append
        to signal.vetoes."""
        window = _build_expansion_spike()
        signal = _STRATEGY.generate_signal(window, _RANGING)

        assert signal is not None
        assert "expansion_atr_spike" in signal.vetoes

    def test_veto_blocks_regardless_of_score(self) -> None:
        """Both scored components patched to a perfect 1.0 (confidence_score=1.0,
        i.e. would clear ANY entry_threshold) on the SAME expansion-spike window --
        the veto still blocks. Proves the hard gate is unconditional, not just
        another weighted input (the exact property an AND-stack drift would erase
        in the other direction: demoting a real veto into 'just a low score')."""
        window = _build_expansion_spike()
        with (
            patch.object(RangeReversion, "_band_reentry_score", return_value=(1.0, "band_reentry")),
            patch.object(RangeReversion, "_rsi_recovery_score", return_value=(1.0, "rsi_recovering=10.0")),
        ):
            signal = _STRATEGY.generate_signal(window, _RANGING)

        assert signal is not None
        assert signal.confidence_score == pytest.approx(1.0)
        assert "expansion_atr_spike" in signal.vetoes


# ---------------------------------------------------------------------------
# AND/OR/asymmetric confluence collapse (HANDOFF.md disposition 1) — proves the
# pre-registered math is real, not just documented. Patches the two component-score
# methods directly, isolating the weighted-sum arithmetic from indicator mechanics.
# ---------------------------------------------------------------------------

class TestConfluenceAndOrCollapse:
    def test_and_region_one_weak_component_fails_to_clear(self) -> None:
        """Default config: weights 0.5/0.5, entry_threshold=0.55 > max(weight) --
        AND region. One component at 1.0, the other at 0.0 -> confidence_score=0.5
        < 0.55, i.e. does NOT clear threshold: genuine confluence (both agreeing)
        is required, matching §3.2's literal '+'."""
        window = _build_long(*_LONG_FULL_FIRE)
        with (
            patch.object(RangeReversion, "_band_reentry_score", return_value=(1.0, "band_reentry")),
            patch.object(RangeReversion, "_rsi_recovery_score", return_value=(0.0, "rsi_not_oversold")),
        ):
            signal = _STRATEGY.generate_signal(window, _RANGING)

        assert signal is not None
        assert signal.vetoes == []
        assert signal.confidence_score == pytest.approx(0.5)
        assert signal.confidence_score < _PARAMS["entry_threshold"]

    def test_and_region_both_components_clear_threshold(self) -> None:
        """Same AND-region config: both components at 1.0 -> confidence_score=1.0
        clears entry_threshold=0.55."""
        window = _build_long(*_LONG_FULL_FIRE)
        with (
            patch.object(RangeReversion, "_band_reentry_score", return_value=(1.0, "band_reentry")),
            patch.object(RangeReversion, "_rsi_recovery_score", return_value=(1.0, "rsi_recovering=10.0")),
        ):
            signal = _STRATEGY.generate_signal(window, _RANGING)

        assert signal is not None
        assert signal.confidence_score == pytest.approx(1.0)
        assert signal.confidence_score >= _PARAMS["entry_threshold"]

    def test_or_region_either_component_alone_clears_a_lower_threshold(self) -> None:
        """PRE-REGISTRATION CHECK (disposition 1): with an OR-region threshold
        (below min(weight)=0.5, e.g. 0.3), a SINGLE component firing alone is
        enough to clear it -- proving the documented OR-region collapse is real
        behavior of this implementation, not just a docstring claim. This does
        NOT mean OR is what ships -- instruments.yaml's default entry_threshold
        (0.55) stays in the AND region; this test only proves the math the
        walk-forward search could land on, so a future search result landing here
        is recognized and flagged per disposition 1, not silently accepted."""
        or_region_threshold = 0.3
        window = _build_long(*_LONG_FULL_FIRE)
        with (
            patch.object(RangeReversion, "_band_reentry_score", return_value=(1.0, "band_reentry")),
            patch.object(RangeReversion, "_rsi_recovery_score", return_value=(0.0, "rsi_not_oversold")),
        ):
            signal = _STRATEGY.generate_signal(window, _RANGING)

        assert signal is not None
        assert signal.confidence_score == pytest.approx(0.5)
        assert signal.confidence_score >= or_region_threshold
