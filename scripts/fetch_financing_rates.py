"""
Financing-rate fetcher — seeds instruments.yaml's cost_model.rollover_pips_per_day
(Phase 4, addressing TRADING-RULES §5.2's rollover-cost requirement).

Read-only against OANDA: a single AccountInstruments GET, no orders, no state
mutation. OANDA's v20 API returns each instrument's financing block as an ANNUALIZED
rate (e.g. financing.longRate = "-0.0075" means -0.75%/year), applied daily against
position notional value. This script converts that annualized rate into a per-day
pip figure so it drops directly into rollover_pips_per_day.long/short.

Conversion, per unit of the pair traded:
    daily_rate = annual_rate / 365
    notional_price = current mid price (base currency amount per 1 unit quote... for
        a BASE_QUOTE pair, 1 unit's notional value in quote currency IS the price)
    daily_cost_in_quote_ccy = price * daily_rate
    daily_cost_in_pips = daily_cost_in_quote_ccy / pip_size(instrument)

Known simplifications (documented, not hidden):
  - OANDA triple-charges financing on Wednesdays to account for weekend rollover
    (T+2 settlement) — this script emits a single uniform daily_rate/365 figure and
    does NOT apply the Wednesday multiplier. bot.backtest.costs.rollover_crossings()
    counts EVERY calendar-day boundary uniformly instead (including weekends), which
    nets out to the same total weekly cost as OANDA's lump-on-Wednesday convention,
    just distributed evenly rather than spiked midweek.
  - This script fetches OANDA's CURRENT rate at run time and that single value is
    then used as a constant across the entire historical backtest window — real
    financing rates drift with central-bank policy over a multi-year backtest period.
    See the LIMITATION note in each instrument's cost_model.calibration_note.
If Phase 11 forward-vs-backtest divergence implicates rollover specifically, revisit
both simplifications together (ROADMAP.md).

Usage:
    python scripts/fetch_financing_rates.py

Prints the computed rollover_pips_per_day for each configured instrument; paste the
values into instruments.yaml manually (kept manual and reviewed, not auto-written,
per this repo's "tuning lives in config, changed deliberately" convention — same
reason scripts/sample_spreads.py appends to a CSV rather than writing yaml directly).
"""

from __future__ import annotations

from oandapyV20 import API
from oandapyV20.endpoints.accounts import AccountInstruments
from oandapyV20.endpoints.pricing import PricingInfo

import config
from bot.backtest.sizing import pip_size

_DAYS_PER_YEAR = 365


def fetch_annualized_rates(instruments: list[str]) -> dict[str, dict[str, float]]:
    """Returns {instrument: {"longRate": float, "shortRate": float}} from OANDA."""
    api = API(access_token=config.OANDA_ACCESS_TOKEN, environment=config.OANDA_ENVIRONMENT)
    params = {"instruments": ",".join(instruments)}
    r = AccountInstruments(accountID=config.OANDA_ACCOUNT_ID, params=params)
    api.request(r)

    rates = {}
    for entry in r.response["instruments"]:
        financing = entry.get("financing")
        if financing is None:
            continue
        rates[entry["name"]] = {
            "longRate": float(financing["longRate"]),
            "shortRate": float(financing["shortRate"]),
        }
    return rates


def fetch_mid_prices(instruments: list[str]) -> dict[str, float]:
    api = API(access_token=config.OANDA_ACCESS_TOKEN, environment=config.OANDA_ENVIRONMENT)
    params = {"instruments": ",".join(instruments)}
    r = PricingInfo(accountID=config.OANDA_ACCOUNT_ID, params=params)
    api.request(r)

    prices = {}
    for entry in r.response.get("prices", []):
        bid = float(entry["bids"][0]["price"])
        ask = float(entry["asks"][0]["price"])
        prices[entry["instrument"]] = (bid + ask) / 2.0
    return prices


def annualized_rate_to_daily_pips(annual_rate: float, price: float, instrument: str) -> float:
    daily_rate = annual_rate / _DAYS_PER_YEAR
    daily_cost_in_quote_ccy = price * daily_rate
    return daily_cost_in_quote_ccy / pip_size(instrument)


def compute_rollover_pips_per_day(instruments: list[str]) -> dict[str, dict[str, float]]:
    rates = fetch_annualized_rates(instruments)
    prices = fetch_mid_prices(instruments)

    result = {}
    for instrument in instruments:
        if instrument not in rates or instrument not in prices:
            continue
        price = prices[instrument]
        result[instrument] = {
            "long": round(annualized_rate_to_daily_pips(rates[instrument]["longRate"], price, instrument), 5),
            "short": round(annualized_rate_to_daily_pips(rates[instrument]["shortRate"], price, instrument), 5),
        }
    return result


if __name__ == "__main__":
    instrument_names = list(config.INSTRUMENTS.keys())
    computed = compute_rollover_pips_per_day(instrument_names)
    for instrument, per_day in computed.items():
        print(f"{instrument}: rollover_pips_per_day: long={per_day['long']}, short={per_day['short']}")
    missing = set(instrument_names) - set(computed)
    if missing:
        print(f"WARNING: no financing/pricing data returned for: {sorted(missing)}")
