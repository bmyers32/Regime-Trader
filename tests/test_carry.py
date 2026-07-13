"""
carry-with-regime-conditioning tests (TRADING-RULES §6, 2026-07-12 hearing, slot 2).

Covers: signal-only structure (confidence_score always 1.0 -- §1.1 exemption), both
directions (sign of the rate differential), the exact-tie no-signal case, EXPANSION
veto journaling (Signal still returned, vetoes non-empty -- NOT a None short-circuit,
same convention range_reversion's own hard veto uses), SL tested both directions
against the real bot.indicators.core.atr() output, warmup gates (H4-side ATR floor,
rate-history floor), and the regime.htf_window=None defensive path (engine bootstrap).

Uses a tmp_path-backed PolicyRateCache (monkeypatched onto carry._RATES_DIR) rather
than the real calibration/rates/ snapshot -- these are structure tests with synthetic
rates, not a re-verification of the pinned real data (that's HANDOFF.md's
sign-stability exhibit's job).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bot.data.rates import PolicyRateCache
from bot.indicators.core import atr as _atr
from bot.regime.classifier import RegimeResult, RegimeState

import bot.strategies.carry as carry_module
from bot.strategies.carry import Carry

_PARAMS = {"sl_atr_mult": 1.5}


@pytest.fixture(autouse=True)
def _fake_rates_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test in this module gets an isolated, synthetic rate cache -- no
    dependency on the real pinned calibration/rates/ snapshot."""
    monkeypatch.setattr(carry_module, "_RATES_DIR", tmp_path)
    return tmp_path


def _seed_rates(rates_dir: Path, currency: str, dates: list[str], values: list[float]) -> None:
    cache = PolicyRateCache(rates_dir)
    df = pd.DataFrame({"date": pd.to_datetime(dates, utc=True), "rate": values})
    cache.save(currency, df)


def _h4_window(n: int = 60) -> pd.DataFrame:
    """Canonical warm H4 series (same shape test_momentum.py uses) -- plenty of bars
    for ATR(14) to be well past its warmup floor."""
    close = pd.Series([150.0 + 0.1 * i for i in range(n)])
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-06-01", periods=n, freq="4h", tz="UTC"),
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "volume": 100,
            "complete": True,
        }
    )


def _d_window(n: int, last_time: str = "2024-06-10") -> pd.DataFrame:
    close = pd.Series([150.0] * n)
    end = pd.Timestamp(last_time, tz="UTC")
    return pd.DataFrame(
        {
            "time": pd.date_range(end=end, periods=n, freq="1D"),
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100,
            "complete": True,
        }
    )


def _regime(
    d_window: pd.DataFrame | None, regime_state: RegimeState = RegimeState.RANGING
) -> RegimeResult:
    return RegimeResult(regime_state, confidence=0.5, bars_in_regime=10, htf_window=d_window)


class TestSignalOnlyStructure:
    def test_long_signal_when_base_rate_exceeds_quote_rate(self, tmp_path: Path) -> None:
        _seed_rates(tmp_path, "USD", ["2024-01-01"], [5.0])
        _seed_rates(tmp_path, "JPY", ["2024-01-01"], [0.1])
        strategy = Carry(_PARAMS, "USD_JPY")

        signal = strategy.generate_signal(_h4_window(), _regime(_d_window(30)))

        assert signal is not None
        assert signal.direction == "long"
        assert signal.confidence_score == pytest.approx(1.0)
        assert signal.vetoes == []
        assert signal.strategy == "carry"
        assert signal.instrument == "USD_JPY"
        assert signal.tp is None
        assert "rate_differential_USD_minus_JPY" in signal.reasons[0]

    def test_short_signal_when_base_rate_below_quote_rate(self, tmp_path: Path) -> None:
        _seed_rates(tmp_path, "GBP", ["2024-01-01"], [0.1])
        _seed_rates(tmp_path, "JPY", ["2024-01-01"], [5.0])
        strategy = Carry(_PARAMS, "GBP_JPY")

        signal = strategy.generate_signal(_h4_window(), _regime(_d_window(30)))

        assert signal is not None
        assert signal.direction == "short"
        assert signal.confidence_score == pytest.approx(1.0)
        assert signal.vetoes == []

    def test_exact_tie_is_no_signal(self, tmp_path: Path) -> None:
        _seed_rates(tmp_path, "USD", ["2024-01-01"], [2.5])
        _seed_rates(tmp_path, "JPY", ["2024-01-01"], [2.5])
        strategy = Carry(_PARAMS, "USD_JPY")

        assert strategy.generate_signal(_h4_window(), _regime(_d_window(30))) is None


class TestExpansionVeto:
    def test_expansion_journals_veto_but_still_returns_signal(self, tmp_path: Path) -> None:
        """Spec C.2: suspend new entries only, journaled -- NOT a None short-circuit.
        Same convention range_reversion's own hard veto uses."""
        _seed_rates(tmp_path, "USD", ["2024-01-01"], [5.0])
        _seed_rates(tmp_path, "JPY", ["2024-01-01"], [0.1])
        strategy = Carry(_PARAMS, "USD_JPY")

        signal = strategy.generate_signal(
            _h4_window(), _regime(_d_window(30), regime_state=RegimeState.EXPANSION)
        )

        assert signal is not None
        assert signal.direction == "long"
        assert signal.vetoes == ["expansion_regime"]

    def test_non_expansion_regimes_never_veto(self, tmp_path: Path) -> None:
        _seed_rates(tmp_path, "USD", ["2024-01-01"], [5.0])
        _seed_rates(tmp_path, "JPY", ["2024-01-01"], [0.1])
        strategy = Carry(_PARAMS, "USD_JPY")

        for state in (
            RegimeState.RANGING,
            RegimeState.TRENDING_UP,
            RegimeState.TRENDING_DOWN,
            RegimeState.COMPRESSION,
        ):
            signal = strategy.generate_signal(_h4_window(), _regime(_d_window(30), regime_state=state))
            assert signal.vetoes == []


class TestStopLossBothDirections:
    def test_long_sl_matches_real_atr(self, tmp_path: Path) -> None:
        _seed_rates(tmp_path, "USD", ["2024-01-01"], [5.0])
        _seed_rates(tmp_path, "JPY", ["2024-01-01"], [0.1])
        strategy = Carry(_PARAMS, "USD_JPY")
        window = _h4_window()
        atr_now = _atr(window["high"], window["low"], window["close"], 14).iloc[-1]
        last_close = window["close"].iloc[-1]

        signal = strategy.generate_signal(window, _regime(_d_window(30)))

        assert signal.sl == pytest.approx(last_close - _PARAMS["sl_atr_mult"] * atr_now)
        assert signal.sl < signal.entry_ref  # protective stop below entry for a long

    def test_short_sl_matches_real_atr(self, tmp_path: Path) -> None:
        _seed_rates(tmp_path, "GBP", ["2024-01-01"], [0.1])
        _seed_rates(tmp_path, "JPY", ["2024-01-01"], [5.0])
        strategy = Carry(_PARAMS, "GBP_JPY")
        window = _h4_window()
        atr_now = _atr(window["high"], window["low"], window["close"], 14).iloc[-1]
        last_close = window["close"].iloc[-1]

        signal = strategy.generate_signal(window, _regime(_d_window(30)))

        assert signal.sl == pytest.approx(last_close + _PARAMS["sl_atr_mult"] * atr_now)
        assert signal.sl > signal.entry_ref  # protective stop above entry for a short


class TestWarmupGates:
    def test_none_when_htf_window_is_none(self, tmp_path: Path) -> None:
        """Engine-bootstrap / non-engine-caller defensive path -- not consulted, not journaled."""
        _seed_rates(tmp_path, "USD", ["2024-01-01"], [5.0])
        _seed_rates(tmp_path, "JPY", ["2024-01-01"], [0.1])
        strategy = Carry(_PARAMS, "USD_JPY")
        assert strategy.generate_signal(_h4_window(), _regime(None)) is None

    def test_none_when_h4_window_shorter_than_atr_warmup(self, tmp_path: Path) -> None:
        _seed_rates(tmp_path, "USD", ["2024-01-01"], [5.0])
        _seed_rates(tmp_path, "JPY", ["2024-01-01"], [0.1])
        strategy = Carry(_PARAMS, "USD_JPY")
        window = _h4_window(n=10)  # well under _ATR_WARMUP_BARS (42)
        assert strategy.generate_signal(window, _regime(_d_window(30))) is None

    def test_none_when_rate_history_does_not_reach_back_this_far(self, tmp_path: Path) -> None:
        """D-bar's date is before either currency's first pinned observation."""
        _seed_rates(tmp_path, "USD", ["2024-06-01"], [5.0])
        _seed_rates(tmp_path, "JPY", ["2024-06-01"], [0.1])
        strategy = Carry(_PARAMS, "USD_JPY")
        # d_window's last bar defaults to 2024-06-10, so an earlier rate-history
        # start (2024-01-01, before either currency's own first observation) should
        # still fail if the D-bar itself predates the observation -- use a D window
        # whose last bar is well before the seeded 2024-06-01 rate.
        early_d = _d_window(30, last_time="2024-01-10")
        assert strategy.generate_signal(_h4_window(), _regime(early_d)) is None

    def test_missing_currency_raises_at_construction(self, tmp_path: Path) -> None:
        """No cached rate history for either leg -- fail loudly at construction,
        not silently at generate_signal time."""
        with pytest.raises(RuntimeError, match="No cached policy-rate history"):
            Carry(_PARAMS, "USD_JPY")
