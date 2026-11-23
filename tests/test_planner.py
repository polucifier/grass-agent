"""Candidate-constrained planner validation, repair, timeout, fallback (T027)."""

from __future__ import annotations

import json

import pytest

from grass_agent.planner import (
    ExecutionPlan,
    Planner,
    PlanStep,
    extract_json,
    validate_plan,
)
from rag_retriever import ToolDoc


def _doc(name: str, category: str = "r") -> ToolDoc:
    return ToolDoc(
        name=name,
        category=category,
        description=f"{name} module",
        signature=f"grass.tools.Tools.{name.replace('.', '_')}()",
        example="",
        params={},
        similarity=0.0,
    )


SHORTLIST = [
    _doc("r.slope.aspect"),
    _doc("r.reclass"),
    _doc("r.recode"),
    _doc("r.to.vect", "r"),
    _doc("v.buffer", "v"),
    _doc("v.clean", "v"),
    _doc("v.overwrite", "v"),
    _doc("r.mapcalc"),
    _doc("v.to.rast", "v"),
    _doc("r.univar"),
]


class _Retriever:
    def __init__(self, docs):
        self.docs = {doc.name: doc for doc in docs}

    def get_tool(self, name):
        return self.docs.get(name)

    def get_manual(self, name):
        return self.docs.get(name)

    def retrieve(self, query, embedding, k=5):
        return list(self.docs.values())[:k]

    def retrieve_shortlist(self, query, embedding, shortlist_k=12, embedding_model=""):
        from rag_retriever import CandidateShortlist

        if shortlist_k < 8 or shortlist_k > 12:
            raise ValueError("shortlist_k must be between 8 and 12")
        docs = self.retrieve(query, embedding, shortlist_k)
        return CandidateShortlist(
            query=query,
            candidates=docs,
            shortlist_shortfall=len(docs) < 8,
            shortlist_k=shortlist_k,
        )


def _valid_plan() -> dict:
    return {
        "steps": [
            {
                "id": 1,
                "intent": "Compute slope",
                "tool": "r.slope.aspect",
                "inputs": ["elevation"],
                "outputs": ["slope"],
                "output_types": ["raster"],
                "constraints": [],
            }
        ],
        "assumptions": [],
    }


def _planner(provider, docs=SHORTLIST):
    return Planner(provider, timeout=2, retriever=_Retriever(docs))


def test_shortlist_uses_twelve_and_rejects_out_of_range():
    retriever = _Retriever(SHORTLIST)
    shortlist = retriever.retrieve_shortlist("slope", [0.0], shortlist_k=12)
    assert shortlist.shortlist_k == 12
    assert len(shortlist.candidates) == 10
    assert shortlist.shortlist_shortfall is False
    with pytest.raises(ValueError):
        retriever.retrieve_shortlist("slope", [0.0], shortlist_k=7)
    with pytest.raises(ValueError):
        retriever.retrieve_shortlist("slope", [0.0], shortlist_k=13)


def test_shortfall_is_recorded_when_fewer_than_eight():
    shortlist = _Retriever(SHORTLIST[:3]).retrieve_shortlist("slope", [0.0])
    assert shortlist.shortlist_shortfall is True


def test_valid_plan_uses_one_invocation(fake_provider):
    fake_provider.responses = [json.dumps(_valid_plan())]
    outcome = _planner(fake_provider).create_plan(
        "slope from elevation", "", SHORTLIST, inventory_maps={"elevation"}
    )
    assert outcome.valid
    assert outcome.invocations == 1
    assert outcome.plan.tools == ["r.slope.aspect"]


def test_markdown_fences_are_tolerated(fake_provider):
    fake_provider.responses = ["```json\n" + json.dumps(_valid_plan()) + "\n```"]
    outcome = _planner(fake_provider).create_plan(
        "slope", "", SHORTLIST, inventory_maps={"elevation"}
    )
    assert outcome.valid


def test_invalid_json_gets_exactly_one_repair_then_valid(fake_provider):
    fake_provider.responses = ["not json at all", json.dumps(_valid_plan())]
    outcome = _planner(fake_provider).create_plan(
        "slope", "", SHORTLIST, inventory_maps={"elevation"}
    )
    assert outcome.valid
    assert outcome.plan_repair_count == 1
    assert outcome.invocations == 2
    assert outcome.plan.revision == 1


def test_invalid_json_twice_falls_back(fake_provider):
    fake_provider.responses = ["not json", "still not json"]
    outcome = _planner(fake_provider).create_plan(
        "slope", "", SHORTLIST, inventory_maps={"elevation"}
    )
    assert outcome.valid is False
    assert outcome.fallback is True
    assert outcome.invocations == 2
    assert outcome.plan is None


def test_timeout_is_treated_as_invalid(fake_provider):
    fake_provider.raise_timeout = True
    outcome = _planner(fake_provider).create_plan(
        "slope", "", SHORTLIST, inventory_maps={"elevation"}
    )
    assert outcome.valid is False
    assert outcome.fallback is True
    assert outcome.invocations == 2


def test_empty_plan_is_rejected():
    validation = validate_plan({"steps": []}, SHORTLIST)
    assert not validation.ok
    assert "no steps" in " ".join(validation.errors)


def test_more_than_five_steps_is_rejected():
    steps = []
    for index in range(1, 7):
        steps.append(
            {
                "id": index,
                "intent": "x",
                "tool": "r.slope.aspect",
                "inputs": ["elevation"],
                "outputs": [f"out{index}"],
                "output_types": ["raster"],
            }
        )
    validation = validate_plan({"steps": steps}, SHORTLIST)
    assert any("maximum is 5" in error for error in validation.errors)


def test_non_contiguous_ids_are_rejected():
    plan = _valid_plan()
    plan["steps"][0]["id"] = 2
    validation = validate_plan(plan, SHORTLIST)
    assert any("contiguous" in error for error in validation.errors)


def test_tool_outside_shortlist_is_rejected_and_names_step_and_tool():
    plan = _valid_plan()
    plan["steps"][0]["tool"] = "v.clean"
    validation = validate_plan(plan, ["r.slope.aspect"])
    message = " ".join(validation.errors)
    assert "step 1 (v.clean)" in message
    assert "shortlist" in message


def test_tool_missing_from_kb_is_rejected():
    retriever = _Retriever([SHORTLIST[0]])
    plan = _valid_plan()
    plan["steps"][0]["tool"] = "r.imaginary"
    validation = validate_plan(plan, ["r.imaginary"], retriever=retriever)
    assert any("does not exist" in error for error in validation.errors)


def test_duplicate_outputs_are_rejected():
    plan = {
        "steps": [
            {
                "id": 1,
                "intent": "a",
                "tool": "r.slope.aspect",
                "inputs": ["elevation"],
                "outputs": ["same"],
                "output_types": ["raster"],
            },
            {
                "id": 2,
                "intent": "b",
                "tool": "r.univar",
                "inputs": ["same"],
                "outputs": ["same"],
                "output_types": ["raster"],
            },
        ]
    }
    validation = validate_plan(plan, SHORTLIST, inventory_maps={"elevation"})
    assert any("duplicate output" in error for error in validation.errors)


def test_outputs_and_output_types_must_match():
    plan = _valid_plan()
    plan["steps"][0]["output_types"] = []
    validation = validate_plan(plan, SHORTLIST)
    assert any("differ in length" in error for error in validation.errors)


def test_inputs_require_inventory_or_prior_step_lineage():
    plan = _valid_plan()
    plan["steps"][0]["inputs"] = ["bathymetry"]
    validation = validate_plan(
        plan, SHORTLIST, inventory_maps={"elevation"}
    )
    assert any("no lineage" in error for error in validation.errors)


def test_type_incompatibility_is_rejected():
    plan = _valid_plan()
    plan["steps"][0]["output_types"] = ["vector"]
    validation = validate_plan(plan, SHORTLIST)
    assert any("produces raster" in error for error in validation.errors)


def test_extract_json_tolerates_prose_and_fences():
    payload = extract_json("Here you go:\n```json\n" + json.dumps(_valid_plan()) + "\n```")
    assert payload["steps"][0]["tool"] == "r.slope.aspect"


def test_replan_is_distinct_and_capped(fake_provider):
    fake_provider.responses = [json.dumps(_valid_plan())]
    planner = _planner(fake_provider)
    failed = ExecutionPlan(
        steps=[
            PlanStep(
                id=1,
                intent="bad",
                tool="r.reclass",
                inputs=["elevation"],
                outputs=["out"],
                output_types=["raster"],
            )
        ]
    )
    outcome = planner.replan(
        "slope",
        "",
        SHORTLIST,
        failed,
        "ERROR: bad",
        inventory_maps={"elevation"},
    )
    assert outcome.valid
    assert outcome.replan_count == 1
    assert outcome.plan.replan_count == 1
    assert outcome.plan.revision == 1
    assert outcome.invocations <= 3
