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
from itertools import combinations
from pathlib import Path
from typing import Callable

import pandas as pd
import yaml

from bot.backtest.engine import BacktestEngine
from bot.backtest.gate_report import build_gate_report, render_text
from bot.backtest.monte_carlo import MonteCarloResult, run_monte_carlo
from bot.backtest.stability import run_stability_sweep
from bot.backtest.walk_forward import WalkForwardWindow, run_walk_forward
from bot.data.cache import CandleCache
from bot.indicators.core import atr as _atr
from bot.indicators.core import bollinger_bands as _bollinger_bands
from bot.regime.classifier import RegimeClassifier, RegimeState
from bot.strategies.momentum import Momentum
from bot.strategies.range_reversion import RangeReversion
from bot.strategies.squeeze_breakout import SqueezeBreakout
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


# ---------------------------------------------------------------------------
# squeeze_breakout param grid (Phase 7, new)
# ---------------------------------------------------------------------------

_SB_STABILITY_KEYS = [
    "sl_atr_mult",
    "entry_threshold",
    "atr_expansion_ratio",
    "atr_expansion_mean_mult",
    "volume_expansion_mult",
]
# compression_box_lookback_bars / volume_lookback_bars excluded -- same precedent as
# trend_pullback's swing_lookback_bars / range_reversion's rejection_lookback_bars:
# integer bar-counts, perturb_one_at_a_time's +/-10% sweep produces non-integer values
# a bar-slicing/rolling-window op can't accept.
_SB_SIMPLEX_GROUPS = [
    [
        "score_weights.close_beyond_band",
        "score_weights.atr_expansion",
        "score_weights.body_pct",
        "score_weights.tick_volume",
    ],
]
_SB_ENTRY_THRESHOLD_GRID = [0.3, 0.5, 0.7, 0.85]
_SB_SCORE_WEIGHTS_GRID = [
    {"close_beyond_band": 0.30, "atr_expansion": 0.30, "body_pct": 0.30, "tick_volume": 0.10},  # current provisional default
    {"close_beyond_band": 0.40, "atr_expansion": 0.30, "body_pct": 0.20, "tick_volume": 0.10},  # band-close-heavy
    {"close_beyond_band": 0.25, "atr_expansion": 0.40, "body_pct": 0.25, "tick_volume": 0.10},  # ATR-expansion-heavy
    {"close_beyond_band": 0.30, "atr_expansion": 0.30, "body_pct": 0.25, "tick_volume": 0.15},  # volume nudged up, still low
]


def _build_param_grid_squeeze_breakout(base_params: dict) -> list[dict]:
    grid = []
    for threshold in _SB_ENTRY_THRESHOLD_GRID:
        for weights in _SB_SCORE_WEIGHTS_GRID:
            candidate = copy.deepcopy(base_params)
            candidate["entry_threshold"] = threshold
            candidate["score_weights"] = dict(weights)
            grid.append(candidate)
    return grid


# ---------------------------------------------------------------------------
# momentum param grid (TRADING-RULES §6, 2026-07-12 hearing, slot 1 -- new)
# ---------------------------------------------------------------------------

# Pre-declared N grid (spec-mapping (1)): {20, 60, 120} trading days, searched
# per-window IS-only, same winner's-curse guard as every other strategy's grid.
# A6 scope statement: this hearing tests short-horizon momentum (effective
# N in {20, 60}) -- 120 stays in the grid (not silently dropped) but is
# structurally near-untestable under this window's IS sizing (see is_bars/
# oos_bars below); flag, don't hide, in the eventual report.
_MOM_N_GRID = [20, 60, 120]

# N belongs in the stability sweep (A8) -- it IS the signal, unlike the other
# three playbooks' excluded bar-count params. bot.backtest.stability.
# perturb_one_at_a_time now rounds int-typed values instead of crashing on a
# float lookback, so "n" can sit alongside the float exit params here.
_MOM_STABILITY_KEYS = [
    "n",
    "sl_atr_mult",
    "exit.trail_atr_mult",
    "exit.partial_at_r",
]
_MOM_SIMPLEX_GROUPS: list[list[str]] = []  # no score_weights -- signal-only, §1.1 exemption


def _build_param_grid_momentum(base_params: dict) -> list[dict]:
    grid = []
    for n in _MOM_N_GRID:
        candidate = copy.deepcopy(base_params)
        candidate["n"] = n
        grid.append(candidate)
    return grid


def _momentum_params_key(params: dict) -> tuple:
    """Momentum's grid varies exactly one scalar (n) -- no score_weights to fold
    in, unlike _params_key below. Kept separate rather than special-cased inside
    _params_key so that function's score_weights assumption stays a real
    invariant for the three strategies that actually have one."""
    return (params["n"],)


def _describe_momentum_params(params: dict) -> str:
    return f"n={params['n']} sl_atr_mult={params['sl_atr_mult']}"


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


def classify_threshold_regime_general(weights: dict, threshold: float) -> str:
    """
    Generalizes classify_threshold_regime (range_reversion's 2-component OR/
    asymmetric/AND trichotomy, left untouched above -- this is a NEW, additive
    function, RR's registry entry still calls the original) to any number of binary
    components -- squeeze_breakout's 4 (DISPOSITION 2, HANDOFF.md/plan doc). Enumerates
    every non-empty subset of `weights`, keeps the ones whose summed weight clears
    `threshold` ("covering" subsets), then keeps only the MINIMAL covering subsets (a
    covering subset containing a smaller covering subset is redundant to report --
    the smaller one already proves that combination suffices). Returns a
    human-readable string: a single-component minimal subset means that component
    alone can fire the signal (OR-region); a subset containing every component means
    all are required (AND-region, matching §3.3's literal "+" for its 3 named trigger
    conditions when tick_volume is not part of any minimal subset); anything else is a
    genuine N-of-M case reported as the literal minimal subset(s), same spirit as RR's
    "asymmetric" label but not collapsed into a fixed vocabulary that only fits 2
    components.
    """
    names = list(weights.keys())
    covering: list[frozenset] = []
    for r in range(1, len(names) + 1):
        for combo in combinations(names, r):
            if sum(weights[n] for n in combo) >= threshold:
                covering.append(frozenset(combo))

    minimal = [c for c in covering if not any(other < c for other in covering)]
    minimal.sort(key=lambda c: (len(c), sorted(c)))

    if not minimal:
        return "UNREACHABLE (no subset of components can clear this threshold)"

    parts = ["+".join(sorted(c)) for c in minimal]
    if len(minimal) == 1 and len(minimal[0]) == len(names):
        return f"AND (all {len(names)} components required: {parts[0]})"
    if all(len(c) == 1 for c in minimal):
        return f"OR (any single component alone fires: {', '.join(parts)})"
    return f"N-of-{len(names)} (minimal firing subsets: {'; '.join(parts)})"


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
    # Overrides below default to None -- the three original playbooks fall back to
    # defaults.timeframe_htf/ltf and the module-level _IS_BARS/_OOS_BARS exactly as
    # before (zero behavior change). momentum is the first strategy whose own
    # anchor:execution TF pair (D/H4) and window sizing differ from that shared
    # default (TRADING-RULES §6, 2026-07-12 hearing).
    htf_gran: str | None = None
    ltf_gran: str | None = None
    is_bars: int | None = None
    oos_bars: int | None = None
    # params_key_fn/describe_params default to the score_weights-based helpers below
    # (every strategy through squeeze_breakout has one) -- momentum is the first
    # strategy without score_weights (signal-only, §1.1 exemption) and supplies its
    # own single-scalar (n) versions instead.
    params_key_fn: Callable[[dict], tuple] | None = None
    describe_params: Callable[[dict], str] | None = None


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
    "squeeze_breakout": _StrategySpec(
        name="squeeze_breakout",
        strategy_class=SqueezeBreakout,
        params_key="squeeze_breakout_params",
        stability_keys=_SB_STABILITY_KEYS,
        simplex_groups=_SB_SIMPLEX_GROUPS,
        build_param_grid=_build_param_grid_squeeze_breakout,
        classify_window=lambda w: classify_threshold_regime_general(
            w.chosen_params["score_weights"], w.chosen_params["entry_threshold"]
        ),
    ),
    "momentum": _StrategySpec(
        name="momentum",
        strategy_class=Momentum,
        params_key="momentum_params",
        stability_keys=_MOM_STABILITY_KEYS,
        simplex_groups=_MOM_SIMPLEX_GROUPS,
        build_param_grid=_build_param_grid_momentum,
        # D:H4 = 6:1, inside §2's 4-6:1 anchor:execution law (TRADING-RULES §6,
        # 2026-07-12 hearing, spec-mapping (3)).
        htf_gran="D",
        ltf_gran="H4",
        # Scaled proportionally from the H1 convention (is_bars=3000/oos_bars=1000
        # over ~13,000 H1 bars/2yr, ~4 rolled windows) to H4's ~4x lower bar density
        # -- same window count, same IS/OOS ratio, not a new law.
        is_bars=750,
        oos_bars=250,
        params_key_fn=_momentum_params_key,
        describe_params=_describe_momentum_params,
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


def most_common_params(windows, key_fn: Callable[[dict], tuple] = _params_key) -> tuple[dict, int, int]:
    """Mode across walk-forward windows' chosen_params. Returns (representative_params,
    mode_count, total_windows) -- caller decides how to report a weak plurality.
    key_fn defaults to the score_weights-based grouping every strategy through
    squeeze_breakout uses; momentum passes _momentum_params_key (single-scalar n,
    no score_weights) via its _StrategySpec.params_key_fn."""
    keys = [key_fn(w.chosen_params) for w in windows]
    mode_key, mode_count = Counter(keys).most_common(1)[0]
    representative = next(w.chosen_params for w in windows if key_fn(w.chosen_params) == mode_key)
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
    htf_gran = spec.htf_gran or defaults["timeframe_htf"]
    ltf_gran = spec.ltf_gran or defaults["timeframe_ltf"]
    is_bars = spec.is_bars or _IS_BARS
    oos_bars = spec.oos_bars or _OOS_BARS
    describe_params = spec.describe_params or (
        lambda p: f"entry_threshold={p['entry_threshold']} score_weights={p['score_weights']}"
    )
    params_key_fn = spec.params_key_fn or _params_key

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

    print(f"[{instrument}/{spec.name}] gate 3: walk-forward (is_bars={is_bars}, oos_bars={oos_bars}) ...", flush=True)
    wf_report = run_walk_forward(ltf_df, htf_df, run_fn, param_grid, is_bars=is_bars, oos_bars=oos_bars)
    print(
        f"[{instrument}/{spec.name}] gate 3 done: {len(wf_report.windows)} windows, "
        f"stitched trade_count={wf_report.stitched_metrics['trade_count']}, "
        f"net_pnl={wf_report.stitched_metrics['net_pnl']:.2f}, passed={wf_report.passed}",
        flush=True,
    )

    representative_params, mode_count, n_windows = most_common_params(wf_report.windows, key_fn=params_key_fn)
    print(
        f"[{instrument}/{spec.name}] per-window chosen params (mode wins {mode_count}/{n_windows} windows): "
        f"{describe_params(representative_params)}",
        flush=True,
    )
    for w in wf_report.windows:
        line = f"    window {w.window_index}: {describe_params(w.chosen_params)}"
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
        # Kept on the return dict (not re-derived) so callers -- e.g. __main__'s
        # squeeze_breakout-only hysteresis-excluded diagnostic -- don't need a second
        # cache load / config parse.
        "ltf_df": ltf_df,
        "htf_df": htf_df,
        "regime_params": regime_params,
        "htf_gran": htf_gran,
        "ltf_gran": ltf_gran,
    }


_GRANULARITY_HOURS = {"M15": 0.25, "H1": 1.0, "H4": 4.0, "D": 24.0}


def compute_hysteresis_excluded(
    ltf_df: pd.DataFrame,
    htf_df: pd.DataFrame,
    regime_params: dict,
    htf_gran: str,
    ltf_gran: str,
    windows: list[WalkForwardWindow],
    instrument: str,
) -> dict:
    """
    DISPOSITION 1's known limitation, made measurable (HANDOFF.md "approved addition
    1"): counts LTF bars where the confirmed regime has just left COMPRESSION (within
    hysteresis_window_bars = htf_ltf_ratio * regime_confirm_bars -- the minimum
    bar-count the HTF hysteresis mechanism can itself take to confirm a switch away
    from COMPRESSION, not an arbitrary round number) but SqueezeBreakout's own trigger
    scoring -- evaluated with THAT walk-forward window's own frozen chosen_params,
    never the provisional yaml defaults, same frozen-params standard as the (a)/(b)
    post-mortem split -- would have cleared threshold. squeeze_breakout carries no
    vetoes ever (module docstring), so "fired" here is just score >= entry_threshold.

    The HTF regime timeline is classified ONCE over the full history (it doesn't
    depend on strategy params, only the trigger evaluation does) and broadcast to LTF
    bars via merge_asof(direction="backward") -- the SAME "latest confirmed regime as
    of this bar" semantics bot.backtest.engine.BacktestEngine uses internally.

    ONLY called for squeeze_breakout (see __main__ below) -- this function is not part
    of the _StrategySpec registry surface trend_pullback/range_reversion use, by
    design: it is meaningless for playbooks with no regime-lag failure mode of this
    shape.
    """
    htf_ltf_ratio = _GRANULARITY_HOURS[htf_gran] / _GRANULARITY_HOURS[ltf_gran]
    hysteresis_window_bars = int(round(htf_ltf_ratio * regime_params["regime_confirm_bars"]))

    classifier = RegimeClassifier(regime_params)
    classifier.reset()
    htf_regimes = [classifier.classify(htf_df.iloc[: i + 1]).regime.value for i in range(len(htf_df))]
    htf_regime_series = pd.DataFrame({"time": htf_df["time"], "regime": htf_regimes})

    merged = pd.merge_asof(ltf_df[["time"]], htf_regime_series, on="time", direction="backward")
    is_compression = (merged["regime"] == RegimeState.COMPRESSION.value).to_numpy()

    idx = pd.Series(range(len(is_compression)))
    last_compression_idx = idx.where(is_compression).ffill()
    bars_since_compression = idx - last_compression_idx
    candidate_mask = (~is_compression) & (bars_since_compression <= hysteresis_window_bars)
    candidate_positions = [i for i in range(len(ltf_df)) if bool(candidate_mask.iloc[i])]

    per_window_results = []
    for w in windows:
        p = w.chosen_params
        strategy = SqueezeBreakout(p, instrument)
        min_bars = max(p["bb_period"], p["compression_box_lookback_bars"] + 1, p["volume_lookback_bars"], 180)
        window_positions = [
            i for i in candidate_positions
            if i >= min_bars and w.oos_start_ts <= ltf_df["time"].iloc[i] <= w.oos_end_ts
        ]
        excluded_count = 0
        for i in window_positions:
            window_slice = ltf_df.iloc[: i + 1]
            close = window_slice["close"]
            upper, _, lower = _bollinger_bands(close, p["bb_period"], p["bb_std"])
            upper_now, lower_now = upper.iloc[-1], lower.iloc[-1]
            last_close = close.iloc[-1]
            atr_now = _atr(window_slice["high"], window_slice["low"], close, 14).iloc[-1]
            direction = SqueezeBreakout._derive_direction(last_close, upper_now, lower_now)
            score, _ = strategy._evaluate_trigger(window_slice, p, direction, upper, lower, atr_now)
            if score >= p["entry_threshold"]:
                excluded_count += 1
        per_window_results.append(
            {"window_index": w.window_index, "candidates": len(window_positions), "hysteresis_excluded": excluded_count}
        )

    return {
        "hysteresis_window_bars": hysteresis_window_bars,
        "per_window": per_window_results,
        "total_hysteresis_excluded": sum(r["hysteresis_excluded"] for r in per_window_results),
    }


def compute_momentum_signflip_diagnostic(windows: list[WalkForwardWindow], htf_df: pd.DataFrame) -> dict:
    """
    TRADING-RULES §6 (2026-07-12, amendment A3): split LOSING stitched OOS trades by
    whether the D-signal's own sign had flipped against the open position before its
    exit. Uses each window's own frozen chosen_params["n"] (never the provisional
    yaml default) -- same "frozen params" standard squeeze_breakout's
    compute_hysteresis_excluded uses above. Sign-flipped losses implicate the
    ATR-trail exit approximation (names signal-flip exit as a concrete, scoped
    revival mechanism if this hearing FAILs); sign-intact losses implicate the
    thesis itself.

    A7 correction: also tags each losing trade as a same-direction re-entry CHAIN
    member (immediately preceded, within its own window's OOS trade list ordered by
    entry_ts, by another trade of the SAME direction) vs. a fresh directional entry.
    Chained losses are sign-intact BY CONSTRUCTION (the position only re-entered
    because the sign hadn't flipped) -- a choppy-but-trending period mechanically
    stacks losses into the sign-intact bucket via repeated stop-outs, independent of
    whether continuation is actually right. This split must be read alongside the
    sign-flipped/sign-intact split, not after it.
    """
    htf_times = htf_df["time"].to_numpy()
    htf_close = htf_df["close"]

    sign_flipped: list = []
    sign_intact_chained: list = []
    sign_intact_fresh: list = []
    excluded_insufficient_history: int = 0
    excluded_exact_zero_at_exit: int = 0

    for w in windows:
        n = w.chosen_params["n"]
        trades_sorted = sorted(w.oos.trades, key=lambda t: t.entry_ts)
        prev_direction = None
        for t in trades_sorted:
            is_chained = prev_direction is not None and t.direction == prev_direction
            prev_direction = t.direction

            if t.pnl >= 0:
                continue  # only losing trades are split (A3's own scope)

            htf_pos = int(htf_times.searchsorted(t.exit_ts, side="right")) - 1
            if htf_pos < n:
                excluded_insufficient_history += 1
                continue  # insufficient D history to evaluate at exit -- exclude, don't guess

            window_close = htf_close.iloc[: htf_pos + 1]
            value_at_exit = window_close.iloc[-1] / window_close.iloc[-1 - n] - 1.0
            if value_at_exit == 0.0:
                excluded_exact_zero_at_exit += 1
                continue  # ambiguous -- exclude rather than force a bucket
            sign_at_exit = "long" if value_at_exit > 0 else "short"

            if sign_at_exit == t.direction:
                (sign_intact_chained if is_chained else sign_intact_fresh).append(t)
            else:
                sign_flipped.append(t)

    sign_intact = sign_intact_chained + sign_intact_fresh
    return {
        "sign_flipped_count": len(sign_flipped),
        "sign_flipped_pnl": sum(t.pnl for t in sign_flipped),
        "sign_intact_count": len(sign_intact),
        "sign_intact_pnl": sum(t.pnl for t in sign_intact),
        "sign_intact_chained_count": len(sign_intact_chained),
        "sign_intact_chained_pnl": sum(t.pnl for t in sign_intact_chained),
        "sign_intact_fresh_count": len(sign_intact_fresh),
        "sign_intact_fresh_pnl": sum(t.pnl for t in sign_intact_fresh),
        "excluded_insufficient_history": excluded_insufficient_history,
        "excluded_exact_zero_at_exit": excluded_exact_zero_at_exit,
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

    if strategy_arg == "squeeze_breakout":
        # Approved addition (HANDOFF.md / plan doc) -- DISPOSITION 1's known
        # hysteresis-lag limitation, made measurable. Only meaningful for this
        # playbook (see compute_hysteresis_excluded's own docstring).
        diag = compute_hysteresis_excluded(
            result["ltf_df"], result["htf_df"], result["regime_params"],
            result["htf_gran"], result["ltf_gran"], wf.windows, instrument_arg,
        )
        fired = wf.stitched_metrics["trade_count"]
        print()
        print(f"Hysteresis-excluded diagnostic (window={diag['hysteresis_window_bars']} LTF bars, per-window frozen params):")
        for r in diag["per_window"]:
            print(f"  window {r['window_index']}: candidates={r['candidates']:4d} hysteresis_excluded={r['hysteresis_excluded']}")
        total = diag["total_hysteresis_excluded"]
        print(f"  TOTAL hysteresis_excluded={total} vs fired={fired}")
        print(
            "  PRE-REGISTERED DECISION RULE: if the overall verdict is FAIL or evidence-thin "
            "AND hysteresis_excluded is large relative to fired, this routes to §2 "
            "regime-routing territory (a Change-Log candidate for a future session) -- "
            "NOT the trigger, NOT the revival budget, NOT an M15 comparison."
        )

    if strategy_arg == "momentum":
        # A6 scope statement (TRADING-RULES §6, 2026-07-12): this hearing tests
        # short-horizon momentum (effective N in {20, 60}) -- 120 is structurally
        # near-untestable under is_bars=750 H4 (~125 D-bars): a fixed-width ROLLING
        # IS window means every window, not just the first, has only ~5 D-bars of
        # actual signal after N=120's own warmup. Flag plainly, don't hide.
        n_wins = Counter(w.chosen_params["n"] for w in wf.windows)
        print()
        print(
            f"A6 scope statement: N-grid window wins across {len(wf.windows)} walk-forward "
            f"windows: {dict(sorted(n_wins.items()))}. is_bars=750 H4 (~125 D-bars) means "
            f"N=120's own warmup consumes ~120 of every window's ~125 D-bars -- near-"
            f"untestable BY CONSTRUCTION in every window, not just the first. This hearing's "
            f"scope is short-horizon momentum (effective N in {{20, 60}}); the literature's "
            f"canonical ~252-trading-day lookback is untestable on this data window at all. "
            f"A FAIL below is scoped to short-horizon momentum, not the time-series-momentum "
            f"thesis in general -- TRADING-RULES §6's renewal clause (>=12mo new candles) is "
            f"the lawful path to a longer-lookback hearing later."
        )

        # A5(a): the funnel is expected to show consulted~=fired with near-misses~=0 --
        # the honest shape of an always-in, signal-only strategy (confidence_score fixed
        # 1.0, no confluence score to produce graded near-misses). Pre-framed here so a
        # future reader doesn't misread it as a broken funnel or a missing veto layer.
        print()
        print(
            "A5(a) funnel-framing note: momentum is signal-only (TRADING-RULES §1.1 "
            "exemption) -- expect consulted~=fired with near-misses~=0 in "
            "scripts/diagnose_gates.py's funnel exhibit. That is the correct, honest shape "
            "for an always-in strategy with no confluence score, not a broken funnel."
        )

        # A3/A7: pre-registered trail-exit sign-flip diagnostic.
        diag = compute_momentum_signflip_diagnostic(wf.windows, result["htf_df"])
        print()
        print("A3 trail-exit sign-flip diagnostic (losing stitched OOS trades only, per-window frozen n):")
        print(
            f"  sign_flipped:        count={diag['sign_flipped_count']:4d} pnl={diag['sign_flipped_pnl']:10.2f}  "
            "(implicates the ATR-trail exit approximation -- signal-flip exit is a named, scoped revival mechanism if this hearing FAILs)"
        )
        print(
            f"  sign_intact (total):  count={diag['sign_intact_count']:4d} pnl={diag['sign_intact_pnl']:10.2f}  "
            "(implicates the thesis itself -- SUBJECT TO the chained/fresh split below, A7 correction)"
        )
        print(
            f"    sign_intact_chained: count={diag['sign_intact_chained_count']:4d} pnl={diag['sign_intact_chained_pnl']:10.2f}  "
            "(re-entry chain member -- sign-intact BY CONSTRUCTION, not independent thesis-failure evidence)"
        )
        print(
            f"    sign_intact_fresh:   count={diag['sign_intact_fresh_count']:4d} pnl={diag['sign_intact_fresh_pnl']:10.2f}  "
            "(first loss in its directional run -- the cleaner thesis-failure signal)"
        )
        print(
            f"  excluded: insufficient_history={diag['excluded_insufficient_history']} "
            f"exact_zero_at_exit={diag['excluded_exact_zero_at_exit']}"
        )
