"""
Phase 4 — cost model tests (bot/backtest/costs.py).

Exit criteria verified here:
  EC-1  session bucketing covers all 24 UTC hours with no gaps, matching HANDOFF's
        documented boundaries (asian 21-07, london 07-12, ny_overlap 12-21)
  EC-2  spread gate refuses when session spread exceeds max_spread_pips
  EC-3  entry cost is adverse to the trader in both directions (half-spread + slippage)
  EC-4  exit cost: TP has half-spread only (no slippage); SL has slippage; SL slippage
        doubles when exit_regime == EXPANSION
  EC-5  rollover accrues once per UTC-day boundary crossed, zero for same-day round trips
  EC-6  ZERO_COST_MODEL produces no adverse adjustment anywhere
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bot.backtest.costs import (
    ZERO_COST_MODEL,
    apply_entry_cost,
    apply_exit_cost,
    current_spread_pips,
    rollover_cost_pips,
    rollover_crossings,
    session_for_hour,
    spread_gate_ok,
)


def _ts(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


_CFG = {
    "spread_pips": {"asian": 3.0, "london": 1.0, "ny_overlap": 1.5},
    "max_spread_pips": 2.0,
    "slippage_pips": 0.5,
    "rollover_pips_long": -0.3,
    "rollover_pips_short": 0.1,
}


# ---------------------------------------------------------------------------
# EC-1 session bucketing — full 24h coverage, no gaps
# ---------------------------------------------------------------------------

def test_session_bucketing_covers_all_hours():
    expected = {}
    for h in range(24):
        if 7 <= h < 12:
            expected[h] = "london"
        elif 12 <= h < 21:
            expected[h] = "ny_overlap"
        else:
            expected[h] = "asian"

    for h in range(24):
        assert session_for_hour(h) == expected[h]


# ---------------------------------------------------------------------------
# EC-2 spread gate
# ---------------------------------------------------------------------------

def test_spread_gate_ok_under_threshold():
    # london bucket = 1.0 pips, max = 2.0 -> ok
    assert spread_gate_ok(_CFG, _ts(2024, 1, 1, 9)) is True


def test_spread_gate_refuses_over_threshold():
    # asian bucket = 3.0 pips, max = 2.0 -> refused
    assert spread_gate_ok(_CFG, _ts(2024, 1, 1, 2)) is False


def test_current_spread_pips_by_session():
    assert current_spread_pips(_CFG, _ts(2024, 1, 1, 2)) == pytest.approx(3.0)   # asian
    assert current_spread_pips(_CFG, _ts(2024, 1, 1, 9)) == pytest.approx(1.0)   # london
    assert current_spread_pips(_CFG, _ts(2024, 1, 1, 15)) == pytest.approx(1.5)  # ny_overlap


# ---------------------------------------------------------------------------
# EC-3 entry cost is adverse
# ---------------------------------------------------------------------------

def test_entry_cost_adverse_long():
    mid = 1.1000
    filled = apply_entry_cost(mid, "long", "EUR_USD", _CFG, _ts(2024, 1, 1, 9))
    # london spread=1.0 pip -> half=0.5 pip=0.00005; slippage=0.5 pip=0.00005; total=0.0001
    assert filled == pytest.approx(mid + 0.0001)
    assert filled > mid


def test_entry_cost_adverse_short():
    mid = 1.1000
    filled = apply_entry_cost(mid, "short", "EUR_USD", _CFG, _ts(2024, 1, 1, 9))
    assert filled == pytest.approx(mid - 0.0001)
    assert filled < mid


# ---------------------------------------------------------------------------
# EC-4 exit cost: TP vs SL, EXPANSION doubling
# ---------------------------------------------------------------------------

def test_exit_cost_tp_no_slippage():
    mid = 1.1000
    filled = apply_exit_cost(mid, "long", "EUR_USD", _CFG, _ts(2024, 1, 1, 9), "tp", exit_regime="RANGING")
    # half-spread only: 0.5 pip = 0.00005
    assert filled == pytest.approx(mid - 0.00005)


def test_exit_cost_sl_has_slippage():
    mid = 1.1000
    filled = apply_exit_cost(mid, "long", "EUR_USD", _CFG, _ts(2024, 1, 1, 9), "sl", exit_regime="RANGING")
    # half-spread 0.00005 + slippage 0.00005 = 0.0001
    assert filled == pytest.approx(mid - 0.0001)


def test_exit_cost_sl_doubles_slippage_on_expansion():
    mid = 1.1000
    filled = apply_exit_cost(mid, "long", "EUR_USD", _CFG, _ts(2024, 1, 1, 9), "sl", exit_regime="EXPANSION")
    # half-spread 0.00005 + doubled slippage 0.0001 = 0.00015
    assert filled == pytest.approx(mid - 0.00015)


def test_exit_cost_short_direction_reversed():
    mid = 1.1000
    filled_long = apply_exit_cost(mid, "long", "EUR_USD", _CFG, _ts(2024, 1, 1, 9), "sl", "RANGING")
    filled_short = apply_exit_cost(mid, "short", "EUR_USD", _CFG, _ts(2024, 1, 1, 9), "sl", "RANGING")
    assert filled_long < mid
    assert filled_short > mid


# ---------------------------------------------------------------------------
# EC-5 rollover
# ---------------------------------------------------------------------------

def test_rollover_zero_within_same_day_before_rollover_hour():
    entry = _ts(2024, 1, 1, 10)
    exit_ = _ts(2024, 1, 1, 20)
    assert rollover_crossings(entry, exit_) == 0


def test_rollover_one_crossing():
    entry = _ts(2024, 1, 1, 10)
    exit_ = _ts(2024, 1, 2, 10)
    assert rollover_crossings(entry, exit_) == 1


def test_rollover_multiple_crossings():
    entry = _ts(2024, 1, 1, 10)
    exit_ = _ts(2024, 1, 4, 10)
    assert rollover_crossings(entry, exit_) == 3


def test_rollover_cost_applies_correct_direction_rate():
    entry = _ts(2024, 1, 1, 10)
    exit_ = _ts(2024, 1, 2, 10)
    long_cost = rollover_cost_pips(_CFG, "long", entry, exit_)
    short_cost = rollover_cost_pips(_CFG, "short", entry, exit_)
    assert long_cost == pytest.approx(-0.3)
    assert short_cost == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# EC-6 zero-cost model
# ---------------------------------------------------------------------------

def test_zero_cost_model_no_adjustment():
    mid = 1.1000
    entry_long = apply_entry_cost(mid, "long", "EUR_USD", ZERO_COST_MODEL, _ts(2024, 1, 1, 9))
    entry_short = apply_entry_cost(mid, "short", "EUR_USD", ZERO_COST_MODEL, _ts(2024, 1, 1, 9))
    exit_tp = apply_exit_cost(mid, "long", "EUR_USD", ZERO_COST_MODEL, _ts(2024, 1, 1, 9), "tp", "RANGING")
    exit_sl = apply_exit_cost(mid, "long", "EUR_USD", ZERO_COST_MODEL, _ts(2024, 1, 1, 9), "sl", "EXPANSION")

    assert entry_long == pytest.approx(mid)
    assert entry_short == pytest.approx(mid)
    assert exit_tp == pytest.approx(mid)
    assert exit_sl == pytest.approx(mid)
    assert rollover_cost_pips(ZERO_COST_MODEL, "long", _ts(2024, 1, 1), _ts(2024, 1, 5)) == pytest.approx(0.0)
    assert spread_gate_ok(ZERO_COST_MODEL, _ts(2024, 1, 1, 2)) is True
