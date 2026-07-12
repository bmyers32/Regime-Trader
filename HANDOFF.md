# HANDOFF — 2026-07-12T00:00Z
Phase: 7 follow-up — squeeze_breakout §2 consultation-window experiment   Status: CLOSED (FAIL, permanently — this closes the three-playbook chapter). NOT a Phase 8 kickoff.

Done this session: executed the pre-drafted §2 routing experiment scheduled at the end
of Phase 7 — the final hearing for squeeze_breakout and the regime-routing question.
Full sequence: TRADING-RULES §2/§3.3 EXPERIMENTAL amendment applied first (dated
2026-07-11), then `prior_regime` added to `RegimeResult`/`RegimeClassifier`
(bot/regime/classifier.py) with a full generalization proof (byte-identical re-run of
trend_pullback EUR_USD/USD_JPY and range_reversion EUR_USD/EUR_GBP against archived
Phase 5/6 numbers — exact match on trade_count/net_pnl/passed for all four), squeeze_
breakout's gate amended (`regime==COMPRESSION OR (regime==EXPANSION AND
prior_regime==COMPRESSION AND bars_in_regime<=regime_confirm_bars)` — note: HTF-bar
units, not the LTF-bar-derived N=8 literally, a real units mismatch caught before
implementation), compression-box SL frozen at the COMPRESSION-exit boundary for
consultation-window entries (new, explicitly-flagged instance state on SqueezeBreakout,
a real deviation from its prior "stateless otherwise" contract), a consistency
assertion cross-checking the strategy's own LTF bar counter against the HTF-derived
bound (never tripped in either live run), and a new early/late (bars_in_regime==1 vs
==2) stratification added to scripts/gross_vs_net.py to separate the pre-registered
SL-geometry bias from a genuine confirmation-quality signal. 248/248 tests pass (236
baseline + 12 new, covering the boundary semantics both directions and the SL-freeze
mechanism).

VERDICT: FAIL, both target pairs, decisively, bit-for-bit identical to Phase 7's
pre-amendment gate 3/4/6 numbers (GBP_USD net_pnl=-691.75, USD_JPY net_pnl=-113.13,
same gate 4 sharp-peak findings, same gate 6 bootstrap probabilities). The amendment
produced ZERO incremental trades in either pair — confirmed independently three ways:
(1) gate numbers unchanged, (2) per-regime attribution shows 100% of fired trades are
`regime_at_entry=="COMPRESSION"` in both pairs, zero `"EXPANSION"`-routed, (3) the new
early/late stratification shows 0/0 in both buckets, both pairs.

THE PRE-REGISTERED PARITY CHECK (admitted population must be >=50% of Phase 7's
excluded baseline, else halt interpretation) tripped at its most extreme value — 0%
admitted against baselines of 52 (GBP_USD) and 35 (USD_JPY). Per the rule, this halted
interpretation pending explanation. Investigated directly (not accepted, not dismissed
as a bug) via: (a) a full-history continuous classifier replay confirming the gate's
own condition (EXPANSION, prior=COMPRESSION, bars_in_regime<=confirm_bars) genuinely
occurs rarely in real data (3 distinct transition events for GBP_USD, 2 for USD_JPY,
across 766 days each); (b) a per-window classifier-reset replay confirming the walk-
forward's own per-window classifier bootstrap does NOT explain the null result (most
windows still observe the same rare transitions within their own bounded slice); (c) a
full population reconciliation cross-tabulating Phase 7's original excluded population
(400 GBP_USD / 464 USD_JPY candidate bars) against real regime state at each bar: only
16 (4.0%) / 8 (1.7%) were ever classified EXPANSION at all — the other 96%/98% were
COMPRESSION resolving into RANGING or TRENDING, a population this amendment's own
correctly-scoped letter (COMPRESSION->EXPANSION *specifically*) cannot and should not
reach. Of the small EXPANSION-classified population that DOES exist, 100% (16/16,
8/8) were correctly admitted by the new gate — zero missed to bug or timing, no
assertion ever tripped. But zero of those correctly-admitted bars ever cleared any
walk-forward window's own selected entry_threshold in real price/indicator data.

THE CORRECTED EPITAPH (more precise than either of the two pre-registered options from
Phase 7's kickoff — neither applies, since zero consultation-window trades occurred in
either pair): two independent conditions were required for this amendment to rescue
squeeze_breakout, and both failed. The targeted transition type (COMPRESSION resolving
directly into confirmed EXPANSION) is genuinely rare — only 4.0%/1.7% of the originally-
diagnosed excluded population. And even within that small, correctly-captured
population, there was no signal at all. Not a bug; a scope-vs-reality mismatch plus a
genuine absence of edge. Full reconciliation table, exact numbers, and the standalone
finding below are recorded permanently in ROADMAP.md's "squeeze_breakout §2
consultation-window experiment" entry (now marked CLOSED with a full POST-MORTEM
section) — not reproduced in full here.

STANDALONE FINDING beyond the verdict (recorded in ROADMAP, load-bearing for future
regime-routing work, not just this playbook): under this classifier's real behavior on
both target pairs, COMPRESSION resolves to a confirmed EXPANSION only ~2-4% of the
time. §2's "COMPRESSION arms squeeze_breakout" narrative (implying a coiled market
about to break out) describes a near-nonexistent sequence in this data — most
COMPRESSION regimes resolve into a directional TRENDING move or fizzle back to RANGING.

PIVOT-SESSION CANDIDATE surfaced by the above (untested, NOT a Phase 7 reopening — a
new, distinct hypothesis, recorded in ROADMAP.md for the next playbook-selection
deliberation, to be ranked on its own merits there, not built on the strength of this
note alone): COMPRESSION->TRENDING is the dominant compression-exit path in this data
(~60%+). "Trend inception from compression" as an entry population is distinct from
both of this system's dead theses — not squeeze_breakout's (which wanted the rare
EXPANSION resolution specifically) and not trend_pullback's tested structure either
(which entered deep into an already-established trend via EMA-pullback zones, not at
the inception moment).

BRAIN.md: two new wisdom entries this session — "A diagnostic must count the
population its remedy can reach" (the scope-mismatch mechanism above) and "A tripped
guardrail is a demand for evidence, not a verdict" (on why the parity check's halt was
honored by investigating rather than by accepting or dismissing the null result).

CODE DISPOSITION: per explicit instruction, this session's code changes were committed
in full as the permanent experimental record (commit: "squeeze_breakout §2
consultation-window experiment: FAIL — eligible population rare (16/8 bars) and
signal-free; full reconciliation in ROADMAP"), then REVERTED in a second commit
restoring bot/regime/classifier.py, bot/strategies/squeeze_breakout.py,
bot/backtest/{engine,results}.py, scripts/{run_validation_gates,diagnose_gates,
gross_vs_net}.py, tests/{test_regime,test_squeeze_breakout}.py, and TRADING-RULES.md's
EXPERIMENTAL clauses to Phase-7-closed lockstep (TRADING-RULES.md's own governing rule:
code contradicting law is a bug by definition; the law does not carry this mechanism
now that it FAILED). ROADMAP.md's post-mortem, BRAIN.md's two entries, and this file
are the permanent record — git history preserves the full diff regardless of the
revert. Full test suite re-confirmed green (236 baseline) after the revert.

***THIS CLOSES THE THREE-PLAYBOOK CHAPTER.*** trend_pullback, range_reversion, and
squeeze_breakout have all FAILED TRADING-RULES §5 gates with verified, non-negotiated
epitaphs; TRADING-RULES §6's revival budget remains fully unspent across all three; the
§2 regime-routing question is now also closed permanently. No playbook is validated to
trade. Phase 8 (risk/execution layer) has no strategy cleared to forward-test.

Not done / next action: the system needs a NEW playbook candidate — this is a pivot
decision, not a Phase 8 kickoff, and not a revival of any closed playbook. Point next
session at the pivot deliberation, ranking candidates on their own merits (not
pre-decided here):
  1. D1/H4 time-series momentum — first per the ranked map referenced this session.
  2. Carry-with-regime-conditioning — second.
  3. "Trend inception from compression" (COMPRESSION->TRENDING entry population,
     surfaced above) — a new candidate this session added to the deliberation, distinct
     from both dead theses, evaluated alongside the other two on its own merits.

Open tensions / do NOT redo:
  - Do not reopen squeeze_breakout, trend_pullback, or range_reversion with a parameter
    retune, a different pair, or a different M-timeframe comparison — all three are
    closed per their own post-mortems, and the §2 routing question specifically is now
    also closed permanently (not on a hunch, not without a genuinely new mechanism).
  - Do not treat the "trend inception from compression" pivot candidate as pre-approved
    — it is one candidate among several for the next session's own ranked deliberation,
    not a green light to start building.
  - Do not re-add `prior_regime`, squeeze_breakout's consultation gate, or the frozen-SL
    mechanism by re-deriving them from scratch — the exact implementation, byte-
    identical generalization proof, and full reconciliation are preserved in git history
    (the "FAIL" commit) and in ROADMAP.md's post-mortem if a genuinely new §2 question
    ever needs this machinery again.
  - Do not run OANDA-credentialed scripts from this local machine — not needed; candle
    cache already complete for all 6 pairs.

Files touched this session: TRADING-RULES.md, bot/regime/classifier.py,
bot/strategies/squeeze_breakout.py, bot/backtest/{engine,results}.py,
scripts/{run_validation_gates,diagnose_gates,gross_vs_net}.py,
tests/{test_regime,test_squeeze_breakout}.py (all committed then reverted — see git
log), ROADMAP.md, BRAIN.md, HANDOFF.md (this file, permanent).
