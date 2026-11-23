"""ManualCard budget, priority, and fail-closed behavior (T010)."""

from __future__ import annotations

from pathlib import Path

import pytest

from grass_agent.kb_parse import parse_module
from grass_agent.manual_context import (
    ManualBudgetExceeded,
    build_card,
    estimate_tokens,
    manual_budget,
    render_manual_cards,
)
from rag_retriever import ToolDoc

FIXTURES = Path(__file__).parent / "fixtures" / "kb"


def _record(name: str):
    xml = FIXTURES / "xml" / f"{name}.xml"
    return parse_module(
        name,
        markdown_path=str(FIXTURES / "markdown" / f"{name}.md"),
        xml_text=xml.read_text(encoding="utf-8") if xml.is_file() else "",
    )


def _records():
    return [_record("r.viewshed"), _record("v.clean"), _record("r.reclass")]


def test_budget_is_45_percent_of_context():
    assert manual_budget(8192) == 3686
    assert manual_budget(16384) == 7372


def test_token_estimate_is_conservative():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 2  # ceil(4/3.5 * 1.1)


def test_card_estimates_are_reported_and_representative_cards_fit_the_target():
    cards = [build_card(record) for record in _records()]
    assert all(card.token_estimate > 0 for card in cards)
    viewshed = next(card for card in cards if card.tool == "r.viewshed")
    clean = next(card for card in cards if card.tool == "v.clean")
    assert 250 <= viewshed.token_estimate <= 600
    assert 250 <= clean.token_estimate <= 600


def test_render_priority_order():
    card = build_card(_record("v.clean"))
    text = card.rendered
    assert text.index("API:") < text.index("Flags:")
    assert text.index("Flags:") < text.index("Parameters:")
    assert text.index("Parameters:") < text.index("Constraints:")
    assert text.index("Constraints:") < text.index("Examples:")


def test_signature_flags_and_enums_are_never_omitted():
    card = build_card(_record("v.clean"))
    assert card.signature in card.rendered
    for flag in card.flags:
        assert flag in card.rendered
    assert "rmdupl" in card.rendered
    assert "snap" in card.rendered
    assert all("Flags" not in omission for omission in card.omissions)
    assert all("Parameters" not in omission for omission in card.omissions)


def test_optional_prose_omissions_are_named():
    card = build_card(_record("r.viewshed"))
    assert "DESCRIPTION" in card.omissions
    assert "[omitted: DESCRIPTION]" in card.rendered


def test_same_tool_is_rendered_once():
    records = _records()
    rendered = render_manual_cards(records + records, budget=3686)
    names = [card.tool for card in rendered.cards]
    assert names == ["r.viewshed", "v.clean", "r.reclass"]


def test_global_budget_is_enforced():
    rendered = render_manual_cards(_records(), budget=3686)
    assert rendered.tokens <= rendered.budget


def test_alternatives_are_compacted_before_mandatory_drops():
    records = [_record("r.reclass")]
    alternatives = {
        "r.reclass": [
            {"name": "r.recode", "note": "rule-based recoding"},
            {"name": "r.mapcalc", "note": "expression-based classification"},
        ]
    }
    full = render_manual_cards(records, budget=3686, alternatives=alternatives)
    assert len(full.cards[0].alternatives) == 2
    tight = render_manual_cards(
        records, budget=max(1, full.tokens - 1), alternatives=alternatives
    )
    assert len(tight.cards[0].alternatives) <= 2


def test_mandatory_overflow_fails_closed_with_a_named_error():
    with pytest.raises(ManualBudgetExceeded) as excinfo:
        render_manual_cards(_records(), budget=10)
    assert excinfo.value.tools
    assert "manual card budget exceeded" in str(excinfo.value)
    assert "r.viewshed" in str(excinfo.value)


def test_examples_are_dropped_before_mandatory_sections():
    record = _record("r.viewshed")
    full = build_card(record)
    without_examples = build_card(record, include_examples=False)
    assert full.token_estimate > without_examples.token_estimate
    assert "EXAMPLES" in without_examples.omissions
    assert without_examples.signature == full.signature


def test_module_without_flags_or_enums_renders_cleanly():
    doc = ToolDoc(
        name="g.region",
        category="g",
        description="Manage the region",
        signature="grass.tools.Tools.g_region(raster=None, flags=None)",
        example="",
        params={
            "raster": {"type": "str", "required": False, "default": None},
            "flags": {"type": "str", "required": False, "default": None},
        },
        similarity=0.0,
    )
    card = build_card(doc)
    assert "Flags:" not in card.rendered
    assert "Parameters:" in card.rendered
    assert card.token_estimate > 0


def test_deterministic_rendering():
    first = render_manual_cards(_records(), budget=3686)
    second = render_manual_cards(_records(), budget=3686)
    assert first.text == second.text
    assert first.card_tokens == second.card_tokens
