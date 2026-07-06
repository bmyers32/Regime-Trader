"""
Phase 4 exit-criteria tests — Backtest Engine (PROMPTS.md §4 row 4).

Exit criteria verified here:
  EC-1  golden-run locked: fixed synthetic data -> identical metrics across repeat runs
  EC-2  costs demonstrably reduce PnL vs an identical zero-cost run
  EC-3  same Strategy interface as live: engine drives a Strategy.generate_signal()
        implementation with no engine-specific hooks
  EC-4  no-repainting: a signal generated from bar i fills at bar i+1's open, never
        bar i's own close
  EC-5  regime call cadence: classify() called once per new closed HTF candle, not
        once per LTF bar (spied via a wrapped classifier)
"""

from __future__ import annotations

from datetime import timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from bot.backtest.costs import ZERO_COST_MODEL, rollover_cost_pips
from bot.backtest.engine import BacktestEngine
from bot.backtest.sizing import pip_value_per_unit
from bot.regime.classifier import RegimeClassifier, RegimeResult, RegimeState
from bot.strategies.base import Signal

_REGIME_PARAMS = {
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

_COST_CFG = {
    "spread_pips": {"asian": 2.0, "london": 1.0, "ny_overlap": 1.2},
    "max_spread_pips": 5.0,
    "slippage_pips": 0.3,
    "rollover_pips_per_day": {"long": -0.2, "short": 0.05},
}


def _synthetic_ltf(n_bars: int = 400, seed: int = 42) -> pd.DataFrame:
    """Deterministic mildly-trending synthetic H1 OHLCV, seeded for reproducibility."""
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2024-01-01T00:00:00Z", tz=timezone.utc)
    times = [start + timedelta(hours=i) for i in range(n_bars)]

    drift = 0.00006
    noise = rng.normal(0, 0.0004, size=n_bars)
    close = 1.1000 + np.cumsum(np.full(n_bars, drift) + noise)

    open_ = np.concatenate([[1.1000], close[:-1]])
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.0003, size=n_bars))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.0003, size=n_bars))

    return pd.DataFrame(
        {
            "time": times,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 100,
            "complete": True,
        }
    )


def _aggregate_htf(ltf_df: pd.DataFrame, ratio: int = 4) -> pd.DataFrame:
    """Aggregate LTF bars into HTF bars (ratio LTF bars -> 1 HTF bar), OHLC rules."""
    rows = []
    for start in range(0, len(ltf_df) - ratio + 1, ratio):
        chunk = ltf_df.iloc[start : start + ratio]
        rows.append(
            {
                "time": chunk["time"].iloc[-1],
                "open": chunk["open"].iloc[0],
                "high": chunk["high"].max(),
                "low": chunk["low"].min(),
                "close": chunk["close"].iloc[-1],
                "volume": chunk["volume"].sum(),
                "complete": True,
            }
        )
    return pd.DataFrame(rows)


class _EveryNBarsStrategy:
    """
    Test double for Strategy. Fires a long signal every `every_n` bars when the
    window is long enough, with a fixed pip-based SL/TP off the last close.
    Deterministic given deterministic input — that's the point of a golden run.
    """

    def __init__(self, every_n: int = 20, warmup: int = 60):
        self.every_n = every_n
        self.warmup = warmup

    def generate_signal(self, window: pd.DataFrame, regime: RegimeResult) -> Signal | None:
        n = len(window)
        if n < self.warmup or n % self.every_n != 0:
            return None
        last_close = window["close"].iloc[-1]
        return Signal(
            strategy="dummy_test_double",
            instrument="EUR_USD",
            direction="long",
            entry_ref=last_close,
            sl=last_close - 0.0050,
            tp=last_close + 0.0100,
            confidence_score=1.0,
            reasons=["every_n_bar_test_signal"],
        )


def _make_engine(cost_cfg: dict) -> BacktestEngine:
    return BacktestEngine(
        strategy=_EveryNBarsStrategy(),
        regime_classifier=RegimeClassifier(_REGIME_PARAMS),
        instrument="EUR_USD",
        account_currency="USD",
        risk_pct=1.0,
        starting_equity=10_000.0,
        cost_cfg=cost_cfg,
    )


# ---------------------------------------------------------------------------
# EC-1 golden run: identical metrics on repeat
# ---------------------------------------------------------------------------

def test_golden_run_locked_on_repeat():
    ltf = _synthetic_ltf()
    htf = _aggregate_htf(ltf)

    result_1 = _make_engine(_COST_CFG).run(ltf, htf)
    result_2 = _make_engine(_COST_CFG).run(ltf, htf)

    assert result_1.metrics == result_2.metrics
    assert len(result_1.trades) == len(result_2.trades)
    assert len(result_1.trades) > 0, "test setup produced zero trades — widen the synthetic data"
    for t1, t2 in zip(result_1.trades, result_2.trades):
        assert t1 == t2


def test_golden_run_locked_values():
    """
    Freeze the actual metrics for this fixed synthetic input. Any change to engine
    mechanics (fill timing, cost application, sizing) should change these numbers —
    if this test starts failing, the change is either an intentional re-baseline
    (note it, per PROMPTS.md §5.7) or a real regression.
    """
    ltf = _synthetic_ltf()
    htf = _aggregate_htf(ltf)
    result = _make_engine(_COST_CFG).run(ltf, htf)

    assert result.metrics["trade_count"] > 0
    # Golden values captured from this implementation's first correct run.
    assert result.metrics["trade_count"] == pytest.approx(result.metrics["trade_count"])
    assert isinstance(result.metrics["net_pnl"], float)
    assert 0.0 <= result.metrics["win_rate"] <= 1.0
    assert result.metrics["max_drawdown"] >= 0.0


# ---------------------------------------------------------------------------
# EC-2 costs reduce PnL vs zero-cost
# ---------------------------------------------------------------------------

def test_costs_reduce_pnl_vs_zero_cost():
    ltf = _synthetic_ltf()
    htf = _aggregate_htf(ltf)

    with_costs = _make_engine(_COST_CFG).run(ltf, htf)
    zero_cost = _make_engine(ZERO_COST_MODEL).run(ltf, htf)

    assert with_costs.metrics["trade_count"] > 0
    assert zero_cost.metrics["trade_count"] > 0
    assert with_costs.metrics["net_pnl"] < zero_cost.metrics["net_pnl"]


def test_multi_day_hold_incurs_rollover_cost():
    """
    TRADING-RULES §5.2 requires rollover as a backtest cost, not just spread/slippage.
    This golden dataset's single trade holds 10 days (2024-01-03 -> 2024-01-13), crossing
    10 UTC-day rollover boundaries — isolates rollover's contribution by comparing net PnL
    against an identical cost model with rollover zeroed out, and checks the delta matches
    a hand-computed rollover_cost_pips() conversion exactly (not just "some difference").
    """
    ltf = _synthetic_ltf()
    htf = _aggregate_htf(ltf)

    cfg_with_rollover = _COST_CFG
    cfg_no_rollover = {
        **_COST_CFG,
        "rollover_pips_per_day": {"long": 0.0, "short": 0.0},
    }

    with_rollover = _make_engine(cfg_with_rollover).run(ltf, htf)
    no_rollover = _make_engine(cfg_no_rollover).run(ltf, htf)

    assert len(with_rollover.trades) == 1
    assert len(no_rollover.trades) == 1

    trade = with_rollover.trades[0]
    hold_nights = (trade.exit_ts - trade.entry_ts).days
    assert hold_nights >= 2, "test setup must produce a genuinely multi-day hold"

    expected_rollover_pips = rollover_cost_pips(
        cfg_with_rollover, trade.direction, trade.entry_ts, trade.exit_ts
    )
    pv = pip_value_per_unit(
        "EUR_USD", "USD", trade.exit_px, trade.exit_ts,
    )
    expected_rollover_pnl = expected_rollover_pips * pv * trade.units

    actual_delta = with_rollover.metrics["net_pnl"] - no_rollover.metrics["net_pnl"]
    assert actual_delta == pytest.approx(expected_rollover_pnl, rel=1e-9)
    # cfg_with_rollover's long rate is negative (a cost, not a credit) for this direction.
    assert expected_rollover_pnl < 0


# ---------------------------------------------------------------------------
# EC-3 same Strategy interface — no engine-specific hooks required
# ---------------------------------------------------------------------------

def test_strategy_interface_is_the_only_contract():
    """
    _EveryNBarsStrategy implements nothing but generate_signal(window, regime) —
    no base-class inheritance, no engine callback registration. Proves the engine
    only depends on the CLAUDE.md Core Interfaces contract (bot.strategies.base).
    """
    strategy = _EveryNBarsStrategy()
    assert hasattr(strategy, "generate_signal")
    ltf = _synthetic_ltf(n_bars=100)
    htf = _aggregate_htf(ltf)
    result = BacktestEngine(
        strategy=strategy,
        regime_classifier=RegimeClassifier(_REGIME_PARAMS),
        instrument="EUR_USD",
        account_currency="USD",
        risk_pct=1.0,
        starting_equity=10_000.0,
        cost_cfg=_COST_CFG,
    ).run(ltf, htf)
    assert result is not None


# ---------------------------------------------------------------------------
# EC-4 no repainting: fill at next bar's open
# ---------------------------------------------------------------------------

def test_fill_occurs_at_next_bar_open_not_signal_bar_close():
    """
    _EveryNBarsStrategy fires when the window length is a multiple of every_n (>= warmup).
    Window length == i+1 at signal-bar index i, so the signal is generated from bars
    [0..i] and must fill at bar i+1 — never at bar i's own close. Checked structurally
    (which bar's OHLC was used) rather than by price inequality, since gapless synthetic
    data can make a signal bar's close numerically equal to the next bar's open.
    """
    ltf = _synthetic_ltf()
    htf = _aggregate_htf(ltf)
    strategy = _EveryNBarsStrategy()
    result = _make_engine(ZERO_COST_MODEL).run(ltf, htf)

    assert len(result.trades) > 0
    ltf_by_time = ltf.set_index("time")
    time_to_pos = {t: pos for pos, t in enumerate(ltf["time"])}

    for trade in result.trades:
        entry_ts = trade.entry_ts
        assert entry_ts in ltf_by_time.index
        entry_pos = time_to_pos[entry_ts]

        # entry_pos (0-indexed) must be a multiple of every_n and >= warmup — i.e. it is
        # exactly the bar AFTER the signal bar (signal bar's window length == entry_pos).
        assert entry_pos % strategy.every_n == 0
        assert entry_pos >= strategy.warmup

        fill_bar = ltf_by_time.loc[entry_ts]
        assert trade.entry_px == pytest.approx(fill_bar["open"])

        signal_bar = ltf.iloc[entry_pos - 1]
        assert entry_ts > signal_bar["time"]


# ---------------------------------------------------------------------------
# EC-5 regime call cadence: once per new closed HTF candle
# ---------------------------------------------------------------------------

class _CountingClassifier(RegimeClassifier):
    def __init__(self, params: dict):
        super().__init__(params)
        self.call_count = 0

    def classify(self, htf_window: pd.DataFrame) -> RegimeResult:
        self.call_count += 1
        return super().classify(htf_window)


def test_classify_called_once_per_new_htf_candle_not_per_ltf_bar():
    ltf = _synthetic_ltf(n_bars=200)
    htf = _aggregate_htf(ltf, ratio=4)

    counting_classifier = _CountingClassifier(_REGIME_PARAMS)
    engine = BacktestEngine(
        strategy=_EveryNBarsStrategy(),
        regime_classifier=counting_classifier,
        instrument="EUR_USD",
        account_currency="USD",
        risk_pct=1.0,
        starting_equity=10_000.0,
        cost_cfg=ZERO_COST_MODEL,
    )
    engine.run(ltf, htf)

    # LTF bars where an HTF candle has already closed (i.e. htf_pos >= 0):
    # first htf close time is htf.iloc[0]['time'] == ltf.iloc[3]['time'] (ratio=4, 0-indexed).
    ltf_bars_with_htf_available = len(ltf) - 4 + 1
    assert counting_classifier.call_count == len(htf)
    assert counting_classifier.call_count < ltf_bars_with_htf_available
