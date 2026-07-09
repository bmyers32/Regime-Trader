"""
One-time historical candle-store builder (TRADING-RULES §5.2: >=2yr real market data
per pair per playbook is required before any backtest counts as validation, not a
signal CSV). Populates instance/candle_cache/ via the SAME DataProvider/CandleCache/
CandleFetcher stack the live loop will use in Phase 8 (Prime Directive 7) — this is a
CLI driver for DataProvider.fetch_history(), not a bespoke one-off parser.

Read-only against OANDA: InstrumentsCandles (paginated internally by CandleFetcher)
plus one AccountInstruments call for displayPrecision. No orders, no account
mutation. complete==True filtering happens inside CandleFetcher, same as every other
caller — this script does not touch that filter.

Standing rule (HANDOFF.md): run this from a PythonAnywhere console, not this local
machine — a TLS cert-verification failure recurred locally across two networks and
was never root-caused. The script has no environment-specific logic; only the
runtime host differs. After running, instance/candle_cache/*.parquet needs to be
copied to the same relative path on whichever machine runs the backtest/validation
harness.

Fetches both configured timeframes (defaults.timeframe_htf / timeframe_ltf) for every
instrument under instruments.yaml's `instruments:` key, calibrated or not — validation
work needs history for a pair regardless of its `calibrated` flag; `enabled` gates live
trading only (TRADING-RULES §4.9), not backtest data availability.

Usage (from PA, project root, venv active):
    PYTHONPATH=. python scripts/fetch_history.py
"""

from __future__ import annotations

from pathlib import Path

import yaml
from oandapyV20 import API

import config
from bot.data.cache import CandleCache
from bot.data.fetcher import CandleFetcher
from bot.data.precision import PrecisionRegistry
from bot.data.provider import DataProvider

_CACHE_DIR = Path(__file__).resolve().parent.parent / "instance" / "candle_cache"
_INSTRUMENTS_YAML = Path(__file__).resolve().parent.parent / "bot" / "config" / "instruments.yaml"


def main() -> None:
    with open(_INSTRUMENTS_YAML) as f:
        raw_config = yaml.safe_load(f)

    instrument_names = list(raw_config["instruments"].keys())
    defaults = raw_config.get("defaults", {})
    granularities = sorted({defaults["timeframe_htf"], defaults["timeframe_ltf"]})

    api = API(access_token=config.OANDA_ACCESS_TOKEN, environment=config.OANDA_ENVIRONMENT)
    fetcher = CandleFetcher(api)
    cache = CandleCache(_CACHE_DIR)
    precision = PrecisionRegistry(api, config.OANDA_ACCOUNT_ID, instrument_names)
    provider = DataProvider(fetcher, cache, precision, raw_config)

    print(f"history_years={defaults.get('history_years', 2)}  granularities={granularities}")
    print(f"cache_dir={_CACHE_DIR}")

    empty: list[str] = []
    for instrument in instrument_names:
        for granularity in granularities:
            print(f"Fetching {instrument} {granularity} ...", flush=True)
            provider.fetch_history(instrument, granularity)
            df = cache.load(instrument, granularity)
            n = 0 if df is None else len(df)
            if n == 0:
                empty.append(f"{instrument}/{granularity}")
                print(f"  {instrument} {granularity}: EMPTY")
            else:
                print(f"  {instrument} {granularity}: {n} candles, {df['time'].min()} -> {df['time'].max()}")

    if empty:
        print(f"WARNING: no candles returned for: {empty}")


if __name__ == "__main__":
    main()
