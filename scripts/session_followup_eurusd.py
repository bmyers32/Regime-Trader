"""
Pre-registered completion of the session-preference experiment (Phase 6 close-out,
2026-07-10) -- NOT a parameter retune. TRADING-RULES §3.2 itself says "prefer
London/NY; Asian-session behavior is per-pair calibration, not assumption." The
kickoff left session out of range_reversion.py entirely so the empirical funnel/
attribution could answer it rather than the strategy assuming it. Exhibit 1
(scripts/gross_vs_net.py) found EUR_USD's losses concentrated in the Asian session
(asian net_pnl=-434.33 vs. london+ny_overlap combined net_pnl=+80.13, out of an
overall net_pnl=-354.20) -- meeting the pre-registered trigger ("losses materially
concentrated in Asian entries") for exactly the one follow-up run promised before
seeing the data. EUR_GBP's losses were concentrated in ny_overlap instead (NOT
Asian), so it does not meet the trigger and gets no follow-up -- its FAIL stays
closed as already recorded.

Implementation: reuses the EXISTING entry_blackout_hours_utc mechanism
(bot.backtest.costs.entry_blackout_ok, the same backtest/live gate already used
for the rollover-hour spread blowout) to exclude all Asian-session UTC hours
(everything outside London 07-11 and NY-overlap 12-20, i.e. 21-23 + 00-06) for
THIS RUN ONLY -- instruments.yaml's cost_model on disk is untouched. No strategy
code changed, no entry_threshold/score_weights/sl_atr_mult retuning -- this is
purely a session-of-day entry filter, exactly matching §3.2's own preference
clause, run once as pre-registered.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_validation_gates as rvg  # noqa: E402

_ASIAN_HOURS_UTC = [21, 22, 23, 0, 1, 2, 3, 4, 5, 6]

if __name__ == "__main__":
    raw = rvg._load_raw_config()
    base_cost_model = raw["instruments"]["EUR_USD"]["cost_model"]
    london_ny_only_cost_model = copy.deepcopy(base_cost_model)
    london_ny_only_cost_model["entry_blackout_hours_utc"] = _ASIAN_HOURS_UTC

    print(f"[EUR_USD/range_reversion] London/NY-only follow-up: entry_blackout_hours_utc={_ASIAN_HOURS_UTC}")
    result = rvg.run_gates_for_pair("EUR_USD", "range_reversion", cost_model_override=london_ny_only_cost_model)

    print()
    print("=" * 78)
    from bot.backtest.gate_report import render_text

    print(render_text(result["report"]))
    print("=" * 78)
