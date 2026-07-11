"""
Phase 7 exit-criteria tests — squeeze_breakout (PROMPTS.md §4 row 7).

Covers: regime-routing hard gate (COMPRESSION only — the OTHER four RegimeState values,
including EXPANSION, must all return None per §2's one-regime-one-playbook routing,
DISPOSITION 1), SL tested both directions, near-miss scoring visible per component (4
components: close_beyond_band / atr_expansion / body_pct / tick_volume — all scored,
never vetoed, vetoes structurally always empty per DISPOSITION 1/2), the tick-volume
weak-evidence property (DISPOSITION 3 — it can never rescue a missing real trigger at
the provisional default weighting), and the 3-real-trigger-AND boundary the default
entry_threshold=0.9 is built around (DISPOSITION 2).

Two real, hand-engineered price fixtures (long/short breakout off a quiet compression
base) prove the real indicator wiring end-to-end (regime routing, SL both directions,
full confluence). The remaining near-miss/arithmetic proofs patch the four component-
score methods directly, isolating the weighted-sum arithmetic from indicator mechanics
— same technique test_range_reversion.py's TestConfluenceAndOrCollapse uses, extended
here from 2 to 4 components since hand-tuning every one of the 2^4 combinations via
price fixtures alone would not be tractable.
"""

from __future__ import annotations

import math
from unittest.mock import patch

import pandas as pd
import pytest

from bot.regime.classifier import RegimeResult, RegimeState
from bot.strategies.squeeze_breakout import SqueezeBreakout

_PARAMS = {
    "bb_period": 20,
    "bb_std": 2.0,
    "compression_box_lookback_bars": 20,
    "sl_atr_mult": 1.5,
    "atr_expansion_ratio": 1.25,
    "atr_expansion_mean_mult": 1.3,
    "volume_lookback_bars": 20,
    "volume_expansion_mult": 1.3,
    "entry_threshold": 0.85,
    "score_weights": {
        "close_beyond_band": 0.3,
        "atr_expansion": 0.3,
        "body_pct": 0.3,
        "tick_volume": 0.1,
    },
}

_COMPRESSION = RegimeResult(RegimeState.COMPRESSION, confidence=0.5, bars_in_regime=10)
_STRATEGY = SqueezeBreakout(_PARAMS, "GBP_USD")


def _quiet_base(n: int = 200, amp: float = 0.0008, base: float = 1.10000, volume: float = 100.0):
    """Low-amplitude sine-wave warmup series (regime is injected directly via the
    RegimeResult argument, so this only needs to produce stable, non-degenerate
    BB/ATR/volume values — not a genuinely-classified COMPRESSION market)."""
    closes = [base + amp * math.sin(2 * math.pi * i / 10) for i in range(n)]
    opens = [base] + closes[:-1]
    highs = [max(o, c) + 0.0002 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 0.0002 for o, c in zip(opens, closes)]
    volumes = [volume] * n
    return opens, highs, lows, closes, volumes


def _append_bar(opens, highs, lows, closes, volumes, o, h, l, c, v):
    return opens + [o], highs + [h], lows + [l], closes + [c], volumes + [v]


def _to_df(opens, highs, lows, closes, volumes) -> pd.DataFrame:
    times = [pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=i) for i in range(len(closes))]
    return pd.DataFrame(
        {
            "time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "complete": True,
        }
    )


def _build_breakout(direction: str, elevated_volume: bool = True) -> pd.DataFrame:
    """Quiet base + one strong breakout candle: closes clearly beyond the band, trips
    the ATR-expansion check (same 0.003 spike magnitude test_range_reversion.py's
    _build_expansion_spike verified numerically against these same threshold
    constants), and has body_pct >= 0.60 in the breakout's own direction."""
    o, h, l, c, v = _quiet_base()
    prev = c[-1]
    sign = 1.0 if direction == "long" else -1.0
    spike_close = prev + sign * 0.003
    spike_open = prev
    spike_high = max(spike_open, spike_close) + 0.0006
    spike_low = min(spike_open, spike_close) - 0.0002
    spike_volume = 250.0 if elevated_volume else 100.0
    o, h, l, c, v = _append_bar(o, h, l, c, v, spike_open, spike_high, spike_low, spike_close, spike_volume)
    return _to_df(o, h, l, c, v)


# ---------------------------------------------------------------------------
# Regime routing hard gate (DISPOSITION 1)
# ---------------------------------------------------------------------------

class TestRegimeRouting:
    @pytest.mark.parametrize(
        "regime",
        [
            RegimeResult(RegimeState.TRENDING_UP, confidence=0.8, bars_in_regime=20),
            RegimeResult(RegimeState.TRENDING_DOWN, confidence=0.8, bars_in_regime=20),
            RegimeResult(RegimeState.RANGING, confidence=0.5, bars_in_regime=20),
            RegimeResult(RegimeState.EXPANSION, confidence=0.5, bars_in_regime=5),
        ],
    )
    def test_non_compression_regime_returns_none(self, regime) -> None:
        window = _build_breakout("long")
        assert _STRATEGY.generate_signal(window, regime) is None

    def test_insufficient_warmup_returns_none(self) -> None:
        o, h, l, c, v = _quiet_base(n=50)
        window = _to_df(o, h, l, c, v)
        assert _STRATEGY.generate_signal(window, _COMPRESSION) is None


# ---------------------------------------------------------------------------
# SL tested both directions (TRADING-RULES §1.3) + full real-fixture confluence
# ---------------------------------------------------------------------------

class TestStopLossBothDirectionsAndFullConfluence:
    def test_long_breakout_sl_below_entry_and_fires(self) -> None:
        window = _build_breakout("long")
        signal = _STRATEGY.generate_signal(window, _COMPRESSION)

        assert signal is not None
        assert signal.direction == "long"
        assert signal.sl < signal.entry_ref, "long SL must sit below entry"
        assert signal.tp is None, "DISPOSITION 6 -- no fixed TP, exit_cfg trail handles targets"
        assert signal.vetoes == []
        assert signal.confidence_score == pytest.approx(1.0)
        assert signal.confidence_score >= _PARAMS["entry_threshold"]
        assert "close_beyond_band" in signal.reasons
        assert "atr_expansion" in signal.reasons
        assert "tick_volume_expansion" in signal.reasons

    def test_short_breakout_sl_above_entry_and_fires(self) -> None:
        window = _build_breakout("short")
        signal = _STRATEGY.generate_signal(window, _COMPRESSION)

        assert signal is not None
        assert signal.direction == "short"
        assert signal.sl > signal.entry_ref, "short SL must sit above entry"
        assert signal.tp is None
        assert signal.vetoes == []
        assert signal.confidence_score == pytest.approx(1.0)

    def test_three_real_triggers_without_volume_still_clears_default_threshold(self) -> None:
        """DISPOSITION 2/3: default weights 0.3/0.3/0.3/0.1 and entry_threshold=0.85
        (a safe margin below the float-realized 3-trigger sum 0.3+0.3+0.3=
        0.8999999999999999, deliberately not landing exactly on that boundary) are
        chosen so the 3 real triggers alone clear the default threshold without
        tick-volume's help — proving tick-volume is genuinely supplementary, not
        load-bearing, using the real indicator path (not patched)."""
        window = _build_breakout("long", elevated_volume=False)
        signal = _STRATEGY.generate_signal(window, _COMPRESSION)

        assert signal is not None
        assert "no_tick_volume_expansion" in signal.reasons
        assert signal.confidence_score == pytest.approx(0.3 + 0.3 + 0.3)
        assert signal.confidence_score >= _PARAMS["entry_threshold"]


# ---------------------------------------------------------------------------
# Near-miss visibility — all four scored components, never vetoed (patched arithmetic,
# isolating the weighted sum from indicator mechanics — same technique
# test_range_reversion.py's TestConfluenceAndOrCollapse uses)
# ---------------------------------------------------------------------------

def _patch_all(band=0.0, expansion=0.0, body=0.0, volume=0.0):
    return (
        patch.object(SqueezeBreakout, "_close_beyond_band_score", return_value=(band, "band_stub")),
        patch.object(SqueezeBreakout, "_atr_expansion_score", return_value=(expansion, "expansion_stub")),
        patch.object(SqueezeBreakout, "_body_score", return_value=(body, "body_stub")),
        patch.object(SqueezeBreakout, "_tick_volume_score", return_value=(volume, "volume_stub")),
    )


class TestNearMissScoringNeverVetoes:
    def test_all_components_zero_scores_zero_and_never_vetoes(self) -> None:
        """The degenerate all-absent case: confidence_score=0.0, vetoes STILL empty --
        this strategy has exactly one hard gate (regime routing) and it already passed
        to reach this point; a fully-absent trigger must never itself become a veto
        (the exact §1.1 AND-stack anti-pattern trend_pullback's law-drift fix
        prevents)."""
        window = _build_breakout("long")
        p1, p2, p3, p4 = _patch_all(0.0, 0.0, 0.0, 0.0)
        with p1, p2, p3, p4:
            signal = _STRATEGY.generate_signal(window, _COMPRESSION)

        assert signal is not None
        assert signal.vetoes == []
        assert signal.confidence_score == pytest.approx(0.0)
        assert signal.confidence_score < _PARAMS["entry_threshold"]

    def test_all_four_fire_clears_threshold(self) -> None:
        window = _build_breakout("long")
        p1, p2, p3, p4 = _patch_all(1.0, 1.0, 1.0, 1.0)
        with p1, p2, p3, p4:
            signal = _STRATEGY.generate_signal(window, _COMPRESSION)

        assert signal is not None
        assert signal.vetoes == []
        assert signal.confidence_score == pytest.approx(1.0)
        assert signal.confidence_score >= _PARAMS["entry_threshold"]

    def test_three_real_triggers_at_exactly_the_and_boundary(self) -> None:
        """DISPOSITION 2's pre-registered boundary: close_beyond_band + atr_expansion +
        body_pct all firing (0.3*3=0.9) clears entry_threshold=0.85 with tick_volume at
        0 -- proving the default threshold is precisely the "AND of the 3 real
        triggers" reading of §3.3's literal "+", with tick-volume mathematically
        irrelevant to whether this bar fires."""
        window = _build_breakout("long")
        p1, p2, p3, p4 = _patch_all(1.0, 1.0, 1.0, 0.0)
        with p1, p2, p3, p4:
            signal = _STRATEGY.generate_signal(window, _COMPRESSION)

        assert signal is not None
        assert signal.confidence_score == pytest.approx(0.3 + 0.3 + 0.3)
        assert signal.confidence_score >= _PARAMS["entry_threshold"]

    def test_tick_volume_cannot_rescue_a_missing_real_trigger(self) -> None:
        """DISPOSITION 3's weak-evidence property: two real triggers firing plus
        tick_volume (0.3+0.3+0.1=0.7) does NOT clear entry_threshold=0.9 -- tick-volume
        is structurally incapable of substituting for a missing real trigger at the
        provisional default weighting, matching §3.3's "never a hard gate" instruction
        in spirit (never load-bearing either) without literally being one."""
        window = _build_breakout("long")
        p1, p2, p3, p4 = _patch_all(1.0, 1.0, 0.0, 1.0)
        with p1, p2, p3, p4:
            signal = _STRATEGY.generate_signal(window, _COMPRESSION)

        assert signal is not None
        assert signal.vetoes == []
        assert signal.confidence_score == pytest.approx(0.7)
        assert signal.confidence_score < _PARAMS["entry_threshold"]

    @pytest.mark.parametrize(
        "band,expansion,body,volume,expected",
        [
            (1.0, 0.0, 0.0, 0.0, 0.3),
            (0.0, 1.0, 0.0, 0.0, 0.3),
            (0.0, 0.0, 1.0, 0.0, 0.3),
            (0.0, 0.0, 0.0, 1.0, 0.1),
        ],
    )
    def test_each_component_scores_independently(self, band, expansion, body, volume, expected) -> None:
        """Any single component firing alone scores exactly its own weight, and the
        Signal always carries a reason for every component regardless of fire/no-fire
        (near-miss visibility, CLAUDE.md's 'near-misses journaled too')."""
        window = _build_breakout("long")
        p1, p2, p3, p4 = _patch_all(band, expansion, body, volume)
        with p1, p2, p3, p4:
            signal = _STRATEGY.generate_signal(window, _COMPRESSION)

        assert signal is not None
        assert signal.vetoes == []
        assert signal.confidence_score == pytest.approx(expected)
        assert len(signal.reasons) == 4
