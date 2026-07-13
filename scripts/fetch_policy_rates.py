"""
Historical policy-rate fetcher -- seeds calibration/rates/*.parquet with real
central-bank policy-rate (or best-available proxy) history for the carry-with-
regime-conditioning hearing (TRADING-RULES §6 slot 2). See HANDOFF.md for the full
signal-source resolution and the four amendments this script implements.

Source: FRED (St. Louis Fed) REST API, one integration for all five currencies
(amendment: FRED-only, HANDOFF.md). Requires a free API key
(fredaccount.stlouisfed.org/apikeys) in FRED_API_KEY.

Unlike scripts/fetch_financing_rates.py (a handful of scalars, kept manual/pasted into
YAML by design), this fetcher AUTO-WRITES its output -- the object here is a full
multi-year time series, not a handful of numbers for human review, so it follows
scripts/fetch_history.py's auto-cache convention instead.

The output is COMMITTED to git (calibration/rates/, not instance/) -- amendment 3,
HANDOFF.md: this hearing's evidence must be reproducible on a fresh clone without
re-hitting FRED or trusting whichever machine fetched it. Re-running this script is a
deliberate, committed act (e.g. a future §6 renewal re-pinning a fresh snapshot), not
an automatic refresh -- nothing else in this repo calls it automatically.

Standing-rule note: unlike OANDA fetches, this is NOT necessarily PA-only -- FRED is a
generic public REST API, not proxied through oandapyV20's TLS stack. Try locally first;
if the local network intercepts financial-data domains (the TLS-interception precedent
behind the OANDA-on-PA-only rule), fall back to PA. Either way the output gets
committed, so the fetch machine doesn't matter downstream.

Usage:
    FRED_API_KEY=... python scripts/fetch_policy_rates.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

import config
from bot.data.rates import PolicyRateCache, apply_effective_date_shift

_CACHE_DIR = Path(__file__).resolve().parent.parent / "calibration" / "rates"

# Amendment: FRED-only signal source (HANDOFF.md) -- one series per currency, chosen
# per the tradeoffs recorded there (true daily policy rate where FRED has one, best
# available OECD-sourced proxy otherwise).
_SERIES_BY_CURRENCY = {
    "USD": "DFF",                # Effective Fed Funds Rate, daily
    "EUR": "ECBDFR",              # ECB Deposit Facility Rate, daily
    "GBP": "IUDSOIA",             # SONIA, daily (proxy -- FRED has no live official Bank Rate series)
    "JPY": "IRSTCB01JPM156N",     # OECD Central Bank Rate for Japan, monthly (proxy)
    "AUD": "IRSTCI01AUM156N",     # OECD interbank/call-money rate for Australia, monthly (proxy)
}

_FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"

# Fetch depth: matches instruments.yaml's defaults.history_years (2) plus a buffer so
# the earliest D-bars in a 2yr backtest window still have a rate observation on or
# before them (no left-edge NaN from rate_asof's backward-only merge).
_HISTORY_YEARS_BUFFER = 2.5


def fetch_series(series_id: str, api_key: str, observation_start: str) -> pd.DataFrame:
    """Return {date, rate} for one FRED series_id, real-time values (no ALFRED vintage)."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": observation_start,
    }
    resp = requests.get(_FRED_OBSERVATIONS_URL, params=params, timeout=30)
    resp.raise_for_status()
    observations = resp.json()["observations"]

    rows = [
        {"date": pd.Timestamp(o["date"], tz="UTC"), "rate": float(o["value"])}
        for o in observations
        if o["value"] != "."  # FRED's own missing-observation sentinel
    ]
    return pd.DataFrame(rows)


def main() -> None:
    api_key = config.FRED_API_KEY
    if not api_key:
        raise RuntimeError(
            "FRED_API_KEY is not set. Register a free key at "
            "fredaccount.stlouisfed.org/apikeys and add it to .env."
        )
    observation_start = (
        datetime.now(timezone.utc) - pd.Timedelta(days=int(365 * _HISTORY_YEARS_BUFFER))
    ).strftime("%Y-%m-%d")

    cache = PolicyRateCache(_CACHE_DIR)
    fetched_at = datetime.now(timezone.utc).isoformat()

    print(f"observation_start={observation_start}  cache_dir={_CACHE_DIR}")

    empty: list[str] = []
    for currency, series_id in _SERIES_BY_CURRENCY.items():
        print(f"Fetching {currency} ({series_id}) ...", flush=True)
        raw = fetch_series(series_id, api_key, observation_start)
        if raw.empty:
            empty.append(currency)
            print(f"  {currency}: EMPTY -- check series_id / API key / date range")
            continue
        shifted = apply_effective_date_shift(raw, currency)
        cache.save(currency, shifted)
        print(
            f"  {currency}: {len(shifted)} observations, "
            f"{shifted['date'].min()} -> {shifted['date'].max()}"
        )

    if empty:
        print(f"WARNING: no observations returned for: {empty}")

    stamp_path = _CACHE_DIR / "fetched_at.txt"
    stamp_path.write_text(fetched_at)
    print(f"fetch complete, stamped {fetched_at} -> {stamp_path}")


if __name__ == "__main__":
    main()
