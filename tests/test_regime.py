"""
Phase 3 exit-criteria tests — Regime Classifier (PROMPTS.md §4 row 3).

Exit criteria verified here:
  EC-1  outputs match known-good refs (TRENDING_UP, DOWN, RANGING, EXPANSION)
  EC-2  transition tests: 2-candle confirm + min-hold
  EC-3  asymmetric EXPANSION hysteresis (entry bypasses min_hold; exit respects it)
  EC-4  gray zone (ADX 20-25) → regime unchanged, bars_in_regime increments
  EC-5  slope persistence: aligned EMAs + ADX>25 but oscillating slope → not TRENDING
  EC-6  reset() proves two sequential backtest runs on same instance are identical
  EC-7  confidence always within [0.0, 1.0]
"""

from __future__ import annotations

import math
from typing import Callable

import pandas as pd
import pytest

from bot.regime.classifier import (
    RegimeClassifier,
    RegimeResult,
    RegimeState,
    _INDETERMINATE,  # private sentinel — valid to import in tests of internal behaviour
)

# ---------------------------------------------------------------------------
# Shared params (match instruments.yaml defaults exactly)
# ---------------------------------------------------------------------------

_PARAMS = {
    "adx_period": 14,
    "adx_trend_min": 25.0,
    "adx_range_max": 20.0,
    "adx_exhaustion": 50.0,
    "slope_persist_bars": 3,
    "atr_expansion_ratio": 1.25,
    "atr_expansion_mean_mult": 1.3,
    "bb_period": 20,
    "bb_std": 2.0,
    "bb_compression_pct": 20,
    "bb_compression_window": 100,
    "regime_confirm_bars": 2,
    "regime_min_hold_bars": 4,
}

# Dummy window passed when _raw_regime is mocked (content ignored by mock)
_DUMMY = pd.DataFrame({
    "open": [1.0], "high": [1.01], "low": [0.99],
    "close": [1.0], "volume": [100], "complete": [True],
})


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _seq_mock(
    responses: list[tuple[object, float]],
) -> Callable[[pd.DataFrame], tuple[object, float]]:
    """Return a _raw_regime replacement that yields responses in order."""
    it = iter(responses)

    def _mock(_window: pd.DataFrame) -> tuple[object, float]:
        return next(it)

    return _mock


def _make_classifier(**overrides: object) -> RegimeClassifier:
    params = {**_PARAMS, **overrides}
    return RegimeClassifier(params)


# ---------------------------------------------------------------------------
# Data generators for integration tests
# ---------------------------------------------------------------------------

def _make_df(close: pd.Series, spread: float = 0.01) -> pd.DataFrame:
    high = close + spread
    low = close - spread
    n = len(close)
    return pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": high,
        "low": low,
        "close": close,
        "volume": pd.Series([1000] * n),
        "complete": pd.Series([True] * n),
    })


def _trending_up_df(n: int = 250) -> pd.DataFrame:
    """Monotone uptrend: ADX high, EMA20>50>200, slope always positive."""
    close = pd.Series([1000.0 + 0.01 * i for i in range(n)])
    return _make_df(close, spread=0.01)


def _trending_down_df(n: int = 250) -> pd.DataFrame:
    """Monotone downtrend: ADX high, EMA20<50<200, slope always negative."""
    close = pd.Series([1000.0 - 0.01 * i for i in range(n)])
    return _make_df(close, spread=0.01)


def _ranging_df(n: int = 250) -> pd.DataFrame:
    """Sine-wave: net directional movement cancels → ADX ≈ 0 → RANGING."""
    close = pd.Series([100.0 + 2.0 * math.sin(2 * math.pi * i / 20) for i in range(n)])
    return _make_df(close, spread=0.5)


def _expansion_df(n_calm: int = 220, n_volatile: int = 30) -> pd.DataFrame:
    """
    Calm period followed by sudden high-amplitude oscillation.
    ATR(10)/ATR(50) > 1.25 at end → EXPANSION.
    """
    calm_close = pd.Series([1000.0] * n_calm)
    # Large alternating swings: TR ≈ 15 per volatile bar
    volatile_close = pd.Series([
        1005.0 if i % 2 == 0 else 995.0 for i in range(n_volatile)
    ])
    close = pd.concat([calm_close, volatile_close], ignore_index=True)
    spread = pd.concat(
        [pd.Series([0.05] * n_calm), pd.Series([5.0] * n_volatile)],
        ignore_index=True,
    )
    high = close + spread
    low = close - spread
    n = n_calm + n_volatile
    return pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": high, "low": low, "close": close,
        "volume": pd.Series([1000] * n),
        "complete": pd.Series([True] * n),
    })


def _slope_fail_df() -> pd.DataFrame:
    """
    247 bars of uptrend (ADX>25, EMA aligned) then 3-bar oscillation.
    EMA20 diffs in last slope_persist_bars are mixed sign → TRENDING_UP fails.
    """
    trend = [1000.0 + 0.01 * i for i in range(247)]
    # Significant drop then recovery so EMA20 diff changes sign
    oscillation = [1002.47, 1001.0, 1003.0]
    close = pd.Series(trend + oscillation)
    return _make_df(close, spread=0.01)


# ---------------------------------------------------------------------------
# EC-1: Integration — known-good regime classification
# ---------------------------------------------------------------------------

class TestRegimeIntegration:
    def test_trending_up_detected(self) -> None:
        clf = _make_classifier()
        result = clf.classify(_trending_up_df())
        assert result.regime == RegimeState.TRENDING_UP

    def test_trending_down_detected(self) -> None:
        clf = _make_classifier()
        result = clf.classify(_trending_down_df())
        assert result.regime == RegimeState.TRENDING_DOWN

    def test_ranging_detected(self) -> None:
        clf = _make_classifier()
        result = clf.classify(_ranging_df())
        assert result.regime == RegimeState.RANGING

    def test_expansion_detected(self) -> None:
        clf = _make_classifier()
        result = clf.classify(_expansion_df())
        assert result.regime == RegimeState.EXPANSION

    def test_expansion_priority_over_ranging(self) -> None:
        """EXPANSION fires even when ADX would suggest ranging (choppy volatile data)."""
        clf = _make_classifier()
        result = clf.classify(_expansion_df())
        assert result.regime == RegimeState.EXPANSION

    def test_bootstrap_bars_is_one(self) -> None:
        clf = _make_classifier()
        result = clf.classify(_trending_up_df())
        assert result.bars_in_regime == 1


# ---------------------------------------------------------------------------
# EC-5: Slope persistence gate
# ---------------------------------------------------------------------------

class TestSlopePersistence:
    def test_aligned_adx_strong_but_slope_oscillates_not_trending(self) -> None:
        """
        ADX > adx_trend_min and EMA alignment hold, but EMA20 slope oscillates
        in the last slope_persist_bars → regime must NOT be TRENDING_UP.
        """
        clf = _make_classifier()
        result = clf.classify(_slope_fail_df())
        assert result.regime != RegimeState.TRENDING_UP, (
            f"Slope check failed to gate TRENDING_UP; got {result.regime}"
        )

    def test_consistent_slope_permits_trending(self) -> None:
        """Confirming the opposite: a clean uptrend does produce TRENDING_UP."""
        clf = _make_classifier()
        result = clf.classify(_trending_up_df())
        assert result.regime == RegimeState.TRENDING_UP


# ---------------------------------------------------------------------------
# EC-2: 2-candle confirm + min-hold (mocked _raw_regime)
# ---------------------------------------------------------------------------

class TestHysteresis:
    def test_single_change_does_not_switch(self) -> None:
        """
        After bootstrap, ONE bar of a different regime must not trigger a switch.
        confirm_bars=2 requires two consecutive bars.
        """
        clf = _make_classifier()
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),       # bootstrap
            (RegimeState.TRENDING_UP, 0.9),   # 1 candidate bar
            (RegimeState.RANGING, 0.8),       # candidate reset (revert)
        ])
        r1 = clf.classify(_DUMMY)
        assert r1.regime == RegimeState.RANGING

        r2 = clf.classify(_DUMMY)
        assert r2.regime == RegimeState.RANGING   # must NOT switch

        r3 = clf.classify(_DUMMY)
        assert r3.regime == RegimeState.RANGING   # still RANGING

    def test_two_consecutive_bars_switch(self) -> None:
        """
        Two consecutive bars of a different regime triggers switch (once min_hold met).
        """
        clf = _make_classifier(regime_min_hold_bars=2)   # shorter hold for this test
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),       # bootstrap → bars=1
            (RegimeState.RANGING, 0.8),       # bars=2 (hold now met)
            (RegimeState.TRENDING_UP, 0.9),   # candidate 1
            (RegimeState.TRENDING_UP, 0.9),   # candidate 2 → switch
        ])
        r1 = clf.classify(_DUMMY)
        assert r1.regime == RegimeState.RANGING
        r2 = clf.classify(_DUMMY)
        assert r2.regime == RegimeState.RANGING
        r3 = clf.classify(_DUMMY)
        assert r3.regime == RegimeState.RANGING    # candidate building, not yet 2
        r4 = clf.classify(_DUMMY)
        assert r4.regime == RegimeState.TRENDING_UP   # switch!

    def test_candidate_reset_if_different_raw_appears(self) -> None:
        """Interrupting the candidate with a third regime resets the count."""
        clf = _make_classifier(regime_min_hold_bars=2)
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),       # bootstrap
            (RegimeState.RANGING, 0.8),       # hold=2
            (RegimeState.TRENDING_UP, 0.9),   # candidate TRENDING candidate_bars=1
            (RegimeState.EXPANSION, 0.9),     # different candidate → resets TRENDING candidate
            (RegimeState.EXPANSION, 0.9),     # candidate EXPANSION bars=2 → switch (entering_exp)
        ])
        for _ in range(4):
            clf.classify(_DUMMY)
        r5 = clf.classify(_DUMMY)
        # EXPANSION candidate had 2 consecutive bars → switch
        assert r5.regime == RegimeState.EXPANSION

    def test_min_hold_blocks_premature_switch(self) -> None:
        """
        With min_hold=4, a switch must not occur until bars_in_regime >= 4
        (except for EXPANSION entry which bypasses this).
        """
        clf = _make_classifier()   # min_hold_bars=4
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),       # bootstrap → bars=1
            (RegimeState.TRENDING_UP, 0.9),   # candidate 1 → bars=2
            (RegimeState.TRENDING_UP, 0.9),   # confirmed, hold=(2>=4)=False → bars=3
            (RegimeState.TRENDING_UP, 0.9),   # confirmed, hold=(3>=4)=False → bars=4
            (RegimeState.TRENDING_UP, 0.9),   # confirmed, hold=(4>=4)=True → SWITCH
        ])
        r1 = clf.classify(_DUMMY)
        assert r1.regime == RegimeState.RANGING   # bootstrap
        r2 = clf.classify(_DUMMY)
        assert r2.regime == RegimeState.RANGING   # candidate 1, no switch
        r3 = clf.classify(_DUMMY)
        assert r3.regime == RegimeState.RANGING   # confirmed but hold=False
        r4 = clf.classify(_DUMMY)
        assert r4.regime == RegimeState.RANGING   # confirmed but hold=False
        r5 = clf.classify(_DUMMY)
        assert r5.regime == RegimeState.TRENDING_UP   # now switches


# ---------------------------------------------------------------------------
# EC-3: Asymmetric EXPANSION hysteresis
# ---------------------------------------------------------------------------

class TestExpansionHysteresis:
    def _enter_expansion(self, clf: RegimeClassifier) -> None:
        """Drive clf into EXPANSION state using exactly 3 mocked calls."""
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),   # bootstrap → RANGING, bars=1
            (RegimeState.EXPANSION, 0.9), # candidate 1 → bars=2
            (RegimeState.EXPANSION, 0.9), # candidate 2 → SWITCH to EXPANSION, bars=1
        ])
        for _ in range(3):
            clf.classify(_DUMMY)
        # Sanity: must be in EXPANSION now
        assert clf._current_regime == RegimeState.EXPANSION
        assert clf._bars_in_regime == 1

    def test_expansion_enters_before_min_hold(self) -> None:
        """
        RANGING with only bars_in_regime=2 (< min_hold=4) must still switch to
        EXPANSION after 2 consecutive EXPANSION bars (bypasses min_hold).
        """
        clf = _make_classifier()   # min_hold=4
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),   # bootstrap → bars=1
            (RegimeState.EXPANSION, 0.9), # candidate 1, no confirm; bars=2
            (RegimeState.EXPANSION, 0.9), # confirmed, entering_expansion → SWITCH
        ])
        r1 = clf.classify(_DUMMY)
        assert r1.regime == RegimeState.RANGING
        r2 = clf.classify(_DUMMY)
        assert r2.regime == RegimeState.RANGING    # not yet confirmed
        assert r2.bars_in_regime == 2              # only 2 bars in RANGING (< min_hold=4)
        r3 = clf.classify(_DUMMY)
        assert r3.regime == RegimeState.EXPANSION  # switched despite bars_in_regime=2

    def test_expansion_exit_blocked_until_confirm_and_hold(self) -> None:
        """
        Once in EXPANSION, exit requires confirm_bars=2 AND min_hold_bars=4.
        Verify it stays EXPANSION for 3 calls, switches on the 4th.
        """
        clf = _make_classifier()
        self._enter_expansion(clf)

        # Now try to exit: 4 consecutive RANGING bars
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),  # E1: candidate 1, bars=2
            (RegimeState.RANGING, 0.8),  # E2: confirmed but hold=(2>=4)=F, bars=3
            (RegimeState.RANGING, 0.8),  # E3: confirmed, hold=(3>=4)=F, bars=4
            (RegimeState.RANGING, 0.8),  # E4: confirmed, hold=(4>=4)=T → SWITCH
        ])
        e1 = clf.classify(_DUMMY)
        assert e1.regime == RegimeState.EXPANSION

        e2 = clf.classify(_DUMMY)
        assert e2.regime == RegimeState.EXPANSION   # confirmed but hold not met

        e3 = clf.classify(_DUMMY)
        assert e3.regime == RegimeState.EXPANSION   # still blocked

        e4 = clf.classify(_DUMMY)
        assert e4.regime == RegimeState.RANGING     # now exits

    def test_expansion_exit_requires_confirm_not_just_one_bar(self) -> None:
        """One ranging bar after EXPANSION must not trigger exit."""
        clf = _make_classifier()
        self._enter_expansion(clf)
        clf._raw_regime = _seq_mock([(RegimeState.RANGING, 0.8)])
        result = clf.classify(_DUMMY)
        assert result.regime == RegimeState.EXPANSION


# ---------------------------------------------------------------------------
# EC-4: Gray zone (ADX 20–25)
# ---------------------------------------------------------------------------

class TestGrayZone:
    def test_indeterminate_does_not_change_regime(self) -> None:
        """Gray zone: current regime preserved, no candidate advancement."""
        clf = _make_classifier()
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),     # bootstrap
            (_INDETERMINATE, 0.0),          # gray zone bar 1
            (_INDETERMINATE, 0.0),          # gray zone bar 2
            (_INDETERMINATE, 0.0),          # gray zone bar 3
        ])
        r1 = clf.classify(_DUMMY)
        assert r1.regime == RegimeState.RANGING

        for call_num in range(2, 5):
            r = clf.classify(_DUMMY)
            assert r.regime == RegimeState.RANGING, (
                f"Gray zone call {call_num} changed regime to {r.regime}"
            )

    def test_indeterminate_increments_bars(self) -> None:
        """Gray zone bars still count toward bars_in_regime."""
        clf = _make_classifier()
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),
            (_INDETERMINATE, 0.0),
            (_INDETERMINATE, 0.0),
        ])
        r1 = clf.classify(_DUMMY)
        assert r1.bars_in_regime == 1

        r2 = clf.classify(_DUMMY)
        assert r2.bars_in_regime == 2

        r3 = clf.classify(_DUMMY)
        assert r3.bars_in_regime == 3

    def test_indeterminate_does_not_advance_candidate(self) -> None:
        """
        After a candidate is started, gray zone bars must NOT advance it.
        Candidate must still need confirm_bars consecutive non-gray bars after the gap.
        """
        clf = _make_classifier(regime_min_hold_bars=2)
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),      # bootstrap
            (RegimeState.RANGING, 0.8),      # hold now 2 bars
            (RegimeState.TRENDING_UP, 0.9),  # candidate_bars=1 (no switch yet, not confirmed)
            (_INDETERMINATE, 0.0),           # gray zone — bars_in_regime increments, candidate NOT advanced
            (RegimeState.TRENDING_UP, 0.9),  # candidate_bars=2 (continues from 1) → switch
        ])
        for _ in range(4):
            clf.classify(_DUMMY)
        r5 = clf.classify(_DUMMY)
        # Gray zone preserved candidate at bars=1; this call advances to 2 → switch
        assert r5.regime == RegimeState.TRENDING_UP


# ---------------------------------------------------------------------------
# EC-6: reset() — sequential identical runs
# ---------------------------------------------------------------------------

class TestReset:
    def test_two_runs_produce_identical_results(self) -> None:
        """
        Two sequential backtest runs on the same classifier instance must
        produce identical (regime, bars_in_regime) sequences after reset().
        """
        sequence = [
            (RegimeState.RANGING, 0.8),
            (RegimeState.RANGING, 0.8),
            (RegimeState.TRENDING_UP, 0.9),
            (RegimeState.TRENDING_UP, 0.9),   # switch
            (RegimeState.RANGING, 0.6),
            (RegimeState.RANGING, 0.6),
        ]

        clf = _make_classifier(regime_min_hold_bars=2)

        # Run 1
        clf._raw_regime = _seq_mock(sequence)
        run1 = [(clf.classify(_DUMMY).regime, clf._bars_in_regime) for _ in range(len(sequence))]

        # Reset and run 2 with identical sequence
        clf.reset()
        clf._raw_regime = _seq_mock(sequence)
        run2 = [(clf.classify(_DUMMY).regime, clf._bars_in_regime) for _ in range(len(sequence))]

        assert run1 == run2, f"Run 1: {run1}\nRun 2: {run2}"

    def test_reset_clears_candidate(self) -> None:
        """After reset(), a partially-built candidate must be gone."""
        clf = _make_classifier()
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),
            (RegimeState.TRENDING_UP, 0.9),   # candidate_bars=1
        ])
        clf.classify(_DUMMY)
        clf.classify(_DUMMY)
        assert clf._candidate_regime == RegimeState.TRENDING_UP

        clf.reset()
        assert clf._candidate_regime is None
        assert clf._candidate_bars == 0
        assert clf._current_regime is None
        assert clf._prior_regime is None


# ---------------------------------------------------------------------------
# prior_regime (§2 consultation-window experiment, dated 2026-07-11) -- tracks the
# regime confirmed immediately before the current one, same hold-through convention
# bars_in_regime/current_regime already follow.
# ---------------------------------------------------------------------------

class TestPriorRegime:
    def test_bootstrap_prior_regime_is_none(self) -> None:
        clf = _make_classifier()
        clf._raw_regime = _seq_mock([(RegimeState.RANGING, 0.8)])
        r1 = clf.classify(_DUMMY)
        assert r1.prior_regime is None

    def test_prior_regime_set_on_confirmed_switch(self) -> None:
        """Reuses TestHysteresis.test_two_consecutive_bars_switch's exact sequence:
        RANGING -> TRENDING_UP confirmed switch on bar 4."""
        clf = _make_classifier(regime_min_hold_bars=2)
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),       # bootstrap -> bars=1
            (RegimeState.RANGING, 0.8),       # bars=2 (hold now met)
            (RegimeState.TRENDING_UP, 0.9),   # candidate 1
            (RegimeState.TRENDING_UP, 0.9),   # candidate 2 -> switch
        ])
        for _ in range(3):
            clf.classify(_DUMMY)
        r4 = clf.classify(_DUMMY)
        assert r4.regime == RegimeState.TRENDING_UP
        assert r4.prior_regime == RegimeState.RANGING

    def test_prior_regime_holds_through_same_regime_reinforcement(self) -> None:
        """After a confirmed switch, further bars of the SAME new regime must keep
        reporting the OLD regime as prior_regime -- not flip to the current one."""
        clf = _make_classifier(regime_min_hold_bars=2)
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),
            (RegimeState.RANGING, 0.8),
            (RegimeState.TRENDING_UP, 0.9),
            (RegimeState.TRENDING_UP, 0.9),   # switch, prior_regime -> RANGING
            (RegimeState.TRENDING_UP, 0.9),   # same regime, reinforcement
            (RegimeState.TRENDING_UP, 0.9),   # same regime, reinforcement
        ])
        for _ in range(4):
            clf.classify(_DUMMY)
        r5 = clf.classify(_DUMMY)
        r6 = clf.classify(_DUMMY)
        assert r5.regime == RegimeState.TRENDING_UP
        assert r5.prior_regime == RegimeState.RANGING
        assert r6.prior_regime == RegimeState.RANGING

    def test_prior_regime_holds_through_gray_zone(self) -> None:
        """After a confirmed switch, gray-zone (_INDETERMINATE) bars must hold
        prior_regime unchanged, same convention current_regime already follows."""
        clf = _make_classifier(regime_min_hold_bars=2)
        clf._raw_regime = _seq_mock([
            (RegimeState.RANGING, 0.8),
            (RegimeState.RANGING, 0.8),
            (RegimeState.TRENDING_UP, 0.9),
            (RegimeState.TRENDING_UP, 0.9),   # switch, prior_regime -> RANGING
            (_INDETERMINATE, 0.0),            # gray zone
            (_INDETERMINATE, 0.0),            # gray zone
        ])
        for _ in range(4):
            clf.classify(_DUMMY)
        r5 = clf.classify(_DUMMY)
        r6 = clf.classify(_DUMMY)
        assert r5.regime == RegimeState.TRENDING_UP   # held through gray zone
        assert r5.prior_regime == RegimeState.RANGING
        assert r6.prior_regime == RegimeState.RANGING


# ---------------------------------------------------------------------------
# EC-7: Confidence bounds
# ---------------------------------------------------------------------------

class TestConfidenceBounds:
    def _collect_confidences(self, df: pd.DataFrame) -> list[float]:
        clf = _make_classifier()
        results: list[float] = []
        # Classify the full window and collect confidence
        # In backtest style: each bar extends the window from 1 → N
        for n in range(1, len(df) + 1, 10):   # sample every 10th bar to keep test fast
            sub = df.iloc[:n].copy()
            if n == 1 or n > 50:   # skip very early bars (indicators uninitialised)
                r = clf.classify(sub)
                results.append(r.confidence)
        return results

    def test_trending_confidence_in_bounds(self) -> None:
        for conf in self._collect_confidences(_trending_up_df()):
            assert 0.0 <= conf <= 1.0, f"confidence={conf} out of [0,1]"

    def test_ranging_confidence_in_bounds(self) -> None:
        for conf in self._collect_confidences(_ranging_df()):
            assert 0.0 <= conf <= 1.0, f"confidence={conf} out of [0,1]"

    def test_expansion_confidence_in_bounds(self) -> None:
        for conf in self._collect_confidences(_expansion_df()):
            assert 0.0 <= conf <= 1.0, f"confidence={conf} out of [0,1]"

    def test_mocked_confidence_passed_through(self) -> None:
        """Confidence from _raw_regime must be preserved in RegimeResult."""
        clf = _make_classifier()
        clf._raw_regime = _seq_mock([(RegimeState.RANGING, 0.72)])
        r = clf.classify(_DUMMY)
        assert r.confidence == pytest.approx(0.72)
