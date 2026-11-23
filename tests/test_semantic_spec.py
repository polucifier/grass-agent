"""Pilot and assertion schema validation (T011).

A malformed pilot must fail with a named violation before any model runs: an
oracle that silently skips a case, or accepts an assertion against an output
that was never declared, measures the wrong thing.
"""

import json

import pytest

from grass_agent.semantic import (
    AssertionSpec,
    CaseSemantics,
    OutputSpec,
    PilotExpectations,
    build_semantic_spec,
    case_semantics,
    resolve_assertions,
    validate_pilot_suite,
)


def _case(case_id="pilot_tc_01", **overrides):
    case = {
        "id": case_id,
        "source_id": "tc_01",
        "source_suite": "tier1",
        "tier": 1,
        "category": "single_tool",
        "prompt": (
            "Create a buffer and write the vector map pilot_streams_buffer. "
            "Do not change the computational region."
        ),
        "expected_tools": ["v.buffer"],
        "auxiliary_inputs": [],
        "outputs": [{"name": "pilot_streams_buffer", "type": "vector"}],
        "assertions": [
            {"output": "pilot_streams_buffer", "check": "feature_count", "min": 1},
            {"output": "pilot_streams_buffer", "check": "geometry_type",
             "expected": "area"},
        ],
    }
    case.update(overrides)
    return case


def _suite(*cases):
    return {"version": "1.0.0", "name": "test", "test_cases": list(cases)}


def test_case_semantics_round_trips_the_declaration():
    semantics = case_semantics(_case())
    assert isinstance(semantics, CaseSemantics)
    assert semantics.outputs == [OutputSpec("pilot_streams_buffer", "vector")]
    assert semantics.assertions[0].check == "feature_count"


def test_unknown_check_is_rejected():
    case = _case(
        assertions=[{"output": "pilot_streams_buffer", "check": "vibes"}]
    )
    violations = validate_pilot_suite(_suite(case))
    assert any("unknown check" in v and "vibes" in v for v in violations)


def test_assertion_naming_an_undeclared_output_is_rejected():
    case = _case(
        assertions=[{"output": "pilot_missing", "check": "feature_count"}]
    )
    violations = validate_pilot_suite(_suite(case))
    assert any("undeclared output" in v and "pilot_missing" in v for v in violations)


def test_duplicate_output_names_are_rejected():
    case = _case(
        outputs=[
            {"name": "pilot_streams_buffer", "type": "vector"},
            {"name": "pilot_streams_buffer", "type": "vector"},
        ]
    )
    violations = validate_pilot_suite(_suite(case))
    assert any("duplicate output names" in v for v in violations)


def test_output_absent_from_the_prompt_is_rejected():
    case = _case(
        prompt="Create a buffer. Do not change the computational region."
    )
    violations = validate_pilot_suite(_suite(case))
    assert any("does not appear verbatim in the prompt" in v for v in violations)


def test_output_without_the_pilot_prefix_is_rejected():
    case = _case(
        outputs=[{"name": "streams_buffer", "type": "vector"}],
        assertions=[{"output": "streams_buffer", "check": "feature_count"}],
        prompt="Create a buffer and write streams_buffer. Do not change the "
               "computational region.",
    )
    violations = validate_pilot_suite(_suite(case))
    assert any("does not start with 'pilot_'" in v for v in violations)


def test_display_only_case_is_a_composition_violation():
    """FR-007a: no persistent output means no execution success is possible."""
    case = _case(
        outputs=[],
        assertions=[],
        expected_tools=["d.rast"],
        prompt="Display the elevation raster.",
    )
    violations = validate_pilot_suite(_suite(case))
    assert any("composition violation" in v for v in violations)


def test_expected_source_must_be_reference():
    case = _case(
        assertions=[
            {"output": "pilot_streams_buffer", "check": "feature_count",
             "expected_source": "candidate"}
        ]
    )
    violations = validate_pilot_suite(_suite(case))
    assert any("only 'reference' is admissible" in v for v in violations)


def test_non_pilot_case_declares_no_semantics():
    """A normal 40-case benchmark entry has no outputs/assertions."""
    raw = {
        "id": "tc_01",
        "category": "single_tool",
        "prompt": "Create a 200-meter buffer.",
        "expected_tools": ["v.buffer"],
    }
    semantics = case_semantics(raw)
    assert semantics.outputs == []
    assert semantics.assertions == []


def test_resolve_assertions_refuses_candidate_values():
    semantics = CaseSemantics(
        case_id="pilot_tc_01",
        outputs=[OutputSpec("pilot_x", "raster")],
        assertions=[
            AssertionSpec(
                output="pilot_x",
                check="mean",
                expected_source="candidate",
            )
        ],
    )
    with pytest.raises(ValueError, match="reference"):
        resolve_assertions(semantics, None)


def test_resolve_assertions_uses_reference_values_and_defaults():
    semantics = CaseSemantics(
        case_id="pilot_tc_01",
        outputs=[OutputSpec("pilot_x", "raster"), OutputSpec("pilot_v", "vector")],
        assertions=[
            AssertionSpec("pilot_x", "non_null_count"),
            AssertionSpec("pilot_x", "value_range"),
            AssertionSpec("pilot_x", "mean"),
            AssertionSpec("pilot_v", "feature_count"),
            AssertionSpec("pilot_v", "geometry_type"),
            AssertionSpec("pilot_v", "required_columns", columns=["cat"]),
        ],
    )
    expectations = {
        "outputs": {
            "pilot_x": {"type": "raster", "n": 10, "min": 1.0, "max": 9.0,
                        "mean": 5.0},
            "pilot_v": {"type": "vector", "geometry": "line",
                        "feature_count": 3, "columns": ["cat"]},
        }
    }
    resolved = resolve_assertions(semantics, expectations)
    by_check = {a["check"]: a for a in resolved}
    assert by_check["non_null_count"]["min"] == 1
    assert by_check["value_range"] == {
        "output": "pilot_x", "check": "value_range",
        "min_value": 1.0, "max": 9.0,
    }
    assert by_check["mean"]["expected"] == 5.0
    assert by_check["mean"]["tolerance"] == pytest.approx(0.01)
    assert by_check["feature_count"]["min"] == 1
    assert by_check["geometry_type"]["expected"] == "line"
    assert by_check["required_columns"]["columns"] == ["cat"]


def test_build_semantic_spec_shape(tmp_path):
    suite = json.loads(json.dumps(_suite(_case())))
    expectations = PilotExpectations(
        grass_version="8.5.0",
        cases={
            "pilot_tc_01": {
                "outputs": {
                    "pilot_streams_buffer": {
                        "type": "vector",
                        "geometry": "area",
                        "feature_count": 100,
                        "columns": [],
                    }
                }
            }
        },
    )
    spec = build_semantic_spec(
        suite["test_cases"][0], expectations, query_timeout_s=7, probe_timeout_s=11
    )
    assert spec["schema_version"] == 1
    assert spec["case_id"] == "pilot_tc_01"
    assert spec["query_timeout_s"] == 7
    assert spec["probe_timeout_s"] == 11
    assert spec["outputs"][0]["name"] == "pilot_streams_buffer"
    assert spec["assertions"][1]["expected"] == "area"
