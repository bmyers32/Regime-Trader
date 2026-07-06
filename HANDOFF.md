# HANDOFF — 2026-07-06T00:00Z
Phase: 4 — Backtester   Status: COMPLETE

Done this session: Phase 4 COMPLETE. 99/99 tests pass (65 prior + 34 new). All §4 exit
criteria met and adversarially tested:
  - Golden-run locked: fixed synthetic data produces byte-identical metrics and trade
    lists across repeat runs (test_golden_run_locked_on_repeat).
  - Costs demonstrably reduce PnL vs an identical zero-cost run
    (test_costs_reduce_pnl_vs_zero_cost).
  - Same Strategy interface as live path: engine drives bot.strategies.base.Strategy
    (generate_signal(window, regime) -> Signal|None) with no engine-specific hooks —
    this IS the contract Phase 5's trend_pullback will implement, not a stand-in.
  - No repainting: signal from bar i fills at bar i+1's open, verified structurally
    (test_fill_occurs_at_next_bar_open_not_signal_bar_close).
  - Regime call cadence: classify() called once per new closed HTF candle, not once
    per LTF bar (test_classify_called_once_per_new_htf_candle_not_per_ltf_bar) — this
    was an unstated but load-bearing timing assumption in the Phase 3 classifier;
    verified explicit this phase.

  Deliverables:
    bot/strategies/base.py — Signal dataclass + Strategy Protocol (CLAUDE.md Core
      Interfaces), shared by backtest and future live loop.
    bot/backtest/sizing.py — size_position(): units = f(equity, risk_pct,
      stop_distance, pip_value). Three currency-conversion cases (direct/self/cross),
      SizingError with no static fallback, backward-only rate lookup (no lookahead).
      Single implementation — Phase 8's RiskManager will import, not reimplement.
    bot/backtest/costs.py — session-bucketed spread (asian/london/ny_overlap),
      asymmetric slippage (entries + SL exits, doubled on EXPANSION exit, none on
      TP), max-spread entry gate (same threshold backtester and future live executor
      will both enforce), rollover cost per UTC-day crossing.
    bot/backtest/results.py — BacktestTrade/BacktestResult, compute_metrics() (net
      PnL, win%, maxDD, trade count, per-regime breakdown — structurally ready for
      §5.5 once real strategies populate more than one regime_at_entry value).
    bot/backtest/engine.py — BacktestEngine: HTF/LTF pointer-walk (merge_asof-
      backward equivalent), regime cached between HTF closes, SL/TP exit sim
      (SL-first tie-break on same-bar touch), wires sizing.py + costs.py.
    bot/config/instruments.yaml — account_currency: USD (top-level); per-instrument
      cost_model blocks (spread_pips sessions, max_spread_pips, slippage_pips,
      rollover_pips_long/short) seeded PENDING (null) — NOT published-typical
      numbers, per explicit user direction.
    config.py — ACCOUNT_CURRENCY.
    scripts/sample_spreads.py — standalone, read-only PricingInfo sampler to seed
      real cost_model values; not yet run against live OANDA (needs the user to
      schedule it across a day+ spanning all three sessions).
    tests/test_sizing.py (13), tests/test_costs.py (15), tests/test_backtest.py (6).

Not done / next action:
  Phase 5 kickoff (PROMPTS.md §5.2) — trend_pullback + walk-forward validation.
  Before real backtests are trustworthy: run scripts/sample_spreads.py across a
  day+ and fill in instruments.yaml cost_model values (currently PENDING/null) —
  Phase 5's walk-forward numbers are only as good as this calibration.

Open tensions:
  - cost_model (spread/slippage/rollover) is PENDING for all 6 pairs — engine and
    tests work fine with inline cost_cfg dicts (decoupled from yaml), but real
    Phase 5-7 walk-forward runs need real sampled values first, not placeholders.
  - rollover_pips has no automated sourcing path (OANDA financing rates aren't on
    the candle/pricing endpoints already in use) — manual entry or a Phase 8
    account-financing lookup; flagged, not solved, this phase.
  - Precision rounding (Prime Directive 4) is NOT applied to backtest fill prices —
    acceptable since Phase 4 submits no real orders; revisit if fidelity vs live
    becomes a concern once PrecisionRegistry is wired into a shared runtime context.
  - Engine's SL/TP same-bar tie-break assumes SL triggers first (conservative,
    standard convention) — not empirically validated against real intrabar path;
    fine for now, worth a footnote when Phase 5's §5 gates run for real.
  - Signal.tp=None means "SL-only exit" in the engine; trend_pullback's ATR/
    Chandelier trailing (Phase 5) will need its own exit-update mechanism — the
    engine has no trailing hook yet, by design (playbook-specific, not generic).

Files touched this session (Phase 4):
  bot/strategies/__init__.py, bot/strategies/base.py,
  bot/backtest/__init__.py, bot/backtest/sizing.py, bot/backtest/costs.py,
  bot/backtest/results.py, bot/backtest/engine.py,
  bot/config/instruments.yaml, config.py, scripts/sample_spreads.py,
  tests/test_sizing.py, tests/test_costs.py, tests/test_backtest.py,
  CLAUDE.md (Phase 4 ticked), ROADMAP.md (bid/ask-deferred entry), HANDOFF.md

Do NOT redo:
  - Do not call RegimeClassifier.classify() more than once per HTF candle close
    from engine/live-loop code — bars_in_regime hysteresis assumes one call = one bar.
  - Do not add a static-rate fallback in sizing.py's cross-currency path —
    SizingError must propagate; refuse, never guess.
  - Do not compute trade PnL from raw price diff without pip_value_per_unit()
    conversion — breaks silently for non-USD-quote pairs (GBP/JPY, EUR/GBP).
  - Do not seed instruments.yaml cost_model with published-typical spread/rollover
    numbers — must come from scripts/sample_spreads.py sampling (or the Phase 8
    journal's Order.spread_at_entry once that exists).
  - Do not fill signals at the signal bar's own close — next bar's open only.
  - Do not remove the SL-first tie-break without a documented reason (TRADING-RULES
    §5.7 revalidation note) — it's a conservative convention, not arbitrary.
