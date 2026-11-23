"""Markdown/XML parsing, merge, and closed-enum classification (T008)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from grass_agent.kb_parse import (
    is_closed_enum_values,
    merge_records,
    parse_html,
    parse_markdown,
    parse_module,
    parse_xml,
)

FIXTURES = Path(__file__).parent / "fixtures" / "kb"


def _md(name: str) -> Path:
    return FIXTURES / "markdown" / f"{name}.md"


def _xml(name: str) -> str:
    return (FIXTURES / "xml" / f"{name}.xml").read_text(encoding="utf-8")


def test_markdown_signature_types_defaults_and_sections():
    parsed = parse_markdown(_md("r.viewshed"))
    assert parsed.name == "r.viewshed"
    assert parsed.signature.startswith("grass.tools.Tools.r_viewshed(")
    assert parsed.params["input"]["required"] is True
    assert parsed.params["observer_elevation"]["default"] == "1.75"
    assert "DESCRIPTION" in parsed.sections
    assert "NOTES" in parsed.sections
    assert "EXAMPLES" in parsed.sections


def test_tab_deduplication_keeps_one_canonical_section():
    parsed = parse_markdown(_md("v.clean"))
    # The Command line / grass.tools / grass.script tabs collapse to one
    # canonical PARAMETERS section rather than three.
    assert len(parsed.sections["PARAMETERS"]) == 1
    assert "grass.script.run_command" not in parsed.sections["PARAMETERS"][0]["text"]


def test_xml_flags_and_finite_values():
    parsed = parse_xml(_xml("v.clean"))
    assert {flag["flag"] for flag in parsed.flags} == {"b", "c"}
    assert [option["value"] for option in parsed.options["tool"]] == [
        "break",
        "snap",
        "rmdupl",
        "rmdangle",
    ]
    assert parsed.params["tool"]["multiple"] is True


def test_range_values_are_not_closed_enums():
    parsed = parse_xml(_xml("r.viewshed"))
    assert "direction_range" in parsed.params
    assert "direction_range" not in parsed.options


def test_merge_uses_markdown_names_and_xml_metadata():
    record = parse_module(
        "v.clean",
        markdown_path=str(_md("v.clean")),
        xml_text=_xml("v.clean"),
    )
    assert record["params"]["tool"]["required"] is True
    assert [option["value"] for option in record["options"]["tool"]] == [
        "break",
        "snap",
        "rmdupl",
        "rmdangle",
    ]
    assert record["xml_validated"] is True


def test_markdown_xml_name_mismatch_is_recorded_not_dropped():
    record = parse_module(
        "r.mismatch",
        markdown_path=str(_md("r.mismatch")),
        xml_text=_xml("r.mismatch"),
    )
    mismatches = record["source_mismatches"]
    assert any(
        item["parameter"] == "direction_range"
        and item["kind"] == "missing_in_markdown"
        for item in mismatches
    )
    assert "direction" in record["params"]
    assert "direction_range" not in record["params"]


def test_synthetic_flag_kwargs_are_always_present():
    record = parse_module("r.reclass", markdown_path=str(_md("r.reclass")))
    for name in ("flags", "overwrite", "verbose", "quiet", "superquiet"):
        assert name in record["params"]
        assert record["params"][name]["required"] is False


def test_ranges_free_text_paths_and_expressions_are_not_enums():
    assert not is_closed_enum_values("direction_range", ["0-360"])
    assert not is_closed_enum_values("rules", ["/tmp/rules.txt"])
    assert not is_closed_enum_values("output", ["result"])
    assert not is_closed_enum_values("expression", ["a = b + c"])
    assert is_closed_enum_values("tool", ["rmdupl", "snap"])


def test_markdown_finite_allowed_values_become_options():
    record = parse_module("v.clean", markdown_path=str(_md("v.clean")))
    assert {"rmdupl", "snap"} <= {
        option["value"] for option in record["options"]["tool"]
    }


def test_html_fallback_extracts_sections():
    parsed = parse_html(FIXTURES / "html" / "v.clean.html")
    assert parsed.name == "v.clean"
    assert "DESCRIPTION" in parsed.sections
    assert "rmdupl" in parsed.sections["NOTES"][0]["text"]


def test_json_persistence_shape_is_stable():
    record = parse_module(
        "r.viewshed",
        markdown_path=str(_md("r.viewshed")),
        xml_text=_xml("r.viewshed"),
    )
    encoded = json.dumps(record, sort_keys=True)
    assert "r.viewshed" in encoded
    assert "flags_json" not in record  # storage names are applied by kb_schema
