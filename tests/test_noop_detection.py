"""Deterministic no-op detection and parameter-list pivoting (T030).

The duplicate decision must be reproducible from candidate bytes alone. These
tests pin every normalization rule: line endings, comments, docstrings, and
formatting collapse; a changed tool or parameter does not.
"""

import ast
import json

import pytest

from grass_agent.healing import (
    Healer,
    NoOpIndex,
    RepairAttempt,
    RepairContext,
    RepairTurn,
    ast_digest,
    byte_digest,
)

BASE = """from grass.tools import Tools
tools = Tools()
tools.v_buffer(input="streams", output="b", distance=200)
"""


def test_byte_identical_candidate_is_a_duplicate():
    index = NoOpIndex()
    index.add(BASE, 1)
    assert index.match(BASE).ordinal == 1


def test_crlf_and_lf_are_the_same_candidate():
    index = NoOpIndex()
    index.add(BASE, 1)
    assert index.match(BASE.replace("\n", "\r\n")) is not None


def test_comment_only_change_is_a_duplicate():
    index = NoOpIndex()
    index.add(BASE, 1)
    commented = BASE.replace(
        'tools = Tools()', '# a helpful comment\ntools = Tools()'
    )
    assert index.match(commented) is not None


def test_docstring_only_change_is_a_duplicate():
    index = NoOpIndex()
    index.add(BASE, 1)
    documented = '"""Generate the buffer."""\n' + BASE
    assert index.match(documented) is not None


def test_formatting_only_change_is_a_duplicate():
    index = NoOpIndex()
    index.add(BASE, 1)
    reformatted = (
        "from grass.tools import Tools\n"
        "tools = Tools( )\n"
        "tools.v_buffer( input='streams' , output='b' , distance=200 )\n"
    )
    assert index.match(reformatted) is not None


def test_changed_parameter_is_not_a_duplicate():
    index = NoOpIndex()
    index.add(BASE, 1)
    changed = BASE.replace("distance=200", "distance=500")
    assert index.match(changed) is None


def test_changed_tool_is_not_a_duplicate():
    index = NoOpIndex()
    index.add(BASE, 1)
    changed = BASE.replace("v_buffer", "v_extract")
    assert index.match(changed) is None


def test_unparseable_candidate_participates_by_byte_digest():
    broken = "tools.v_buffer(input='streams'\n"
    assert ast_digest(broken) is None
    index = NoOpIndex()
    index.add(broken, 1)
    assert index.match(broken) is not None
    assert index.match("totally different(") is None


def test_initial_candidate_is_seeded_and_matched_across_tiers():
    index = NoOpIndex()
    index.add(BASE, 1)
    # A runtime-tier repair repeating the initial candidate is still rejected.
    assert index.match(BASE).ordinal == 1


class FakeRetriever:
    def get_tool(self, name):
        from rag_retriever import ToolDoc

        if name not in ("v.buffer", "v_buffer"):
            return None
        return ToolDoc(
            name="v.buffer",
            category="vector",
            description="Buffer",
            signature=(
                "grass.tools.Tools.v_buffer(input, layer=\"-1\", output, "
                "distance=None, flags=None)"
            ),
            example="tools.v_buffer(input='streams', output='b', distance=200)",
            params={
                "input": {"type": "str", "required": True},
                "output": {"type": "str", "required": True},
                "distance": {"type": "float", "required": False, "default": "None"},
            },
            similarity=0.0,
        )


def test_pivot_prompt_contains_the_parameter_list(monkeypatch):
    healer = Healer(config=None, provider=None, retriever=FakeRetriever())
    monkeypatch.setattr(
        healer, "targeted_documentation", lambda *a, **k: ("### v.buffer", [], False)
    )
    context = healer.build_context(
        original_prompt="Buffer the streams.",
        previous_code=BASE,
        error_text="ERROR: option distance",
        failing_tool="v.buffer",
        failure_mode="schema_misuse",
        history=[RepairTurn(ordinal=1, code=BASE, failure_mode="schema_misuse")],
        pivot=True,
    )
    message = context.to_user_message()
    assert "| Parameter | Type | Required | Default |" in message
    assert "`input`" in message
    assert "`distance`" in message
    assert "change the approach" in message


def test_unknown_tool_pivot_degrades_to_the_generic_instruction(monkeypatch):
    healer = Healer(config=None, provider=False, retriever=FakeRetriever())
    monkeypatch.setattr(
        healer, "targeted_documentation", lambda *a, **k: ("### docs", [], False)
    )
    assert healer.parameter_list("not.a.tool") is None
    context = healer.build_context(
        original_prompt="p",
        previous_code="c",
        error_text="e",
        failing_tool="not.a.tool",
        history=[RepairTurn(ordinal=1, code="c", failure_mode="schema_misuse")],
        pivot=True,
    )
    message = context.to_user_message()
    assert "DO NOT repeat previous scripts" in message
    assert "### Failing Tool Parameters" not in message


def test_duplicate_decision_is_deterministic_across_two_runs():
    candidates = [
        BASE,
        BASE.replace("\n", "\r\n"),
        '# comment\n' + BASE,
        BASE.replace("distance=200", "distance=500"),
        "print('broken'\n",
        "print('broken'\n",
    ]

    def run():
        index = NoOpIndex()
        verdicts = []
        for ordinal, candidate in enumerate(candidates, start=1):
            match = index.match(candidate)
            verdicts.append(None if match is None else match.ordinal)
            if match is None:
                index.add(candidate, ordinal)
        return verdicts

    assert run() == run() == [None, 1, 1, None, None, 5]


def test_repair_attempt_records_the_pivot(monkeypatch):
    healer = Healer(config=None, provider=None, retriever=FakeRetriever())

    class Provider:
        def chat_with_stats(self, messages, options=None):
            return "print('new candidate')", {"prompt_tokens": 1, "completion_tokens": 2}

    healer.provider = Provider()
    context = RepairContext("p", "c", "e", "d", pivot=True)
    attempt = healer.repair(context)
    assert isinstance(attempt, RepairAttempt)
    assert attempt.pivot_used is True


def test_a_stub_case_sequence_accepts_zero_duplicates_for_execution():
    """SC-003: only genuinely new candidates ever reach execution."""
    index = NoOpIndex()
    accepted = []
    produced = [BASE, BASE, BASE.replace("distance=200", "distance=100"),
                BASE.replace("distance=200", "distance=100")]
    for ordinal, candidate in enumerate(produced, start=1):
        if index.match(candidate) is not None:
            continue  # rejected before execution
        index.add(candidate, ordinal)
        accepted.append(candidate)
    assert len(accepted) == 2
    assert len({byte_digest(c) for c in accepted}) == len(accepted)
