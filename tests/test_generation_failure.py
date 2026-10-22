"""Unparsable generation must not kill the suite (FR-002).

Gate 1's `validate_syntax` raises rather than returning. If the harness lets
that escape, one bad generation ends a 40-case run -- observed live on this
project before the fix. The requirement is explicit: a syntax error is a static
rejection that routes into the healing loop, not a harness fault.
"""

import pytest

from benchmarks.run_execution import GenerationFailed, generate_attempt, static_guard


class ExplodingGenerator:
    """Mimics Gate 1: `generate` raises ValueError on unparsable output."""

    def __init__(self, last_code="from grass.tools import Tools\ndef broken(:\n"):
        self.last_code = last_code
        self.last_system_prompt = "sys"
        self.last_user_message = "user"
        self.provider = self

    def generate(self, prompt):
        raise ValueError("Generated code is not valid Python (line 12): invalid syntax")

    def chat_with_stats(self, messages):
        return "", {"prompt_tokens": 0, "completion_tokens": 0}


def test_unparsable_generation_becomes_a_generation_failure():
    generator = ExplodingGenerator()
    with pytest.raises(GenerationFailed) as excinfo:
        generate_attempt(generator, "some task", None)
    assert "not valid Python" in str(excinfo.value)
    assert excinfo.value.code, "the partial output must be carried for the repair prompt"


def test_generation_failure_is_a_usable_static_rejection():
    """The recovered code is still handed to the guard, which rejects it."""
    generator = ExplodingGenerator()
    try:
        generate_attempt(generator, "some task", None)
    except GenerationFailed as exc:
        issues = [str(exc)] + static_guard(exc.code, generator)
        assert issues
        assert issues[0] == str(exc)


def test_valid_generation_is_not_wrapped():
    class GoodGenerator(ExplodingGenerator):
        def generate(self, prompt):
            self.last_code = "from grass.tools import Tools\ntools = Tools()\n"
            return self.last_code

    code, prompt_tokens, completion_tokens = generate_attempt(
        GoodGenerator(), "some task", None
    )
    assert "from grass.tools import Tools" in code
    assert prompt_tokens == 0 and completion_tokens == 0


def test_reuse_path_bypasses_generation_entirely(tmp_path):
    """--reuse-artifacts must not call the model at all (SC-015)."""

    class NeverCalled(ExplodingGenerator):
        def generate(self, prompt):  # pragma: no cover - must not run
            raise AssertionError("generation must be skipped when reusing artifacts")

    artifact = tmp_path / "tc_01_qwen2.5-coder_3b.py"
    artifact.write_text("from grass.tools import Tools\ntools = Tools()\n", encoding="utf-8")
    code, prompt_tokens, completion_tokens = generate_attempt(
        NeverCalled(), "task", artifact
    )
    assert "from grass.tools import Tools" in code
    assert prompt_tokens == 0 and completion_tokens == 0