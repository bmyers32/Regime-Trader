"""
Position sizing: units = f(equity, risk_pct, stop_distance, pip_value) — Prime Directive 6.
Never fixed units.

This is the SINGLE implementation of the sizing formula. Phase 8's RiskManager imports
size_position() and layers caps/breakers/cooldowns on top of its output — it does not
reimplement the formula. Both the backtester (Phase 4) and the live loop (Phase 8) call
through here, so a sizing bug fixed once is fixed everywhere (Prime Directive 7).

Pip-value currency conversion has three cases, determined by comparing account_currency
against the instrument's base/quote currency codes (instrument name = "{BASE}_{QUOTE}"):

  1. quote == account_currency:  direct. A 1-pip move is already worth pip_size units of
     account currency per unit traded (e.g. EUR_USD, quote=USD, account=USD).

  2. base == account_currency:   self-conversion via the pair's OWN price. The pip value
     is quoted in the quote currency; dividing by the pair's current price converts it to
     the account (base) currency (e.g. USD_JPY, quote=JPY, account=USD: divide by the
     USD_JPY rate itself — no separate series needed).

  3. cross: neither leg matches the account currency (e.g. GBP_JPY with a USD account, or
     EUR_GBP with a USD account). Requires an auxiliary conversion series against the
     account currency (USD_JPY for GBP_JPY's JPY leg; GBP_USD for EUR_GBP's GBP leg).
     These pairs are already in the cached universe — DataProvider supplies the series,
     no new fetch code. There is NO static-rate fallback: if the required series is
     missing, or has no observation at-or-before the bar timestamp, size_position raises
     SizingError. Refuse to size rather than guess (mirrors TRADING-RULES §4.9's refusal
     pattern for uncalibrated pairs).

Conversion-pair orientation is not fixed (some real pairs list as ACCT_QUOTE, e.g.
USD_JPY; others list as QUOTE_ACCT, e.g. GBP_USD) — _find_conversion_pair() tries both
and applies the correct arithmetic for whichever orientation is available.

All rate lookups use the last known value AT OR BEFORE the bar timestamp (backward,
no lookahead) via binary search on the sorted 'time' column.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd


class SizingError(Exception):
    """Raised when position sizing cannot be computed correctly — never silently guessed."""


def pip_size(instrument: str) -> float:
    """0.01 for JPY-quoted pairs, 0.0001 otherwise."""
    _, quote = _split(instrument)
    return 0.01 if quote == "JPY" else 0.0001


def _split(instrument: str) -> tuple[str, str]:
    base, _, quote = instrument.partition("_")
    if not base or not quote:
        raise SizingError(f"Instrument name not in BASE_QUOTE form: {instrument!r}")
    return base, quote


def _rate_at_or_before(df: pd.DataFrame, ts: datetime) -> float | None:
    """Last 'close' value with time <= ts, via binary search (df sorted ascending)."""
    idx = df["time"].searchsorted(ts, side="right") - 1
    if idx < 0:
        return None
    return float(df["close"].iloc[idx])


def _find_conversion_pair(
    quote: str, account_currency: str, conversion_series: dict[str, pd.DataFrame]
) -> tuple[str, str]:
    """
    Returns (instrument_name, orientation). orientation is:
      'divide'   — pair is ACCT_QUOTE (e.g. USD_JPY): quote_amount / rate = acct_amount.
      'multiply' — pair is QUOTE_ACCT (e.g. GBP_USD): quote_amount * rate = acct_amount.
    Raises SizingError if neither orientation is available.
    """
    acct_quote = f"{account_currency}_{quote}"
    quote_acct = f"{quote}_{account_currency}"
    if acct_quote in conversion_series:
        return acct_quote, "divide"
    if quote_acct in conversion_series:
        return quote_acct, "multiply"
    raise SizingError(
        f"No conversion series for quote currency {quote!r} -> {account_currency!r}: "
        f"need one of {acct_quote!r} or {quote_acct!r} in conversion_series"
    )


def pip_value_per_unit(
    instrument: str,
    account_currency: str,
    price: float,
    bar_time: datetime,
    conversion_series: dict[str, pd.DataFrame] | None = None,
) -> float:
    """
    Value, in account currency, of a 1-pip move on 1 unit of instrument at bar_time.
    """
    base, quote = _split(instrument)
    size = pip_size(instrument)

    if quote == account_currency:
        return size

    if base == account_currency:
        if price <= 0:
            raise SizingError(f"Non-positive price for self-conversion of {instrument!r}: {price}")
        return size / price

    conversion_series = conversion_series or {}
    conv_instrument, orientation = _find_conversion_pair(quote, account_currency, conversion_series)
    rate = _rate_at_or_before(conversion_series[conv_instrument], bar_time)
    if rate is None:
        raise SizingError(
            f"No {conv_instrument} rate at or before {bar_time} to size {instrument!r}"
        )
    if orientation == "divide":
        if rate <= 0:
            raise SizingError(f"Non-positive conversion rate for {conv_instrument!r}: {rate}")
        return size / rate
    return size * rate


def size_position(
    equity: float,
    risk_pct: float,
    stop_distance: float,
    instrument: str,
    account_currency: str,
    price: float,
    bar_time: datetime,
    conversion_series: dict[str, pd.DataFrame] | None = None,
) -> float:
    """
    units = risk_amount / (stop_distance_in_pips * pip_value_per_unit)

    stop_distance: |entry - sl| in price terms (must be positive).
    Raises SizingError for non-positive equity/risk_pct/stop_distance or unresolvable
    pip-value conversion — never returns a fixed/fallback unit count.
    """
    if equity <= 0:
        raise SizingError(f"Non-positive equity: {equity}")
    if risk_pct <= 0:
        raise SizingError(f"Non-positive risk_pct: {risk_pct}")
    if stop_distance <= 0:
        raise SizingError(f"Non-positive stop_distance: {stop_distance}")

    p_size = pip_size(instrument)
    stop_distance_pips = stop_distance / p_size
    pv = pip_value_per_unit(instrument, account_currency, price, bar_time, conversion_series)
    risk_amount = equity * (risk_pct / 100.0)

    return risk_amount / (stop_distance_pips * pv)
