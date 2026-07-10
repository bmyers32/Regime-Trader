from __future__ import annotations

import pandas as pd
import pytest

from bot.backtest.results import BacktestResult, BacktestTrade
from bot.backtest.walk_forward import (
    WindowOOSResult,
    default_gate3_pass_fn,
    generate_window_bounds,
    run_walk_forward,
    stitch_oos_results,
)


def _trade(entry_ts, pnl: float) -> BacktestTrade:
    step = pd.Timedelta(hours=1) if isinstance(entry_ts, pd.Timestamp) else 1
    return BacktestTrade(
        instrument="EUR_USD",
        direction="long",
        entry_ts=entry_ts,
        exit_ts=entry_ts + step,
        entry_px=1.1,
        exit_px=1.11,
        units=1000.0,
        pnl=pnl,
        pnl_r=pnl / 100.0,
        exit_reason="tp",
        regime_at_entry="TRENDING_UP",
    )


# ---------------------------------------------------------------------------
# generate_window_bounds: contiguous, no gap, no overlap on the OOS side
# ---------------------------------------------------------------------------

def test_generate_window_bounds_contiguous_oos_partition():
    bounds = generate_window_bounds(n_bars=8, is_bars=2, oos_bars=2)

    assert bounds == [(0, 2, 4), (2, 4, 6), (4, 6, 8)]
    # OOS segments partition [2, 8) with no gap and no overlap:
    oos_ranges = [(b[1], b[2]) for b in bounds]
    for (start_a, end_a), (start_b, _) in zip(oos_ranges, oos_ranges[1:]):
        assert end_a == start_b


def test_generate_window_bounds_rejects_nonpositive_sizes():
    with pytest.raises(ValueError):
        generate_window_bounds(n_bars=10, is_bars=0, oos_bars=2)


def test_generate_window_bounds_empty_when_too_few_bars():
    assert generate_window_bounds(n_bars=3, is_bars=2, oos_bars=2) == []


# ---------------------------------------------------------------------------
# stitch_oos_results: known-answer, 3 hand-built windows
# ---------------------------------------------------------------------------

def test_stitch_known_answer_no_gap_no_duplicate():
    w0 = WindowOOSResult(
        trades=[_trade(2, 10.0), _trade(3, -5.0)],
        equity_curve=pd.Series([1002.0, 1003.0], index=pd.Index([2, 3], name="time")),
    )
    w1 = WindowOOSResult(
        trades=[_trade(4, 7.0), _trade(5, 2.0)],
        equity_curve=pd.Series([2002.0, 2003.0], index=pd.Index([4, 5], name="time")),
    )
    w2 = WindowOOSResult(
        trades=[_trade(6, -1.0), _trade(7, 4.0)],
        equity_curve=pd.Series([3002.0, 3003.0], index=pd.Index([6, 7], name="time")),
    )

    trades, equity = stitch_oos_results([w0, w1, w2])

    assert [t.entry_ts for t in trades] == [2, 3, 4, 5, 6, 7]
    assert list(equity.index) == [2, 3, 4, 5, 6, 7]
    assert list(equity.values) == [1002.0, 1003.0, 2002.0, 2003.0, 3002.0, 3003.0]


def test_stitch_raises_on_duplicate_boundary_timestamp():
    w0 = WindowOOSResult(trades=[], equity_curve=pd.Series([1.0, 2.0], index=[2, 3]))
    w1 = WindowOOSResult(trades=[], equity_curve=pd.Series([3.0, 4.0], index=[3, 4]))  # 3 duplicated

    with pytest.raises(ValueError):
        stitch_oos_results([w0, w1])


def test_stitch_raises_on_out_of_order_windows():
    w0 = WindowOOSResult(trades=[], equity_curve=pd.Series([1.0], index=[4]))
    w1 = WindowOOSResult(trades=[], equity_curve=pd.Series([1.0], index=[2]))

    with pytest.raises(ValueError):
        stitch_oos_results([w0, w1])


# ---------------------------------------------------------------------------
# default_gate3_pass_fn
# ---------------------------------------------------------------------------

def test_gate3_pass_fn_fails_on_thin_sample():
    passed, reason = default_gate3_pass_fn({"trade_count": 3, "net_pnl": 500.0}, min_trade_count=20)
    assert not passed
    assert "thin sample" in reason


def test_gate3_pass_fn_fails_on_nonpositive_pnl():
    passed, reason = default_gate3_pass_fn({"trade_count": 50, "net_pnl": -1.0}, min_trade_count=20)
    assert not passed


def test_gate3_pass_fn_passes():
    passed, _ = default_gate3_pass_fn({"trade_count": 50, "net_pnl": 100.0}, min_trade_count=20)
    assert passed


# ---------------------------------------------------------------------------
# run_walk_forward: IS/OOS isolation + boundary-trim, no double counting
#
# Real pd.Timestamp "time" values here (not the bare ints the stitch-only tests
# above use) because run_walk_forward's final stitched_metrics = compute_metrics(...)
# call now buckets trades by entry hour (per-session attribution, Phase 6) — that
# requires entry_ts to actually be a datetime, matching BacktestTrade's declared
# type, not a test-fixture shortcut.
# ---------------------------------------------------------------------------

_EPOCH = pd.Timestamp("2024-01-01", tz="UTC")


def _ts(hour_offset: int) -> pd.Timestamp:
    return _EPOCH + pd.Timedelta(hours=hour_offset)


def _hour_offset(ts: pd.Timestamp) -> int:
    return int((ts - _EPOCH) / pd.Timedelta(hours=1))


def _trade_ts(hour_offset: int, pnl: float) -> BacktestTrade:
    return _trade(_ts(hour_offset), pnl)


def _ltf(n_bars: int) -> pd.DataFrame:
    return pd.DataFrame({"time": [_ts(i) for i in range(n_bars)], "close": [1.0] * n_bars})


def test_run_walk_forward_is_selection_never_sees_oos_bars():
    ltf_df = _ltf(8)
    htf_df = pd.DataFrame({"time": [_ts(i) for i in range(8)]})
    is_call_max_times: list[int] = []

    def run_fn(params, ltf_slice, htf_slice):
        if len(ltf_slice) == 2:  # IS-only selection call (is_bars=2)
            is_call_max_times.append(_hour_offset(ltf_slice["time"].max()))
            return BacktestResult(metrics={"net_pnl": params["x"]})
        # OOS eval call (extended slice, length 4)
        start_ts = _hour_offset(ltf_slice["time"].iloc[0])
        oos_start_ts = start_ts + 2
        trades = [_trade_ts(start_ts + 1, -1.0), _trade_ts(oos_start_ts, 1.0), _trade_ts(oos_start_ts + 1, 1.0)]
        equity = pd.Series(
            [float(t) for t in range(4)],
            index=pd.Index(list(ltf_slice["time"]), name="time"),
        )
        return BacktestResult(trades=trades, equity_curve=equity, metrics={"net_pnl": 0.0})

    report = run_walk_forward(
        ltf_df, htf_df, run_fn, param_grid=[{"x": 1.0}], is_bars=2, oos_bars=2,
    )

    # window boundaries are 2, 4, 6 -- no IS-selection call ever saw a bar >= its own boundary
    assert is_call_max_times == [1, 3, 5]
    assert len(report.windows) == 3


def test_run_walk_forward_trims_boundary_trades_without_double_counting():
    ltf_df = _ltf(8)
    htf_df = pd.DataFrame({"time": [_ts(i) for i in range(8)]})

    def run_fn(params, ltf_slice, htf_slice):
        if len(ltf_slice) == 2:
            return BacktestResult(metrics={"net_pnl": 0.0})
        start_ts = _hour_offset(ltf_slice["time"].iloc[0])
        oos_start_ts = start_ts + 2
        # one trade in the IS-only portion (must be trimmed) + two in OOS (must be kept)
        trades = [_trade_ts(start_ts + 1, -1.0), _trade_ts(oos_start_ts, 1.0), _trade_ts(oos_start_ts + 1, 1.0)]
        equity = pd.Series(
            [10.0, 11.0, 12.0, 13.0],
            index=pd.Index(list(ltf_slice["time"]), name="time"),
        )
        return BacktestResult(trades=trades, equity_curve=equity, metrics={"net_pnl": 0.0})

    report = run_walk_forward(ltf_df, htf_df, run_fn, param_grid=[{"x": 1.0}], is_bars=2, oos_bars=2)

    # 3 windows x 2 kept trades each = 6, each entry_ts appearing exactly once
    entry_times = [t.entry_ts for t in report.stitched_trades]
    assert entry_times == sorted(entry_times)
    assert len(entry_times) == len(set(entry_times)) == 6
    assert entry_times == [_ts(2), _ts(3), _ts(4), _ts(5), _ts(6), _ts(7)]
    # stitched equity has exactly one point per OOS bar, 6 bars total, no gaps/dupes
    assert list(report.stitched_equity.index) == [_ts(2), _ts(3), _ts(4), _ts(5), _ts(6), _ts(7)]


def test_run_walk_forward_raises_when_not_enough_bars():
    ltf_df = _ltf(3)
    htf_df = pd.DataFrame({"time": [0, 1, 2]})
    with pytest.raises(ValueError):
        run_walk_forward(ltf_df, htf_df, lambda *a: None, param_grid=[{"x": 1.0}], is_bars=2, oos_bars=2)
