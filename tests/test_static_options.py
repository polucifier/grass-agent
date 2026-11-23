"""Strict closed-enum validation is gated to the new pipeline modes (T011)."""

from __future__ import annotations

import pytest

from code_generator import validate_api
from rag_retriever import ClosedEnumOption, ModuleFlag, ToolDoc


def _viewshed() -> ToolDoc:
    return ToolDoc(
        name="r.viewshed",
        category="r",
        description="Viewshed",
        signature="grass.tools.Tools.r_viewshed(input, output, coordinates, flags=None)",
        example="",
        params={
            "input": {"type": "str", "required": True},
            "output": {"type": "str", "required": True},
            "coordinates": {"type": "str", "required": True},
            "direction_range": {"type": "str", "required": False},
            "flags": {"type": "str", "required": False},
        },
        similarity=0.0,
        flags=[
            ModuleFlag("b", "binary visibility"),
            ModuleFlag("c", "curvature"),
            ModuleFlag("e", "elevation difference"),
            ModuleFlag("r", "refraction"),
        ],
    )


def _clean() -> ToolDoc:
    return ToolDoc(
        name="v.clean",
        category="v",
        description="Clean topology",
        signature="grass.tools.Tools.v_clean(input, output, tool, flags=None)",
        example="",
        params={
            "input": {"type": "str", "required": True},
            "output": {"type": "str", "required": True},
            "tool": {"type": "str", "required": True},
            "threshold": {"type": "str", "required": False},
            "flags": {"type": "str", "required": False},
        },
        similarity=0.0,
        flags=[ModuleFlag("b", "no topology"), ModuleFlag("c", "combine")],
        options={
            "tool": [
                ClosedEnumOption("tool", "break"),
                ClosedEnumOption("tool", "snap"),
                ClosedEnumOption("tool", "rmdupl"),
            ]
        },
    )


class _Retriever:
    def __init__(self):
        self.docs = {doc.name: doc for doc in (_viewshed(), _clean())}

    def get_tool(self, name):
        return self.docs.get(name)


VIEWSHED_OK = (
    'tools.r_viewshed(input="elevation", output="out", '
    'coordinates="0,0", flags="b")'
)
CLEAN_BAD = (
    'tools.v_clean(input="roads", output="clean", tool="rm_duplicates")'
)


def test_flags_are_accepted_in_new_modes():
    assert validate_api(VIEWSHED_OK, _Retriever(), pipeline="manual-kb") == []
    assert validate_api(VIEWSHED_OK, _Retriever(), pipeline="planned") == []


def test_invalid_flag_is_rejected_in_new_modes():
    code = VIEWSHED_OK.replace('flags="b"', 'flags="z"')
    issues = validate_api(code, _Retriever(), pipeline="manual-kb")
    assert any("invalid flag" in issue for issue in issues)


def test_invalid_enum_is_rejected_with_legal_values():
    issues = validate_api(CLEAN_BAD, _Retriever(), pipeline="manual-kb")
    assert issues
    message = " ".join(issues)
    assert "rm_duplicates" in message
    assert "rmdupl" in message
    assert "snap" in message


def test_list_enums_are_split_on_commas():
    code = (
        'tools.v_clean(input="roads", output="clean", tool="rmdupl,snap")'
    )
    assert validate_api(code, _Retriever(), pipeline="manual-kb") == []


def test_free_text_map_names_ranges_and_paths_are_not_rejected():
    # direction_range has no finite options; a range-looking string is free text.
    code = (
        'tools.r_viewshed(input="elevation", output="out", '
        'coordinates="0,0", direction_range="0-360")'
    )
    assert validate_api(code, _Retriever(), pipeline="manual-kb") == []
    path_code = (
        'tools.v_clean(input="roads", output="clean", tool="rmdupl", '
        'threshold="thresholds.txt")'
    )
    # threshold has no closed options in this record, so it is free text.
    assert validate_api(path_code, _Retriever(), pipeline="manual-kb") == []


def test_legacy_default_behavior_is_unchanged():
    assert validate_api(CLEAN_BAD, _Retriever()) == []
    assert validate_api(CLEAN_BAD, _Retriever(), pipeline="legacy") == []
    assert validate_api(CLEAN_BAD, _Retriever(), strict_options=False) == []


def test_new_modes_cannot_disable_strict_validation():
    issues = validate_api(
        CLEAN_BAD, _Retriever(), strict_options=False, pipeline="manual-kb"
    )
    assert issues
    issues = validate_api(
        CLEAN_BAD, _Retriever(), strict_options=False, pipeline="planned"
    )
    assert issues


def test_legacy_opt_in_enables_strict_validation():
    issues = validate_api(CLEAN_BAD, _Retriever(), strict_options=True)
    assert issues


def test_strict_options_is_rejected_with_a_new_pipeline():
    from benchmarks import run_gate2

    code = run_gate2.main(["--pipeline", "manual-kb", "--strict-options"])
    assert code == 2
    code = run_gate2.main(["--pipeline", "planned", "--strict-options"])
    assert code == 2


def test_pipeline_and_budget_validation_is_argument_error():
    from benchmarks import run_gate2

    assert run_gate2.main(["--pipeline", "bogus"]) == 2
    assert run_gate2.main(["--manual-context-tokens", "0"]) == 2
    assert run_gate2.main(["--num-ctx", "8192", "--manual-context-tokens", "6000"]) == 2
    assert run_gate2.main(["--planner-timeout", "0"]) == 2


def test_planner_model_is_validated_only_in_planned_mode():
    from benchmarks import run_gate2

    planner_args = run_gate2.build_parser().parse_args(
        ["--pipeline", "planned", "--planner-model", "not-approved:1b"]
    )
    assert run_gate2.resolve_config(planner_args).config_errors()

    manual_args = run_gate2.build_parser().parse_args(
        ["--pipeline", "manual-kb", "--planner-model", "not-approved:1b"]
    )
    assert run_gate2.resolve_config(manual_args).config_errors() == []


def test_approved_planner_model_passes_in_planned_mode():
    from benchmarks import run_gate2

    args = run_gate2.build_parser().parse_args(
        ["--pipeline", "planned", "--planner-model", "qwen2.5-coder:14b"]
    )
    config = run_gate2.resolve_config(args)
    assert config.config_errors() == []
    assert config.resolved_planner_model() == "qwen2.5-coder:14b"
