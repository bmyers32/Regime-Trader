"""
TRADING-RULES §5: the GateReport artifact consumed by Phase 11's live gate and, later,
the Phase 9 /backtests dashboard page. Assembles gates 3 (walk-forward), 4 (parameter
stability), 6 (Monte Carlo) built by this session's Track 2 harness.

Gate 5 (per-regime attribution, TRADING-RULES §5.5) is explicitly OUT of this harness
-- deferred to Session B reporting per HANDOFF.md -- and every report carries a note
saying so, so that omission is visible at read time rather than a silent gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from bot.backtest.monte_carlo import MonteCarloResult
from bot.backtest.stability import StabilityResult
from bot.backtest.walk_forward import WalkForwardReport

_GATE_5_DEFERRED_NOTE = (
    "Gate 5 (per-regime attribution, TRADING-RULES §5.5) is deferred to Session B "
    "reporting -- not computed by this harness (HANDOFF.md Track 2 scope note)."
)


@dataclass
class GateResult:
    gate: str
    passed: bool
    reason: str
    detail: object = None


@dataclass
class GateReport:
    instrument: str
    strategy: str
    generated_at: datetime
    gates: list[GateResult] = field(default_factory=list)
    passed: bool = False
    notes: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def build_gate_report(
    instrument: str,
    strategy: str,
    walk_forward_result: WalkForwardReport,
    stability_result: StabilityResult,
    monte_carlo_result: MonteCarloResult,
    notes: list[str] | None = None,
    generated_at: datetime | None = None,
) -> GateReport:
    gates = [
        GateResult(
            gate="3_walk_forward",
            passed=walk_forward_result.passed,
            reason=walk_forward_result.reason,
            detail=walk_forward_result,
        ),
        GateResult(
            gate="4_stability",
            passed=stability_result.passed,
            reason=stability_result.reason,
            detail=stability_result,
        ),
        GateResult(
            gate="6_monte_carlo",
            passed=monte_carlo_result.passed,
            reason=monte_carlo_result.reason,
            detail=monte_carlo_result,
        ),
    ]

    all_notes = list(notes or [])
    all_notes.append(_GATE_5_DEFERRED_NOTE)

    # Gates 4 and 6 each carry their own scoping limitation (StabilityResult's
    # perturbation scoping, MonteCarloResult's trade-independence assumption) --
    # surfaced together here so a reader of the overall report sees both without
    # having to open each gate's detail object. getattr guards duck-typed stubs
    # (e.g. test doubles) that don't carry a limitations field.
    limitations = [
        note
        for note in (getattr(stability_result, "limitations", None), getattr(monte_carlo_result, "limitations", None))
        if note
    ]

    return GateReport(
        instrument=instrument,
        strategy=strategy,
        generated_at=generated_at or datetime.now(timezone.utc),
        gates=gates,
        passed=all(g.passed for g in gates),
        notes=all_notes,
        limitations=limitations,
    )


def gate_report_to_dict(report: GateReport) -> dict:
    """JSON-safe summary (gate `detail` payloads carry pandas/dataclass objects that
    are not JSON-serializable -- full diagnostics stay on the in-memory GateReport;
    wiring a richer serialization is Phase 9 dashboard scope, not this harness's)."""
    return {
        "instrument": report.instrument,
        "strategy": report.strategy,
        "generated_at": report.generated_at.isoformat(),
        "passed": report.passed,
        "gates": [{"gate": g.gate, "passed": g.passed, "reason": g.reason} for g in report.gates],
        "notes": report.notes,
        "limitations": report.limitations,
    }


def render_text(report: GateReport) -> str:
    """Human-readable rendering for CLI/session output -- every verdict line carries
    its own reason string, and every reason string carries its own numbers and
    thresholds (HANDOFF.md Track 2 disposition: no bare pass/fail booleans)."""
    lines = [
        f"GateReport: {report.instrument} / {report.strategy}",
        f"Generated:  {report.generated_at.isoformat()}",
        f"OVERALL:    {'PASS' if report.passed else 'FAIL'}",
        "",
    ]
    for g in report.gates:
        lines.append(f"[{'PASS' if g.passed else 'FAIL'}] {g.gate}")
        lines.append(f"       {g.reason}")
    if report.notes:
        lines.append("")
        lines.append("Notes:")
        lines.extend(f"  - {note}" for note in report.notes)
    if report.limitations:
        lines.append("")
        lines.append("Limitations:")
        lines.extend(f"  - {note}" for note in report.limitations)
    return "\n".join(lines)
