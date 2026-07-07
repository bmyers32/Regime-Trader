"""
Standalone spread sampler — seeds instruments.yaml's cost_model.spread_pips (Phase 4).

Read-only against OANDA: a single PricingInfo GET per sample, no orders, no state
mutation on the broker side. Run this as a PA Always-On Task (not a Tasks-tab
scheduled task — that UI only offers daily/hourly recurrence, which cannot express
the few-minutes cadence needed to densely cover all three session buckets
(asian/london/ny_overlap) in a day+) before filling in real cost_model values —
see TRADING-RULES §1.7: thresholds need an empirical basis, not published-typical
numbers.

Each sample appends one row per configured, enabled-or-not instrument to
instance/spread_samples.csv (gitignored, same as candle_cache/ and journal.db).
After a day+ of samples, aggregate by (instrument, session) — e.g. median spread —
and write those values into instruments.yaml's cost_model.spread_pips blocks.

Usage (Always-On Task, runs until PA stops it):
    python scripts/sample_spreads.py

Usage (single one-shot sample, e.g. manual check):
    python scripts/sample_spreads.py --once

After Phase 8 ships, Order.spread_at_entry in the journal becomes the ongoing
recalibration source instead of this script.
"""

from __future__ import annotations

import csv
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from oandapyV20 import API
from oandapyV20.endpoints.pricing import PricingInfo

import config
from bot.backtest.costs import session_for_hour
from bot.backtest.sizing import pip_size

_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "instance" / "spread_samples.csv"
_FIELDNAMES = ["timestamp_utc", "instrument", "session", "bid", "ask", "spread_pips"]
_SAMPLE_INTERVAL_SECONDS = 150  # ~2-3min cadence; PA Tasks-tab scheduling can't go finer than hourly


def sample_once(instruments: list[str]) -> list[dict]:
    api = API(access_token=config.OANDA_ACCESS_TOKEN, environment=config.OANDA_ENVIRONMENT)
    params = {"instruments": ",".join(instruments)}
    r = PricingInfo(accountID=config.OANDA_ACCOUNT_ID, params=params)
    api.request(r)

    now = datetime.now(timezone.utc)
    session = session_for_hour(now.hour)
    rows = []
    for entry in r.response.get("prices", []):
        instrument = entry["instrument"]
        bid = float(entry["bids"][0]["price"])
        ask = float(entry["asks"][0]["price"])
        spread_pips = (ask - bid) / pip_size(instrument)
        rows.append(
            {
                "timestamp_utc": now.isoformat(),
                "instrument": instrument,
                "session": session,
                "bid": bid,
                "ask": ask,
                "spread_pips": round(spread_pips, 2),
            }
        )
    return rows


def append_rows(rows: list[dict]) -> None:
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not _OUTPUT_PATH.exists()
    with open(_OUTPUT_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def run_loop(instrument_names: list[str], interval_seconds: int) -> None:
    # Runs until PA kills the Always-On Task; one bad request must not end the
    # whole task, so errors are logged and the loop continues on the next tick.
    while True:
        try:
            rows = sample_once(instrument_names)
            append_rows(rows)
            print(f"[{datetime.now(timezone.utc).isoformat()}] appended {len(rows)} rows", flush=True)
        except Exception:
            print(f"[{datetime.now(timezone.utc).isoformat()}] sample failed:", flush=True)
            traceback.print_exc()
        time.sleep(interval_seconds)


if __name__ == "__main__":
    instrument_names = list(config.INSTRUMENTS.keys())
    if "--once" in sys.argv:
        sampled = sample_once(instrument_names)
        append_rows(sampled)
        print(f"Appended {len(sampled)} spread samples to {_OUTPUT_PATH}")
    else:
        run_loop(instrument_names, _SAMPLE_INTERVAL_SECONDS)
