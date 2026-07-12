"""
D1/H4 time-series momentum tests (TRADING-RULES §6, 2026-07-12 hearing, slot 1).

Covers: signal-only structure (confidence_score always 1.0, vetoes always empty --
TRADING-RULES §1.1 exemption), both directions, the flat/zero-return no-signal case,
SL tested both directions against the real bot.indicators.core.atr() output (not
hand-derived -- same "verified numerically before writing fixtures" discipline
test_range_reversion.py uses), warmup gates (D-side n+1 floor, H4-side ATR floor),
and the regime.htf_window=None defensive path (engine bootstrap / non-engine callers).
"""

from __future__ import annotations

import pandas as pd
import pytest

from bot.indicators.core import atr as _atr
from bot.regime.classifier import RegimeResult, RegimeState
from bot.strategies.momentum import Momentum

_PARAMS = {"n": 20, "sl_atr_mult": 1.5}
_STRATEGY = Momentum(_PARAMS, "EUR_USD")


def _h4_window(n: int = 60) -> pd.DataFrame:
    """Canonical warm H4 series (same shape as test_indicators.py's golden series) --
    plenty of bars for ATR(14) to be well past its warmup floor."""
    close = pd.Series([1.0 + 0.01 * i for i in range(n)])
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC"),
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 0.005,
            "low": close - 0.005,
            "close": close,
            "volume": 100,
            "complete": True,
        }
    )


def _d_window(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    close = pd.Series(closes)
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC"),
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100,
            "complete": True,
        }
    )


def _regime(d_closes: list[float] | None) -> RegimeResult:
    htf_window = _d_window(d_closes) if d_closes is not None else None
    return RegimeResult(RegimeState.RANGING, confidence=0.5, bars_in_regime=10, htf_window=htf_window)


class TestSignalOnlyStructure:
    def test_long_signal_fires_confidence_1_no_vetoes(self) -> None:
        d_closes = [100.0] * 20 + [110.0]  # 21 bars, trailing_return(20) = +0.10
        regime = _regime(d_closes)
        window = _h4_window()

        signal = _STRATEGY.generate_signal(window, regime)

        assert signal is not None
        assert signal.direction == "long"
        assert signal.confidence_score == pytest.approx(1.0)
        assert signal.vetoes == []
        assert signal.strategy == "momentum"
        assert signal.instrument == "EUR_USD"
        assert signal.tp is None
        assert "trailing_return_n20" in signal.reasons[0]

    def test_short_signal_mirrors(self) -> None:
        d_closes = [100.0] * 20 + [90.0]  # trailing_return(20) = -0.10
        regime = _regime(d_closes)
        window = _h4_window()

        signal = _STRATEGY.generate_signal(window, regime)

        assert signal is not None
        assert signal.direction == "short"
        assert signal.confidence_score == pytest.approx(1.0)
        assert signal.vetoes == []

    def test_zero_trailing_return_is_no_signal(self) -> None:
        d_closes = [100.0] * 21  # flat -> trailing_return(20) == 0.0 exactly
        regime = _regime(d_closes)
        window = _h4_window()

        assert _STRATEGY.generate_signal(window, regime) is None


class TestStopLossBothDirections:
    def test_long_sl_matches_real_atr(self) -> None:
        d_closes = [100.0] * 20 + [110.0]
        regime = _regime(d_closes)
        window = _h4_window()
        atr_now = _atr(window["high"], window["low"], window["close"], 14).iloc[-1]
        last_close = window["close"].iloc[-1]

        signal = _STRATEGY.generate_signal(window, regime)

        assert signal.sl == pytest.approx(last_close - _PARAMS["sl_atr_mult"] * atr_now)
        assert signal.sl < signal.entry_ref  # protective stop below entry for a long

    def test_short_sl_matches_real_atr(self) -> None:
        d_closes = [100.0] * 20 + [90.0]
        regime = _regime(d_closes)
        window = _h4_window()
        atr_now = _atr(window["high"], window["low"], window["close"], 14).iloc[-1]
        last_close = window["close"].iloc[-1]

        signal = _STRATEGY.generate_signal(window, regime)

        assert signal.sl == pytest.approx(last_close + _PARAMS["sl_atr_mult"] * atr_now)
        assert signal.sl > signal.entry_ref  # protective stop above entry for a short


class TestWarmupGates:
    def test_none_when_htf_window_is_none(self) -> None:
        """Engine-bootstrap / non-engine-caller defensive path -- not consulted, not journaled."""
        regime = _regime(None)
        window = _h4_window()
        assert _STRATEGY.generate_signal(window, regime) is None

    def test_none_when_d_window_shorter_than_n_plus_1(self) -> None:
        d_closes = [100.0] * 15  # < n+1 (21) for n=20
        regime = _regime(d_closes)
        window = _h4_window()
        assert _STRATEGY.generate_signal(window, regime) is None

    def test_none_when_h4_window_shorter_than_atr_warmup(self) -> None:
        d_closes = [100.0] * 20 + [110.0]
        regime = _regime(d_closes)
        window = _h4_window(n=10)  # well under _ATR_WARMUP_BARS (42)
        assert _STRATEGY.generate_signal(window, regime) is None

    def test_exactly_n_plus_1_d_bars_is_sufficient(self) -> None:
        """The floor is len(d_close) >= n+1, not a stricter multiple."""
        d_closes = [100.0] * 20 + [105.0]  # exactly 21 bars for n=20
        regime = _regime(d_closes)
        window = _h4_window()
        signal = _STRATEGY.generate_signal(window, regime)
        assert signal is not None


class TestDifferentN:
    def test_n60_reads_its_own_params_n(self) -> None:
        strategy_n60 = Momentum({"n": 60, "sl_atr_mult": 1.5}, "GBP_JPY")
        d_closes = [100.0] * 60 + [120.0]  # trailing_return(60) = +0.20
        regime = _regime(d_closes)
        window = _h4_window()

        signal = strategy_n60.generate_signal(window, regime)

        assert signal is not None
        assert signal.direction == "long"
        assert "trailing_return_n60" in signal.reasons[0]
