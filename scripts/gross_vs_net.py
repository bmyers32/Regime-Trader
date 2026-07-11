"""
Post-verdict exhibit (Phase 6 close-out, 2026-07-10, both pre-registered before
seeing the data, neither a rescue of range_reversion's already-accepted FAIL):

(1) Per-session attribution for range_reversion's two target pairs -- the
    kickoff's explicit empirical question ("Asian-session behavior is per-pair
    calibration, not assumption") replacing a session-preference ASSUMPTION with
    a MEASUREMENT. Decision rule stated up front: roughly uniform losses across
    sessions -> FAIL fully closed as already recorded; losses materially
    concentrated in Asian entries -> one follow-up run per pair with London/NY-
    only entry is the completion of the pre-registered experiment (§3.2's own
    preference clause), not a parameter retune.

(2) Gross-vs-net PnL for both playbooks' already-accepted final runs, to
    classify each FAIL's failure mode: no-edge (gross <= 0, costs are not the
    story) vs. cost-dominated (gross > 0, net < 0, a real edge exists pre-cost
    but frictions erase it). "Gross" replays the EXACT SAME already-selected
    per-window chosen_params (loaded from each run's diagnostics cache pickle,
    never re-optimized) through BacktestEngine with cost_cfg=ZERO_COST_MODEL
    instead of the real cost_model -- same window bounds, same trimming/stitching
    run_walk_forward itself uses, only the cost line items zeroed. This is a
    re-costing of an already-decided set of trades, not a new search: reusing the
    frozen params is what keeps this a diagnostic rather than a second attempt at
    a PASS (BRAIN.md: "A clean FAIL with reasons is a deliverable").

Reads instance/diagnostics_cache_*.pkl files already produced by scripts/
diagnose_gates.py during the accepted gate runs (Phase 5 for trend_pullback,
Phase 6 for range_reversion) -- no OANDA calls, no re-optimization.
"""

from __future__ import annotations

import pickle
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_validation_gates as rvg  # noqa: E402 -- sibling script, same _STRATEGIES registry

from bot.backtest.costs import ZERO_COST_MODEL, session_for_hour  # noqa: E402
from bot.backtest.engine import BacktestEngine  # noqa: E402
from bot.backtest.walk_forward import generate_window_bounds  # noqa: E402
from bot.data.cache import CandleCache  # noqa: E402
from bot.regime.classifier import RegimeClassifier  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _ROOT / "instance" / "candle_cache"
_IS_BARS = 3000
_OOS_BARS = 1000


def _bound_htf(htf_df, max_ltf_ts):
    return htf_df[htf_df["time"] <= max_ltf_ts]


def false_break_vs_insufficient_expansion(trades) -> dict:
    """
    Phase 7 pre-registered post-mortem split (HANDOFF.md / squeeze_breakout plan doc),
    squeeze_breakout only -- attributes LOSING stitched OOS trades between:
      (a) false-break losses: never reached partial_at_r (BacktestTrade.
          partial_exit_ts is None) -- stopped out before the expansion materialized
          at all. Only this case is something the deferred optional-confirmation
          filter (ROADMAP.md) could plausibly fix.
      (b) expansion-materialized-but-insufficient losses: the partial WAS taken
          (partial_exit_ts is not None) but total trade pnl is still negative -- the
          move happened but wasn't enough to overcome the partial-vs-remainder math/
          costs. Implicates trigger/exit tuning instead; does NOT license spending
          the revival budget on the confirmation-filter mechanism.
    Winning trades are counted separately (informational only -- the split's whole
    purpose is diagnosing LOSSES).
    """
    losers = [t for t in trades if t.pnl < 0]
    false_break = [t for t in losers if t.partial_exit_ts is None]
    insufficient = [t for t in losers if t.partial_exit_ts is not None]
    winners = [t for t in trades if t.pnl >= 0]
    return {
        "total_trades": len(trades),
        "winners": len(winners),
        "losers": len(losers),
        "false_break_count": len(false_break),
        "false_break_pnl": sum(t.pnl for t in false_break),
        "insufficient_expansion_count": len(insufficient),
        "insufficient_expansion_pnl": sum(t.pnl for t in insufficient),
    }


def r_multiple_distribution(trades) -> dict:
    """
    Approved addition (HANDOFF.md / plan doc): realized R-multiple distribution
    (BacktestTrade.pnl_r) across all stitched OOS trades -- REQUIRED non-degeneracy
    check before false_break_vs_insufficient_expansion's split is interpreted. If
    nearly every trade clusters at ~-1R with none approaching +partial_at_r (or the
    reverse), the (a)/(b) split is not meaningfully discriminating and must be
    flagged, not reported as a clean classification.
    """
    if not trades:
        return {"count": 0}
    r_values = sorted(t.pnl_r for t in trades)
    n = len(r_values)

    def _pct(p: float) -> float:
        idx = min(n - 1, int(round(p * (n - 1))))
        return r_values[idx]

    return {
        "count": n,
        "min": r_values[0],
        "p25": _pct(0.25),
        "median": _pct(0.50),
        "p75": _pct(0.75),
        "max": r_values[-1],
    }


def per_session_attribution(trades) -> dict:
    per_session: dict[str, dict] = {}
    for t in trades:
        session = session_for_hour(t.entry_ts.hour)
        b = per_session.setdefault(session, {"count": 0, "net_pnl": 0.0, "wins": 0})
        b["count"] += 1
        b["net_pnl"] += t.pnl
        if t.pnl > 0:
            b["wins"] += 1
    for b in per_session.values():
        b["win_rate"] = b["wins"] / b["count"] if b["count"] else 0.0
    return per_session


def gross_stitched_pnl(instrument: str, strategy_name: str, window_chosen_params: list[dict]) -> tuple[float, int]:
    """Re-costs the EXACT already-selected per-window params at zero cost. Returns
    (gross_stitched_net_pnl, trade_count). Window bounds are recomputed
    deterministically from the same cached ltf_df length -- not stored, not needed,
    since generate_window_bounds(n_bars, is_bars, oos_bars) is pure."""
    spec = rvg._STRATEGIES[strategy_name]
    raw = rvg._load_raw_config()
    account_currency = raw.get("account_currency", "USD")
    risk_pct = raw["defaults"]["risk_pct"]
    regime_params = raw["defaults"]["regime_params"]
    htf_gran, ltf_gran = raw["defaults"]["timeframe_htf"], raw["defaults"]["timeframe_ltf"]

    cache = CandleCache(_CACHE_DIR)
    htf_df = cache.load(instrument, htf_gran)
    ltf_df = cache.load(instrument, ltf_gran)
    conversion_series = rvg.load_conversion_series(instrument, account_currency, cache, ltf_gran)

    n_bars = len(ltf_df)
    bounds = generate_window_bounds(n_bars, _IS_BARS, _OOS_BARS)
    if len(bounds) != len(window_chosen_params):
        raise RuntimeError(
            f"{instrument}/{strategy_name}: {len(bounds)} recomputed window bounds != "
            f"{len(window_chosen_params)} cached chosen_params -- cached candle history "
            "must have changed since the accepted run; do not proceed on a mismatch."
        )

    all_trades = []
    for (is_start_idx, oos_start_idx, oos_end_idx), params in zip(bounds, window_chosen_params):
        oos_start_ts = ltf_df["time"].iloc[oos_start_idx]
        eval_slice = ltf_df.iloc[is_start_idx:oos_end_idx]
        htf_eval_slice = _bound_htf(htf_df, eval_slice["time"].iloc[-1])

        strategy = spec.strategy_class(params, instrument)
        classifier = RegimeClassifier(regime_params)
        engine = BacktestEngine(
            strategy=strategy,
            regime_classifier=classifier,
            instrument=instrument,
            account_currency=account_currency,
            risk_pct=risk_pct,
            starting_equity=10_000.0,
            cost_cfg=ZERO_COST_MODEL,  # only difference from the accepted run
            conversion_series=conversion_series,
            exit_cfg=params.get("exit"),
            signal_threshold=params["entry_threshold"],
            record_signals=False,
        )
        result = engine.run(eval_slice, htf_eval_slice)
        all_trades.extend(t for t in result.trades if t.entry_ts >= oos_start_ts)

    gross_net_pnl = sum(t.pnl for t in all_trades)
    return gross_net_pnl, len(all_trades)


def _load_cache(path: Path) -> dict:
    with open(path, "rb") as f:
        return pickle.load(f)


if __name__ == "__main__":
    instance_dir = _ROOT / "instance"

    print("=" * 78)
    print("EXHIBIT 1: per-session attribution, range_reversion target pairs")
    print("=" * 78)
    for instrument, path in [
        ("EUR_USD", instance_dir / "diagnostics_cache_range_reversion_EUR_USD.pkl"),
        ("EUR_GBP", instance_dir / "diagnostics_cache_range_reversion_EUR_GBP.pkl"),
    ]:
        cache = _load_cache(path)
        per_session = per_session_attribution(cache["trades"])
        print(f"\n[{instrument}/range_reversion] net_pnl by session (stitched OOS trades):")
        for session in ("asian", "london", "ny_overlap"):
            b = per_session.get(session, {"count": 0, "net_pnl": 0.0, "win_rate": 0.0})
            print(f"  {session:12s} count={b['count']:3d} net_pnl={b['net_pnl']:10.2f} win_rate={b['win_rate']:.3f}")

    print()
    print("=" * 78)
    print("EXHIBIT 2: gross-vs-net PnL, both playbooks' accepted final runs")
    print("=" * 78)
    runs = [
        ("EUR_USD", "trend_pullback", instance_dir / "diagnostics_cache_EUR_USD.pkl", -1437.53),
        ("USD_JPY", "trend_pullback", instance_dir / "diagnostics_cache_USD_JPY.pkl", -700.08),
        ("EUR_USD", "range_reversion", instance_dir / "diagnostics_cache_range_reversion_EUR_USD.pkl", -354.20),
        ("EUR_GBP", "range_reversion", instance_dir / "diagnostics_cache_range_reversion_EUR_GBP.pkl", -163.13),
        ("GBP_USD", "squeeze_breakout", instance_dir / "diagnostics_cache_squeeze_breakout_GBP_USD.pkl", -691.75),
        ("USD_JPY", "squeeze_breakout", instance_dir / "diagnostics_cache_squeeze_breakout_USD_JPY.pkl", -113.13),
    ]
    for instrument, strategy_name, path, accepted_net in runs:
        cache = _load_cache(path)
        gross, gross_trade_count = gross_stitched_pnl(instrument, strategy_name, cache["window_chosen_params"])
        net = sum(t.pnl for t in cache["trades"])
        classification = "no-edge (gross<=0)" if gross <= 0 else "COST-DOMINATED (gross>0, net<0)"
        print(
            f"[{instrument}/{strategy_name}] gross={gross:10.2f} ({gross_trade_count} trades) "
            f"net={net:10.2f} (accepted={accepted_net:.2f}) -> {classification}"
        )

    print()
    print("=" * 78)
    print("EXHIBIT 3: squeeze_breakout pre-registered false-break split + R-distribution")
    print("=" * 78)
    for instrument, path in [
        ("GBP_USD", instance_dir / "diagnostics_cache_squeeze_breakout_GBP_USD.pkl"),
        ("USD_JPY", instance_dir / "diagnostics_cache_squeeze_breakout_USD_JPY.pkl"),
    ]:
        cache = _load_cache(path)
        trades = cache["trades"]
        rdist = r_multiple_distribution(trades)
        print(f"\n[{instrument}/squeeze_breakout] realized R-multiple distribution (non-degeneracy check, {rdist['count']} trades):")
        print(f"  min={rdist['min']:.3f} p25={rdist['p25']:.3f} median={rdist['median']:.3f} p75={rdist['p75']:.3f} max={rdist['max']:.3f}")
        split = false_break_vs_insufficient_expansion(trades)
        print(f"[{instrument}/squeeze_breakout] false-break vs insufficient-expansion split (pre-registered protocol):")
        print(
            f"  winners={split['winners']} losers={split['losers']} | "
            f"(a) false_break: count={split['false_break_count']} pnl={split['false_break_pnl']:.2f} | "
            f"(b) insufficient_expansion: count={split['insufficient_expansion_count']} pnl={split['insufficient_expansion_pnl']:.2f}"
        )
        per_session = per_session_attribution(trades)
        print(f"[{instrument}/squeeze_breakout] net_pnl by session (informational -- no pre-registered follow-up trigger this phase):")
        for session in ("asian", "london", "ny_overlap"):
            b = per_session.get(session, {"count": 0, "net_pnl": 0.0, "win_rate": 0.0})
            print(f"  {session:12s} count={b['count']:3d} net_pnl={b['net_pnl']:10.2f} win_rate={b['win_rate']:.3f}")
