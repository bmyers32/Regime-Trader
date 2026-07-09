# HANDOFF — 2026-07-09T21:00Z
Phase: 6 — range_reversion   Status: NOT STARTED (Phase 5 CLOSED this session)

Done this session: Phase 5 (trend_pullback) closed. TRADING-RULES §5 gates 2-6 run
on EUR_USD + USD_JPY, TWICE (original code, then again after fixing a law-drift bug
where 3 of trend_pullback's 4 §3.1 score components were wired as hard vetoes,
reintroducing the §1.1 AND-stack anti-pattern). FAILED both times, both pairs,
decisively (gate 4: no profitable parameter neighborhood in either pair; gate 6:
bootstrap P(net_pnl<=0) 86.8-100% across all four pair/structure combinations run).
Remaining 4 pairs (GBP_USD, AUD_USD, EUR_GBP, GBP_JPY) deliberately NOT run — see
ROADMAP.md's "trend_pullback H1 post-mortem" for the full verdict, re-entry
condition, and a correction to the initial cost-ranking rationale for skipping them
(AUD_USD/EUR_GBP are actually CHEAPER than the two tested pairs, not worse — the
skip rests on the FAIL's decisiveness, not cost economics). CLAUDE.md's Phase 5 row
is ticked (exit criteria are about gates running+reporting per pair, not the
strategy passing — pre-committed rule from earlier this phase). Full session detail
(gate numbers, veto breakdown, funnel diagnostics, law-drift audit) is archived in
the "Phase 5 complete" commit message, not reproduced here —
`git log --grep "Phase 5 complete"`.

Not done / next action: Phase 6 kickoff — range_reversion per TRADING-RULES §3.2
(RANGING-only playbook: re-entry INSIDE lower/upper BB + RSI turning, target middle
band first, hard veto on EXPANSION/ATR-spike). Use PROMPTS.md §5.2's kickoff
template. Same harness (scripts/run_validation_gates.py, generalize its run_fn for
range_reversion instead of trend_pullback), same discipline this session
established: **audit the implemented gate/score split against §3.2's letter BEFORE
trusting existing unit tests describe correct behavior** — this session's law-drift
finding (3 of 4 score components silently wired as vetoes, defended by tests that
asserted the drift instead of the spec) could recur in any new playbook; do not
assume a fresh implementation is exempt just because it's new. Pairs: EUR_USD and
EUR_GBP first. scripts/fetch_history.py already has EUR_USD H1+H4 cached
(instance/candle_cache/) from Phase 5; EUR_GBP needs its own fetch (same PA
round-trip) unless already present — check before assuming.

Open tensions:
  - trend_pullback is CLOSED but its code, tests, and cost_model calibration remain
    in the repo (not deleted) — `enabled: false` for all 6 pairs is the only gate
    preventing it from trading; do not flip that without a redefined playbook per
    ROADMAP's re-entry condition.
  - Engine note (bot/backtest/engine.py, general — not trend_pullback-specific):
    `generate_signal()` is only called when `open_position is None` — a strategy
    firing MORE trades can cause `consulted` (the funnel/pass-rate denominator) to
    DROP, since more total time is spent holding a position, crowding out
    consultation opportunities on the bars in between. Confirmed directly this
    session (trend_pullback's law-drift fix: fired roughly doubled, consulted
    dropped ~3-4x, same stitched-OOS window). Relevant when reading range_reversion's
    funnel diagnostics too — don't assume `consulted` is a stable opportunity-count
    baseline across a strategy or parameter change.
  - cost_model (instruments.yaml) is real and calibrated for all 6 pairs
    (spread_pips/max_spread_pips/slippage_pips/entry_blackout_hours_utc) — reusable
    as-is for range_reversion, no re-calibration needed (cost_model is per-pair, not
    per-playbook).
  - slippage_pips is still an explicit INTERIM methodology (0.25x pooled median
    spread_pips) pending real Order.spread_at_entry data — unchanged by this phase,
    just restating so it isn't mistaken for a final calibration later.

Files touched (Phase 5 close-out, this pass — 13 files, see "Phase 5 complete"
commit for the full diff): bot/strategies/trend_pullback.py (law-drift fix),
bot/backtest/costs.py + engine.py (session-bucketed max_spread_pips,
entry_blackout_hours_utc — landed earlier this phase, unrelated to the law-drift
fix), bot/config/instruments.yaml (cost_model fill + per-pair calibration notes),
scripts/fetch_history.py + run_validation_gates.py + diagnose_gates.py (new),
tests/test_{costs,backtest,validation_defendants,trend_pullback}.py, CLAUDE.md,
ROADMAP.md, BRAIN.md. 182/182 tests pass.

Do NOT redo:
  - Do not run OANDA-credentialed scripts from this local machine — use PA
    (recurring, never-root-caused local TLS failure).
  - Do not re-open trend_pullback's FAIL with a wider param_grid or a third
    parameter attempt — closed per ROADMAP.md; revival needs a new edge thesis
    (new trigger/zone definitions), entering via PROMPTS.md §5.7.
  - Do not run trend_pullback's §5 gates on GBP_USD/AUD_USD/EUR_GBP/GBP_JPY under
    the current spec — see ROADMAP.md's post-mortem for why.
  - Do not treat AUD_USD/EUR_GBP as "worse pairs" than EUR_USD/USD_JPY on cost
    grounds — they have CHEAPER spread/slippage economics; the skip decision rests
    on the FAIL's decisiveness, not their cost profile (see ROADMAP.md correction).
  - Do not schedule sub-hourly-cadence scripts via PA's Tasks tab — hourly is that
    UI's finest recurrence. Use an Always-On Task with an internal sleep loop.
  - Do not disable/bypass TLS certificate verification anywhere.
  - Do not silently fill any new pair's cost_model with published-typical or
    placeholder numbers if range_reversion ever needs a 7th pair.
