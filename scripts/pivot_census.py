"""
Pivot-cycle moments census (ROADMAP.md "Pivot cycle: census + hearings-budget",
TRADING-RULES.md §6 2026-07-12 entry). Measurement only -- no strategy code, no
gates, no OANDA calls (cached H1/H4 only). Produces population counts, ATR-
normalized event-study forward returns at +4/+8/+24 LTF (H1) bars vs. a matched
same-regime random baseline, and spread-cost-ratio context, for 8 pre-registered
candidates across all 6 pairs.

Methodology (frozen 2026-07-12, approved before any candidate was computed --
no tuning after seeing results):

Regime alignment: RegimeClassifier rolled bar-by-bar over full H4 history (same
O(n^2) full-reclassify-per-call pattern already used by
scripts/run_validation_gates.py's compute_hysteresis_excluded), then broadcast
onto H1 via merge_asof(direction="backward") -- the SAME "latest confirmed
regime as of this bar" semantics bot.backtest.engine.BacktestEngine uses
internally. Events are detected natively on this merged LTF series (regime
change-points), not by re-deriving HTF/LTF boundary alignment separately --
this sidesteps any open/close-time ambiguity by asking the same question a live
strategy would ask: "what regime does THIS bar see."

Baseline pool per event = all OTHER H1 bars in the SAME pair carrying the SAME
regime sub-state the event carries (TRENDING_UP matches only TRENDING_UP),
excluding the event bars themselves and excluding any bar within
GUARD_BAND_BARS of ANY event bar of that SAME candidate. Drawn without
replacement, BASELINE_MULT x that pair's event count (capped at pool size),
seed=SEED (frozen, no reseeding after results).

Forward return = (close[t+k] - close[t]) / ATR14(t), k in HORIZONS -- ATR-
normalized so all 6 pairs pool into one distribution. Directional candidates
are signed in the hypothesis direction; character/aftermath candidates use
|return| (see CANDIDATE_SIGN_MODE). Distinguishability = bootstrap 95% CI
(2000 resamples, same with-replacement method as bot/backtest/monte_carlo.py)
on (event mean - baseline mean) at the PRIMARY horizon (+24 bars) excludes
zero -- the single gating horizon (multiple-comparison control); +4/+8
reported as context only. Cost ratio = median |price-forward-move| at +24
bars / that pair's session-bucketed cost_model.spread_pips at the event's UTC
hour, pooled across pairs' own events.

Award floor (added at approval, pre-registered before computing): pooled
post-guard-band event count < EVENT_FLOOR disqualifies a candidate from slot 3
regardless of CI outcome.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.backtest.costs import session_for_hour  # noqa: E402
from bot.backtest.sizing import pip_size  # noqa: E402
from bot.data.cache import CandleCache  # noqa: E402
from bot.indicators.core import atr as _atr  # noqa: E402
from bot.indicators.core import adx as _adx  # noqa: E402
from bot.regime.classifier import RegimeClassifier, RegimeState  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_INSTRUMENTS_YAML = _ROOT / "bot" / "config" / "instruments.yaml"
_CACHE_DIR = _ROOT / "instance" / "candle_cache"

PAIRS = ["GBP_JPY", "EUR_USD", "USD_JPY", "GBP_USD", "AUD_USD", "EUR_GBP"]
HORIZONS = [4, 8, 24]
PRIMARY_HORIZON = 24
SEED = 20260712
BASELINE_MULT = 5
GUARD_BAND_BARS = 24
HTF_WARMUP_BARS = 210          # EMA200 + buffer before any HTF episode is trusted
LTF_WARMUP_BARS = 250          # box/ATR warmup before any LTF-native event is trusted
RESUMPTION_MAX_DWELL_HTF_BARS = 20   # candidate (ii): RANGING dwell ceiling, ~5x regime_min_hold_bars
FAILED_BREAKOUT_WINDOW_BARS = 4      # candidate (v): re-entry must occur within this many LTF bars
COMPRESSION_BOX_LOOKBACK = 20        # candidate (v): matches squeeze_breakout_params default
EVENT_FLOOR = 30                     # pre-registered slot-3 floor (added at approval)
COST_RATIO_BAR = 4.0

CANDIDATES = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii"]
CANDIDATE_NAMES = {
    "i": "COMPRESSION->TRENDING (trend inception)",
    "ii": "TRENDING->RANGING->TRENDING (resumption)",
    "iii": "EXPANSION->RANGING (aftermath)",
    "iv": "London-open after Asian range",
    "v": "Failed-breakout re-entry into compression box",
    "vi": "TRENDING death (ADX rollover <20)",
    "vii": "Monday open gaps",
    "viii": "Month-end final two trading days",
}
# unsigned candidates use |return|; signed candidates carry a per-event sign
UNSIGNED_CANDIDATES = {"iii", "iv", "vi", "viii"}


def load_raw_config() -> dict:
    with open(_INSTRUMENTS_YAML) as f:
        return yaml.safe_load(f)


def build_htf_regime_series(h4: pd.DataFrame, regime_params: dict) -> pd.DataFrame:
    """Roll RegimeClassifier bar-by-bar over full H4 history. Same pattern as
    scripts/run_validation_gates.py's compute_hysteresis_excluded."""
    classifier = RegimeClassifier(regime_params)
    classifier.reset()
    regimes = []
    bars_in_regime = []
    for i in range(len(h4)):
        r = classifier.classify(h4.iloc[: i + 1])
        regimes.append(r.regime.value)
        bars_in_regime.append(r.bars_in_regime)
    adx14 = _adx(h4["high"], h4["low"], h4["close"], 14)
    return pd.DataFrame(
        {
            "time": h4["time"],
            "regime": regimes,
            "bars_in_regime": bars_in_regime,
            "adx14": adx14.to_numpy(),
        }
    )


def merge_onto_ltf(h1: pd.DataFrame, htf_series: pd.DataFrame) -> pd.DataFrame:
    merged = pd.merge_asof(
        h1[["time", "open", "high", "low", "close"]],
        htf_series,
        on="time",
        direction="backward",
    )
    merged["ltf_atr14"] = _atr(h1["high"], h1["low"], h1["close"], 14).to_numpy()
    return merged


def build_episodes(merged: pd.DataFrame) -> list[dict]:
    """Consecutive-run episodes over the merged regime series."""
    regime = merged["regime"]
    change = regime.ne(regime.shift(1))
    change.iloc[0] = True
    group_id = change.cumsum()
    episodes = []
    for _, idx in merged.groupby(group_id).groups.items():
        idx = list(idx)
        episodes.append(
            {
                "regime": regime.loc[idx[0]],
                "start": idx[0],
                "end": idx[-1],
                "end_bars_in_regime": merged["bars_in_regime"].loc[idx[-1]],
            }
        )
    return episodes


def _valid_start(n: int) -> int:
    return max(HTF_WARMUP_BARS, LTF_WARMUP_BARS)


# ---------------------------------------------------------------------------
# Candidate event detectors -- each returns list of dict{idx, sign, regime_match}
# ---------------------------------------------------------------------------


def detect_i(episodes: list[dict], n: int) -> list[dict]:
    start_ok = _valid_start(n)
    out = []
    for prev, cur in zip(episodes, episodes[1:]):
        if cur["start"] < start_ok:
            continue
        if prev["regime"] == RegimeState.COMPRESSION.value and cur["regime"] in (
            RegimeState.TRENDING_UP.value,
            RegimeState.TRENDING_DOWN.value,
        ):
            sign = 1.0 if cur["regime"] == RegimeState.TRENDING_UP.value else -1.0
            out.append({"idx": cur["start"], "sign": sign, "regime_match": cur["regime"]})
    return out


def detect_ii(episodes: list[dict], n: int) -> list[dict]:
    start_ok = _valid_start(n)
    out = []
    for a, b, c in zip(episodes, episodes[1:], episodes[2:]):
        if c["start"] < start_ok:
            continue
        if (
            a["regime"] in (RegimeState.TRENDING_UP.value, RegimeState.TRENDING_DOWN.value)
            and b["regime"] == RegimeState.RANGING.value
            and c["regime"] == a["regime"]
            and b["end_bars_in_regime"] <= RESUMPTION_MAX_DWELL_HTF_BARS
        ):
            sign = 1.0 if c["regime"] == RegimeState.TRENDING_UP.value else -1.0
            out.append({"idx": c["start"], "sign": sign, "regime_match": c["regime"]})
    return out


def detect_iii(episodes: list[dict], n: int) -> list[dict]:
    start_ok = _valid_start(n)
    out = []
    for prev, cur in zip(episodes, episodes[1:]):
        if cur["start"] < start_ok:
            continue
        if prev["regime"] == RegimeState.EXPANSION.value and cur["regime"] == RegimeState.RANGING.value:
            out.append({"idx": cur["start"], "sign": 1.0, "regime_match": cur["regime"]})
    return out


def detect_vi(episodes: list[dict], merged: pd.DataFrame, n: int) -> list[dict]:
    start_ok = _valid_start(n)
    out = []
    for ep in episodes:
        if ep["regime"] not in (RegimeState.TRENDING_UP.value, RegimeState.TRENDING_DOWN.value):
            continue
        if ep["start"] < start_ok:
            continue
        window = merged.iloc[ep["start"] : ep["end"] + 1]
        below = window.index[window["adx14"] < 20.0]
        if len(below) == 0:
            continue
        first_idx = int(below[0])
        # de-overlap clause: first cross per episode only
        out.append({"idx": first_idx, "sign": 1.0, "regime_match": ep["regime"]})
    return out


def detect_iv(merged: pd.DataFrame, n: int) -> list[dict]:
    start_ok = _valid_start(n)
    out = []
    hours = merged["time"].dt.hour.to_numpy()
    for i in range(start_ok, n):
        if hours[i] == 7:
            out.append({"idx": i, "sign": 1.0, "regime_match": merged["regime"].iloc[i]})
    return out


def detect_v(merged: pd.DataFrame, n: int) -> list[dict]:
    start_ok = _valid_start(n)
    close = merged["close"].to_numpy()
    box_high = merged["high"].rolling(COMPRESSION_BOX_LOOKBACK).max().shift(1).to_numpy()
    box_low = merged["low"].rolling(COMPRESSION_BOX_LOOKBACK).min().shift(1).to_numpy()
    is_compression = (merged["regime"] == RegimeState.COMPRESSION.value).to_numpy()

    out = []
    i = start_ok
    while i < n - FAILED_BREAKOUT_WINDOW_BARS:
        if not is_compression[i] or np.isnan(box_high[i]) or np.isnan(box_low[i]):
            i += 1
            continue
        breakout_dir = 0
        if close[i] > box_high[i]:
            breakout_dir = 1
        elif close[i] < box_low[i]:
            breakout_dir = -1
        if breakout_dir == 0:
            i += 1
            continue
        bh, bl = box_high[i], box_low[i]
        resolved = False
        for k in range(1, FAILED_BREAKOUT_WINDOW_BARS + 1):
            if bl <= close[i + k] <= bh:
                sign = -1.0 if breakout_dir == 1 else 1.0
                out.append({"idx": i + k, "sign": sign, "regime_match": RegimeState.COMPRESSION.value})
                i += k + 1
                resolved = True
                break
        if not resolved:
            i += 1
    return out


def detect_vii(merged: pd.DataFrame, n: int) -> list[dict]:
    start_ok = _valid_start(n)
    times = merged["time"].to_numpy()
    open_ = merged["open"].to_numpy()
    close = merged["close"].to_numpy()
    out = []
    for i in range(max(start_ok, 1), n):
        gap_hours = (times[i] - times[i - 1]) / np.timedelta64(1, "h")
        if gap_hours > 24:
            gap_sign = 1.0 if open_[i] > close[i - 1] else -1.0
            out.append({"idx": i, "sign": gap_sign, "regime_match": merged["regime"].iloc[i]})
    return out


def detect_viii(merged: pd.DataFrame, n: int) -> list[dict]:
    start_ok = _valid_start(n)
    dates = merged["time"].dt.tz_convert("UTC").dt.date
    unique_dates = sorted(dates.unique())
    months = {}
    for d in unique_dates:
        months.setdefault((d.year, d.month), []).append(d)
    out = []
    first_idx_by_date = dates.reset_index().groupby("time")["index"].min()
    for _, day_list in months.items():
        day_list = sorted(day_list)
        if len(day_list) < 2:
            continue
        target_date = day_list[-2]
        idx = int(first_idx_by_date.loc[target_date])
        if idx < start_ok:
            continue
        out.append({"idx": idx, "sign": 1.0, "regime_match": merged["regime"].iloc[idx]})
    return out


# ---------------------------------------------------------------------------
# Event study
# ---------------------------------------------------------------------------


def forward_returns(merged: pd.DataFrame, idx: int, horizons: list[int]) -> dict[int, float] | None:
    close = merged["close"]
    atr = merged["ltf_atr14"]
    n = len(merged)
    if idx + max(horizons) >= n:
        return None
    atr0 = atr.iloc[idx]
    if pd.isna(atr0) or atr0 <= 0:
        return None
    c0 = close.iloc[idx]
    out = {}
    for k in horizons:
        out[k] = (close.iloc[idx + k] - c0) / atr0
    return out


def price_move(merged: pd.DataFrame, idx: int, k: int) -> float | None:
    close = merged["close"]
    n = len(merged)
    if idx + k >= n:
        return None
    return float(close.iloc[idx + k] - close.iloc[idx])


def effective_guard_band(event_idxs: set[int]) -> int:
    """
    GUARD_BAND_BARS=24 is sized for rare/transition-type candidates (avoid
    resampling the aftermath of the SAME move). High-frequency calendar
    candidates (e.g. (iv), spaced ~24 LTF bars apart, one per trading day)
    would have a fixed 24-bar band tile the entire timeline around their own
    events, degenerately emptying the baseline pool -- a computation failure,
    not a substantive finding. Mechanical, frequency-derived shrink (applied
    uniformly, before inspecting any candidate's distinguishability result):
    cap the band at half the median gap between this candidate's own event
    bars, minus 1, floored at 1 (always exclude at least the event bar
    itself). Rare candidates (gap >> 48) are unaffected -- this only bites
    candidates dense enough to need it.
    """
    if len(event_idxs) < 2:
        return GUARD_BAND_BARS
    sorted_idx = sorted(event_idxs)
    gaps = np.diff(sorted_idx)
    median_gap = float(np.median(gaps))
    return max(1, min(GUARD_BAND_BARS, int(median_gap // 2) - 1))


def build_baseline_pool(
    merged: pd.DataFrame, regime_match: str, event_idxs: set[int], n: int, guard_band: int
) -> list[int]:
    start_ok = _valid_start(n)
    same_regime = (merged["regime"] == regime_match).to_numpy()
    excluded = np.zeros(n, dtype=bool)
    for e in event_idxs:
        lo, hi = max(0, e - guard_band), min(n, e + guard_band + 1)
        excluded[lo:hi] = True
    pool = [
        i
        for i in range(start_ok, n - max(HORIZONS))
        if same_regime[i] and not excluded[i]
    ]
    return pool


def bootstrap_mean_diff_ci(event_vals: np.ndarray, baseline_vals: np.ndarray, seed: int, n_resamples: int = 2000):
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_resamples)
    for r in range(n_resamples):
        e = rng.choice(event_vals, size=len(event_vals), replace=True)
        b = rng.choice(baseline_vals, size=len(baseline_vals), replace=True)
        diffs[r] = e.mean() - b.mean()
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(lo), float(hi)


def run_candidate_for_pair(candidate: str, merged: pd.DataFrame, episodes: list[dict]) -> dict:
    n = len(merged)
    if candidate == "i":
        events = detect_i(episodes, n)
    elif candidate == "ii":
        events = detect_ii(episodes, n)
    elif candidate == "iii":
        events = detect_iii(episodes, n)
    elif candidate == "iv":
        events = detect_iv(merged, n)
    elif candidate == "v":
        events = detect_v(merged, n)
    elif candidate == "vi":
        events = detect_vi(episodes, merged, n)
    elif candidate == "vii":
        events = detect_vii(merged, n)
    elif candidate == "viii":
        events = detect_viii(merged, n)
    else:
        raise ValueError(candidate)

    raw_count = len(events)
    event_idx_set = {e["idx"] for e in events}

    # per-event guard-band self-exclusion is handled by excluding OTHER events'
    # neighborhoods from the baseline pool; events themselves stay in the
    # event population (the population count IS the phenomenon's frequency).
    valid_events = [
        e for e in events if forward_returns(merged, e["idx"], HORIZONS) is not None
    ]

    return {
        "raw_count": raw_count,
        "events": valid_events,
        "event_idx_set": event_idx_set,
    }


def main():
    raw_cfg = load_raw_config()
    regime_params = raw_cfg["defaults"]["regime_params"]
    instruments_cfg = raw_cfg["instruments"]
    cache = CandleCache(_CACHE_DIR)

    pair_data = {}
    print("Loading cache + rolling regime classifier per pair...")
    for pair in PAIRS:
        h1 = cache.load(pair, "H1")
        h4 = cache.load(pair, "H4")
        if h1 is None or h4 is None:
            raise RuntimeError(f"{pair}: missing cached H1/H4 candles")
        htf_series = build_htf_regime_series(h4, regime_params)
        merged = merge_onto_ltf(h1, htf_series)
        episodes = build_episodes(merged)
        cost_model = instruments_cfg[pair]["cost_model"]
        pair_data[pair] = {"merged": merged, "episodes": episodes, "cost_model": cost_model}
        print(f"  {pair}: H1={len(h1)} H4={len(h4)} episodes={len(episodes)}")

    results = {}
    for candidate in CANDIDATES:
        pooled_event_vals = {k: [] for k in HORIZONS}
        pooled_baseline_vals = {k: [] for k in HORIZONS}
        pooled_price_moves = []
        per_pair_counts = {}
        raw_counts = {}
        guard_bands = {}

        for pair in PAIRS:
            pd_ = pair_data[pair]
            merged, episodes, cost_model = pd_["merged"], pd_["episodes"], pd_["cost_model"]
            n = len(merged)
            out = run_candidate_for_pair(candidate, merged, episodes)
            raw_counts[pair] = out["raw_count"]
            events = out["events"]
            per_pair_counts[pair] = len(events)

            # group events by regime_match for stratified baseline draw
            by_regime: dict[str, list[dict]] = {}
            for e in events:
                by_regime.setdefault(e["regime_match"], []).append(e)

            event_idx_set = out["event_idx_set"]
            rng_seed = SEED + hash((candidate, pair)) % 10_000
            guard_band = effective_guard_band(event_idx_set)
            guard_bands[pair] = guard_band

            for regime_match, ev_list in by_regime.items():
                # Event returns are always recorded -- independent of whether a
                # baseline could be drawn for this stratum (a bug in the first
                # run tied these together via a shared `continue`, silently
                # zeroing candidate (iv)'s entire event population).
                for e in ev_list:
                    fr = forward_returns(merged, e["idx"], HORIZONS)
                    if fr is None:
                        continue
                    for k in HORIZONS:
                        val = abs(fr[k]) if candidate in UNSIGNED_CANDIDATES else fr[k] * e["sign"]
                        pooled_event_vals[k].append(val)
                    pm = price_move(merged, e["idx"], PRIMARY_HORIZON)
                    if pm is not None:
                        hour = merged["time"].iloc[e["idx"]].hour
                        session = session_for_hour(hour)
                        spread_price = cost_model["spread_pips"][session] * pip_size(pair)
                        if spread_price > 0:
                            pooled_price_moves.append(abs(pm) / spread_price)

                pool = build_baseline_pool(merged, regime_match, event_idx_set, n, guard_band)
                sample_size = min(len(pool), BASELINE_MULT * len(ev_list))
                if sample_size == 0:
                    continue
                rng = np.random.default_rng(rng_seed)
                baseline_idxs = rng.choice(pool, size=sample_size, replace=False)

                for bidx in baseline_idxs:
                    fr = forward_returns(merged, int(bidx), HORIZONS)
                    if fr is None:
                        continue
                    for k in HORIZONS:
                        val = abs(fr[k]) if candidate in UNSIGNED_CANDIDATES else fr[k]
                        pooled_baseline_vals[k].append(val)

        pooled_n = sum(per_pair_counts.values())
        ci_by_horizon = {}
        event_mean_by_horizon = {}
        baseline_mean_by_horizon = {}
        for k in HORIZONS:
            ev = np.array(pooled_event_vals[k])
            ba = np.array(pooled_baseline_vals[k])
            if len(ev) < 2 or len(ba) < 2:
                ci_by_horizon[k] = (float("nan"), float("nan"))
                event_mean_by_horizon[k] = float("nan") if len(ev) == 0 else float(ev.mean())
                baseline_mean_by_horizon[k] = float("nan") if len(ba) == 0 else float(ba.mean())
                continue
            lo, hi = bootstrap_mean_diff_ci(ev, ba, seed=SEED)
            ci_by_horizon[k] = (lo, hi)
            event_mean_by_horizon[k] = float(ev.mean())
            baseline_mean_by_horizon[k] = float(ba.mean())

        cost_ratio_median = float(np.median(pooled_price_moves)) if pooled_price_moves else float("nan")

        primary_lo, primary_hi = ci_by_horizon[PRIMARY_HORIZON]
        distinguishable = not (np.isnan(primary_lo) or (primary_lo <= 0 <= primary_hi))
        cost_ok = (not np.isnan(cost_ratio_median)) and cost_ratio_median >= COST_RATIO_BAR
        floor_ok = pooled_n >= EVENT_FLOOR

        results[candidate] = {
            "name": CANDIDATE_NAMES[candidate],
            "raw_counts": raw_counts,
            "per_pair_counts": per_pair_counts,
            "pooled_n": pooled_n,
            "ci_by_horizon": ci_by_horizon,
            "event_mean_by_horizon": event_mean_by_horizon,
            "baseline_mean_by_horizon": baseline_mean_by_horizon,
            "cost_ratio_median": cost_ratio_median,
            "distinguishable": distinguishable,
            "cost_ok": cost_ok,
            "floor_ok": floor_ok,
            "clears_both_bars": distinguishable and cost_ok and floor_ok,
        }

        print(f"\n=== Candidate {candidate}: {CANDIDATE_NAMES[candidate]} ===")
        print(f"  per-pair events (post-guard-band): {per_pair_counts}")
        if len(set(guard_bands.values())) == 1 and next(iter(guard_bands.values())) != GUARD_BAND_BARS:
            print(f"  guard band shrunk to {next(iter(guard_bands.values()))} bars (frequency-adaptive, see effective_guard_band)")
        elif len(set(guard_bands.values())) > 1:
            print(f"  guard bands (frequency-adaptive per pair): {guard_bands}")
        print(f"  pooled n = {pooled_n}  (floor={EVENT_FLOOR}, floor_ok={floor_ok})")
        for k in HORIZONS:
            lo, hi = ci_by_horizon[k]
            print(
                f"  +{k:>2} bars: event_mean={event_mean_by_horizon[k]:.4f} "
                f"baseline_mean={baseline_mean_by_horizon[k]:.4f} "
                f"diff_CI=[{lo:.4f}, {hi:.4f}]"
            )
        print(f"  cost ratio (median |move|/spread @ +24): {cost_ratio_median:.2f}")
        print(f"  distinguishable(+24)={distinguishable}  cost_ok={cost_ok}  clears_both={results[candidate]['clears_both_bars']}")

    print("\n\n=== SLOT 3 MECHANICAL DETERMINATION ===")
    eligible = [c for c in CANDIDATES if results[c]["clears_both_bars"]]
    if not eligible:
        print("No candidate clears both bars (or clears floor). Slot 3 FORFEITED. Budget is two.")
    else:
        # "Most distinguishable" = CI edge nearest zero, farthest from zero --
        # sign-agnostic (a positive-effect and a negative-effect candidate are
        # compared on confidence margin, not on raw bound value).
        def margin(c):
            lo, hi = results[c]["ci_by_horizon"][PRIMARY_HORIZON]
            return min(abs(lo), abs(hi))

        eligible.sort(key=margin, reverse=True)
        winner = eligible[0]
        print(f"Slot 3 AWARDED to candidate {winner}: {results[winner]['name']}")
        if len(eligible) > 1:
            print(f"  (other eligible candidates recorded, not awarded: {eligible[1:]})")

    return results


if __name__ == "__main__":
    main()
