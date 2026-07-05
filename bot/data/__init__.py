"""
bot.data — complete-candle fetch, disk cache, precision registry, and DataProvider.

Public surface:
    PrecisionRegistry  — displayPrecision from OANDA; round_price / format_price
    CandleFetcher      — oandapyV20 wrapper; enforces complete==True
    CandleCache        — parquet-backed disk cache (instance/candle_cache/)
    DataProvider       — orchestrates fetch+cache; always-incremental get_candles()
"""
from .cache import CandleCache
from .fetcher import CandleFetcher
from .precision import PrecisionRegistry
from .provider import DataProvider

__all__ = ["CandleCache", "CandleFetcher", "PrecisionRegistry", "DataProvider"]
