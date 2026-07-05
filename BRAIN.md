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
