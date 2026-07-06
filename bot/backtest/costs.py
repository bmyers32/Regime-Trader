"""
Cost model: spread, slippage, rollover — TRADING-RULES §1.11 ("mid-price signals,
spread ignored" is the exact failure this module exists to prevent) and §5.2.

The backtester and the (Phase 8) live executor read the SAME cost_model config and
apply the SAME max-spread entry gate here — a trade the live bot would refuse for
spread must be refused in simulation too, not just cost-adjusted after the fact.

Spread is session-bucketed rather than a single average: London/NY-overlap liquidity
is materially different from the Asian session, and flattening to one number under-
or over-charges roughly half the trading day. Session buckets are approximate UTC-hour
ranges (session opens aren't sharp, and this module isn't the blackout-window
calendar) — see session_for_hour().

Slippage is asymmetric: charged on market entries and SL exits (adverse, urgent fills);
never charged on TP fills (resting order, no urgency); doubled on SL exits when the
exit-time regime is EXPANSION (fast-moving market, worse realistic fills).

Rollover is a per-unit cost applied once per UTC-day rollover-time crossed while a
position is open — see rollover_crossings().

cost_cfg is a plain dict (same pattern as RegimeClassifier's params dict) with keys:
  spread_pips: {"asian": float, "london": float, "ny_overlap": float}
  max_spread_pips: float
  slippage_pips: float
  rollover_pips_long: float
  rollover_pips_short: float
Callers are responsible for resolving instruments.yaml's PENDING (null) placeholders
into real numbers before use — this module does no config loading of its own.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from bot.backtest.sizing import pip_size

ROLLOVER_HOUR_UTC = 22

ZERO_COST_MODEL: dict = {
    "spread_pips": {"asian": 0.0, "london": 0.0, "ny_overlap": 0.0},
    "max_spread_pips": float("inf"),
    "slippage_pips": 0.0,
    "rollover_pips_long": 0.0,
    "rollover_pips_short": 0.0,
}


def session_for_hour(utc_hour: int) -> str:
    """UTC-hour -> session bucket. asian wraps midnight (21:00-07:00)."""
    if 7 <= utc_hour < 12:
        return "london"
    if 12 <= utc_hour < 21:
        return "ny_overlap"
    return "asian"


def current_spread_pips(cost_cfg: dict, bar_time: datetime) -> float:
    session = session_for_hour(bar_time.hour)
    return float(cost_cfg["spread_pips"][session])


def spread_gate_ok(cost_cfg: dict, bar_time: datetime) -> bool:
    """False when the current session spread exceeds max_spread_pips — refuse entry."""
    return current_spread_pips(cost_cfg, bar_time) <= cost_cfg["max_spread_pips"]


def apply_entry_cost(
    mid_price: float, direction: str, instrument: str, cost_cfg: dict, bar_time: datetime
) -> float:
    """Fill price for a market entry: half-spread + slippage, against the trader."""
    p_size = pip_size(instrument)
    spread_price = current_spread_pips(cost_cfg, bar_time) * p_size
    slip_price = cost_cfg["slippage_pips"] * p_size
    adverse = spread_price / 2.0 + slip_price
    return mid_price + adverse if direction == "long" else mid_price - adverse


def apply_exit_cost(
    mid_price: float,
    direction: str,
    instrument: str,
    cost_cfg: dict,
    bar_time: datetime,
    exit_reason: str,
    exit_regime: str | None,
) -> float:
    """
    Fill price for a position exit: half-spread always; slippage only on non-TP exits,
    doubled when exit_regime == 'EXPANSION'. Adverse direction is reversed relative to
    entry — a long position SELLS to exit, so an adverse fill is a LOWER price.
    """
    p_size = pip_size(instrument)
    spread_price = current_spread_pips(cost_cfg, bar_time) * p_size

    if exit_reason == "tp":
        adverse = spread_price / 2.0
    else:
        slip_price = cost_cfg["slippage_pips"] * p_size
        if exit_regime == "EXPANSION":
            slip_price *= 2.0
        adverse = spread_price / 2.0 + slip_price

    return mid_price - adverse if direction == "long" else mid_price + adverse


def rollover_crossings(
    entry_ts: datetime, exit_ts: datetime, rollover_hour: int = ROLLOVER_HOUR_UTC
) -> int:
    """
    Count of rollover_hour:00 UTC boundaries in (entry_ts, exit_ts] — how many nights
    the position was held across the daily rollover mark.
    """
    if exit_ts <= entry_ts:
        return 0

    first = entry_ts.replace(hour=rollover_hour, minute=0, second=0, microsecond=0)
    if first <= entry_ts:
        first += timedelta(days=1)

    count = 0
    cur = first
    while cur < exit_ts:
        count += 1
        cur += timedelta(days=1)
    return count


def rollover_cost_pips(
    cost_cfg: dict,
    direction: str,
    entry_ts: datetime,
    exit_ts: datetime,
    rollover_hour: int = ROLLOVER_HOUR_UTC,
) -> float:
    """Total rollover cost in pips (sign encodes cost vs credit) for the held period."""
    nights = rollover_crossings(entry_ts, exit_ts, rollover_hour)
    rate = cost_cfg["rollover_pips_long"] if direction == "long" else cost_cfg["rollover_pips_short"]
    return rate * nights
