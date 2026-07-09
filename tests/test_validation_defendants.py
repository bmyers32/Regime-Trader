"""
"Known-guilt" defendants for the TRADING-RULES §5 validation harness (session prompt's
test philosophy: the harness is a judge, so tests are defendants of known guilt). If a
defendant that SHOULD be convicted survives instead, the harness is broken, not the
test.

One synthetic strategy test double (_MarkerThresholdStrategy) drives all four
defendants: it fires long whenever a precomputed, deterministic "marker" column
(independent uniform noise, no relation to price) exceeds a threshold. Real edge is
injected at DATA-GENERATION time only -- never inside the strategy -- by nudging
future returns upward for a short window strictly AFTER a marker fires (never before,
so this is not lookahead). edge_bps=0.0 means the marker carries no real predictive
information at all: any performance from it is pure sampling noise.

(a) real injected edge -> all three gates pass.
(b) coin-flip (edge_bps=0.0, real transaction costs) -> gate 3 fails: negative
    expectancy is exactly what a zero-edge process plus real costs must produce.
(c) overfit-by-construction: a wide threshold grid searched purely against 1000 bars
    of zero-edge, ZERO-COST noise. Costs are deliberately zeroed for this one
    defendant only -- with real costs every candidate is already negative (cost drag
    swamps the signal), which would convict via "unprofitable," not via the sharp-peak
    mechanism this defendant exists to exercise. The winner-take-max over ~19 noisy
    zero-mean candidates is winner's-curse selection bias, not a rigged number: gate 4
    must flag the sharp peak, gate 3 must fail on the full-dataset OOS.
(d) zero-edge process, cherry-picked lucky seed (found by scanning seeds 0-79 in a
    throwaway calibration script, not hand-tuned) whose one realized stitched-OOS
    trade sequence happens to sum positive. Gate 3's raw net_pnl check alone would
    rubber-stamp this defendant; gate 6's bootstrap resampling is what convicts it
    (HANDOFF.md Track 2 disposition on the gate 6 pass rule).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from bot.backtest.costs import ZERO_COST_MODEL
from bot.backtest.engine import BacktestEngine
from bot.backtest.gate_report import build_gate_report
from bot.backtest.monte_carlo import run_monte_carlo
from bot.backtest.param_sweep import select_best_params
from bot.backtest.stability import run_stability_sweep
from bot.backtest.walk_forward import run_walk_forward
from bot.regime.classifier import RegimeResult, RegimeState
from bot.strategies.base import Signal

_COST_CFG = {
    "spread_pips": {"asian": 1.5, "london": 1.0, "ny_overlap": 1.0},
    "max_spread_pips": {"asian": 5.0, "london": 5.0, "ny_overlap": 5.0},
    "slippage_pips": 0.2,
    "rollover_pips_per_day": {"long": -0.3, "short": 0.1},
}

_N_BARS = 3000
_IS_BARS = 1000
_OOS_BARS = 250


class _AlwaysTrendingUpClassifier:
    """Regime-routing test double: this harness tests gates 3/4/6 in isolation from
    the real regime classifier, so every bar is unconditionally routed TRENDING_UP."""

    def reset(self) -> None:
        pass

    def classify(self, htf_window: pd.DataFrame) -> RegimeResult:
        return RegimeResult(regime=RegimeState.TRENDING_UP, confidence=1.0, bars_in_regime=999)


class _MarkerThresholdStrategy:
    """Fires long whenever window['marker'].iloc[-1] > threshold. Fixed pip SL/TP
    (exit_cfg=None path) keeps trade resolution fast relative to _N_BARS."""

    def __init__(self, threshold: float, warmup: int = 5) -> None:
        self.threshold = threshold
        self.warmup = warmup

    def generate_signal(self, window: pd.DataFrame, regime: RegimeResult) -> Signal | None:
        if len(window) < self.warmup:
            return None
        fired = window["marker"].iloc[-1] > self.threshold
        last_close = window["close"].iloc[-1]
        return Signal(
            strategy="marker_threshold",
            instrument="EUR_USD",
            direction="long",
            entry_ref=last_close,
            sl=last_close - 0.0010,
            tp=last_close + 0.0020,
            confidence_score=1.0 if fired else 0.0,
            reasons=["marker_threshold"],
            vetoes=[],
        )


def _generate_marker_data(
    n_bars: int, marker_seed: int, noise_seed: int, threshold: float, edge_bps: float,
    base_vol: float = 0.0004, boost_bars: int = 6,
) -> pd.DataFrame:
    marker = np.random.default_rng(marker_seed).random(n_bars)

    rng = np.random.default_rng(noise_seed)
    returns = rng.normal(0.0, base_vol, size=n_bars)
    if edge_bps:
        fires = np.nonzero(marker > threshold)[0]
        boost = np.zeros(n_bars)
        for i in fires:
            end = min(n_bars, i + 1 + boost_bars)
            boost[i + 1 : end] = edge_bps  # strictly AFTER the firing bar -- no lookahead
        returns = returns + boost

    close = 1.1000 * np.cumprod(1 + returns)
    open_ = np.concatenate([[1.1000], close[:-1]])
    high = np.maximum(open_, close) + np.abs(rng.normal(0, base_vol * 0.5, size=n_bars))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, base_vol * 0.5, size=n_bars))
    start = pd.Timestamp("2024-01-01T00:00:00Z", tz=timezone.utc)
    times = [start + timedelta(hours=i) for i in range(n_bars)]

    return pd.DataFrame(
        {
            "time": times, "open": open_, "high": high, "low": low, "close": close,
            "volume": 100.0, "complete": True, "marker": marker,
        }
    )


def _aggregate_htf(ltf_df: pd.DataFrame, ratio: int = 4) -> pd.DataFrame:
    rows = []
    for start in range(0, len(ltf_df) - ratio + 1, ratio):
        chunk = ltf_df.iloc[start : start + ratio]
        rows.append(
            {
                "time": chunk["time"].iloc[-1], "open": chunk["open"].iloc[0], "high": chunk["high"].max(),
                "low": chunk["low"].min(), "close": chunk["close"].iloc[-1], "volume": chunk["volume"].sum(),
                "complete": True,
            }
        )
    return pd.DataFrame(rows)


def _make_run_fn(cost_cfg: dict):
    def run_fn(params: dict, ltf_slice: pd.DataFrame, htf_slice: pd.DataFrame):
        engine = BacktestEngine(
            strategy=_MarkerThresholdStrategy(threshold=params["threshold"]),
            regime_classifier=_AlwaysTrendingUpClassifier(),
            instrument="EUR_USD",
            account_currency="USD",
            risk_pct=1.0,
            starting_equity=10_000.0,
            cost_cfg=cost_cfg,
            record_signals=False,
        )
        return engine.run(ltf_slice, htf_slice)

    return run_fn


def _bound_htf(htf_df: pd.DataFrame, max_ltf_ts) -> pd.DataFrame:
    return htf_df[htf_df["time"] <= max_ltf_ts]


@dataclass
class _UnevaluatedGate:
    """Stand-in for a gate this defendant test doesn't need to compute -- the
    defendant's guilt/innocence is fully decided by the gate(s) under test."""

    passed: bool = True
    reason: str = "not evaluated by this defendant test"


# ---------------------------------------------------------------------------
# (a) real injected edge -> all gates pass
# ---------------------------------------------------------------------------

def test_defendant_a_real_edge_passes_all_gates():
    run_fn = _make_run_fn(_COST_CFG)
    ltf = _generate_marker_data(_N_BARS, marker_seed=1, noise_seed=2, threshold=0.5, edge_bps=0.0001)
    htf = _aggregate_htf(ltf)

    wf_report = run_walk_forward(ltf, htf, run_fn, param_grid=[{"threshold": 0.5}], is_bars=_IS_BARS, oos_bars=_OOS_BARS)
    assert wf_report.passed
    assert wf_report.stitched_metrics["trade_count"] > 50

    is_slice = ltf.iloc[:_IS_BARS]
    htf_is = _bound_htf(htf, is_slice["time"].iloc[-1])
    stability = run_stability_sweep(run_fn, is_slice, htf_is, {"threshold": 0.5}, ["threshold"], pct=0.10)
    assert stability.passed

    pnls = [t.pnl for t in wf_report.stitched_trades]
    mc = run_monte_carlo(pnls, starting_equity=10_000.0, seed=42)
    assert mc.passed

    report = build_gate_report("EUR_USD", "marker_threshold", wf_report, stability, mc)
    assert report.passed


# ---------------------------------------------------------------------------
# (b) coin-flip, real costs -> gate 3 fails
# ---------------------------------------------------------------------------

def test_defendant_b_coinflip_fails_gate3():
    run_fn = _make_run_fn(_COST_CFG)
    ltf = _generate_marker_data(_N_BARS, marker_seed=10, noise_seed=11, threshold=0.5, edge_bps=0.0)
    htf = _aggregate_htf(ltf)

    wf_report = run_walk_forward(ltf, htf, run_fn, param_grid=[{"threshold": 0.5}], is_bars=_IS_BARS, oos_bars=_OOS_BARS)

    assert not wf_report.passed
    assert wf_report.stitched_metrics["net_pnl"] <= 0

    report = build_gate_report(
        "EUR_USD", "marker_threshold", wf_report,
        stability_result=_UnevaluatedGate(),
        monte_carlo_result=_UnevaluatedGate(),
    )
    assert not report.passed  # a single failing gate must fail the overall verdict


# ---------------------------------------------------------------------------
# (c) overfit-by-construction: wide grid searched on zero-edge, zero-cost noise
# ---------------------------------------------------------------------------

def test_defendant_c_overfit_by_construction_fails_gate3_and_gate4():
    # ZERO_COST_MODEL deliberately: with real costs every zero-edge candidate is
    # already negative, which would convict via "unprofitable" and never exercise
    # the sharp-peak mechanism gate 4 exists to catch (see module docstring).
    run_fn = _make_run_fn(ZERO_COST_MODEL)
    ltf = _generate_marker_data(_N_BARS, marker_seed=40, noise_seed=41, threshold=0.5, edge_bps=0.0)
    htf = _aggregate_htf(ltf)
    wide_grid = [{"threshold": round(t, 2)} for t in np.arange(0.05, 0.96, 0.05)]

    is_slice = ltf.iloc[:_IS_BARS]
    htf_is = _bound_htf(htf, is_slice["time"].iloc[-1])
    overfit_params, scoreboard = select_best_params(run_fn, is_slice, htf_is, wide_grid)
    best_score = max(row["score"] for row in scoreboard)
    assert best_score > 0  # a spurious positive peak -- winner's-curse selection bias, not real edge

    stability = run_stability_sweep(run_fn, is_slice, htf_is, overfit_params, ["threshold"], pct=0.10)
    assert not stability.passed
    assert "sharp peak" in stability.reason

    wf_report = run_walk_forward(ltf, htf, run_fn, param_grid=wide_grid, is_bars=_IS_BARS, oos_bars=_OOS_BARS)
    assert not wf_report.passed
    assert wf_report.stitched_metrics["net_pnl"] <= 0

    report = build_gate_report(
        "EUR_USD", "marker_threshold", wf_report, stability,
        monte_carlo_result=_UnevaluatedGate(),
    )
    assert not report.passed


# ---------------------------------------------------------------------------
# (d) zero-edge, cherry-picked lucky seed -> gate 3 passes, gate 6 convicts
# ---------------------------------------------------------------------------

def test_defendant_d_lucky_seed_passes_gate3_but_gate6_convicts():
    run_fn = _make_run_fn(_COST_CFG)
    # marker_seed=179/noise_seed=279 found by scanning seeds 0-79 in a throwaway
    # calibration script for a zero-edge (edge_bps=0.0) run whose one realized
    # stitched-OOS trade sequence happens to sum positive -- exactly the "lucky
    # seed" scenario (d) needs, not hand-picked to rig a specific number.
    ltf = _generate_marker_data(_N_BARS, marker_seed=179, noise_seed=279, threshold=0.5, edge_bps=0.0)
    htf = _aggregate_htf(ltf)

    wf_report = run_walk_forward(ltf, htf, run_fn, param_grid=[{"threshold": 0.5}], is_bars=_IS_BARS, oos_bars=_OOS_BARS)
    assert wf_report.passed  # gate 3 alone is fooled by this specific lucky draw
    assert wf_report.stitched_metrics["net_pnl"] > 0

    pnls = [t.pnl for t in wf_report.stitched_trades]
    mc = run_monte_carlo(pnls, starting_equity=10_000.0, seed=42)

    assert not mc.passed
    assert mc.prob_nonpositive > 0.05  # resampling the SAME trades easily produces a non-positive total

    report = build_gate_report(
        "EUR_USD", "marker_threshold", wf_report,
        stability_result=_UnevaluatedGate(),
        monte_carlo_result=mc,
    )
    assert not report.passed  # gate 6 alone overturns gate 3's rubber stamp
