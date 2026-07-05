# HANDOFF — 2026-07-05T00:00Z
Phase: 4 — Backtester   Status: NOT-STARTED

Done this session: Phase 3 COMPLETE. 65/65 tests pass. All §4 exit criteria met.
  Deliverables: bot/indicators/core.py (ema/true_range/atr-Wilder/adx-Wilder/bollinger_bands/bb_width),
  bot/regime/classifier.py (RegimeState, RegimeResult, RegimeClassifier with asymmetric EXPANSION
  hysteresis, slope persistence, alignment hard gate), instruments.yaml regime_params + 6-pair
  calibration stubs, tests/test_indicators.py + tests/test_regime.py.

Not done / next action:
  Phase 4 kickoff — use PROMPTS.md §5.2 template. Objective: event-driven backtester with
  spread + slippage + rollover costs; golden-run tests with locked output. Exit criteria:
  golden-run locked (fixed data→identical metrics on repeat); costs demonstrably reduce PnL
  vs zero-cost run; same Strategy interface as live path.

Open tensions:
  - sqlite:/// relative URL: Phase 4 journal writer must use same absolute-path resolution as dashboard
  - pyarrow 24.0.0 / requests 2.34.2 release dates: unverifiable in dev env; flag if PA install rejects
  - EXPANSION/TRENDING ATR overlap: Phase 4 pass-rates will reveal whether atr_expansion_ratio
    needs lifting per pair (watch-item; see ROADMAP Compression-within-trend proposal)

Files touched this session (Phase 3):
  bot/indicators/__init__.py, bot/indicators/core.py,
  bot/regime/__init__.py, bot/regime/classifier.py,
  bot/config/instruments.yaml, tests/test_indicators.py, tests/test_regime.py,
  CLAUDE.md (Phase 3 ticked), BRAIN.md (2 seeds), ROADMAP.md (1 proposal), HANDOFF.md

Do NOT redo:
  - Do not re-run flask db init
  - Do not change journal model column names without migration
  - Do not remove complete==True filter from _parse_response()
  - Do not add cache-freshness guard to get_candles()
  - Do not call fetch_history() from live loop
  - format_price() must return str, not float
  - Do not revert regime priority order (TRENDING before COMPRESSION) — correct market semantics
  - Do not change ATR to standard EWM (span=period) — must stay Wilder (alpha=1/period)
