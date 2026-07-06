# HANDOFF — 2026-07-06T00:00Z
Phase: 4 — Backtester   Status: COMPLETE (accepted, with follow-up hardening)

Done this session: Phase 4 accepted by user, then five follow-up items resolved before
Phase 5 kickoff (user treated all as blocking, not deferrable). 101/101 tests pass.

  (1) Rollover — RESOLVED, not deferred. TRADING-RULES §5.2 requires rollover as a
      backtest cost; scripts/fetch_financing_rates.py now sources it from OANDA's own
      published per-instrument financing rates (AccountInstruments financing.longRate/
      shortRate, annualized) rather than a manual guess, converting annual_rate/365 into
      a daily-pip figure via the pair's current price. cost_model's rollover key renamed
      rollover_pips_long/short -> rollover_pips_per_day: {long, short} (matches the
      spread_pips: {session: ...} nesting convention). test_multi_day_hold_incurs_
      rollover_cost() in tests/test_backtest.py isolates the golden dataset's 10-day
      hold, compares net PnL against an identical run with rollover zeroed, and asserts
      the delta equals a hand-computed rollover_cost_pips() conversion exactly (rel=1e-9)
      — not just "some difference exists."
      Known simplification, documented not hidden: OANDA triples financing on Wednesdays
      (weekend T+2 settlement); this script emits a uniform daily rate and
      rollover_crossings() counts calendar days uniformly — Wednesday's 3x multiplier is
      NOT modeled. Logged in ROADMAP.md; revisit only if Phase 11 divergence implicates
      rollover specifically (low $ impact expected vs spread/slippage, but watch
      trend_pullback's multi-day trailing-exit holds in Phase 5).

  (2) Re-baseline protocol — documented, not yet exercised (cost_model is still PENDING
      for all pairs, so no golden-run has shifted yet). instruments.yaml now carries an
      explicit RE-BASELINE RULE comment block: filling in any PENDING cost_model value
      WILL shift golden-run/walk-forward metrics for any strategy reading it. Required
      sequence when that happens: fill values -> re-run existing goldens/walk-forward ->
      expect the shift -> re-baseline deliberately with a dated note in both the yaml
      calibration_note and the relevant test file. Never regenerate a baseline silently
      (PROMPTS.md §5.7). This HANDOFF entry is the marker that no re-baseline has
      happened yet — the next session that fills in real spread/rollover numbers is the
      one that must follow this sequence.

  (3) Commit provenance — confirmed: commit 9fa611d was preceded by an explicit
      AskUserQuestion ("Commit Phase 4 now?") which the user answered "Yes, commit"
      before `git commit` ran. No autonomous commit occurred.

  (4) Rollover day-counting — CONFIRMED calendar days, not bars/trading days. Verified
      by reading rollover_crossings() (operates only on entry_ts/exit_ts via raw
      timedelta(days=1) arithmetic; never touches the LTF/HTF dataframe, so it cannot
      "skip" a day for lack of a candle) and by adding
      test_rollover_counts_weekend_calendar_days_not_bars (Friday 10:00 -> Monday
      10:00 = 3 crossings, proving Saturday/Sunday nights are charged, not skipped —
      a weekend-spanning hold would otherwise undercharge financing by 2/7). Both
      costs.py's docstring and the yaml comment now state this explicitly. The
      Wednesday-triple-charge deferral (item 1 above) stands as-is: our uniform daily
      counting nets out to the same total weekly cost as OANDA's lump-on-Wednesday
      convention, just spread evenly instead of spiked midweek.
      Added dated LIMITATION note to all 6 pairs' cost_model.calibration_note:
      fetch_financing_rates.py reads OANDA's rate ONCE at run time and that single
      value is applied as a constant across the entire historical backtest window —
      real financing rates drift with central-bank policy over a multi-year window.
      Acceptable for Phases 4-7 (rollover is a minor cost next to spread/slippage for
      typical hold times); revisit if Phase 11 divergence implicates it, or before any
      strategy whose edge depends on very long holds.

  (5) Precision-rounding deferral rationale (Prime Directive 4) — recorded for the
      record, one line: the backtester never submits a real OANDA order, so there is no
      wire-format boundary for PrecisionRegistry.round_price()/format_price() to guard;
      the invariant it protects (float noise causing silent broker rejection) cannot
      manifest in a pure in-memory simulation. It becomes live-relevant only once the
      engine or a shared runtime context actually constructs order payloads (Phase 8),
      at which point precision rounding is non-negotiable per Prime Directive 4 and must
      be added at that seam, not before.

  Deliverables (cumulative, Phase 4 + this follow-up):
    bot/strategies/base.py — Signal dataclass + Strategy Protocol (CLAUDE.md Core
      Interfaces), shared by backtest and future live loop.
    bot/backtest/sizing.py — size_position(): units = f(equity, risk_pct,
      stop_distance, pip_value). Three currency-conversion cases (direct/self/cross),
      SizingError with no static fallback, backward-only rate lookup (no lookahead).
      Single implementation — Phase 8's RiskManager will import, not reimplement.
    bot/backtest/costs.py — session-bucketed spread (asian/london/ny_overlap),
      asymmetric slippage (entries + SL exits, doubled on EXPANSION exit, none on
      TP), max-spread entry gate (same threshold backtester and future live executor
      will both enforce), rollover cost per UTC-day crossing via
      rollover_pips_per_day: {long, short}.
    bot/backtest/results.py — BacktestTrade/BacktestResult, compute_metrics() (net
      PnL, win%, maxDD, trade count, per-regime breakdown — structurally ready for
      §5.5 once real strategies populate more than one regime_at_entry value).
    bot/backtest/engine.py — BacktestEngine: HTF/LTF pointer-walk (merge_asof-
      backward equivalent), regime cached between HTF closes, SL/TP exit sim
      (SL-first tie-break on same-bar touch), wires sizing.py + costs.py.
    bot/config/instruments.yaml — account_currency: USD (top-level); per-instrument
      cost_model blocks (spread_pips sessions, max_spread_pips, slippage_pips,
      rollover_pips_per_day) seeded PENDING (null) — NOT published-typical numbers;
      RE-BASELINE RULE comment added this session.
    config.py — ACCOUNT_CURRENCY.
    scripts/sample_spreads.py — standalone, read-only PricingInfo sampler to seed
      real spread/slippage cost_model values; not yet run against live OANDA.
    scripts/fetch_financing_rates.py — standalone, read-only AccountInstruments +
      PricingInfo fetcher to seed rollover_pips_per_day; not yet run against live OANDA.
    tests/test_sizing.py (13), tests/test_costs.py (16, +1 this session for the
      weekend calendar-day proof), tests/test_backtest.py (7, +1 this session for
      rollover isolation).

Not done / next action:
  Phase 5 kickoff (PROMPTS.md §5.2) — trend_pullback + walk-forward validation.
  Before real backtests are trustworthy: run scripts/sample_spreads.py AND
  scripts/fetch_financing_rates.py, then fill in instruments.yaml's PENDING cost_model
  values. THIS WILL SHIFT existing golden-run assertions in tests/test_backtest.py
  (test_golden_run_locked_values currently asserts on the zero-ish-cost placeholder
  metrics) — when that session runs, follow the RE-BASELINE RULE in instruments.yaml:
  fill -> run -> expect failure -> re-baseline deliberately with a dated note, do not
  silently regenerate.

Open tensions:
  - cost_model (spread/slippage/rollover) is PENDING for all 6 pairs — engine and
    tests work fine with inline cost_cfg dicts (decoupled from yaml), but real
    Phase 5-7 walk-forward runs need real sampled/fetched values first, not placeholders.
  - Wednesday triple-charge rollover not modeled (see item 1 above) — logged in
    ROADMAP.md, not blocking, revisit only if Phase 11 divergence implicates it.
  - Precision rounding (Prime Directive 4) is NOT applied to backtest fill prices —
    rationale recorded in item 4 above; must be added when engine/live share an order-
    construction seam (Phase 8), not before.
  - Engine's SL/TP same-bar tie-break assumes SL triggers first (conservative,
    standard convention) — not empirically validated against real intrabar path;
    fine for now, worth a footnote when Phase 5's §5 gates run for real.
  - Signal.tp=None means "SL-only exit" in the engine; trend_pullback's ATR/
    Chandelier trailing (Phase 5) will need its own exit-update mechanism — the
    engine has no trailing hook yet, by design (playbook-specific, not generic).

Files touched this session (Phase 4 + follow-up):
  bot/strategies/__init__.py, bot/strategies/base.py,
  bot/backtest/__init__.py, bot/backtest/sizing.py, bot/backtest/costs.py,
  bot/backtest/results.py, bot/backtest/engine.py,
  bot/config/instruments.yaml, config.py,
  scripts/sample_spreads.py, scripts/fetch_financing_rates.py,
  tests/test_sizing.py, tests/test_costs.py, tests/test_backtest.py,
  CLAUDE.md (Phase 4 ticked), ROADMAP.md (bid/ask + Wednesday-rollover deferred entries),
  HANDOFF.md

Do NOT redo:
  - Do not call RegimeClassifier.classify() more than once per HTF candle close
    from engine/live-loop code — bars_in_regime hysteresis assumes one call = one bar.
  - Do not add a static-rate fallback in sizing.py's cross-currency path —
    SizingError must propagate; refuse, never guess.
  - Do not compute trade PnL from raw price diff without pip_value_per_unit()
    conversion — breaks silently for non-USD-quote pairs (GBP/JPY, EUR/GBP).
  - Do not seed instruments.yaml cost_model with published-typical spread/rollover
    numbers — must come from scripts/sample_spreads.py + scripts/fetch_financing_rates.py
    (or the Phase 8 journal's Order.spread_at_entry once that exists).
  - Do not fill signals at the signal bar's own close — next bar's open only.
  - Do not remove the SL-first tie-break without a documented reason (TRADING-RULES
    §5.7 revalidation note) — it's a conservative convention, not arbitrary.
  - Do not regenerate a golden-run baseline silently when cost_model values change from
    PENDING to real numbers — follow instruments.yaml's RE-BASELINE RULE.
