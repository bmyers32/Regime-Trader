# HANDOFF — 2026-07-04T23:00Z
Phase: 2 — Data Layer   Status: COMPLETE

Done this session:
- bot/data/__init__.py: public surface re-exports all four classes
- bot/data/precision.py: PrecisionRegistry fetches displayPrecision from AccountInstruments
  at construction; round_price() -> float, format_price() -> str (wire format for Phase 8 payloads);
  both raise KeyError for unknown instruments
- bot/data/fetcher.py: CandleFetcher wraps InstrumentsCandles; enforces complete==True in
  _parse_response() before any row escapes; transparent pagination for >5000-candle ranges;
  fetch(count=) for cold start, fetch(from_dt=) for incremental
- bot/data/cache.py: CandleCache parquet-backed, atomic write (tmp→rename), UTC timezone
  preservation on round-trip; last_complete_ts() drives incremental fetch
- bot/data/provider.py: DataProvider — every get_candles() makes exactly ONE incremental
  OANDA request (from=last_cached_ts); boundary-candle dedup on merge (drop_duplicates keep=last);
  warm_up() = read parquet + gap-fetch (one request per pair/TF); fetch_history() = one-time
  historical store builder, not called in live loop
- bot/config/instruments.yaml: added history_years: 2 and live_warmup_candles: 750 to defaults
- requirements.txt: added pyarrow==24.0.0, requests==2.34.2, certifi==2026.6.17,
  charset-normalizer==3.4.7, idna==3.18, urllib3==2.7.0 (oandapyV20 transitive deps)
- tests/test_data.py: 12 tests, all pass — EC-1 (complete filter, 2 tests), EC-2 (incremental
  two-call / boundary-dedup), EC-3/4 (precision JPY+non-JPY round+format), AM-1 (str equality),
  AM-2 (KeyError unknown), AM-3 (warm_up restart cost = 1 request/pair/TF), AM-4 (Phase 8
  construction order composition test)
- Total suite: 17/17 pass (12 Phase 2 + 5 Phase 1)
- Phase 2 ticked complete in CLAUDE.md

Not done / next action:
- Phase 3: Indicators + regime classifier
- Kickoff: load CLAUDE.md, TRADING-RULES.md, HANDOFF.md (this file), PROMPTS.md §4 row for Phase 3
- Before code: CODE-RECON on bot/indicators/ + bot/regime/ (both empty); state topology per
  AGENTS.md; plan pure-vectorized indicator functions + RegimeClassifier with 2-candle hysteresis
  + min-hold; flag per-pair calibration pass-rate note requirement (TRADING-RULES §1.7)

Open tensions carrying forward:
- sqlite:/// relative URL resolution: bot's Phase 4 journal writer must use same absolute-path
  resolution logic as dashboard/app/__init__.py create_app(), not raw DATABASE_URL
- pyarrow 24.0.0 release date: could not verify via PyPI HTTPS (SSL cert issue in dev env);
  confirmed >7-day old by reasoning (Apache Arrow major releases are months apart); flag if
  PythonAnywhere pip install rejects it
- requests==2.34.2 release date: similarly unverifiable via network; well-established package;
  same flag applies
- Dashboard auth (Flask-Login) wired but no User model or login routes — Phase 9

Files touched this session:
- bot/data/__init__.py (new)
- bot/data/precision.py (new)
- bot/data/fetcher.py (new)
- bot/data/cache.py (new)
- bot/data/provider.py (new)
- bot/config/instruments.yaml (modified — added history_years, live_warmup_candles defaults)
- requirements.txt (modified — pyarrow + requests chain)
- tests/test_data.py (new)
- HANDOFF.md (this file)
- CLAUDE.md (Phase 2 ticked)

Do NOT redo:
- Do not re-run flask db init
- Do not change journal model column names without a new migration
- Do not remove complete==True filter from _parse_response() — this is the §1.5 firewall
- Do not add cache-freshness guard to get_candles() — always-incremental is DECISION 1
- Do not call fetch_history() from the live loop — it is a one-time store builder only
- format_price() must return str, not float — OANDA wire format requirement (DECISION 2)
