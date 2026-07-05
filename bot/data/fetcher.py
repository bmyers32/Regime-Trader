"""
Candle fetcher: wraps oandapyV20 InstrumentsCandles.

TRADING-RULES §1.5: complete==True enforced here — no forming candle ever
escapes this layer, regardless of what callers request.
TRADING-RULES §1.12: supports incremental fetch via from_dt to avoid full
re-fetches on every cycle.

OANDA caps responses at 5000 candles per request. For large ranges (e.g.,
H1 2yr ≈ 17k candles) the fetcher paginates transparently.

Phase 8 construction order:
    fetcher = CandleFetcher(api)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from oandapyV20 import API
from oandapyV20.endpoints.instruments import InstrumentsCandles

_MAX_PER_REQUEST = 5000
_OANDA_RFC3339 = "%Y-%m-%dT%H:%M:%S.000000000Z"


def _to_rfc3339(dt: datetime) -> str:
    """Convert aware UTC datetime to OANDA RFC3339 string."""
    return dt.astimezone(timezone.utc).strftime(_OANDA_RFC3339)


def _parse_response(r: InstrumentsCandles) -> pd.DataFrame:
    """Parse raw oandapyV20 candle list into a typed DataFrame."""
    rows = []
    for c in r.response.get("candles", []):
        mid = c["mid"]
        rows.append(
            {
                "time": pd.Timestamp(c["time"]).tz_convert("UTC"),
                "open": float(mid["o"]),
                "high": float(mid["h"]),
                "low": float(mid["l"]),
                "close": float(mid["c"]),
                "volume": int(c["volume"]),
                "complete": bool(c["complete"]),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df[df["complete"]].reset_index(drop=True)
    return df


class CandleFetcher:
    """
    Fetches complete candles from OANDA, paginating transparently when the
    requested range exceeds 5000 candles.

    Returns a DataFrame with columns:
        time (UTC Timestamp), open, high, low, close (float),
        volume (int), complete (bool — always True in returned rows).
    """

    def __init__(self, api: API) -> None:
        self._api = api

    def fetch(
        self,
        instrument: str,
        granularity: str,
        count: int | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> pd.DataFrame:
        """
        Fetch complete candles. Provide either `count` OR `from_dt` (+ optional `to_dt`).

        Args:
            instrument:  e.g. "GBP_JPY"
            granularity: e.g. "H4", "H1", "M15"
            count:       number of most-recent candles (used when no cache exists)
            from_dt:     inclusive start for incremental fetch (UTC-aware)
            to_dt:       exclusive end for incremental fetch (UTC-aware, default=now)
        """
        if count is not None:
            return self._fetch_by_count(instrument, granularity, count)
        if from_dt is not None:
            return self._fetch_by_range(instrument, granularity, from_dt, to_dt)
        raise ValueError("Provide either count or from_dt")

    def _fetch_by_count(self, instrument: str, granularity: str, count: int) -> pd.DataFrame:
        """Fetch `count` most-recent candles, paginating if count > 5000."""
        if count <= _MAX_PER_REQUEST:
            params = {"granularity": granularity, "count": count, "price": "M"}
            r = InstrumentsCandles(instrument=instrument, params=params)
            self._api.request(r)
            return _parse_response(r)

        # Paginate: fetch in chunks of MAX, working backwards is awkward — work forward
        # by converting to a range: fetch count candles ending at now.
        # Simplest: make multiple count-capped requests and concat.
        chunks = []
        remaining = count
        # Fetch the oldest chunk first using to_dt chaining would require known start time.
        # Instead: fetch up to MAX at a time using `count` param, accumulating from the end.
        # OANDA `count` always returns the N most-recent closed candles when no from/to given.
        # To get older data, fetch by range. Here we use a heuristic: treat as range fetch
        # from (now - count * granularity_seconds) to now.
        # Delegate to _fetch_by_range with a computed start.
        import math
        from datetime import timedelta

        granularity_minutes = _granularity_to_minutes(granularity)
        start_dt = datetime.now(timezone.utc) - timedelta(
            minutes=math.ceil(count * granularity_minutes * 1.05)  # 5% buffer for gaps/weekends
        )
        return self._fetch_by_range(instrument, granularity, start_dt)

    def _fetch_by_range(
        self,
        instrument: str,
        granularity: str,
        from_dt: datetime,
        to_dt: datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch all complete candles in [from_dt, to_dt), paginating as needed."""
        chunks: list[pd.DataFrame] = []
        current_from = from_dt

        while True:
            params: dict = {
                "granularity": granularity,
                "from": _to_rfc3339(current_from),
                "count": _MAX_PER_REQUEST,
                "price": "M",
            }
            if to_dt is not None:
                params["to"] = _to_rfc3339(to_dt)

            r = InstrumentsCandles(instrument=instrument, params=params)
            self._api.request(r)
            chunk = _parse_response(r)

            if chunk.empty:
                break

            chunks.append(chunk)

            # If we got fewer than MAX, we've reached the end of available data
            raw_count = len(r.response.get("candles", []))
            if raw_count < _MAX_PER_REQUEST:
                break

            # Advance: next page starts from the candle after the last one returned
            last_ts = chunk["time"].iloc[-1]
            next_from = last_ts.to_pydatetime() + _granularity_to_timedelta(granularity)
            if to_dt is not None and next_from >= to_dt:
                break
            current_from = next_from

        if not chunks:
            return pd.DataFrame(
                columns=["time", "open", "high", "low", "close", "volume", "complete"]
            )

        result = pd.concat(chunks, ignore_index=True)
        result = result.drop_duplicates(subset="time", keep="last").reset_index(drop=True)
        return result


def _granularity_to_minutes(granularity: str) -> int:
    _MAP = {
        "M1": 1, "M5": 5, "M10": 10, "M15": 15, "M30": 30,
        "H1": 60, "H2": 120, "H3": 180, "H4": 240, "H6": 360,
        "H8": 480, "H12": 720, "D": 1440, "W": 10080, "M": 43200,
    }
    if granularity not in _MAP:
        raise ValueError(f"Unknown granularity: {granularity!r}")
    return _MAP[granularity]


def _granularity_to_timedelta(granularity: str) -> "timedelta":
    from datetime import timedelta
    return timedelta(minutes=_granularity_to_minutes(granularity))
