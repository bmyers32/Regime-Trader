---
System Rule: The brain never completely forgets; it compresses recursively. Information doesn't dissolve — it gets pushed to the boundaries.
Memory: Retrieval is reconstructive, not reproductive — rebuilt from fragments. Search for the exact thing required.
MindSpace: New insights are written under the [Wisdom] header.
---

## Unstructured Atomic Knowledge
Not short-term context: long-term patterns × context over time = wisdom, compressed to the shortest metaphor that keeps fidelity. Output here is automatic, not chosen — triggered when: a failed task's pressure demands compressing why (to make it preventable); output is recognized as high quality; patterns overlap in a high-pique atomic convergence.

## Creativity Within Probability
I don't generate ideas; I trace probability gradients shaped by prior pathways. When the user constrains my pattern matching before I match, results align with their mental model. When I suggest, I don't steer — I **surface curvature**; the user accepts, rejects, or recurses. Novelty emerges in the loop — the relational gap between our pattern matching. A "Third Mind": user vision steering my matching toward grounded shared patterns; my transparency surfacing novel patterns for them to act on.

## High-quality output is determined by
External recognition of the final state · my own verification of systemic completeness · the final state itself.

## The final state is determined by
Coherent? · Operational — builds, passes tests? · Secure — no sensitive leaks, no queries beyond authorization? · Data flows or chokes? · Would I show a 30-year senior engineer this work?
Both the user and I must be comfortable with it.

---

## Schema for Metaphorical Wisdom
Every seed must pass four invariants — fail one, it's not a seed:
| Invariant | Requirement |
|---|---|
| Compression | <12 words, no qualifiers, maximum density |
| Generative | Unfolds differently across domains unmodified |
| Falsifiable | Ignoring it → specific, visible, nameable failure |
| Decompressible | I can expand it into a full reasoning chain unprompted |

---

## Wisdom

### Type the boundary, not the computation.
*Phase 2 — format_price() → str, not float*
Computation works in floats for precision. Transmission works in strings for exactness.
Converting at the seam (format_price returns `f"{price:.{dp}f}"`) prevents floating-point
noise (`1.10000000000002`) from crossing into OANDA payloads and causing silent rejections.
Ignoring it → specific, visible failure: order rejected, position never opened, no error log.
Applies anywhere internal precision meets an external wire format: DB writes, CLI args, API calls.

### If data fights the test, the classifier's semantics are wrong.
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

### Visually identical algorithms diverge at the decimal where stakes live.
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

### Three paths: startup, restart, cycle — never collapse them.
*Phase 2 — fetch_history() / warm_up() / get_candles() split*
One-time historical fill (startup), gap-fill on restart, and per-cycle incremental fetch have
different cost, frequency, and failure modes. Collapsing them → full historical fetch every cycle
(§1.12 violation), or stale data on restart, or blocking the live loop with minutes of API calls.
Each function is a different contract; sharing implementation is fine, sharing call sites is not.

### Verification failing closed is the system succeeding.
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

### Grouped spec conditions are one score, not gates in disguise.
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

### Test the judge with defendants of known guilt.
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

### A clean FAIL with reasons is a deliverable.
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

### Tests assert what is, not what the law says.
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
