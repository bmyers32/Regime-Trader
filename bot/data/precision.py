"""
Precision registry: fetches displayPrecision from OANDA once at startup and
provides the single rounding / wire-formatting functions for all outgoing prices.

TRADING-RULES §1.4: precision fetched from OANDA at startup; never hardcoded;
one rounding function for all outgoing prices.

Phase 8 construction order:
    precision = PrecisionRegistry(api, account_id, instrument_names)
"""

from __future__ import annotations

from oandapyV20 import API
from oandapyV20.endpoints.accounts import AccountInstruments


class PrecisionRegistry:
    """
    Maps each instrument to its OANDA displayPrecision (decimal places).

    After construction the registry is immutable for the session lifetime.
    Both methods raise KeyError for unknown instruments — silent precision
    errors would corrupt order payloads (TRADING-RULES §1.4).
    """

    def __init__(self, api: API, account_id: str, instrument_names: list[str]) -> None:
        params = {"instruments": ",".join(instrument_names)}
        r = AccountInstruments(accountID=account_id, params=params)
        api.request(r)
        self._precision: dict[str, int] = {
            inst["name"]: int(inst["displayPrecision"])
            for inst in r.response["instruments"]
        }

    def round_price(self, instrument: str, price: float) -> float:
        """Round price to instrument's displayPrecision. Raises KeyError for unknown instruments."""
        dp = self._precision[instrument]
        return round(price, dp)

    def format_price(self, instrument: str, price: float) -> str:
        """
        Format price as wire-format string for OANDA order payloads (Phase 8).
        Uses f-string precision matching displayPrecision exactly.
        Raises KeyError for unknown instruments.
        """
        dp = self._precision[instrument]
        return f"{price:.{dp}f}"
