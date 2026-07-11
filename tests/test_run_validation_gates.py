"""
Unit tests for scripts/run_validation_gates.py's classify_threshold_regime_general
(Phase 7, squeeze_breakout). This function has no prior test coverage -- neither does
the 2-component classify_threshold_regime it generalizes (range_reversion's Phase 6
harness), so this file closes that gap for both by exercising the general function
against range_reversion's own 2-component weight/threshold values (parity in
CLASSIFICATION MEANING, not identical text -- the general function reports the literal
minimal covering subset(s) rather than RR's fixed OR/ASYMMETRIC/AND vocabulary, a
deliberate choice recorded in the function's own docstring since a fixed 3-way
vocabulary only fits exactly 2 components) plus 3- and 4-component scenarios matching
squeeze_breakout's actual shape.

scripts/ is not a package (no __init__.py) -- imported via sys.path insertion, same
pattern scripts/gross_vs_net.py itself already uses to import run_validation_gates.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from run_validation_gates import classify_threshold_regime, classify_threshold_regime_general  # noqa: E402


# ---------------------------------------------------------------------------
# 2-component parity (range_reversion's own weight/threshold shape)
# ---------------------------------------------------------------------------

class TestTwoComponentParity:
    def test_or_region(self) -> None:
        weights = {"a": 0.5, "b": 0.5}
        assert classify_threshold_regime(weights, 0.3) == "OR (either component alone fires)"
        general = classify_threshold_regime_general(weights, 0.3)
        assert general.startswith("OR")
        assert "a" in general and "b" in general

    def test_and_region_symmetric_weights(self) -> None:
        weights = {"a": 0.5, "b": 0.5}
        assert classify_threshold_regime(weights, 0.55) == "AND (both components required)"
        general = classify_threshold_regime_general(weights, 0.55)
        assert general.startswith("AND (all 2 components required")

    def test_asymmetric_region_only_heavier_component_alone_suffices(self) -> None:
        """RR's own 'ASYMMETRIC' label collapses to the general function's literal
        report: exactly one minimal covering subset, containing only the
        heavier-weighted component -- the SAME classification, described precisely
        rather than via a fixed vocabulary word."""
        weights = {"a": 0.6, "b": 0.4}
        assert classify_threshold_regime(weights, 0.55) == (
            "ASYMMETRIC (only the heavier-weighted component can fire alone)"
        )
        general = classify_threshold_regime_general(weights, 0.55)
        assert "a" in general
        assert "b" not in general.split(":", 1)[-1]  # b never appears in a firing subset

    def test_and_region_skewed_weights_high_threshold(self) -> None:
        weights = {"a": 0.6, "b": 0.4}
        assert classify_threshold_regime(weights, 0.9) == "AND (both components required)"
        general = classify_threshold_regime_general(weights, 0.9)
        assert general.startswith("AND (all 2 components required")


# ---------------------------------------------------------------------------
# 3- and 4-component scenarios matching squeeze_breakout's actual shape
# ---------------------------------------------------------------------------

class TestGeneralNAryClassification:
    def test_three_equal_weight_components_or_region(self) -> None:
        weights = {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}
        general = classify_threshold_regime_general(weights, 0.2)
        assert general.startswith("OR")
        assert "a" in general and "b" in general and "c" in general

    def test_three_equal_weight_components_and_region(self) -> None:
        weights = {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}
        general = classify_threshold_regime_general(weights, 0.95)
        assert general.startswith("AND (all 3 components required")

    def test_squeeze_breakout_default_weights_at_provisional_threshold(self) -> None:
        """squeeze_breakout's own DISPOSITION 2 provisional default (instruments.yaml):
        the 3 real triggers form the ONLY minimal covering subset at
        entry_threshold=0.85 -- tick_volume never appears in it, matching the
        design intent that it can nudge a near-1.0 score but never substitute for a
        missing real trigger."""
        weights = {"close_beyond_band": 0.30, "atr_expansion": 0.30, "body_pct": 0.30, "tick_volume": 0.10}
        general = classify_threshold_regime_general(weights, 0.85)
        assert general.startswith("N-of-4")
        subset_part = general.split(":", 1)[-1]
        assert "tick_volume" not in subset_part
        assert "close_beyond_band" in subset_part
        assert "atr_expansion" in subset_part
        assert "body_pct" in subset_part

    def test_squeeze_breakout_default_weights_tick_volume_can_join_a_near_miss(self) -> None:
        """At a threshold BELOW the 3-real-trigger sum (0.3+0.3+0.3), any 2-of-3 real
        triggers PLUS tick_volume (0.3+0.3+0.1=0.7) becomes a genuine minimal firing
        subset alongside any 2 real triggers alone -- proving tick_volume is not
        inert, just never load-bearing at the actual shipped threshold (see the test
        above)."""
        weights = {"close_beyond_band": 0.30, "atr_expansion": 0.30, "body_pct": 0.30, "tick_volume": 0.10}
        general = classify_threshold_regime_general(weights, 0.65)
        assert general.startswith("N-of-4")
        subset_part = general.split(":", 1)[-1]
        assert "tick_volume" in subset_part  # appears in at least one minimal subset here

    def test_unreachable_threshold_above_full_sum(self) -> None:
        weights = {"a": 0.3, "b": 0.3, "c": 0.3, "d": 0.1}
        assert classify_threshold_regime_general(weights, 1.5) == (
            "UNREACHABLE (no subset of components can clear this threshold)"
        )

    def test_threshold_at_or_below_zero_every_single_component_covers(self) -> None:
        weights = {"a": 0.5, "b": 0.5}
        general = classify_threshold_regime_general(weights, 0.0)
        assert general.startswith("OR")
