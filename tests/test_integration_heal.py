"""Healing loop against a stubbed model.

Exercises the repair path end to end without inference cost: the model is
replaced with a queue of canned responses, so the test proves the *harness*
re-queries, re-prompts, and records correctly.
"""

import pytest

from grass_agent.healing import Healer, RepairContext
from grass_agent.results import (
    OUTCOME_EXECUTED_OK,
    OUTCOME_RUNTIME_FAILED,
    Attempt,
    CaseResult,
)


class StubProvider:
    """Returns canned replies and records what it was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []
        self.seen_options = []

    def chat_with_stats(self, messages, options=None):
        self.seen.append(messages)
        self.seen_options.append(options)
        reply = self.replies.pop(0) if self.replies else ""
        return reply, {"prompt_tokens": 10, "completion_tokens": 5}

    def generate_embeddings(self, text):
        return [0.0] * 768


class StubRetriever:
    """Resolves a fixed tool table."""

    def __init__(self, tools=()):
        self.tools = {name: {"name": name} for name in tools}

    def get_tool(self, name):
        doc = self.tools.get(name)
        return _Doc(name) if doc else None

    def retrieve(self, query, embedding, k=5):
        return [_Doc(name) for name in list(self.tools)[:k]]


class _Doc:
    def __init__(self, name):
        self.name = name
        self.category = "vector"
        self.description = f"{name} documentation"
        self.signature = f"tools.{name.replace('.', '_')}(input, output)"
        self.example = None
        self.params = {"input": {"required": True}, "output": {"required": True}}


REPLY_WITH_FENCE = """Here is the corrected script:
```python
from grass.tools import Tools
tools = Tools()
tools.v_buffer(input="streams", output="buffered", distance=200)
```
"""


def _healer(replies, tools=("v.buffer",)):
    return Healer(
        config=None,
        provider=StubProvider(replies),
        retriever=StubRetriever(tools),
        top_k=2,
    )


def test_repair_strips_markdown_fences():
    """The Zero-Chat contract applies to repair output too."""
    healer = _healer([REPLY_WITH_FENCE])
    attempt = healer.repair(
        RepairContext("buffer streams", "old code", "ERROR: x", "docs")
    )
    assert "```" not in attempt.code
    assert "from grass.tools import Tools" in attempt.code


def test_repair_caps_generation_length():
    """An unbounded local model can loop forever (observed: 19,579 tokens).

    The repair call must carry a num_predict cap so the suite cannot stall.
    """
    healer = _healer([REPLY_WITH_FENCE])
    healer.repair(RepairContext("t", "c", "e", "d"))
    assert healer.provider.seen_options[0] is not None
    assert "num_predict" in healer.provider.seen_options[0]
    assert healer.num_predict <= 4096


def test_repair_records_token_stats():
    healer = _healer([REPLY_WITH_FENCE])
    attempt = healer.repair(RepairContext("t", "c", "e", "d"))
    assert attempt.prompt_tokens == 10
    assert attempt.completion_tokens == 5


def test_repair_prompt_carries_all_four_elements():
    healer = _healer([REPLY_WITH_FENCE])
    error = "grass.tools.session_tools.ToolError: Vector map <strems> not found"
    healer.repair(
        RepairContext(
            original_prompt="buffer the streams",
            previous_code="tools.v_buffer(input='strems', ...)",
            error_text=error,
            tool_documentation="### v.buffer\n...",
        )
    )
    user_message = healer.provider.seen[0][1]["content"]
    assert "buffer the streams" in user_message
    assert "strems" in user_message
    assert error in user_message
    assert "v.buffer" in user_message


def test_targeted_requery_uses_the_failing_tool():
    """FR-011: the re-query targets the failing tool, not the original task."""
    healer = _healer([])
    docs, names, used_fallback = healer.targeted_documentation(
        "v.buffer", "some error", "original unrelated prompt"
    )
    assert names == ["v.buffer"]
    assert used_fallback is False
    assert "v.buffer" in docs


def test_requery_falls_back_when_no_tool_identified():
    """A failure with no tool name must still get documentation (FR-011)."""
    healer = _healer([])
    docs, names, used_fallback = healer.targeted_documentation(
        None, "AttributeError: 'x' object has no attribute 'y'", "original prompt"
    )
    assert used_fallback is True
    assert names  # the fallback still returned something


def test_case_recovers_on_retry():
    """The recorded verdicts for a case that heals on retry 1."""
    result = CaseResult(tc_id="tc_01")
    result.attempts.append(
        Attempt(
            ordinal=1,
            outcome=OUTCOME_RUNTIME_FAILED,
            failure_mode="missing_input",
            error_excerpt="Vector map <strems> not found",
        )
    )
    result.attempts.append(Attempt(ordinal=2, outcome=OUTCOME_EXECUTED_OK))
    result.recompute_verdicts()

    assert result.pass_at_1 is False
    assert result.pass_at_healed is True
    assert result.failure_mode_transitions == ["missing_input", None]


def test_repair_normalises_dotted_calls():
    """A repair that reintroduces dots must be normalised, not executed."""
    from grass_agent.healing import _normalise_dotted_calls

    assert (
        _normalise_dotted_calls("tools.v.buffer(input='x')")
        == "tools.v_buffer(input='x')"
    )