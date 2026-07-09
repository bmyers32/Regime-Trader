"""
TRADING-RULES §5 gates 2-6 driver for trend_pullback, real OANDA history + real
cost_model (Session B, Step 3). One CLI invocation per pair.

Gate 2 ("backtest w/ costs, >=2yr") is satisfied structurally by every run_fn call
this script makes: real cost_model from instruments.yaml, real >=2yr candle history
from instance/candle_cache/. TRADING-RULES §5 defines no separate gate-2 artifact
and GateReport (bot/backtest/gate_report.py) only carries gates 3/4/6 -- there is
nothing further to compute for gate 2 beyond confirming those two "real" conditions,
which this script's startup log does explicitly (bar counts + date span printed).
Gate 5 (per-regime attribution) is deferred -- GateReport.notes says so on every report.

Fixed choices this script makes, NOT tunable via CLI flags (recorded here so a
re-run is reproducible, not a moving target -- this session's ground rules
prohibit a parameter hunt):
  - param_grid (CHANGED 2026-07-09, Experiment 1 amendment 1): entry_threshold and
    score_weights are now searched INSIDE the walk-forward's own per-window IS
    selection (build_param_grid below) -- NOT pre-tuned on the full dataset first.
    This is the winner's-curse guard test_validation_defendants.py's defendant (c)
    exists to motivate: searching a grid against the FULL dataset before validation
    would let the search see data gate 3 is supposed to judge out-of-sample. Doing
    the search inside each window's own IS slice (the walk-forward's intended use of
    select_best_params) keeps the OOS judgment honest -- each window picks its own
    winner from ONLY its own IS history, stitched-OOS is still evaluated on data the
    selection never saw. All other trend_pullback_params keys (rsi_period,
    pullback_zone_atr_min/max, sl_atr_mult, swing_lookback_bars, exit.*) stay fixed
    at instruments.yaml's provisional defaults -- out of scope for this experiment.
  - walk-forward window sizing: is_bars=3000 H1 bars (~5.7 months), oos_bars=1000
    H1 bars (~1.9 months), step_bars=oos_bars (default) -- standard rolling WFO,
    non-overlapping stitched OOS windows.
  - stability sweep (gate 4) runs over the FULL real history using a REPRESENTATIVE
    config: the (entry_threshold, score_weights) combination chosen by the most
    windows (mode across the 10 walk-forward windows) -- there is no longer a single
    frozen params dict once selection happens per-window, so gate 4 tests the
    config that would most consistently have been "in production" across this
    history. If no config has a clear plurality, that itself is diagnostic (params
    unstable across time) and is printed, not silently resolved by an arbitrary
    tie-break.
  - stability keys/simplex groups (unchanged from before) still cover
    entry_threshold/score_weights alongside the other independent params -- gate 4
    is a DIFFERENT question (is the representative config's neighborhood stable)
    from gate 3's per-window selection (which config wins each window).
  - regime classifier params: instruments.yaml's defaults.regime_params, fixed
    (Phase 3/4 scope, already marked complete in CLAUDE.md's phase table -- not
    re-litigated by this Phase 5 gate run).
  - starting_equity=$10,000, account_currency from instruments.yaml (USD) -- an
    absolute PnL scale factor only; risk_pct-based sizing makes relative results
    (win_rate, R-multiples, drawdown %) independent of this choice.

Usage:
    PYTHONPATH=. python scripts/run_validation_gates.py EUR_USD
"""

from __future__ import annotations

import copy
import sys
from collections import Counter
from pathlib import Path

import yaml

from bot.backtest.engine import BacktestEngine
from bot.backtest.gate_report import build_gate_report, render_text
from bot.backtest.monte_carlo import MonteCarloResult, run_monte_carlo
from bot.backtest.stability import run_stability_sweep
from bot.backtest.walk_forward import run_walk_forward
from bot.data.cache import CandleCache
from bot.regime.classifier import RegimeClassifier
from bot.strategies.trend_pullback import TrendPullback

_ROOT = Path(__file__).resolve().parent.parent
_INSTRUMENTS_YAML = _ROOT / "bot" / "config" / "instruments.yaml"
_CACHE_DIR = _ROOT / "instance" / "candle_cache"

_IS_BARS = 3000
_OOS_BARS = 1000
_STARTING_EQUITY = 10_000.0

_STABILITY_KEYS = [
    "sl_atr_mult",
    "pullback_zone_atr_min",
    "pullback_zone_atr_max",
    "entry_threshold",
    "exit.trail_atr_mult",
    "exit.partial_at_r",
]
_SIMPLEX_GROUPS = [
    [
        "score_weights.pullback_zone",
        "score_weights.reversal_trigger",
        "score_weights.rsi_side",
        "score_weights.ema200_side",
    ],
]

# Experiment 1 amendment 1: entry_threshold/score_weights candidates searched INSIDE
# each walk-forward window's own IS slice (see module docstring). Kept small and
# principled (not an exhaustive hyperparameter search) -- this is validating the
# post-fix structure, not hunting for the best possible number.
_ENTRY_THRESHOLD_GRID = [0.35, 0.45, 0.55, 0.65]
_SCORE_WEIGHTS_GRID = [
    {"pullback_zone": 0.30, "reversal_trigger": 0.25, "rsi_side": 0.25, "ema200_side": 0.20},  # current provisional default
    {"pullback_zone": 0.25, "reversal_trigger": 0.25, "rsi_side": 0.25, "ema200_side": 0.25},  # equal weight
    {"pullback_zone": 0.20, "reversal_trigger": 0.40, "rsi_side": 0.20, "ema200_side": 0.20},  # trigger-heavy
]


def build_param_grid(base_params: dict) -> list[dict]:
    """base_params supplies every OTHER key unchanged (rsi_period, pullback_zone_atr_
    min/max, sl_atr_mult, swing_lookback_bars, exit) -- only entry_threshold and
    score_weights vary across the grid."""
    grid = []
    for threshold in _ENTRY_THRESHOLD_GRID:
        for weights in _SCORE_WEIGHTS_GRID:
            candidate = copy.deepcopy(base_params)
            candidate["entry_threshold"] = threshold
            candidate["score_weights"] = dict(weights)
            grid.append(candidate)
    return grid


def _params_key(params: dict) -> tuple:
    w = params["score_weights"]
    return (params["entry_threshold"], w["pullback_zone"], w["reversal_trigger"], w["rsi_side"], w["ema200_side"])


def most_common_params(windows) -> tuple[dict, int, int]:
    """Mode across walk-forward windows' chosen_params. Returns (representative_params,
    mode_count, total_windows) -- caller decides how to report a weak plurality."""
    keys = [_params_key(w.chosen_params) for w in windows]
    mode_key, mode_count = Counter(keys).most_common(1)[0]
    representative = next(w.chosen_params for w in windows if _params_key(w.chosen_params) == mode_key)
    return representative, mode_count, len(windows)


def _load_raw_config() -> dict:
    with open(_INSTRUMENTS_YAML) as f:
        return yaml.safe_load(f)


def _make_run_fn(instrument: str, account_currency: str, risk_pct: float, regime_params: dict, cost_cfg: dict):
    def run_fn(params: dict, ltf_slice, htf_slice):
        strategy = TrendPullback(params, instrument)
        classifier = RegimeClassifier(regime_params)
        engine = BacktestEngine(
            strategy=strategy,
            regime_classifier=classifier,
            instrument=instrument,
            account_currency=account_currency,
            risk_pct=risk_pct,
            starting_equity=_STARTING_EQUITY,
            cost_cfg=cost_cfg,
            exit_cfg=params["exit"],
            signal_threshold=params["entry_threshold"],
            record_signals=False,
        )
        return engine.run(ltf_slice, htf_slice)

    return run_fn


def run_gates_for_pair(instrument: str) -> dict:
    raw = _load_raw_config()
    defaults = raw["defaults"]
    account_currency = raw.get("account_currency", "USD")
    risk_pct = defaults["risk_pct"]
    regime_params = defaults["regime_params"]
    strategy_params = defaults["trend_pullback_params"]
    cost_model = raw["instruments"][instrument]["cost_model"]
    htf_gran, ltf_gran = defaults["timeframe_htf"], defaults["timeframe_ltf"]

    cache = CandleCache(_CACHE_DIR)
    htf_df = cache.load(instrument, htf_gran)
    ltf_df = cache.load(instrument, ltf_gran)
    if htf_df is None or ltf_df is None or htf_df.empty or ltf_df.empty:
        raise RuntimeError(
            f"No cached history for {instrument} ({htf_gran}/{ltf_gran}) -- "
            "run scripts/fetch_history.py on PA first, then copy instance/candle_cache/*.parquet locally."
        )

    span_days = (ltf_df["time"].max() - ltf_df["time"].min()).days
    print(
        f"[{instrument}] {ltf_gran} bars={len(ltf_df)} {htf_gran} bars={len(htf_df)} "
        f"span={ltf_df['time'].min().date()} -> {ltf_df['time'].max().date()} ({span_days}d) "
        f"cost_model.max_spread_pips={cost_model['max_spread_pips']} "
        f"entry_blackout_hours_utc={cost_model.get('entry_blackout_hours_utc')}"
    )

    run_fn = _make_run_fn(instrument, account_currency, risk_pct, regime_params, cost_model)
    param_grid = build_param_grid(strategy_params)
    print(
        f"[{instrument}] param_grid: {len(param_grid)} candidates "
        f"({len(_ENTRY_THRESHOLD_GRID)} thresholds x {len(_SCORE_WEIGHTS_GRID)} weight vectors), "
        f"searched inside each window's own IS slice",
        flush=True,
    )

    print(f"[{instrument}] gate 3: walk-forward (is_bars={_IS_BARS}, oos_bars={_OOS_BARS}) ...", flush=True)
    wf_report = run_walk_forward(ltf_df, htf_df, run_fn, param_grid, is_bars=_IS_BARS, oos_bars=_OOS_BARS)
    print(
        f"[{instrument}] gate 3 done: {len(wf_report.windows)} windows, "
        f"stitched trade_count={wf_report.stitched_metrics['trade_count']}, "
        f"net_pnl={wf_report.stitched_metrics['net_pnl']:.2f}, passed={wf_report.passed}",
        flush=True,
    )

    representative_params, mode_count, n_windows = most_common_params(wf_report.windows)
    print(
        f"[{instrument}] per-window chosen params (mode wins {mode_count}/{n_windows} windows): "
        f"entry_threshold={representative_params['entry_threshold']} "
        f"score_weights={representative_params['score_weights']}",
        flush=True,
    )
    for w in wf_report.windows:
        print(
            f"    window {w.window_index}: entry_threshold={w.chosen_params['entry_threshold']} "
            f"score_weights={w.chosen_params['score_weights']}"
        )

    print(f"[{instrument}] gate 4: stability sweep over full history (representative config) ...", flush=True)
    stability = run_stability_sweep(
        run_fn, ltf_df, htf_df, representative_params, _STABILITY_KEYS, simplex_groups=_SIMPLEX_GROUPS
    )
    print(f"[{instrument}] gate 4 done: passed={stability.passed}", flush=True)

    pnls = [t.pnl for t in wf_report.stitched_trades]
    print(f"[{instrument}] gate 6: monte carlo over {len(pnls)} stitched OOS trades ...", flush=True)
    if pnls:
        mc = run_monte_carlo(pnls, starting_equity=_STARTING_EQUITY)
    else:
        mc = MonteCarloResult(passed=False, reason="no stitched OOS trades to evaluate -- Monte Carlo requires >=1 trade")
    print(f"[{instrument}] gate 6 done: passed={mc.passed}", flush=True)

    report = build_gate_report(instrument, "trend_pullback", wf_report, stability, mc)

    return {
        "instrument": instrument,
        "ltf_bars": len(ltf_df),
        "htf_bars": len(htf_df),
        "span_days": span_days,
        "wf_report": wf_report,
        "stability": stability,
        "monte_carlo": mc,
        "report": report,
        "representative_params": representative_params,
        "mode_count": mode_count,
        "n_windows": n_windows,
    }


if __name__ == "__main__":
    instrument_arg = sys.argv[1] if len(sys.argv) > 1 else "EUR_USD"
    result = run_gates_for_pair(instrument_arg)

    print()
    print("=" * 78)
    print(render_text(result["report"]))
    print("=" * 78)

    wf = result["wf_report"]
    print()
    print(f"Walk-forward windows ({len(wf.windows)}):")
    for w in wf.windows:
        print(
            f"  window {w.window_index}: IS {w.is_start_ts.date()} -> {w.oos_start_ts.date()} "
            f"| OOS {w.oos_start_ts.date()} -> {w.oos_end_ts.date()} "
            f"| OOS trades this window={len(w.oos.trades)}"
        )

    st = result["stability"]
    print()
    print(f"Stability neighbors ({len(st.neighbors)}), base_metric={st.base_metric:.2f}:")
    for n in st.neighbors:
        print(f"  {n.key:55s} {n.direction:20s} metric={n.metric:.2f}")

    mc = result["monte_carlo"]
    print()
    print(
        f"Monte Carlo: observed_net_pnl={mc.observed_net_pnl:.2f} "
        f"observed_drawdown={mc.observed_drawdown:.3f} "
        f"prob_nonpositive={mc.prob_nonpositive:.3f} drawdown_p95={mc.drawdown_p95:.3f}"
    )
