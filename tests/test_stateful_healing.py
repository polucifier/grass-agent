"""Stateful repair prompts: full ordered history and the no-repeat instruction (T029).

FR-005 requires every prior attempt to survive into the repair prompt with its
metadata intact. FR-005a bounds the *code* the model sees, never the failure
evidence.
"""

from grass_agent.healing import (
    HISTORY_CONTEXT_BUDGET,
    NO_REPEAT_INSTRUCTION,
    RepairContext,
    RepairTurn,
)


def _context(history, **kwargs):
    return RepairContext(
        original_prompt="Buffer the streams.",
        previous_code="print('current')\n",
        error_text="ERROR: Raster map <nope> not found",
        tool_documentation="### v.buffer\nsignature",
        attempt_history=history,
        **kwargs,
    )


def test_history_metadata_survives_for_every_attempt():
    history = [
        RepairTurn(
            ordinal=1,
            budget_tier="initial",
            code="first = 1\n",
            failure_mode="schema_misuse",
            error_excerpt="unknown tool",
            stage="static",
            duplicate=False,
        ),
        RepairTurn(
            ordinal=2,
            budget_tier="static",
            code="second = 2\n",
            failure_mode="missing_input",
            error_excerpt="Raster map <x> not found",
            stage="runtime",
            duplicate=True,
        ),
        RepairTurn(
            ordinal=3,
            budget_tier="runtime",
            code="third = 3\n",
            failure_mode="missing_input",
            error_excerpt="Raster map <y> not found",
            stage="runtime",
            duplicate=False,
        ),
    ]
    message = _context(history).to_user_message()
    for ordinal in (1, 2, 3):
        assert f"Attempt {ordinal}" in message
    assert "tier=initial" in message
    assert "tier=static" in message
    assert "tier=runtime" in message
    assert "failure=schema_misuse" in message
    assert "failure=missing_input" in message
    assert "stage=static" in message
    assert "stage=runtime" in message
    assert "duplicate=yes" in message
    assert "duplicate=no" in message
    assert "unknown tool" in message
    assert "Raster map <x> not found" in message
    assert "Raster map <y> not found" in message


def test_no_repeat_instruction_is_verbatim():
    message = _context(
        [RepairTurn(ordinal=1, code="x = 1\n", failure_mode="missing_input")]
    ).to_user_message()
    assert NO_REPEAT_INSTRUCTION == (
        "DO NOT repeat previous scripts or failed parameter combinations."
    )
    assert NO_REPEAT_INSTRUCTION in message


def test_newest_failed_attempt_code_is_present_in_full():
    newest = "from grass.tools import Tools\n" + "x = 1\n" * 50
    history = [
        RepairTurn(ordinal=1, code="old = 0\n", failure_mode="missing_input"),
        RepairTurn(ordinal=2, code=newest, failure_mode="runtime_failed"),
    ]
    message = _context(history).to_user_message()
    assert newest in message


def test_older_code_is_digested_once_history_exceeds_the_budget():
    big = "y = 2\n" * 2000  # ~12k characters, well over the budget
    newest = "z = 3\n"
    history = [
        RepairTurn(ordinal=1, code=big, failure_mode="missing_input"),
        RepairTurn(ordinal=2, code=newest, failure_mode="missing_input"),
    ]
    message = _context(history).to_user_message()
    assert "Code digest: sha256:" in message
    assert big not in message
    assert newest in message
    assert len(message) < 3 * HISTORY_CONTEXT_BUDGET


def test_empty_history_preserves_the_four_element_prompt():
    plain = RepairContext(
        original_prompt="p",
        previous_code="c",
        error_text="e",
        tool_documentation="d",
    )
    assert plain.to_user_message() == (
        "Task: p\n\nRelevant GRASS tools documentation:\n\nd\n\n"
        "The previous script failed with this error:\n\ne\n\n"
        "Previous script:\n\nc\n\nGenerate the corrected Python script:"
    )


def test_history_keeps_the_four_elements_in_order():
    context = _context(
        [RepairTurn(ordinal=1, code="x = 1\n", failure_mode="missing_input")],
        available_maps="### Available Dataset Maps\nAvailable Rasters: [elevation]",
    )
    message = context.to_user_message()
    assert "Task: Buffer the streams." in message
    assert "Relevant GRASS tools documentation" in message
    assert message.index("### Available Dataset Maps") > message.index(
        "Relevant GRASS tools documentation"
    )
    assert message.index("### Previous Attempts") > message.index(
        "### Available Dataset Maps"
    )
    assert message.index(NO_REPEAT_INSTRUCTION) > message.index("### Previous Attempts")
    assert message.index("The previous script failed") > message.index(
        NO_REPEAT_INSTRUCTION
    )
    assert message.rstrip().endswith("Generate the corrected Python script:")


def test_pivot_adds_the_constraint():
    message = _context(
        [RepairTurn(ordinal=1, code="x = 1\n", failure_mode="missing_input")],
        pivot=True,
        parameter_table="| Parameter | Type | Required | Default |",
    ).to_user_message()
    assert "### Failing Tool Parameters" in message
    assert "change the approach" in message
