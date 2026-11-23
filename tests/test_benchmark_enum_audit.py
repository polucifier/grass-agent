"""Statically invalid closed enums never launch GRASS (T055 / SC-006)."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks import run_gate2
from code_generator import PipelineGenerationResult, validate_api
from grass_agent.config import ExecutionConfig
from grass_agent.results import ResumeKey
from rag_retriever import ClosedEnumOption, ModuleFlag, ToolDoc


def _doc(name, params, flags=None, options=None):
    return ToolDoc(
        name=name,
        category=name.split(".")[0],
        description=name,
        signature=f"grass.tools.Tools.{name.replace('.', '_')}(...)",
        example="",
        params=params,
        similarity=0.0,
        flags=flags or [],
        options=options or {},
    )


def _retriever():
    return _StaticRetriever(
        [
            _doc(
                "v.clean",
                {
                    "input": {"required": True},
                    "output": {"required": True},
                    "tool": {"required": True},
                },
                flags=[ModuleFlag("b"), ModuleFlag("c")],
                options={
                    "tool": [
                        ClosedEnumOption("tool", "break"),
                        ClosedEnumOption("tool", "snap"),
                        ClosedEnumOption("tool", "rmdupl"),
                    ]
                },
            ),
            _doc(
                "r.viewshed",
                {
                    "input": {"required": True},
                    "output": {"required": True},
                    "coordinates": {"required": True},
                },
                flags=[ModuleFlag("b"), ModuleFlag("c")],
            ),
            _doc(
                "v.to.rast",
                {
                    "input": {"required": True},
                    "output": {"required": True},
                    "use": {"required": True},
                },
                options={
                    "use": [
                        ClosedEnumOption("use", "raster"),
                        ClosedEnumOption("use", "attr"),
                        ClosedEnumOption("use", "value"),
                    ]
                },
            ),
        ]
    )


class _StaticRetriever:
    def __init__(self, docs):
        self.docs = {doc.name: doc for doc in docs}

    def get_tool(self, name):
        return self.docs.get(name)

    def get_manual(self, name):
        return self.docs.get(name)

    def retrieve(self, query, embedding, k=5):
        return list(self.docs.values())[:k]


class _FakeGenerator:
    def __init__(self, retriever, code):
        self.config = type(
            "C",
            (),
            {
                "pipeline": "manual-kb",
                "num_ctx": 8192,
                "manual_context_tokens": 3686,
            },
        )()
        self.retriever = retriever
        self.code = code

    def generate_result(self, request, inventory_block="", agentic_pipeline=None, inventory_maps=None):
        return PipelineGenerationResult(code=self.code)


class _ForbiddenExecutor:
    def __init__(self):
        self.calls = 0

    def execute(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("GRASS must not launch for a statically invalid enum")


class _UnusedHealer:
    pass


CASES = [
    (
        'tools.v_clean(input="roads", output="clean", tool="rm_duplicates")',
        ["rmdupl", "snap"],
    ),
    (
        'tools.r_viewshed(input="elevation", output="out", '
        'coordinates="0,0", flags="z")',
        ["b", "c"],
    ),
    (
        'tools.v_to_rast(input="roads", output="rast", use="magic")',
        ["raster", "attr", "value"],
    ),
]


@pytest.mark.parametrize("code,legal_values", CASES)
def test_invalid_closed_enum_is_rejected_with_legal_values(code, legal_values):
    issues = validate_api(code, _retriever(), pipeline="manual-kb")
    assert issues
    joined = " ".join(issues)
    for value in legal_values:
        assert value in joined


@pytest.mark.parametrize("code,legal_values", CASES)
def test_invalid_enum_never_launches_grass(code, legal_values, tmp_path):
    retriever = _retriever()
    generator = _FakeGenerator(retriever, code)
    executor = _ForbiddenExecutor()
    config = ExecutionConfig(
        pipeline="manual-kb",
        num_ctx=8192,
        max_static_retries=0,
        max_runtime_retries=0,
    )
    key = ResumeKey(
        model="m",
        max_retries=2,
        timeout=120,
        attempt1_source="fresh",
        max_static_retries=0,
        max_runtime_retries=0,
        harness="gate3",
        pipeline="manual-kb",
        num_ctx=8192,
        manual_context_tokens=3686,
    )
    result = run_gate2.run_case(
        {"id": "audit_case", "tier": 1, "category": "enum", "prompt": "do it"},
        config,
        generator,
        _UnusedHealer(),
        executor,
        tmp_path,
        tmp_path / "out",
        key,
    )
    assert executor.calls == 0
    assert result.attempts
    assert result.attempts[0].stage == "static"
    assert result.attempts[0].static_passed is False
