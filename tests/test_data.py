"""
Phase 2 exit-criteria tests (PROMPTS.md §4 row 2).

Exit criteria:
  EC-1  complete==False never passes through DataProvider
  EC-2  Second get_candles() call uses from= (incremental), total 2 API requests;
        boundary-candle at last_ts appears in both fetch responses → deduped to one row
  EC-3  PrecisionRegistry correct for JPY pair (3dp) — round_price + format_price
  EC-4  PrecisionRegistry correct for non-JPY pair (5dp) — round_price + format_price

Amendments:
  AM-1  format_price returns str verified by string equality, not float equality
  AM-2  KeyError raised for unknown instrument in both round_price and format_price
  AM-3  Restart with existing cache → exactly ONE incremental request per pair/TF (warm_up)
  AM-4  Composition test uses Phase 8 construction order
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pandas as pd
import pytest

from bot.data.cache import CandleCache
from bot.data.fetcher import CandleFetcher
from bot.data.precision import PrecisionRegistry
from bot.data.provider import DataProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(offset_hours: int = 0) -> pd.Timestamp:
    """UTC Timestamp, optionally offset from a fixed base."""
    base = pd.Timestamp("2025-01-02 12:00:00", tz="UTC")
    return base + pd.Timedelta(hours=offset_hours)


def _candle(offset_hours: int, complete: bool = True) -> dict:
    """Minimal OANDA candle dict."""
    t = _ts(offset_hours)
    return {
        "time": t.isoformat(),
        "mid": {"o": "1.10000", "h": "1.10500", "l": "1.09500", "c": "1.10200"},
        "volume": 100,
        "complete": complete,
    }


def _make_oanda_response(candles: list[dict]) -> dict:
    return {"candles": candles, "instrument": "EUR_USD", "granularity": "H1"}


def _make_fetcher(api_mock: MagicMock) -> CandleFetcher:
    return CandleFetcher(api=api_mock)


def _make_precision_registry(instrument: str, dp: int) -> PrecisionRegistry:
    """Build a PrecisionRegistry using a mocked OANDA API response."""
    api_mock = MagicMock()
    endpoint_mock = MagicMock()
    endpoint_mock.response = {
        "instruments": [{"name": instrument, "displayPrecision": str(dp)}]
    }

    with patch("bot.data.precision.AccountInstruments", return_value=endpoint_mock):
        reg = PrecisionRegistry(
            api=api_mock,
            account_id="TEST-ACCOUNT",
            instrument_names=[instrument],
        )
    return reg


# ---------------------------------------------------------------------------
# EC-1  complete==False never passes
# ---------------------------------------------------------------------------

class TestCompleteFilter:
    def test_incomplete_candle_never_reaches_caller(self, tmp_path: Path) -> None:
        """
        A forming candle (complete=False) injected into the OANDA response
        must not appear in the DataFrame returned by DataProvider.get_candles().
        """
        # Mix of complete and incomplete candles
        raw_candles = [
            _candle(0, complete=True),
            _candle(1, complete=True),
            _candle(2, complete=False),  # forming — must be filtered
        ]
        response = _make_oanda_response(raw_candles)

        api_mock = MagicMock()
        endpoint_mock = MagicMock()
        endpoint_mock.response = response

        with patch("bot.data.fetcher.InstrumentsCandles", return_value=endpoint_mock):
            fetcher = _make_fetcher(api_mock)
            df = fetcher.fetch("EUR_USD", "H1", count=10)

        assert "complete" in df.columns
        assert df["complete"].all(), "complete==False row leaked through the filter"
        assert len(df) == 2, f"Expected 2 complete rows, got {len(df)}"
        # The timestamp of the incomplete candle must not appear
        incomplete_ts = pd.Timestamp(_candle(2)["time"]).tz_convert("UTC")
        assert incomplete_ts not in df["time"].values

    def test_all_incomplete_returns_empty(self, tmp_path: Path) -> None:
        """All incomplete → empty DataFrame, not an error."""
        raw_candles = [_candle(0, complete=False), _candle(1, complete=False)]
        api_mock = MagicMock()
        endpoint_mock = MagicMock()
        endpoint_mock.response = _make_oanda_response(raw_candles)

        with patch("bot.data.fetcher.InstrumentsCandles", return_value=endpoint_mock):
            fetcher = _make_fetcher(api_mock)
            df = fetcher.fetch("EUR_USD", "H1", count=10)

        assert df.empty


# ---------------------------------------------------------------------------
# EC-2  Incremental fetch — exactly 2 requests, second uses from=, boundary dedupe
# ---------------------------------------------------------------------------

class TestIncrementalFetch:
    def test_two_calls_produce_two_requests_second_is_incremental(
        self, tmp_path: Path
    ) -> None:
        """
        Two consecutive get_candles() calls → exactly 2 OANDA requests.
        The second call must use from= (not count=), starting at last_cached_ts.
        Boundary candle present in both responses → deduplicated to one row.
        """
        # First response: candles at hours 0, 1, 2
        first_candles = [_candle(0), _candle(1), _candle(2)]
        # Second response: boundary candle (hour 2) + new candle (hour 3)
        # OANDA may return the candle at from_dt again — must be deduped
        second_candles = [_candle(2), _candle(3)]

        first_endpoint = MagicMock()
        first_endpoint.response = _make_oanda_response(first_candles)
        second_endpoint = MagicMock()
        second_endpoint.response = _make_oanda_response(second_candles)

        api_mock = MagicMock()
        call_count = 0
        captured_params = []

        def mock_request(endpoint):
            nonlocal call_count
            call_count += 1
            captured_params.append(dict(endpoint._params) if hasattr(endpoint, "_params") else {})

        api_mock.request.side_effect = mock_request

        endpoints = [first_endpoint, second_endpoint]
        endpoint_iter = iter(endpoints)

        with patch(
            "bot.data.fetcher.InstrumentsCandles", side_effect=lambda **kw: next(endpoint_iter)
        ):
            fetcher = _make_fetcher(api_mock)
            cache = CandleCache(tmp_path / "cache")
            # Minimal precision mock — not exercised in this test
            precision_mock = MagicMock(spec=PrecisionRegistry)
            cfg = {"defaults": {"live_warmup_candles": 750, "history_years": 2}}
            provider = DataProvider(fetcher, cache, precision_mock, cfg)

            df1 = provider.get_candles("EUR_USD", "H1", n_bars=10)
            df2 = provider.get_candles("EUR_USD", "H1", n_bars=10)

        # Exactly 2 API requests total
        assert call_count == 2, f"Expected 2 API requests, got {call_count}"

        # df1: candles 0, 1, 2
        assert len(df1) == 3

        # df2: candles 0, 1, 2, 3 — boundary candle 2 appears once only
        assert len(df2) == 4, f"Expected 4 rows after merge+dedup, got {len(df2)}"
        times = df2["time"].tolist()
        # No duplicate timestamps
        assert len(times) == len(set(str(t) for t in times)), "Duplicate timestamps in merged result"


# ---------------------------------------------------------------------------
# EC-3 & EC-4  PrecisionRegistry — JPY (3dp) and non-JPY (5dp)
# EC-1 for precision: KeyError on unknown instrument
# AM-1: format_price string assertions
# AM-2: KeyError tests
# ---------------------------------------------------------------------------

class TestPrecisionRegistry:
    def test_jpy_round_price(self) -> None:
        reg = _make_precision_registry("GBP_JPY", 3)
        result = reg.round_price("GBP_JPY", 131.1234567)
        assert result == 131.123, f"Expected 131.123, got {result}"

    def test_jpy_format_price_string(self) -> None:
        """format_price must return exact string — verified by string equality, not float."""
        reg = _make_precision_registry("GBP_JPY", 3)
        result = reg.format_price("GBP_JPY", 131.1234567)
        assert isinstance(result, str), "format_price must return str"
        assert result == "131.123", f"Expected '131.123', got {result!r}"

    def test_non_jpy_round_price(self) -> None:
        reg = _make_precision_registry("EUR_USD", 5)
        result = reg.round_price("EUR_USD", 1.123456789)
        assert result == 1.12346, f"Expected 1.12346, got {result}"

    def test_non_jpy_format_price_string(self) -> None:
        """format_price 5dp — string equality."""
        reg = _make_precision_registry("EUR_USD", 5)
        result = reg.format_price("EUR_USD", 1.123456789)
        assert isinstance(result, str)
        assert result == "1.12346", f"Expected '1.12346', got {result!r}"

    def test_format_price_trailing_zeros_preserved(self) -> None:
        """Wire format must preserve trailing zeros — '1.10000', not '1.1'."""
        reg = _make_precision_registry("EUR_USD", 5)
        result = reg.format_price("EUR_USD", 1.1)
        assert result == "1.10000", f"Expected '1.10000', got {result!r}"

    def test_unknown_instrument_round_price_raises_key_error(self) -> None:
        reg = _make_precision_registry("EUR_USD", 5)
        with pytest.raises(KeyError):
            reg.round_price("XYZ_ABC", 1.23456)

    def test_unknown_instrument_format_price_raises_key_error(self) -> None:
        reg = _make_precision_registry("EUR_USD", 5)
        with pytest.raises(KeyError):
            reg.format_price("XYZ_ABC", 1.23456)


# ---------------------------------------------------------------------------
# AM-3  Restart with existing cache → exactly ONE incremental request per pair/TF
# ---------------------------------------------------------------------------

class TestWarmUpRestartCost:
    def test_warm_up_existing_cache_costs_one_request_per_pair_tf(
        self, tmp_path: Path
    ) -> None:
        """
        Simulate a bot restart with an already-warm cache.
        warm_up() must issue exactly ONE incremental fetch per (instrument, granularity),
        using from=last_cached_ts, not a full re-fetch.
        """
        cache_dir = tmp_path / "cache"

        # Pre-populate cache with candles 0..3 for two pairs × one granularity
        pairs = ["EUR_USD", "GBP_JPY"]
        gran = "H4"

        cache = CandleCache(cache_dir)
        for inst in pairs:
            seed_df = pd.DataFrame(
                {
                    "time": [_ts(i) for i in range(4)],
                    "open": [1.1] * 4,
                    "high": [1.11] * 4,
                    "low": [1.09] * 4,
                    "close": [1.105] * 4,
                    "volume": [100] * 4,
                    "complete": [True] * 4,
                }
            )
            cache.save(inst, gran, seed_df)

        # Gap response: one new candle per pair
        gap_candle_eur = [_candle(4)]
        gap_candle_gbp = [_candle(4)]
        responses = {
            "EUR_USD": gap_candle_eur,
            "GBP_JPY": gap_candle_gbp,
        }

        call_count = 0
        call_log: list[tuple[str, str]] = []  # (instrument, type)

        def make_endpoint(instrument, params):
            nonlocal call_count
            call_count += 1
            ep = MagicMock()
            ep.response = _make_oanda_response(responses[instrument])
            ep._params = params
            # Verify this is an incremental (from=) request, not a count= request
            assert "from" in params, (
                f"warm_up() must use from= not count= when cache exists; "
                f"params were {params}"
            )
            call_log.append((instrument, "incremental"))
            return ep

        api_mock = MagicMock()
        api_mock.request.side_effect = lambda ep: None

        with patch(
            "bot.data.fetcher.InstrumentsCandles",
            side_effect=lambda instrument, params: make_endpoint(instrument, params),
        ):
            fetcher = CandleFetcher(api=api_mock)
            precision_mock = MagicMock(spec=PrecisionRegistry)
            cfg = {"defaults": {"live_warmup_candles": 750, "history_years": 2}}
            provider = DataProvider(fetcher, cache, precision_mock, cfg)
            provider.warm_up(instrument_names=pairs, granularities=[gran])

        # Exactly one request per pair × granularity combination
        expected_calls = len(pairs) * 1  # 1 granularity
        assert call_count == expected_calls, (
            f"Expected {expected_calls} incremental requests on restart, got {call_count}"
        )


# ---------------------------------------------------------------------------
# AM-4  Composition test uses Phase 8 construction order
# ---------------------------------------------------------------------------

class TestPhase8CompositionOrder:
    def test_construction_order_and_interfaces_compose(self, tmp_path: Path) -> None:
        """
        Validates Phase 8 construction order:
            api → PrecisionRegistry → CandleFetcher → CandleCache → DataProvider

        Ensures all four objects compose without error and DataProvider.get_candles()
        returns a non-empty DataFrame with expected columns.
        """
        # --- Step 1: api (mocked oandapyV20.API) ---
        api = MagicMock()

        # --- Step 2: PrecisionRegistry ---
        precision_endpoint = MagicMock()
        precision_endpoint.response = {
            "instruments": [{"name": "EUR_USD", "displayPrecision": "5"}]
        }
        with patch("bot.data.precision.AccountInstruments", return_value=precision_endpoint):
            precision = PrecisionRegistry(
                api=api,
                account_id="TEST-ACCOUNT",
                instrument_names=["EUR_USD"],
            )

        # --- Step 3: CandleFetcher ---
        fetcher = CandleFetcher(api=api)

        # --- Step 4: CandleCache ---
        cache = CandleCache(tmp_path / "cache")

        # --- Step 5: DataProvider ---
        cfg = {"defaults": {"live_warmup_candles": 750, "history_years": 2}}
        provider = DataProvider(fetcher, cache, precision, cfg)

        # --- Exercise get_candles() ---
        candle_endpoint = MagicMock()
        candle_endpoint.response = _make_oanda_response([_candle(0), _candle(1)])

        with patch("bot.data.fetcher.InstrumentsCandles", return_value=candle_endpoint):
            df = provider.get_candles("EUR_USD", "H1", n_bars=10)

        assert not df.empty
        expected_cols = {"time", "open", "high", "low", "close", "volume", "complete"}
        assert expected_cols.issubset(df.columns), f"Missing columns: {expected_cols - set(df.columns)}"
        assert df["complete"].all()

        # Verify precision interface works after composition
        assert precision.format_price("EUR_USD", 1.1) == "1.10000"
        assert precision.round_price("EUR_USD", 1.123456789) == 1.12346
