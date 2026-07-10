"""
TRADING-RULES §5 gates 2-6 driver, generalized across strategies (Phase 6,
disposition 5, 2026-07-09 -- was trend_pullback-only through Phase 5). One CLI
invocation per (instrument, strategy) pair.

GENERALIZATION PROOF (disposition 5): after this refactor, `python scripts/
run_validation_gates.py EUR_USD` (no second arg, defaulting to trend_pullback) must
reproduce the Phase 5 "complete" commit's numbers byte-for-byte -- confirmed by
re-running and diffing against that archived output before this file's Phase 6
range_reversion path is trusted. See HANDOFF.md for the diff record.

Gate 2 ("backtest w/ costs, >=2yr") is satisfied structurally by every run_fn call
this script makes: real cost_model from instruments.yaml, real >=2yr candle history
from instance/candle_cache/. TRADING-RULES §5 defines no separate gate-2 artifact
and GateReport (bot/backtest/gate_report.py) only carries gates 3/4/6 -- there is
nothing further to compute for gate 2 beyond confirming those two "real" conditions,
which this script's startup log does explicitly (bar counts + date span printed).
Gate 5 (per-regime attribution) is deferred -- GateReport.notes says so on every report.

Per-strategy configuration lives in _STRATEGIES below (a _StrategySpec per playbook)
instead of module-level constants, so adding a strategy means adding one registry
entry, not editing the run/report plumbing. Fixed choices NOT tunable via CLI flags
(recorded here so a re-run is reproducible, not a moving target):
  - param_grid: entry_threshold and score_weights are searched INSIDE the walk-
    forward's own per-window IS selection (each spec's build_param_grid) -- NOT
    pre-tuned on the full dataset first (winner's-curse guard,
    test_validation_defendants.py's defendant (c)).
  - walk-forward window sizing: is_bars=3000 H1 bars (~5.7 months), oos_bars=1000
    H1 bars (~1.9 months), step_bars=oos_bars (default) -- standard rolling WFO.
  - stability sweep (gate 4) runs over the FULL real history using a REPRESENTATIVE
    config: the (entry_threshold, score_weights) combination chosen by the most
    windows (mode across the walk-forward windows).
  - regime classifier params: instruments.yaml's defaults.regime_params, fixed.
  - starting_equity=$10,000, account_currency from instruments.yaml (USD).

range_reversion-specific (HANDOFF.md disposition 1): both scored components are
binary and their weights sum to 1.0, so the (entry_threshold, score_weights) search
selects among discrete effective regimes (OR / asymmetric / AND), not a continuous
dial -- see bot/strategies/range_reversion.py's module docstring for the exact
boundary math. This script classifies and prints each walk-forward window's chosen
(threshold, weights) into one of those three regimes so a search landing in OR or
asymmetric (overruling §3.2's conjunctive letter) is visible without manual
inspection, per that disposition.

Usage:
    PYTHONPATH=. python scripts/run_validation_gates.py EUR_USD [trend_pullback|range_reversion]
"""

from __future__ import annotations

import copy
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from bot.backtest.engine import BacktestEngine
from bot.backtest.gate_report import build_gate_report, render_text
from bot.backtest.monte_carlo import MonteCarloResult, run_monte_carlo
from bot.backtest.stability import run_stability_sweep
from bot.backtest.walk_forward import WalkForwardWindow, run_walk_forward
from bot.data.cache import CandleCache
from bot.regime.classifier import RegimeClassifier
from bot.strategies.range_reversion import RangeReversion
from bot.strategies.trend_pullback import TrendPullback

_ROOT = Path(__file__).resolve().parent.parent
_INSTRUMENTS_YAML = _ROOT / "bot" / "config" / "instruments.yaml"
_CACHE_DIR = _ROOT / "instance" / "candle_cache"

_IS_BARS = 3000
_OOS_BARS = 1000
_STARTING_EQUITY = 10_000.0


# ---------------------------------------------------------------------------
# trend_pullback param grid (UNCHANGED from Phase 5 -- see generalization proof above)
# ---------------------------------------------------------------------------

_TP_STABILITY_KEYS = [
    "sl_atr_mult",
    "pullback_zone_atr_min",
    "pullback_zone_atr_max",
    "entry_threshold",
    "exit.trail_atr_mult",
    "exit.partial_at_r",
]
_TP_SIMPLEX_GROUPS = [
    [
        "score_weights.pullback_zone",
        "score_weights.reversal_trigger",
        "score_weights.rsi_side",
        "score_weights.ema200_side",
    ],
]
_TP_ENTRY_THRESHOLD_GRID = [0.35, 0.45, 0.55, 0.65]
_TP_SCORE_WEIGHTS_GRID = [
    {"pullback_zone": 0.30, "reversal_trigger": 0.25, "rsi_side": 0.25, "ema200_side": 0.20},  # current provisional default
    {"pullback_zone": 0.25, "reversal_trigger": 0.25, "rsi_side": 0.25, "ema200_side": 0.25},  # equal weight
    {"pullback_zone": 0.20, "reversal_trigger": 0.40, "rsi_side": 0.20, "ema200_side": 0.20},  # trigger-heavy
]


def _build_param_grid_trend_pullback(base_params: dict) -> list[dict]:
    grid = []
    for threshold in _TP_ENTRY_THRESHOLD_GRID:
        for weights in _TP_SCORE_WEIGHTS_GRID:
            candidate = copy.deepcopy(base_params)
            candidate["entry_threshold"] = threshold
            candidate["score_weights"] = dict(weights)
            grid.append(candidate)
    return grid


# ---------------------------------------------------------------------------
# range_reversion param grid (Phase 6, new)
# ---------------------------------------------------------------------------

_RR_STABILITY_KEYS = [
    "sl_atr_mult",
    "entry_threshold",
    "expansion_veto_atr_ratio",
    "expansion_veto_atr_mean_mult",
]
# rejection_lookback_bars excluded (same precedent as trend_pullback's
# swing_lookback_bars, absent from _TP_STABILITY_KEYS): it's an integer bar-count,
# and perturb_one_at_a_time's +/-10% sweep produces non-integer values (e.g. 3 ->
# 2.7) that a bar-slicing operation (window.iloc[-n:]) cannot accept -- a
# continuous +/-10% perturbation isn't a meaningful operation on a bar count anyway.
_RR_SIMPLEX_GROUPS = [
    ["score_weights.band_reentry", "score_weights.rsi_recovery"],
]
# Thresholds deliberately span all three AND/OR/asymmetric regions relative to the
# weight vectors below (min weight 0.4, max weight 0.6): 0.35 < 0.4 (OR for every
# combo); 0.55 sits between 0.4/0.6 (asymmetric for the skewed combos, AND for the
# symmetric 0.5/0.5 combo since 0.55 > 0.5); 0.75/0.95 > 0.6 (AND for every combo).
_RR_ENTRY_THRESHOLD_GRID = [0.35, 0.55, 0.75, 0.95]
_RR_SCORE_WEIGHTS_GRID = [
    {"band_reentry": 0.5, "rsi_recovery": 0.5},  # current provisional default
    {"band_reentry": 0.6, "rsi_recovery": 0.4},  # band_reentry-heavy
    {"band_reentry": 0.4, "rsi_recovery": 0.6},  # rsi_recovery-heavy
]


def _build_param_grid_range_reversion(base_params: dict) -> list[dict]:
    grid = []
    for threshold in _RR_ENTRY_THRESHOLD_GRID:
        for weights in _RR_SCORE_WEIGHTS_GRID:
            candidate = copy.deepcopy(base_params)
            candidate["entry_threshold"] = threshold
            candidate["score_weights"] = dict(weights)
            grid.append(candidate)
    return grid


def classify_threshold_regime(weights: dict, threshold: float) -> str:
    """HANDOFF.md disposition 1: classify a binary-2-component (threshold, weights)
    choice into the discrete effective regime it produces. Only meaningful for
    strategies whose scored components are ALL binary with weights summing to 1.0
    (range_reversion) -- not applicable to trend_pullback's 4-component continuous
    scoring, so this is only called for range_reversion below."""
    lo, hi = sorted(weights.values())[0], sorted(weights.values())[-1]
    if threshold <= lo:
        return "OR (either component alone fires)"
    if threshold <= hi:
        return "ASYMMETRIC (only the heavier-weighted component can fire alone)"
    return "AND (both components required)"


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

@dataclass
class _StrategySpec:
    name: str
    strategy_class: type
    params_key: str  # instruments.yaml defaults key, e.g. "trend_pullback_params"
    stability_keys: list[str]
    simplex_groups: list[list[str]]
    build_param_grid: Callable[[dict], list[dict]]
    classify_window: Callable[[WalkForwardWindow], str] | None = None


_STRATEGIES: dict[str, _StrategySpec] = {
    "trend_pullback": _StrategySpec(
        name="trend_pullback",
        strategy_class=TrendPullback,
        params_key="trend_pullback_params",
        stability_keys=_TP_STABILITY_KEYS,
        simplex_groups=_TP_SIMPLEX_GROUPS,
        build_param_grid=_build_param_grid_trend_pullback,
    ),
    "range_reversion": _StrategySpec(
        name="range_reversion",
        strategy_class=RangeReversion,
        params_key="range_reversion_params",
        stability_keys=_RR_STABILITY_KEYS,
        simplex_groups=_RR_SIMPLEX_GROUPS,
        build_param_grid=_build_param_grid_range_reversion,
        classify_window=lambda w: classify_threshold_regime(
            w.chosen_params["score_weights"], w.chosen_params["entry_threshold"]
        ),
    ),
}


def _params_key(params: dict) -> tuple:
    """Generic mode-grouping key: works for any number/naming of score_weights
    components (trend_pullback's 4 or range_reversion's 2) -- shape changed from
    Phase 5's positional tuple to a sorted (key, value) tuple, but produces
    IDENTICAL grouping/equality behavior, so it does not affect any printed output
    (representative_params' own dict fields are what gets printed, not this key)."""
    w = params["score_weights"]
    return (params["entry_threshold"],) + tuple(sorted(w.items()))


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


def load_conversion_series(instrument: str, account_currency: str, cache: CandleCache, granularity: str) -> dict:
    """
    bot.backtest.sizing.pip_value_per_unit needs an auxiliary conversion series for
    CROSS pairs (neither leg matches account_currency, e.g. EUR_GBP with a USD
    account -- needs GBP_USD or USD_GBP). trend_pullback's Phase 5 pairs (EUR_USD,
    USD_JPY) never exercised this path (quote==USD or base==USD respectively, both
    direct/self-conversion, see sizing.py's module docstring) -- EUR_GBP is the
    first pair this harness has actually run that needs it. Returns {} when the
    instrument doesn't need one (direct or self-conversion cases); raises loudly if
    it does and neither orientation is cached (refuse to size rather than guess,
    matching sizing.py's own SizingError philosophy).
    """
    base, _, quote = instrument.partition("_")
    if quote == account_currency or base == account_currency:
        return {}
    acct_quote = f"{account_currency}_{quote}"
    quote_acct = f"{quote}_{account_currency}"
    for candidate in (acct_quote, quote_acct):
        df = cache.load(candidate, granularity)
        if df is not None and not df.empty:
            return {candidate: df}
    raise RuntimeError(
        f"{instrument} needs a cross-currency conversion series ({acct_quote} or {quote_acct}) "
        f"at {granularity}, but neither is cached -- run scripts/fetch_history.py for it first."
    )


def _make_run_fn(
    strategy_class: type,
    instrument: str,
    account_currency: str,
    risk_pct: float,
    regime_params: dict,
    cost_cfg: dict,
    conversion_series: dict | None = None,
):
    def run_fn(params: dict, ltf_slice, htf_slice):
        strategy = strategy_class(params, instrument)
        classifier = RegimeClassifier(regime_params)
        engine = BacktestEngine(
            strategy=strategy,
            regime_classifier=classifier,
            instrument=instrument,
            account_currency=account_currency,
            risk_pct=risk_pct,
            starting_equity=_STARTING_EQUITY,
            cost_cfg=cost_cfg,
            conversion_series=conversion_series,
            exit_cfg=params.get("exit"),  # None for range_reversion (static TP path, no exit_cfg)
            signal_threshold=params["entry_threshold"],
            record_signals=False,
        )
        return engine.run(ltf_slice, htf_slice)

    return run_fn


def run_gates_for_pair(
    instrument: str, strategy_name: str = "trend_pullback", cost_model_override: dict | None = None
) -> dict:
    """
    cost_model_override: when supplied, used INSTEAD of instruments.yaml's cost_model
    for this run only (yaml on disk untouched). Added for the range_reversion
    session-preference follow-up (Phase 6 close-out, disposition: "§3.2's own
    preference clause, not a parameter retune") -- reuses the EXISTING
    entry_blackout_hours_utc mechanism (bot.backtest.costs.entry_blackout_ok, same
    backtest/live path) to exclude Asian-session hours for one diagnostic re-run,
    rather than inventing new session-filter machinery. None (default) reproduces
    prior behavior exactly.
    """
    spec = _STRATEGIES[strategy_name]

    raw = _load_raw_config()
    defaults = raw["defaults"]
    account_currency = raw.get("account_currency", "USD")
    risk_pct = defaults["risk_pct"]
    regime_params = defaults["regime_params"]
    strategy_params = defaults[spec.params_key]
    cost_model = cost_model_override if cost_model_override is not None else raw["instruments"][instrument]["cost_model"]
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
        f"[{instrument}/{spec.name}] {ltf_gran} bars={len(ltf_df)} {htf_gran} bars={len(htf_df)} "
        f"span={ltf_df['time'].min().date()} -> {ltf_df['time'].max().date()} ({span_days}d) "
        f"cost_model.max_spread_pips={cost_model['max_spread_pips']} "
        f"entry_blackout_hours_utc={cost_model.get('entry_blackout_hours_utc')}"
    )

    conversion_series = load_conversion_series(instrument, account_currency, cache, ltf_gran)
    run_fn = _make_run_fn(
        spec.strategy_class, instrument, account_currency, risk_pct, regime_params, cost_model, conversion_series
    )
    param_grid = spec.build_param_grid(strategy_params)
    print(
        f"[{instrument}/{spec.name}] param_grid: {len(param_grid)} candidates, "
        f"searched inside each window's own IS slice",
        flush=True,
    )

    print(f"[{instrument}/{spec.name}] gate 3: walk-forward (is_bars={_IS_BARS}, oos_bars={_OOS_BARS}) ...", flush=True)
    wf_report = run_walk_forward(ltf_df, htf_df, run_fn, param_grid, is_bars=_IS_BARS, oos_bars=_OOS_BARS)
    print(
        f"[{instrument}/{spec.name}] gate 3 done: {len(wf_report.windows)} windows, "
        f"stitched trade_count={wf_report.stitched_metrics['trade_count']}, "
        f"net_pnl={wf_report.stitched_metrics['net_pnl']:.2f}, passed={wf_report.passed}",
        flush=True,
    )

    representative_params, mode_count, n_windows = most_common_params(wf_report.windows)
    print(
        f"[{instrument}/{spec.name}] per-window chosen params (mode wins {mode_count}/{n_windows} windows): "
        f"entry_threshold={representative_params['entry_threshold']} "
        f"score_weights={representative_params['score_weights']}",
        flush=True,
    )
    for w in wf_report.windows:
        line = (
            f"    window {w.window_index}: entry_threshold={w.chosen_params['entry_threshold']} "
            f"score_weights={w.chosen_params['score_weights']}"
        )
        if spec.classify_window is not None:
            line += f"  -> {spec.classify_window(w)}"
        print(line)

    print(f"[{instrument}/{spec.name}] gate 4: stability sweep over full history (representative config) ...", flush=True)
    stability = run_stability_sweep(
        run_fn, ltf_df, htf_df, representative_params, spec.stability_keys, simplex_groups=spec.simplex_groups
    )
    print(f"[{instrument}/{spec.name}] gate 4 done: passed={stability.passed}", flush=True)

    pnls = [t.pnl for t in wf_report.stitched_trades]
    print(f"[{instrument}/{spec.name}] gate 6: monte carlo over {len(pnls)} stitched OOS trades ...", flush=True)
    if pnls:
        mc = run_monte_carlo(pnls, starting_equity=_STARTING_EQUITY)
    else:
        mc = MonteCarloResult(passed=False, reason="no stitched OOS trades to evaluate -- Monte Carlo requires >=1 trade")
    print(f"[{instrument}/{spec.name}] gate 6 done: passed={mc.passed}", flush=True)

    report = build_gate_report(instrument, spec.name, wf_report, stability, mc)

    return {
        "instrument": instrument,
        "strategy": spec.name,
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
    strategy_arg = sys.argv[2] if len(sys.argv) > 2 else "trend_pullback"
    result = run_gates_for_pair(instrument_arg, strategy_arg)

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
