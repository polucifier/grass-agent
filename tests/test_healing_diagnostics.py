"""Repair diagnostics preserve the real error and legal values (T012)."""

from __future__ import annotations

from config import GenerationConfig
from grass_agent.classifier import error_excerpt
from grass_agent.healing import Healer
from rag_retriever import ClosedEnumOption, ModuleFlag, ToolDoc


class _Retriever:
    def __init__(self, docs):
        self.docs = {doc.name: doc for doc in docs}

    def get_tool(self, name):
        return self.docs.get(name)

    def get_manual(self, name):
        return self.docs.get(name)

    def retrieve(self, query, embedding, k=5):
        return list(self.docs.values())[:k]


def _clean_doc() -> ToolDoc:
    return ToolDoc(
        name="v.clean",
        category="v",
        description="Clean topology",
        signature="grass.tools.Tools.v_clean(input, output, tool, threshold=None, flags=None)",
        example="",
        params={
            "input": {"type": "str", "required": True},
            "output": {"type": "str", "required": True},
            "tool": {"type": "str", "required": True},
            "threshold": {"type": "float", "required": False, "default": "0.0"},
            "flags": {"type": "str", "required": False},
        },
        similarity=0.0,
        flags=[ModuleFlag("b", "no topology")],
        options={
            "tool": [
                ClosedEnumOption("tool", "break"),
                ClosedEnumOption("tool", "snap"),
                ClosedEnumOption("tool", "rmdupl"),
            ]
        },
    )


def _healer(retriever, pipeline="legacy"):
    from tests.conftest import FakeOllamaProvider

    return Healer(
        GenerationConfig(pipeline=pipeline),
        FakeOllamaProvider(),
        retriever,
        pipeline=pipeline,
    )


def test_wrapper_toolerror_preserves_error_and_legal_range():
    stderr = (
        "grass.tools.session_tools.ToolError: Run `r.viewshed input=elevation` "
        "ended with an error (return code 1):\n"
        "ERROR: Value <400> out of range for parameter <direction_range>\n"
        "       Legal range: 0-360\n"
    )
    excerpt = error_excerpt("", stderr, limit=800)
    assert excerpt.startswith("ERROR:")
    assert "out of range" in excerpt
    assert "Legal range: 0-360" in excerpt
    assert excerpt in stderr


def test_wrapper_toolerror_preserves_options_continuation():
    stderr = (
        "grass.tools.session_tools.ToolError: Run `v.clean input=roads` "
        "ended with an error (return code 1):\n"
        "ERROR: Sorry, <rm_duplicates> is not a valid option\n"
        "       options: break, snap, rmdupl\n"
    )
    excerpt = error_excerpt("", stderr, limit=800)
    assert "ERROR:" in excerpt
    assert "options:" in excerpt
    assert "rmdupl" in excerpt


def test_non_wrapper_excerpts_remain_single_line():
    stderr = "progress\nERROR: Required parameter <map> not set\nmore\n"
    assert error_excerpt("", stderr) == "ERROR: Required parameter <map> not set"


def test_parameter_list_includes_flags_and_closed_values():
    healer = _healer(_Retriever([_clean_doc()]))
    table = healer.parameter_list("v.clean")
    assert table is not None
    assert "- `-b`" in table
    assert "rmdupl" in table
    assert "snap" in table
    assert "Allowed values" in table


def test_parameter_list_still_returns_none_for_unknown_tools():
    healer = _healer(_Retriever([_clean_doc()]))
    assert healer.parameter_list("not.a.tool") is None


def test_manual_kb_targeted_documentation_uses_cards():
    healer = _healer(_Retriever([_clean_doc()]), pipeline="manual-kb")
    documentation, names, fallback = healer.targeted_documentation(
        "v.clean", "ERROR: bad tool", "clean roads"
    )
    assert names == ["v.clean"]
    assert fallback is False
    assert "API:" in documentation
    assert "rmdupl" in documentation


def test_tool_swap_candidates_are_documented_family_members():
    docs = [
        _clean_doc(),
        ToolDoc(
            name="v.edit",
            category="v",
            description="Edit vectors",
            signature="",
            example="",
            params={},
            similarity=0.0,
        ),
    ]
    healer = _healer(_Retriever(docs), pipeline="manual-kb")
    assert "v.edit" in healer.tool_swap_candidates("v.clean")
