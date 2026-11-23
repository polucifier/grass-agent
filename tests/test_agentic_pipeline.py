"""Planned-mode orchestration: cards, dedupe, alternatives, fallback (T028)."""

from __future__ import annotations

import json

import pytest

from config import GenerationConfig
from code_generator import GrassCodeGenerator
from grass_agent.agentic import AgenticPipeline
from grass_agent.manual_context import ManualBudgetExceeded
from grass_agent.planner import Planner
from rag_retriever import ClosedEnumOption, ModuleFlag, ToolDoc

CODE = (
    "from grass.tools import Tools\n"
    "tools = Tools()\n"
    'tools.r_slope_aspect(input="elevation", output="slope")\n'
)


def _doc(name: str, category: str, description: str = "") -> ToolDoc:
    params = {
        "input": {"type": "str", "required": True, "description": "input map"},
        "output": {"type": "str", "required": True, "description": "output map"},
        "flags": {"type": "str", "required": False, "default": None},
        "overwrite": {"type": "bool", "required": False, "default": None},
        "verbose": {"type": "bool", "required": False, "default": None},
        "quiet": {"type": "bool", "required": False, "default": None},
        "superquiet": {"type": "bool", "required": False, "default": None},
    }
    sections = {"NOTES": [{"text": "Use the documented flags."}], "EXAMPLES": [{"text": f"{name} example"}]}
    return ToolDoc(
        name=name,
        category=category,
        description=description or f"{name} module",
        signature=f"grass.tools.Tools.{name.replace('.', '_')}(input, output, flags=None)",
        example="",
        params=params,
        similarity=0.0,
        flags=[ModuleFlag("b", "documented flag")],
        sections=sections,
        source="fixture",
        xml_validated=True,
    )


def _shortlist():
    return [
        _doc("r.slope.aspect", "r"),
        _doc("r.reclass", "r"),
        _doc("r.recode", "r"),
        _doc("r.mapcalc", "r"),
        _doc("r.to.vect", "r"),
        _doc("r.univar", "r"),
        _doc("r.mask", "r"),
        _doc("r.null", "r"),
        _doc("v.clean", "v"),
        _doc("v.buffer", "v"),
    ]


class _Retriever:
    def __init__(self, docs):
        self.docs = {doc.name: doc for doc in docs}
        self.shortlist_calls: list[int] = []

    def get_tool(self, name):
        return self.docs.get(name)

    def get_manual(self, name):
        return self.docs.get(name)

    def retrieve(self, query, embedding, k=5):
        return list(self.docs.values())[:k]

    def retrieve_shortlist(self, query, embedding, shortlist_k=12, embedding_model=""):
        from rag_retriever import CandidateShortlist

        self.shortlist_calls.append(shortlist_k)
        docs = self.retrieve(query, embedding, shortlist_k)
        return CandidateShortlist(
            query=query,
            candidates=docs,
            shortlist_shortfall=len(docs) < 8,
            shortlist_k=shortlist_k,
        )


def _config(**overrides):
    values = dict(
        model="fake:model",
        pipeline="planned",
        num_ctx=8192,
        shortlist_k=12,
        planner_timeout=2,
        rag_top_k=5,
    )
    values.update(overrides)
    return GenerationConfig(**values)


def _pipeline(provider, docs=None, **config_overrides):
    config = _config(**config_overrides)
    retriever = _Retriever(docs if docs is not None else _shortlist())
    generator = GrassCodeGenerator(config, provider, retriever)
    planner = Planner(provider, timeout=2, retriever=retriever)
    return (
        AgenticPipeline(config, provider, retriever, generator=generator, planner=planner),
        generator,
        retriever,
    )


def _plan_json(tools=("r.slope.aspect",)) -> str:
    steps = []
    for index, tool in enumerate(tools, start=1):
        steps.append(
            {
                "id": index,
                "intent": f"step {index}",
                "tool": tool,
                "inputs": ["elevation"] if index == 1 else [f"map{index - 1}"],
                "outputs": [f"map{index}"],
                "output_types": ["raster"],
                "constraints": [],
            }
        )
    return json.dumps({"steps": steps, "assumptions": []})


def test_planned_shortlist_uses_shortlist_k_12(fake_provider):
    fake_provider.responses = [_plan_json(), CODE]
    pipeline, _, retriever = _pipeline(fake_provider)
    result = pipeline.generate("slope", "", inventory_maps={"elevation"})
    assert retriever.shortlist_calls == [12]
    assert result.plan is not None
    assert result.planned_tools == ["r.slope.aspect"]
    assert result.plan_fallback is False


def test_plan_json_never_appears_in_final_code(fake_provider):
    fake_provider.responses = [_plan_json(), CODE]
    pipeline, _, _ = _pipeline(fake_provider)
    result = pipeline.generate("slope", "", inventory_maps={"elevation"})
    assert '"steps"' not in result.code
    assert "r.slope.aspect" in result.code or "r_slope_aspect" in result.code


def test_per_step_cards_are_deduplicated(fake_provider):
    fake_provider.responses = [_plan_json(("r.slope.aspect", "r.slope.aspect")), CODE]
    pipeline, _, _ = _pipeline(fake_provider)
    result = pipeline.generate("slope", "", inventory_maps={"elevation"})
    tools = [card.tool for card in result.manual_cards]
    assert tools.count("r.slope.aspect") == 1


def test_alternatives_are_limited_to_two_per_step(fake_provider):
    fake_provider.responses = [_plan_json(("r.reclass",)), CODE]
    pipeline, _, _ = _pipeline(fake_provider)
    result = pipeline.generate("reclass", "", inventory_maps={"elevation"})
    card = result.manual_cards[0]
    assert len(card.alternatives) <= 2
    assert any("r.recode" in alternative for alternative in card.alternatives)


def test_shortfall_is_recorded_with_fewer_than_eight(fake_provider):
    fake_provider.responses = [_plan_json(), CODE]
    pipeline, _, _ = _pipeline(fake_provider, docs=_shortlist()[:3])
    result = pipeline.generate("slope", "", inventory_maps={"elevation"})
    assert result.shortlist_shortfall is True


def test_zero_candidates_falls_back_to_manual_kb(fake_provider):
    fake_provider.responses = [CODE]
    pipeline, _, _ = _pipeline(fake_provider, docs=[])
    result = pipeline.generate("slope", "", inventory_maps={"elevation"})
    assert result.plan_fallback is True
    assert result.code.strip() == CODE.strip()


def test_invalid_plan_falls_back_without_a_plan(fake_provider):
    fake_provider.responses = ["not json", "still not json", CODE]
    pipeline, _, _ = _pipeline(fake_provider)
    result = pipeline.generate("slope", "", inventory_maps={"elevation"})
    assert result.plan_fallback is True
    assert result.plan is None
    assert result.plan_repair_count == 1
    assert result.planner_invocations == 2


def test_global_manual_budget_is_enforced(fake_provider):
    fake_provider.responses = [_plan_json(("r.slope.aspect", "r.reclass")), CODE]
    pipeline, _, _ = _pipeline(fake_provider, manual_context_tokens=10)
    with pytest.raises(ManualBudgetExceeded):
        pipeline.generate("slope", "", inventory_maps={"elevation"})


def test_diagnostics_are_populated(fake_provider):
    fake_provider.responses = [_plan_json(), CODE]
    pipeline, generator, _ = _pipeline(fake_provider)
    result = generator.generate_result("slope", inventory_block="", agentic_pipeline=pipeline)
    assert generator.last_generation_result is result
    assert generator.last_manual_cards
    assert generator.last_user_message
    assert generator.last_system_prompt
    assert result.manual_tokens > 0
