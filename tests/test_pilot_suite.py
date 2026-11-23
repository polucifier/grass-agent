"""Pilot composition, naming, and assertion coverage (T013).

The pilot is only trustworthy if every declared output is named in its prompt,
carries the pilot_ prefix, and has at least one assertion. Composition is part
of the contract: exactly ten cases, at least four per benchmark tier, and at
least four multi-step or mixed raster/vector workflows.
"""

import json
from pathlib import Path

import pytest

from grass_agent.semantic import (
    PILOT_CASE_COUNT,
    load_expectations,
    load_pilot_suite,
    pilot_cases,
    validate_pilot_suite,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SUITE_PATH = REPO_ROOT / "benchmarks" / "benchmark_prompts_pilot10.json"
EXPECTATIONS_PATH = REPO_ROOT / "benchmarks" / "pilot_expectations.json"


@pytest.fixture(scope="module")
def suite():
    return load_pilot_suite(SUITE_PATH)


@pytest.fixture(scope="module")
def expectations():
    return load_expectations(EXPECTATIONS_PATH)


def test_pilot_has_exactly_ten_cases(suite):
    cases = pilot_cases(suite)
    assert len(cases) == PILOT_CASE_COUNT == 10
    assert len({c["id"] for c in cases}) == 10


def test_pilot_tier_split_is_at_least_four_four(suite):
    cases = pilot_cases(suite)
    tier1 = [c for c in cases if c["tier"] == 1]
    tier2 = [c for c in cases if c["tier"] == 2]
    assert len(tier1) >= 4
    assert len(tier2) >= 4
    assert len(tier1) + len(tier2) == 10


def test_pilot_has_at_least_four_multi_step_or_mixed_cases(suite):
    cases = pilot_cases(suite)
    multi = [
        c
        for c in cases
        if c["category"] == "multi_step"
        or {o["type"] for o in c["outputs"]} == {"raster", "vector"}
    ]
    assert len(multi) >= 4


def test_both_raster_and_vector_outputs_are_covered(suite):
    types = {o["type"] for c in pilot_cases(suite) for o in c["outputs"]}
    assert types == {"raster", "vector"}


def test_every_output_name_follows_the_pilot_convention_and_is_in_the_prompt(suite):
    for case in pilot_cases(suite):
        prompt = case["prompt"]
        for output in case["outputs"]:
            assert output["name"].startswith("pilot_")
            assert output["name"] in prompt
        assert prompt.rstrip().endswith("Do not change the computational region.")


def test_every_declared_output_has_at_least_one_assertion(suite):
    for case in pilot_cases(suite):
        declared = {o["name"] for o in case["outputs"]}
        asserted = {a["output"] for a in case["assertions"]}
        assert declared <= asserted


def test_every_case_declares_outputs_and_assertions(suite):
    for case in pilot_cases(suite):
        assert case["outputs"]
        assert case["assertions"]
        assert case["auxiliary_inputs"] == []
        assert case["source_id"].startswith("tc_")


def test_suite_passes_full_validation(suite, expectations):
    violations = validate_pilot_suite(
        suite,
        expectations,
        reference_dir=REPO_ROOT / "benchmarks" / "pilot_reference",
    )
    assert violations == []


def test_expectations_cover_every_output(suite, expectations):
    for case in pilot_cases(suite):
        assert expectations.case(case["id"]) is not None
        for output in case["outputs"]:
            assert expectations.output(case["id"], output["name"]) is not None


def test_display_only_case_is_rejected_as_a_composition_violation(tmp_path):
    """FR-007a exclusion lint, with a deliberately broken fixture."""
    suite = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    suite["test_cases"].append(
        {
            "id": "pilot_tc_99",
            "source_id": "tc_04",
            "source_suite": "tier1",
            "tier": 1,
            "category": "single_tool",
            "prompt": "Display the elevation raster on the active monitor.",
            "expected_tools": ["d.rast"],
            "auxiliary_inputs": [],
            "outputs": [],
            "assertions": [],
        }
    )
    violations = validate_pilot_suite(suite)
    assert any("composition violation" in v for v in violations)
