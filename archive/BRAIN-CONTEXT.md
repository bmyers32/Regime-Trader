# archive/BRAIN-CONTEXT.md — Wisdom decompression stories

Full reasoning chains behind BRAIN.md's compressed Wisdom seeds, same order. Loaded
only when a seed needs unfolding — never at session kickoff. Each `## §N` heading
matches the seed's position in BRAIN.md's Wisdom list.

## §1 Type the boundary, not the computation.
*Phase 2 — format_price() → str, not float*
Computation works in floats for precision. Transmission works in strings for exactness.
Converting at the seam (format_price returns `f"{price:.{dp}f}"`) prevents floating-point
noise (`1.10000000000002`) from crossing into OANDA payloads and causing silent rejections.
Ignoring it → specific, visible failure: order rejected, position never opened, no error log.
Applies anywhere internal precision meets an external wire format: DB writes, CLI args, API calls.

## §2 If data fights the test, the classifier's semantics are wrong.
*Phase 3 — COMPRESSION-before-TRENDING priority bug*
A linear uptrend has monotonically decreasing BB width (constant std numerator, rising price
denominator) — the last bar is always the minimum. Every attempt to engineer test data that
avoided COMPRESSION firing was a fight against a mathematical identity. The correct fix was
not cleverer data; it was recognising that classifying a confirmed trend (ADX>25, aligned EMAs,
consistent slope) as COMPRESSION is semantically wrong. Reordering the priority check resolved
both failing tests and was the correct market-semantic decision.
Ignoring it → specific failure: you ship clever test data that avoids the bad path; production
data hits it every time; the wrong playbook is armed on valid trending setups.
Applies anywhere a branch priority is wrong: the data will always route correctly only if the
conditions are checked in the order that matches the domain's precedence rules.

## §3 Visually identical algorithms diverge at the decimal where stakes live.
*Phase 3 — Wilder EWM (α=1/period) vs standard EWM (α=2/(period+1)) for ATR and ADX*
Both produce smooth lines that look the same on a chart. At period=14: Wilder α=0.0714,
standard α=0.1333 — a 2× difference in smoothing weight. Over 50 bars the golden ATR
diverges by ~1.3e-4: meaningless on a chart, decisive in a test. Frozen golden tests with
tolerance abs=2e-4 are the only guard; visual inspection and "known-good from the same code"
references both miss it.
Ignoring it → specific failure: wrong EWM formula ships; ADX reads 25 on both but one
crosses the threshold one bar earlier; different trade count; walk-forward validation compares
two implementations of different algorithms, not two runs of the same one.
Applies anywhere two formulas are "close enough" in normal range but diverge at the boundary
where a threshold lives: order prices at displayPrecision, sizing at rounding modes, date
arithmetic across DST transitions.

## §4 Three paths: startup, restart, cycle — never collapse them.
*Phase 2 — fetch_history() / warm_up() / get_candles() split*
One-time historical fill (startup), gap-fill on restart, and per-cycle incremental fetch have
different cost, frequency, and failure modes. Collapsing them → full historical fetch every cycle
(§1.12 violation), or stale data on restart, or blocking the live loop with minutes of API calls.
Each function is a different contract; sharing implementation is fine, sharing call sites is not.

## §5 Verification failing closed is the system succeeding.
*Phase 5 — OANDA TLS handshake rejected on a local machine, cause never confirmed*
A certificate chain that fails to verify and a request that never reaches the wire are
not a bug to route around — they are the exact behavior TLS verification exists to
produce. Under time pressure the temptation is to treat "the check blocked me" as an
obstacle; the correct read is "the check did its job." The first theory (employer
network TLS inspection) didn't survive a second data point — the identical failure
recurred from the home network too, meaning the actual cause was never root-caused.
That didn't matter: no CA bundle changes, no proxy config, no disabled verification —
the fix was routing the credentialed call through a known-good path (PA console)
instead of trying to make an unexplained failure go away locally.
Ignoring it → specific failure: a disabled/bypassed verification step "succeeds" once,
then silently accepts a MITM'd response (or transmits a real token through one)
indefinitely, with no log line marking the moment trust was removed.
Applies anywhere a security check's failure gets treated as friction instead of signal:
cert verification, signature checks, permission prompts, secrets-grep pre-commit hooks.

## §6 Grouped spec conditions are one score, not gates in disguise.
*Phase 5 — EMA200 pullback depth implemented as a hard veto instead of a score component*
TRADING-RULES §3.1 lists pullback-zone proximity, reversal trigger, RSI, and EMA200
depth together under one "Score:" bullet, separate from "Hard gates: regime; spread;
blackout." Implementing the last item as an unconditional veto (non-empty vetoes never
fire, regardless of the other three) is functionally a 4th hard gate — the exact
AND-stack shape TRADING-RULES §1.1 was written to kill, reintroduced one field at a
time because a boolean-shaped check (on-side or not) reads like a gate even when the
spec already said it wasn't one.
Ignoring it → specific failure: score components silently regain veto power one at a
time until "weighted confluence" degrades back into the 7-condition AND-stack whose
near-zero signal probability was the original failure being fixed.
Applies anywhere a spec lists several conditions under one heading (one score, one
config block, one validation pass): the implementation must preserve that they trade
off against each other, not each become an independent kill-switch.

## §7 Test the judge with defendants of known guilt.
*Phase 5 (Track 2) — TRADING-RULES §5 walk-forward/stability/Monte-Carlo harness*
A validation harness has no ground truth to check itself against — a strategy backtest
can be graded against known-good indicator values, but nothing hands you the "correct"
walk-forward verdict for a real strategy. The fix: build synthetic defendants whose
guilt or innocence is fixed by construction (a coin-flip process must be unprofitable
after real costs; a threshold hand-optimized on pure noise must collapse out-of-sample;
a lucky seed's one realized positive result must fail to survive resampling), then
require the harness to reach that specific verdict. Two of the four defendants this
session (overfit-by-construction, cherry-picked lucky seed) needed real calibration —
the first attempt at the "overfit" defendant produced a uniformly negative grid instead
of a spurious peak, because real transaction costs swamped the noise signal the test
was trying to isolate; the "lucky seed" defendant required scanning ~80 seeds for one
that actually fooled gate 3. If a defendant that should be convicted is acquitted
instead — or an innocent one is convicted — the fix is never to adjust the test's
assertion; it's to find what the harness got backwards.
Ignoring it → specific failure: a walk-forward/stability/Monte-Carlo harness ships with
only "smoke test" coverage (does it run without crashing), passes code review because
the code looks reasonable, and then silently rubber-stamps an overfit strategy in
production because nothing ever proved the harness could convict one.
Applies anywhere a system's job is to judge other systems and no ground-truth oracle
exists: anomaly detectors, spam/fraud classifiers, CI flakiness detectors, code-review
bots, alerting thresholds — build the thing you already know should fail the check,
and the thing you already know should pass it, before trusting a verdict on the
unknown case.

## §8 A clean FAIL with reasons is a deliverable.
*Phase 5 (Session B) — trend_pullback §5 gates 2-6, EUR_USD/USD_JPY, 2026-07-09*
A validation gate's job is to produce a trustworthy verdict, not a passing one. Both
pairs failed all three gates this session — walk-forward net_pnl negative, no
profitable stability peak to test, Monte Carlo confirming the negative result isn't a
shuffling artifact — and every failure carries its own numbers, thresholds, and a
diagnostic trail (evaluation funnel, score distribution, regime attribution) explaining
why. That IS the deliverable: not "ship" or "don't ship," but a documented, falsifiable
account the next session can act on without re-deriving it. Treating a FAIL as an
unfinished task invites the exact failure mode TRADING-RULES §5 exists to prevent:
re-running with tweaked params until something passes, at which point the "pass" was
manufactured, not discovered.
Ignoring it → specific failure: a session chases a PASS by nudging thresholds/params
after a real FAIL, shipping a strategy that looks validated on paper but was actually
parameter-hunted against the same historical noise the walk-forward split existed to
guard against — TRADING-RULES §1.7's "always-true filter" failure mode wearing
different clothes.
Applies anywhere a check's purpose is to be honest, not agreeable: code review, test
suites, security audits, hiring bars — a rejection with a clear, evidenced reason is
the process working, not the process failing to produce the "right" answer.

## §9 Tests assert what is, not what the law says.
*Phase 5 (Session B) — trend_pullback's zone/trigger/rsi veto drift, 2026-07-09*
Three unit tests (test_rsi_wrong_side_veto, test_no_reversal_trigger_veto,
test_outside_pullback_zone_veto) asserted that specific score components appeared in
Signal.vetoes — a faithful, green description of what the code did, and a direct
contradiction of TRADING-RULES §3.1, which lists all three under "Score:", never
"Hard gates:". The tests were written by observing the implementation and codifying
it, not by deriving the expectation independently from the spec. That inversion is
what let three separate AND-stack reintroductions (TRADING-RULES §1.1's exact failure
mode) ship green for an unknown number of sessions: the tests didn't just fail to
catch the drift, they actively defended it — a future attempt to fix the code would
see "passing tests break" and read that as evidence the fix was wrong, when the tests
were the thing wrong all along. The empirical funnel that finally surfaced it (gates
passed = 3-4% of consulted, fired==gates_passed exactly) came from a real backtest,
not from this test suite — the suite was blind to its own drift by construction.
Ignoring it → specific failure: a test suite that encodes "whatever the code
currently does" instead of "what the spec says it should do" turns green coverage into
a moat protecting bugs from correction — every future fix attempt looks like a
regression until someone re-derives intent from the spec and inverts the assertions.
Applies anywhere a test is written by running the code and asserting the output,
rather than by reading the spec/contract first and asserting what SHOULD happen:
snapshot tests taken during a bug, API contract tests written against a buggy client,
golden files regenerated to match broken output — the fastest way to write a test that
can never fail is to let broken behavior write its own assertion.

## §10 A branch no caller has ever taken isn't proven, however carefully it was written.
*Phase 6 — EUR_GBP's missing conversion_series, 2026-07-10*
bot.backtest.sizing.py's cross-currency conversion path has existed since Phase 4,
with a correct docstring, three documented cases, and a loud SizingError refusal.
But every pair scripts/run_validation_gates.py actually ran in Phase 5 (EUR_USD:
quote=USD; USD_JPY: base=USD) took the direct or self-conversion branch — the
cross-conversion branch had zero live callers despite looking complete. EUR_GBP
(quote=GBP, account=USD, the first pair this session that genuinely needed a
cross series) hit it immediately: the gate-running scripts never built or passed a
conversion_series argument at all, because nothing had ever needed one.
Ignoring it → specific failure: a correctly-written function ships beside caller
code that never exercises one of its documented branches; the gap is invisible
until the first real input that needs it, at which point it looks like a fresh bug
instead of what it is — a coverage gap that existed since the function was written.
Applies anywhere a shared module supports N cases but the caller fleet has only
ever supplied a subset: currency conversion, locale/i18n branches, error-recovery
paths, feature flags — a branch with no caller is unverified regardless of how
carefully it was written.

## §11 A green equity curve is one gate of three.
*Phase 6 close-out — EUR_USD range_reversion's Asian-exclusion follow-up, 2026-07-10*
tests/test_validation_defendants.py's defendant (d) was built on synthetic marker
data specifically to prove the harness could catch a lucky, zero-edge draw whose
one realized stitched-OOS trade sequence happens to sum positive — gate 3 (walk-
forward) rubber-stamps it, gate 6 (Monte Carlo bootstrap resampling the SAME
trades) overturns it. This session's pre-registered session-preference follow-up
(excluding Asian-hour entries) reproduced that exact pattern on REAL data for the
first time: gate 3 flipped from FAIL to PASS (net_pnl=+82.34, 76 trades — a real,
not synthetic, positive result), and gates 4 AND 6 both still failed it (no
profitable parameter neighborhood; bootstrap P(net_pnl<=0)=42.3%, far above the 5%
robustness bar). The synthetic defendant proved the harness COULD convict this
shape of false positive; this run is the first time it actually did, in the wild,
on a result a less disciplined process would have reported as "the fix worked."
Ignoring it → specific failure: treating gate 3's PASS as the verdict (because it's
the most legible, chart-shaped number — a rising equity curve) and shipping on it,
when gates 4/6 exist precisely because a positive stitched backtest can be
achieved by a handful of lucky trades that don't represent a stable, resamplable
edge.
Applies anywhere a single passing metric is mistaken for the whole verdict: a green
CI run with no coverage gate, a profitable backtest with no walk-forward split, an
A/B test read at the first significant p-value with no correction for peeking — the
number that's easiest to look at is rarely the number that was built to protect you.

## §12 Decide which diagnostic wins before either diagnostic exists.
*Phase 7 close-out — squeeze_breakout's hysteresis-excluded vs. false-break findings, 2026-07-11*
Two diagnostics were pre-registered before any real data existed: a hysteresis-excluded
count (bars where the trigger would have cleared threshold but the regime gate had
just left COMPRESSION) and a false-break-vs-insufficient-expansion split (the
playbook's own named failure mode, and the literal trigger condition for a deferred,
already-drafted revival mechanism). Both fired on real data — hysteresis-excluded
~98%/70% of fired trades on the two target pairs, AND 100% of losing trades on both
pairs were false-break type. Taken alone, the false-break result is the more
narratively satisfying one: it names the exact failure mode the playbook was built to
guard against and points straight at a mechanism already sitting in ROADMAP.md ready
to build. It was not acted on, because the decision rule written before the data
existed said the hysteresis finding wins that specific conflict. Without a
pre-registered arbitration rule, the session would have had to choose between two
true-and-relevant findings under the pull of whichever one offered the more buildable
next step — exactly the moment post-hoc reasoning finds its opening.
Ignoring it → specific failure: two honest diagnostics disagree on what to do next,
and the tie gets broken by which explanation is more convenient to act on rather than
which one is more likely correct — the same rationalization risk pre-registration
exists to prevent, just moved one level up from "which threshold" to "which finding."
Applies anywhere a system can produce more than one true diagnostic pointing at
different fixes: incident postmortems with two plausible root causes, A/B tests with
conflicting primary and secondary metrics, code review flagging both a design smell
and a quick patch — decide the priority order while neutral, not after seeing which
story is more flattering to already-planned work.

## §13 A diagnostic must count the population its remedy can reach.
*Phase 7 follow-up — squeeze_breakout's §2 consultation-window experiment, 2026-07-11*
The hysteresis-excluded diagnostic measured "bars within N of a COMPRESSION exit" —
any post-COMPRESSION regime, not specifically EXPANSION. The amendment it motivated
(admit COMPRESSION-originated EXPANSION for N bars) targeted only the EXPANSION
subset, correctly, per the law's own letter. Reconciling the two on real data: of
400/464 originally-excluded bars, only 16/8 (4.0%/1.7%) were ever classified
EXPANSION at all — the rest were COMPRESSION resolving into RANGING or TRENDING, a
population the amendment structurally could not and should not reach. The amendment
worked exactly as designed on its own narrow population (100% correctly admitted,
zero missed to bug or timing) and still failed, because that population was never
more than a sliver of what the diagnostic had measured. The diagnostic's number was
real; it was just answering a different, broader question than the remedy could ever
address.
Ignoring it → specific failure: a remedy is judged against the diagnostic's full
count instead of the subset the remedy's own scope can actually touch, producing
false confidence going in ("52 excluded bars, this should help") and a confusing
null result coming out that looks like a bug instead of a scope mismatch.
Applies anywhere a fix is sized against a problem's total measured count rather than
the fraction its own mechanism can reach: a caching layer judged against total
requests instead of cacheable ones, a retry policy judged against all failures
instead of transient ones, an amended filter judged against everything the old
filter excluded instead of the specific excluded subtype it was built for.

## §14 A tripped guardrail is a demand for evidence, not a verdict.
*Phase 7 follow-up — squeeze_breakout's pre-registered parity check, 2026-07-11*
The pre-registered rule (admitted population must be >=50% of the diagnostic's
excluded count, or halt interpretation) tripped at its most extreme possible value:
0% admitted against baselines of 52 and 35. The path of least resistance was either
direction — accept "the amendment didn't work" as the whole story, or explain away
the zero as an artifact and move on. The rule itself only says stop; it doesn't say
what the answer is. Stopping to investigate (full-history vs. per-window classifier
replay, then the population-reconciliation cross-tab) turned an unexplained null
into a precise, falsifiable, more valuable finding — one that also surfaced an
untested pivot hypothesis (COMPRESSION->TRENDING dominance) the null result alone
would never have revealed. The guardrail's job was never to render the verdict; it
was to force the investigation that made the verdict trustworthy.
Ignoring it → specific failure: a guardrail fires, gets treated as self-explanatory,
and the session either ships a conclusion nobody actually verified or discards a
real result as "probably a bug" without checking — either way the guardrail's one
job (forcing a human look) never happens.
Applies anywhere an automated check can only detect an anomaly, not diagnose it:
CI flakiness flags, statistical-significance gates, anomaly-detection alerts, a
code-review bot flagging an unusual diff — the check earns its keep by making
someone look, not by pre-deciding what they'll find.
