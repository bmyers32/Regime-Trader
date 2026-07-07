from __future__ import annotations

import json
from datetime import datetime, timezone

from bot.backtest.gate_report import build_gate_report, gate_report_to_dict, render_text
from bot.backtest.monte_carlo import MonteCarloResult
from bot.backtest.stability import StabilityResult
from bot.backtest.walk_forward import WalkForwardReport


def _report(wf_passed: bool, stability_passed: bool, mc_passed: bool):
    return build_gate_report(
        instrument="EUR_USD",
        strategy="trend_pullback",
        walk_forward_result=WalkForwardReport(passed=wf_passed, reason="wf_reason"),
        stability_result=StabilityResult(passed=stability_passed, reason="stability_reason"),
        monte_carlo_result=MonteCarloResult(passed=mc_passed, reason="mc_reason"),
        generated_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
    )


def test_overall_passed_requires_all_gates():
    assert _report(True, True, True).passed
    assert not _report(True, True, False).passed
    assert not _report(False, True, True).passed
    assert not _report(True, False, True).passed


def test_gate_order_and_reasons_preserved():
    report = _report(True, True, True)
    assert [g.gate for g in report.gates] == ["3_walk_forward", "4_stability", "6_monte_carlo"]
    assert report.gates[0].reason == "wf_reason"


def test_gate5_deferred_note_always_present():
    report = _report(True, True, True)
    assert any("Gate 5" in note for note in report.notes)


def test_to_dict_is_json_serializable_and_shaped():
    report = _report(True, False, True)
    d = gate_report_to_dict(report)
    serialized = json.dumps(d)  # must not raise

    assert json.loads(serialized)["passed"] is False
    assert d["instrument"] == "EUR_USD"
    assert d["generated_at"] == "2026-07-07T00:00:00+00:00"
    assert len(d["gates"]) == 3
    assert d["limitations"] == report.limitations


def test_limitations_aggregated_from_gates_4_and_6():
    report = _report(True, True, True)

    assert len(report.limitations) == 2
    assert any("one-at-a-time" in note.lower() for note in report.limitations)
    assert any("independent draws" in note.lower() for note in report.limitations)


def test_render_text_shows_reasons_not_bare_booleans():
    report = _report(True, False, True)
    text = render_text(report)

    assert "PASS] 3_walk_forward" in text
    assert "FAIL] 4_stability" in text
    assert "stability_reason" in text  # every verdict line's reason is shown, not just PASS/FAIL
    assert "Limitations:" in text
    assert "Notes:" in text
