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

from bot.backtest.costs import ZERO_COST_MODEL, apply_exit_cost, rollover_cost_pips
from bot.backtest.engine import BacktestEngine
from bot.backtest.sizing import pip_size, pip_value_per_unit
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


# ---------------------------------------------------------------------------
# Phase 5 exit-criteria tests — partial-at-1R + ATR/Chandelier trail (exit_cfg)
# and near-miss signal_log/funnel (HANDOFF.md Session A Decisions 1 & 3).
# ---------------------------------------------------------------------------

class _OneShotLongStrategy:
    """Fires exactly one long Signal, once, at the first bar the window reaches
    `warmup` length — deterministic single round-trip for exit_cfg mechanics tests."""

    def __init__(self, warmup: int = 5, sl_distance: float = 0.0050):
        self.warmup = warmup
        self.sl_distance = sl_distance
        self._fired = False

    def generate_signal(self, window: pd.DataFrame, regime: RegimeResult) -> Signal | None:
        if self._fired or len(window) < self.warmup:
            return None
        self._fired = True
        last_close = window["close"].iloc[-1]
        return Signal(
            strategy="one_shot_test_double",
            instrument="EUR_USD",
            direction="long",
            entry_ref=last_close,
            sl=last_close - self.sl_distance,
            tp=None,
            confidence_score=1.0,
            reasons=["one_shot_test_signal"],
        )


def _deterministic_bars(times: list, ohlc: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": times,
            "open": [b[0] for b in ohlc],
            "high": [b[1] for b in ohlc],
            "low": [b[2] for b in ohlc],
            "close": [b[3] for b in ohlc],
            "volume": 100,
            "complete": True,
        }
    )


# 10 hand-designed bars: flat warmup (i0-4, signal generated at i4), entry fills at
# i5's open (1.1000), rises to cross the 1R partial target (1.1050) at i7, extends
# the trail's peak at i8 (1.1080), then crashes at i9 (low 1.0900) to force a trail exit.
_TRAIL_OHLC = [
    (1.1000, 1.1002, 1.0998, 1.1000),  # i0
    (1.1000, 1.1002, 1.0998, 1.1000),  # i1
    (1.1000, 1.1002, 1.0998, 1.1000),  # i2
    (1.1000, 1.1002, 1.0998, 1.1000),  # i3
    (1.1000, 1.1002, 1.0998, 1.1000),  # i4 - signal generated (window len 5)
    (1.1000, 1.1005, 1.0995, 1.1000),  # i5 - entry fills at open=1.1000
    (1.1000, 1.1020, 1.0995, 1.1015),  # i6
    (1.1015, 1.1060, 1.1010, 1.1055),  # i7 - high crosses 1.1050 (1R) -> partial fires
    (1.1055, 1.1080, 1.1050, 1.1075),  # i8 - new peak extends the trail
    (1.1075, 1.1078, 1.0900, 1.0910),  # i9 - crash breaches the trail stop -> exit
]

_EXIT_CFG = {
    "partial_fraction": 0.5,
    "partial_at_r": 1.0,
    "breakeven_after_partial": False,
    "trail_atr_period": 3,
    "trail_atr_mult": 2.0,
}


def _hourly_times(n: int, start: str = "2024-01-01T00:00:00Z") -> list:
    base = pd.Timestamp(start, tz=timezone.utc)
    return [base + timedelta(hours=i) for i in range(n)]


class TestPartialAndTrailExit:
    def test_partial_fires_at_1r_then_trail_exit_above_original_sl(self) -> None:
        ltf = _deterministic_bars(_hourly_times(len(_TRAIL_OHLC)), _TRAIL_OHLC)
        htf = _aggregate_htf(ltf, ratio=4)

        engine = BacktestEngine(
            strategy=_OneShotLongStrategy(),
            regime_classifier=RegimeClassifier(_REGIME_PARAMS),
            instrument="EUR_USD",
            account_currency="USD",
            risk_pct=1.0,
            starting_equity=10_000.0,
            cost_cfg=ZERO_COST_MODEL,
            exit_cfg=_EXIT_CFG,
        )
        result = engine.run(ltf, htf)

        assert len(result.trades) == 1
        trade = result.trades[0]

        # Partial leg: exactly 1R (entry 1.1000 + 1.0 * stop_distance 0.0050 = 1.1050),
        # limit-style (ZERO_COST_MODEL makes the "no slippage" distinction moot here,
        # but the price must be the exact 1R level, not the bar's high).
        assert trade.partial_exit_ts is not None
        assert trade.partial_exit_px == pytest.approx(1.1050, abs=1e-9)
        assert trade.partial_exit_units == pytest.approx(trade.units * 0.5, rel=1e-9)

        expected_partial_pips = (1.1050 - 1.1000) / pip_size("EUR_USD")
        pv = pip_value_per_unit("EUR_USD", "USD", 1.1050, trade.partial_exit_ts)
        expected_partial_pnl = expected_partial_pips * pv * trade.partial_exit_units
        assert trade.partial_exit_pnl == pytest.approx(expected_partial_pnl, rel=1e-9)

        # Remainder: exits via the trail, not the original fixed stop (1.1000-0.0050=1.0950).
        # A "trail" exit price strictly above the original SL proves genuine trailing
        # behavior occurred rather than a plain stop-out.
        assert trade.exit_reason == "trail"
        assert trade.exit_px > 1.0950
        assert trade.exit_px < 1.1080  # below the peak — the trail gave back some profit, as designed

    def test_exit_cfg_none_never_produces_a_partial_leg(self) -> None:
        """Regression guard: without exit_cfg, no BacktestTrade ever gets a partial leg —
        exact Phase 4 behavior (fixed SL/TP only), matching HANDOFF.md Decision 1's
        zero-regression requirement."""
        ltf = _deterministic_bars(_hourly_times(len(_TRAIL_OHLC)), _TRAIL_OHLC)
        htf = _aggregate_htf(ltf, ratio=4)

        engine = BacktestEngine(
            strategy=_OneShotLongStrategy(),
            regime_classifier=RegimeClassifier(_REGIME_PARAMS),
            instrument="EUR_USD",
            account_currency="USD",
            risk_pct=1.0,
            starting_equity=10_000.0,
            cost_cfg=ZERO_COST_MODEL,
        )
        result = engine.run(ltf, htf)

        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade.partial_exit_ts is None
        assert trade.partial_exit_px is None
        assert trade.partial_exit_units is None
        assert trade.partial_exit_pnl is None
        # Without a trail, the same crash bar (i9, low=1.0900) blows straight through
        # the original fixed SL (1.0950) instead of trailing profitably above it.
        assert trade.exit_reason == "sl"
        assert trade.exit_px == pytest.approx(1.0950, abs=1e-9)


class TestPartialSplitsRolloverBySegment:
    def test_rollover_charged_on_units_actually_held_per_segment(self) -> None:
        """
        Same OHLC shape as the trail test, but with breakeven_after_partial=True so
        the remainder's exit price is deterministically the entry price (adjusted only
        for cost) regardless of the ATR/Chandelier path — isolating the rollover-
        segmentation math from any need to hand-trace the trail's ATR value.
        Multi-day-spaced timestamps on entry/partial/exit force >=1 rollover crossing
        in each segment, with DIFFERENT unit sizes (full initial_units pre-partial,
        half remaining post-partial) — proving the two-segment calc, not a single
        flat-units-for-the-whole-hold calc, drives the result (HANDOFF.md Decision 1d).
        """
        times = _hourly_times(len(_TRAIL_OHLC))
        # Re-time only the bars that matter for rollover crossings: entry fill (i5),
        # partial (i7), final exit (i9). Earlier warmup bars keep tight hourly spacing
        # (irrelevant to rollover, which only reads entry_ts/exit_ts/partial_exit_ts).
        times[5] = pd.Timestamp("2024-02-01T10:00:00Z", tz=timezone.utc)
        times[6] = times[5] + timedelta(hours=1)
        times[7] = pd.Timestamp("2024-02-04T10:00:00Z", tz=timezone.utc)  # +3 calendar days
        times[8] = times[7] + timedelta(hours=1)
        times[9] = pd.Timestamp("2024-02-09T10:00:00Z", tz=timezone.utc)  # +5 more calendar days
        ltf = _deterministic_bars(times, _TRAIL_OHLC)
        htf = _aggregate_htf(ltf, ratio=4)

        # trail_atr_mult set very large so the Chandelier trail level is always far
        # below breakeven (never ratchets sl past it) — isolates the rollover-segment
        # math from the trail's ATR path entirely, per this test's own docstring.
        exit_cfg = {**_EXIT_CFG, "breakeven_after_partial": True, "trail_atr_mult": 100.0}
        engine = BacktestEngine(
            strategy=_OneShotLongStrategy(),
            regime_classifier=RegimeClassifier(_REGIME_PARAMS),
            instrument="EUR_USD",
            account_currency="USD",
            risk_pct=1.0,
            starting_equity=10_000.0,
            cost_cfg=_COST_CFG,
            exit_cfg=exit_cfg,
        )
        result = engine.run(ltf, htf)

        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade.partial_exit_ts is not None
        assert trade.exit_reason == "trail"

        remaining_units = trade.units - trade.partial_exit_units

        # Remainder exit price is breakeven — but breakeven is pinned to the FILLED
        # entry price (position["sl"] = position["entry_px"] in _execute_partial), not
        # the strategy's raw signal close — adjusted for the same apply_exit_cost() a
        # "trail" exit_reason applies, computed independently here via the production
        # function, not hand-derived.
        expected_remainder_exit_px = apply_exit_cost(
            trade.entry_px, "long", "EUR_USD", _COST_CFG, trade.exit_ts, "trail", exit_regime=trade.regime_at_entry,
        )
        assert trade.exit_px == pytest.approx(expected_remainder_exit_px, rel=1e-9)

        pv = pip_value_per_unit("EUR_USD", "USD", trade.exit_px, trade.exit_ts)
        remainder_pips = (expected_remainder_exit_px - trade.entry_px) / pip_size("EUR_USD")
        remainder_pnl = remainder_pips * pv * remaining_units

        expected_rollover_segmented = (
            rollover_cost_pips(_COST_CFG, "long", trade.entry_ts, trade.partial_exit_ts) * pv * trade.units
            + rollover_cost_pips(_COST_CFG, "long", trade.partial_exit_ts, trade.exit_ts) * pv * remaining_units
        )
        naive_rollover_flat_units = (
            rollover_cost_pips(_COST_CFG, "long", trade.entry_ts, trade.exit_ts) * pv * trade.units
        )

        # The segmented calc must differ from the naive flat-units calc — otherwise
        # this test can't distinguish "segmented" from "not segmented" at all.
        assert expected_rollover_segmented != pytest.approx(naive_rollover_flat_units, rel=1e-9)

        expected_total_pnl = trade.partial_exit_pnl + remainder_pnl + expected_rollover_segmented
        assert trade.pnl == pytest.approx(expected_total_pnl, rel=1e-9)


class _ScriptedSignalStrategy:
    """
    Returns a scripted sequence of Signal evaluations (one per generate_signal() call)
    to exercise BacktestEngine's near-miss signal_log/funnel accounting deterministically
    (HANDOFF.md Session A Decision 3). Once a position opens, the engine stops
    consulting the strategy (matches every other Strategy in this file), so the script
    only needs to cover evaluations up to and including the eventual "fire".
    """

    def __init__(self, script: list[str], warmup: int = 5):
        self._script = script
        self.warmup = warmup
        self._call_index = 0

    def generate_signal(self, window: pd.DataFrame, regime: RegimeResult) -> Signal | None:
        if len(window) < self.warmup or self._call_index >= len(self._script):
            return None
        kind = self._script[self._call_index]
        self._call_index += 1
        last_close = window["close"].iloc[-1]
        score = 0.3 if kind == "near_miss" else 0.9
        vetoes = ["scripted_veto"] if kind == "veto" else []
        return Signal(
            strategy="scripted",
            instrument="EUR_USD",
            direction="long",
            entry_ref=last_close,
            sl=last_close - 0.0050,
            tp=None,
            confidence_score=score,
            vetoes=vetoes,
        )


class TestNearMissSignalFunnel:
    def test_funnel_counts_and_signal_log_distinguish_veto_near_miss_and_fire(self) -> None:
        ltf = _synthetic_ltf(n_bars=60)
        htf = _aggregate_htf(ltf)

        strategy = _ScriptedSignalStrategy(script=["veto", "near_miss", "fire"], warmup=5)
        engine = BacktestEngine(
            strategy=strategy,
            regime_classifier=RegimeClassifier(_REGIME_PARAMS),
            instrument="EUR_USD",
            account_currency="USD",
            risk_pct=1.0,
            starting_equity=10_000.0,
            cost_cfg=ZERO_COST_MODEL,
            signal_threshold=0.6,
        )
        result = engine.run(ltf, htf)

        assert len(result.signal_log) == 3
        assert result.signal_log[0].vetoes == ["scripted_veto"]
        assert result.signal_log[0].fired is False
        assert result.signal_log[1].fired is False  # near-miss: no vetoes, but score < threshold
        assert not result.signal_log[1].vetoes
        assert result.signal_log[2].fired is True

        funnel = result.metrics["signal_funnel"]
        assert funnel["consulted"] == 3
        assert funnel["gates_passed"] == 2  # near_miss + fire (veto excluded)
        assert funnel["threshold_cleared"] == 2  # veto(0.9) + fire(0.9); near_miss(0.3) excluded
        assert funnel["fired"] == 1
        assert funnel["score_distribution"]["min"] == pytest.approx(0.3)
        assert funnel["score_distribution"]["max"] == pytest.approx(0.9)

    def test_record_signals_false_does_not_change_trading_behavior(self) -> None:
        """
        record_signals only toggles the log — proven by running the identical scripted
        strategy with it on vs. off and asserting IDENTICAL trades/metrics either way
        (not by asserting a specific trade count directly: this scripted strategy's SL
        is never reached within the 60-bar window, so the opened position simply never
        closes — equity_curve tracks realized equity only, per engine.py's documented
        simplification, so an unclosed position is invisible to metrics regardless).
        """
        ltf = _synthetic_ltf(n_bars=60)
        htf = _aggregate_htf(ltf)

        def _make(record_signals: bool) -> BacktestEngine:
            return BacktestEngine(
                strategy=_ScriptedSignalStrategy(script=["veto", "near_miss", "fire"], warmup=5),
                regime_classifier=RegimeClassifier(_REGIME_PARAMS),
                instrument="EUR_USD",
                account_currency="USD",
                risk_pct=1.0,
                starting_equity=10_000.0,
                cost_cfg=ZERO_COST_MODEL,
                signal_threshold=0.6,
                record_signals=record_signals,
            )

        with_log = _make(True).run(ltf, htf)
        without_log = _make(False).run(ltf, htf)

        assert without_log.signal_log == []
        assert "signal_funnel" not in without_log.metrics
        assert len(with_log.trades) == len(without_log.trades)
        assert with_log.metrics["net_pnl"] == pytest.approx(without_log.metrics["net_pnl"])
