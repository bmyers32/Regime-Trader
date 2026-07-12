"""
Post-verdict diagnostics, generalized across strategies (Phase 6, disposition 5 --
was trend_pullback-only through Phase 5): evaluation funnel, score distribution,
regime-classification frequency, veto breakdown, and regime-transition proximity for
any registered strategy's gate runs (see scripts/run_validation_gates.py's
_STRATEGIES registry, reused here so the two scripts never drift on param grids/
stability keys).

This does NOT re-litigate a FAIL/PASS verdict already accepted from
scripts/run_validation_gates.py -- same frozen instruments.yaml params, same
cost_model, same cached candle history, same deterministic engine, so the
trades/PnL recomputed here are identical to that run. The only difference is
`record_signals=True` (the gate run used False for speed and never persisted
signal_log) plus a separate, cheap regime-only timeline pass that needs no
BacktestEngine at all. Diagnostic capture, not a new experiment.

Produces, per pair/strategy:
  1. Stitched-OOS evaluation funnel (consulted/gates_passed/threshold_cleared/
     fired) + score distribution, mirroring compute_signal_funnel but over the
     SAME OOS-trimmed window stitching walk_forward.py uses for trades.
  2. Per-regime attribution (TRADING-RULES §5.5 / gate 5) from the identical
     stitched OOS trades already implicit in the accepted gate 3 result.
  3. Full-history H4 regime-classification frequency (RANGING/EXPANSION/
     TRENDING_UP/TRENDING_DOWN/COMPRESSION bar counts).
  4. Regime-transition proximity: each trade's bars_in_regime at entry
     (backward-asof against the regime timeline), bucketed early-in-regime
     vs. established.
  5. Veto breakdown by specific gate string, incl. the no-veto count.

range_reversion-specific (disposition 4): also computes the expansion/ATR-spike
veto's fire-rate among RANGING-consulted bars -- the §1.7 pass-rate check that
must clear (neither <1% nor >95%) before that pair's gate results are trusted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

from bot.backtest.engine import BacktestEngine
from bot.backtest.param_sweep import select_best_params
from bot.backtest.walk_forward import generate_window_bounds
from bot.data.cache import CandleCache
from bot.regime.classifier import RegimeClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_validation_gates as rvg  # noqa: E402 -- sibling script, same _STRATEGIES registry

_ROOT = Path(__file__).resolve().parent.parent
_INSTRUMENTS_YAML = _ROOT / "bot" / "config" / "instruments.yaml"
_CACHE_DIR = _ROOT / "instance" / "candle_cache"

_IS_BARS = 3000
_OOS_BARS = 1000
_EARLY_REGIME_BARS = 5  # bars_in_regime <= this => "just transitioned" bucket (H4 bars ~20h)


def _load_raw_config() -> dict:
    with open(_INSTRUMENTS_YAML) as f:
        return yaml.safe_load(f)


def _bound_htf(htf_df: pd.DataFrame, max_ltf_ts) -> pd.DataFrame:
    return htf_df[htf_df["time"] <= max_ltf_ts]


def stitched_oos_trades_and_signals(instrument: str, strategy_name: str = "trend_pullback"):
    """
    Mirrors run_validation_gates.py's own walk-forward loop EXACTLY (same
    spec.build_param_grid, same per-window IS selection via select_best_params) so
    the funnel/veto/regime diagnostics below reflect what the ACTUAL accepted gate
    run selected per window -- not a single frozen params dict. Only difference from
    the real gate run: record_signals=True (that run used False for speed and never
    persisted signal_log), and it also returns each window's chosen_params so the
    per-window funnel breakdown is traceable to what fired for that specific window.
    """
    spec = rvg._STRATEGIES[strategy_name]
    raw = _load_raw_config()
    defaults = raw["defaults"]
    account_currency = raw.get("account_currency", "USD")
    risk_pct = defaults["risk_pct"]
    regime_params = defaults["regime_params"]
    strategy_params = defaults[spec.params_key]
    cost_model = raw["instruments"][instrument]["cost_model"]
    htf_gran, ltf_gran = defaults["timeframe_htf"], defaults["timeframe_ltf"]

    cache = CandleCache(_CACHE_DIR)
    htf_df = cache.load(instrument, htf_gran)
    ltf_df = cache.load(instrument, ltf_gran)
    conversion_series = rvg.load_conversion_series(instrument, account_currency, cache, ltf_gran)

    def run_fn(params, ltf_slice, htf_slice):
        strategy = spec.strategy_class(params, instrument)
        classifier = RegimeClassifier(regime_params)
        engine = BacktestEngine(
            strategy=strategy,
            regime_classifier=classifier,
            instrument=instrument,
            account_currency=account_currency,
            risk_pct=risk_pct,
            starting_equity=10_000.0,
            cost_cfg=cost_model,
            conversion_series=conversion_series,
            exit_cfg=params.get("exit"),
            signal_threshold=params["entry_threshold"],
            record_signals=True,  # only diff from run_validation_gates.py's run_fn
        )
        return engine.run(ltf_slice, htf_slice)

    param_grid = spec.build_param_grid(strategy_params)
    n_bars = len(ltf_df)
    bounds = generate_window_bounds(n_bars, _IS_BARS, _OOS_BARS)

    all_trades = []
    all_signals = []
    window_chosen_params = []
    for (is_start_idx, oos_start_idx, oos_end_idx) in bounds:
        is_slice = ltf_df.iloc[is_start_idx:oos_start_idx]
        oos_start_ts = ltf_df["time"].iloc[oos_start_idx]
        htf_is_slice = _bound_htf(htf_df, is_slice["time"].iloc[-1])
        chosen_params, _scoreboard = select_best_params(run_fn, is_slice, htf_is_slice, param_grid)
        window_chosen_params.append(chosen_params)

        eval_slice = ltf_df.iloc[is_start_idx:oos_end_idx]
        htf_eval_slice = _bound_htf(htf_df, eval_slice["time"].iloc[-1])
        result = run_fn(chosen_params, eval_slice, htf_eval_slice)
        all_trades.extend(t for t in result.trades if t.entry_ts >= oos_start_ts)
        all_signals.extend(s for s in result.signal_log if s.ts >= oos_start_ts)

    all_trades.sort(key=lambda t: t.entry_ts)
    all_signals.sort(key=lambda s: s.ts)
    return all_trades, all_signals, window_chosen_params, regime_params, htf_df


def regime_timeline(htf_df: pd.DataFrame, regime_params: dict) -> pd.DataFrame:
    classifier = RegimeClassifier(regime_params)
    classifier.reset()
    rows = []
    for i in range(len(htf_df)):
        window = htf_df.iloc[: i + 1]
        r = classifier.classify(window)
        rows.append({"time": htf_df["time"].iloc[i], "regime": r.regime.value, "bars_in_regime": r.bars_in_regime})
    return pd.DataFrame(rows)


def per_regime_attribution(trades) -> dict:
    per_regime: dict[str, dict] = {}
    for t in trades:
        b = per_regime.setdefault(t.regime_at_entry, {"count": 0, "net_pnl": 0.0, "wins": 0})
        b["count"] += 1
        b["net_pnl"] += t.pnl
        if t.pnl > 0:
            b["wins"] += 1
    for b in per_regime.values():
        b["win_rate"] = b["wins"] / b["count"] if b["count"] else 0.0
    return per_regime


def transition_proximity(trades, timeline: pd.DataFrame) -> dict:
    """bars_in_regime at each trade's entry via backward-asof against the regime
    timeline; bucket early-in-regime (<=_EARLY_REGIME_BARS) vs. established."""
    if not trades:
        return {"early": {"count": 0, "net_pnl": 0.0, "win_rate": 0.0}, "established": {"count": 0, "net_pnl": 0.0, "win_rate": 0.0}}

    trades_df = pd.DataFrame(
        {"entry_ts": [t.entry_ts for t in trades], "pnl": [t.pnl for t in trades]}
    ).sort_values("entry_ts")
    merged = pd.merge_asof(
        trades_df, timeline[["time", "bars_in_regime"]].sort_values("time"),
        left_on="entry_ts", right_on="time", direction="backward",
    )

    buckets = {"early": {"count": 0, "net_pnl": 0.0, "wins": 0}, "established": {"count": 0, "net_pnl": 0.0, "wins": 0}}
    for _, row in merged.iterrows():
        key = "early" if row["bars_in_regime"] <= _EARLY_REGIME_BARS else "established"
        buckets[key]["count"] += 1
        buckets[key]["net_pnl"] += row["pnl"]
        if row["pnl"] > 0:
            buckets[key]["wins"] += 1
    for b in buckets.values():
        b["win_rate"] = b["wins"] / b["count"] if b["count"] else 0.0
    return buckets


def veto_breakdown(signals) -> dict:
    """Count occurrences of each specific veto string across ALL consulted
    evaluations (an evaluation's vetoes list can carry more than one veto
    simultaneously), plus the count of evaluations carrying zero vetoes (gates_passed)."""
    from collections import Counter

    counts: Counter = Counter()
    no_veto = 0
    for s in signals:
        if not s.vetoes:
            no_veto += 1
        for v in s.vetoes:
            counts[v] += 1
    return {"no_veto": no_veto, "total": len(signals), "by_veto": dict(counts.most_common())}


def compute_funnel_per_record_threshold(signals) -> dict:
    """
    Like bot.backtest.results.compute_signal_funnel, but each SignalEvaluation's
    OWN .threshold is used instead of one external value -- necessary since
    different walk-forward windows can select different entry_threshold candidates.
    """
    consulted = len(signals)
    gates_passed = sum(1 for s in signals if not s.vetoes)
    threshold_cleared = sum(1 for s in signals if s.score >= s.threshold)
    fired = sum(1 for s in signals if s.fired)
    scores = sorted(s.score for s in signals)

    def _median(values):
        if not values:
            return None
        mid = len(values) // 2
        if len(values) % 2:
            return values[mid]
        return (values[mid - 1] + values[mid]) / 2.0

    return {
        "consulted": consulted,
        "gates_passed": gates_passed,
        "threshold_cleared": threshold_cleared,
        "fired": fired,
        "score_distribution": {
            "min": scores[0] if scores else None,
            "max": scores[-1] if scores else None,
            "mean": (sum(scores) / len(scores)) if scores else None,
            "median": _median(scores),
        },
    }


def expansion_veto_pass_rate(signals) -> dict:
    """
    HANDOFF.md disposition 4 (range_reversion only): fire-rate of the
    'expansion_atr_spike' veto specifically, among all consulted (RANGING-routed)
    bars. <1% or >95% means this pair's LTF-reused expansion thresholds need their
    own recalibration before this pair's gates are trusted (TRADING-RULES §1.7,
    the v3 bb_width<0.05 always-true-filter failure mode).
    """
    total = len(signals)
    fired = sum(1 for s in signals if "expansion_atr_spike" in s.vetoes)
    rate = fired / total if total else 0.0
    flagged = total > 0 and (rate < 0.01 or rate > 0.95)
    return {"total": total, "fired": fired, "rate": rate, "flagged": flagged}


def run_diagnostics(instrument: str, strategy_name: str = "trend_pullback") -> None:
    print(f"[{instrument}/{strategy_name}] re-running walk-forward (grid search per window) with record_signals=True ...", flush=True)
    trades, signals, window_chosen_params, regime_params, htf_df = stitched_oos_trades_and_signals(instrument, strategy_name)
    print(f"[{instrument}/{strategy_name}] stitched OOS: trades={len(trades)} signal_evaluations={len(signals)}", flush=True)
    for i, cp in enumerate(window_chosen_params):
        print(f"    window {i}: entry_threshold={cp['entry_threshold']} score_weights={cp['score_weights']}")

    import pickle
    cache_path = _ROOT / "instance" / f"diagnostics_cache_{strategy_name}_{instrument}.pkl"
    with open(cache_path, "wb") as f:
        pickle.dump(
            {"trades": trades, "signals": signals, "window_chosen_params": window_chosen_params, "regime_params": regime_params},
            f,
        )
    print(f"[{instrument}/{strategy_name}] cached trades/signals -> {cache_path} (reuse without re-running)", flush=True)

    funnel = compute_funnel_per_record_threshold(signals)
    print(f"[{instrument}/{strategy_name}] DIAGNOSTIC 1 -- evaluation funnel + score distribution (per-record threshold)")
    print(f"  consulted={funnel['consulted']} gates_passed={funnel['gates_passed']} "
          f"threshold_cleared={funnel['threshold_cleared']} fired={funnel['fired']}")
    print(f"  score_distribution: {funnel['score_distribution']}")

    print(f"[{instrument}/{strategy_name}] DIAGNOSTIC 1b -- veto breakdown by specific gate")
    vb = veto_breakdown(signals)
    print(f"  total consulted={vb['total']} no_veto={vb['no_veto']} ({vb['no_veto']/vb['total']:.1%})" if vb["total"] else "  no consulted evaluations")
    for veto_name, count in vb["by_veto"].items():
        print(f"    {veto_name:25s} {count:5d} ({count/vb['total']:.1%} of all consulted)")

    if strategy_name == "range_reversion":
        print(f"[{instrument}/{strategy_name}] DIAGNOSTIC 4 -- expansion-veto fire-rate (disposition 4, §1.7 pass-rate)")
        ev = expansion_veto_pass_rate(signals)
        flag_str = "FLAGGED -- recalibrate before trusting this pair's gates" if ev["flagged"] else "OK (within 1%-95%)"
        print(f"  fired={ev['fired']}/{ev['total']} rate={ev['rate']:.1%} -- {flag_str}")

    scores = sorted(s.score for s in signals)
    if scores:
        import statistics
        print(f"  score stdev={statistics.pstdev(scores):.4f} unique_score_values={len(set(round(s, 6) for s in scores))}")
        hist = {}
        for s in scores:
            bucket = round(s, 1)
            hist[bucket] = hist.get(bucket, 0) + 1
        print(f"  histogram (0.1 buckets): {dict(sorted(hist.items()))}")

    print(f"[{instrument}/{strategy_name}] DIAGNOSTIC 3 -- full H4 regime-classification frequency ...", flush=True)
    timeline = regime_timeline(htf_df, regime_params)
    regime_counts = timeline["regime"].value_counts().to_dict()
    total_bars = len(timeline)
    print(f"  total H4 bars={total_bars}")
    for regime, count in sorted(regime_counts.items(), key=lambda kv: -kv[1]):
        print(f"    {regime:15s} {count:5d} ({count/total_bars:.1%})")

    print(f"[{instrument}/{strategy_name}] DIAGNOSTIC 2/5 -- per-regime trade attribution (gate 5)")
    per_regime = per_regime_attribution(trades)
    for regime, b in per_regime.items():
        print(f"  {regime:15s} count={b['count']:3d} net_pnl={b['net_pnl']:10.2f} win_rate={b['win_rate']:.3f}")

    print(f"[{instrument}/{strategy_name}] DIAGNOSTIC (regime transition proximity, early<= {_EARLY_REGIME_BARS} bars_in_regime)")
    prox = transition_proximity(trades, timeline)
    for key, b in prox.items():
        print(f"  {key:12s} count={b['count']:3d} net_pnl={b['net_pnl']:10.2f} win_rate={b['win_rate']:.3f}")

    print(f"[{instrument}/{strategy_name}] DONE\n", flush=True)


if __name__ == "__main__":
    instrument_arg = sys.argv[1] if len(sys.argv) > 1 else "EUR_USD"
    strategy_arg = sys.argv[2] if len(sys.argv) > 2 else "trend_pullback"
    run_diagnostics(instrument_arg, strategy_arg)
