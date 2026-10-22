"""Healing loop: unified budget and repair-prompt assembly (tasks T047, T048).

The budget property is the one that is easy to get wrong: every failed attempt
-- static rejection, runtime failure, crash, timeout -- costs exactly one unit
of a *single* allowance (FR-009a). A case can therefore exhaust its budget
without ever executing, which is intended and reported, not a fault.
"""

import pytest

from grass_agent.healing import (
    Healer,
    RepairContext,
    legacy_interface_issues,
)
from grass_agent.inventory import MapInventory, read_inventory
from grass_agent.results import (
    OUTCOME_CRASHED,
    OUTCOME_EXECUTED_OK,
    OUTCOME_RUNTIME_FAILED,
    OUTCOME_STATIC_REJECTED,
    OUTCOME_TIMEOUT,
    Attempt,
    CaseResult,
)

ALL_FAILING_OUTCOMES = [
    OUTCOME_STATIC_REJECTED,
    OUTCOME_RUNTIME_FAILED,
    OUTCOME_CRASHED,
    OUTCOME_TIMEOUT,
]


# --------------------------------------------------------------------------
# Unified budget (FR-009a, SC-017)
# --------------------------------------------------------------------------


def _result_with(outcomes, max_retries=2):
    modes = {
        OUTCOME_STATIC_REJECTED: "schema_misuse",
        OUTCOME_RUNTIME_FAILED: "missing_input",
        OUTCOME_CRASHED: "general_exception",
        OUTCOME_TIMEOUT: "general_exception",
    }
    result = CaseResult(tc_id="tc_01", resume_key=None)
    for ordinal, outcome in enumerate(outcomes, start=1):
        result.attempts.append(
            Attempt(
                ordinal=ordinal,
                outcome=outcome,
                failure_mode=None if outcome == OUTCOME_EXECUTED_OK else modes[outcome],
            )
        )
    result.recompute_verdicts()
    return result


@pytest.mark.parametrize("failing_outcome", ALL_FAILING_OUTCOMES)
def test_every_failure_kind_costs_exactly_one_turn(failing_outcome):
    """No failure kind is free, and none costs two."""
    budget = 2
    result = _result_with([failing_outcome] * (budget + 1), max_retries=budget)
    assert len(result.attempts) == budget + 1


def test_static_and_runtime_share_one_allowance():
    """A static rejection consumes the same budget a runtime failure does.

    Charging static rejections separately would let a case exceed its budget,
    and charging them nothing would let it fail pre-flight forever.
    """
    mixed = _result_with(
        [OUTCOME_STATIC_REJECTED, OUTCOME_RUNTIME_FAILED, OUTCOME_EXECUTED_OK]
    )
    assert len(mixed.attempts) == 3  # initial + 2 retries, shared
    assert mixed.pass_at_healed is True
    assert mixed.pass_at_1 is False
    assert mixed.failure_mode_transitions == ["schema_misuse", "missing_input", None]


def test_budget_ceiling_is_enforced():
    from grass_agent.results import check_invariants, ResultValidationError

    result = _result_with([OUTCOME_RUNTIME_FAILED] * 4)
    with pytest.raises(ResultValidationError, match="I1"):
        check_invariants(result, max_retries=2)


def test_case_can_exhaust_budget_without_executing():
    """Intended outcome, not a fault: three static rejections, zero runs."""
    result = _result_with([OUTCOME_STATIC_REJECTED] * 3)
    assert all(a.outcome == OUTCOME_STATIC_REJECTED for a in result.attempts)
    assert result.pass_at_healed is False


def test_first_success_stops_the_loop():
    result = _result_with([OUTCOME_RUNTIME_FAILED, OUTCOME_EXECUTED_OK])
    assert len(result.attempts) == 2


# --------------------------------------------------------------------------
# Repair prompt assembly (FR-012, SC-006)
# --------------------------------------------------------------------------


def _full_context() -> RepairContext:
    return RepairContext(
        original_prompt="Create a 200-meter buffer around the stream network lines.",
        previous_code="from grass.tools import Tools\ntools = Tools()\n",
        error_text="grass.tools.session_tools.ToolError: Vector map <streams> not found",
        tool_documentation="### v.buffer\ngrass.tools signature: tools.v_buffer(...)",
    )


def test_all_four_elements_present():
    context = _full_context()
    message = context.to_user_message()
    assert "Task: " in message
    assert context.original_prompt in message
    assert "previous script" in message.lower()
    assert context.previous_code in message
    assert "failed with this error" in message
    assert context.error_text in message
    assert context.tool_documentation in message
    assert context.missing_elements() == []


@pytest.mark.parametrize(
    "field,expected",
    [
        ("original_prompt", "original task"),
        ("previous_code", "previous script"),
        ("error_text", "exact error"),
        ("tool_documentation", "targeted tool documentation"),
    ],
)
def test_each_element_is_required(field, expected):
    context = _full_context()
    setattr(context, field, "")
    assert context.missing_elements() == [expected]


def test_error_is_passed_verbatim_not_paraphrased():
    """FR-010: the model must see the exact bytes, not a summary."""
    error = "ERROR: No 'from' features selected. Please check options 'from_layer',"
    context = RepairContext(
        original_prompt="p",
        previous_code="c",
        error_text=error,
        tool_documentation="d",
    )
    assert error in context.to_user_message()


def test_error_with_backticks_survives():
    """ToolError messages contain backticks; they must not be mangled."""
    error = "Run `v.buffer input=streams output=b` ended with an error (return code 1)"
    context = RepairContext("p", "c", error, "d")
    assert error in context.to_user_message()


# --------------------------------------------------------------------------
# Legacy interface rejection (FR-015, SC-010)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "import grass.script as gs\ntools = gs.run_command('r.info', map='elevation')",
        "from grass.tools import Tools\nimport subprocess\nsubprocess.run(['r.info'])",
        "import os\nos.system('r.info map=elevation')",
        "from grass.script import run_command\nrun_command('r.info')",
        "from grass.tools import Tools\nimport grass.script as gs\n"
        "gs.run_command('v.buffer', input='x', output='y', distance=100)",
    ],
)
def test_legacy_and_shell_usage_is_rejected(code):
    assert legacy_interface_issues(code), "must be flagged as a failed attempt"


@pytest.mark.parametrize(
    "code",
    [
        "from grass.tools import Tools\ntools = Tools()\n"
        "tools.v_buffer(input='streams', output='b', distance=200)",
        # A string *mentioning* run_command is not a call.
        "from grass.tools import Tools\n"
        "# never use run_command here\n"
        "tools.r_slope_aspect(elevation='elevation', slope='s', aspect='a')",
    ],
)
def test_modern_interface_is_accepted(code):
    assert legacy_interface_issues(code) == []


def test_zero_chat_preserved_on_repair_output():
    """Repair output goes through the same extractor as initial generation."""
    from code_generator import extract_python_code

    fenced = "Here you go:\n```python\nfrom grass.tools import Tools\ntools = Tools()\n```"
    assert "```" not in extract_python_code(fenced)
    assert "from grass.tools import Tools" in extract_python_code(fenced)


# --------------------------------------------------------------------------
# Dataset map inventory grounding (FR-012a, SC-006a)
# --------------------------------------------------------------------------


def _fake_healer(monkeypatch, inventory):
    """A Healer whose RAG lookup is stubbed and whose inventory is supplied.

    Only the inventory path is under test here; the retriever and provider are
    deliberately not exercised, so the documentation block is fixed.
    """
    healer = Healer(
        config=None,
        provider=None,
        retriever=None,
        inventory_provider=lambda: inventory,
    )
    monkeypatch.setattr(
        healer, "targeted_documentation", lambda *a, **k: ("### stubbed docs", [], False)
    )
    return healer


_MISSING_INPUT_ERROR = (
    "grass.tools.session_tools.ToolError: Raster map <bathymetry> not found"
)


def test_inventory_is_injected_into_missing_input_repair_prompt(monkeypatch):
    """The whole point of FR-012a: the model must see which maps exist.

    Without this block the model learns only that ``bathymetry`` was wrong and
    has no way to discover that ``lakes`` is the map it wanted -- the failure
    is unhealable by construction.
    """
    inventory = MapInventory(
        rasters=("basins", "elevation", "lakes", "landuse"),
        vectors=("boundary_state", "roadsmajor", "streams"),
    )
    healer = _fake_healer(monkeypatch, inventory)

    context = healer.build_context(
        original_prompt="Delineate watersheds from the lake raster.",
        previous_code="tools.r_info(map='bathymetry')",
        error_text=_MISSING_INPUT_ERROR,
        failing_tool="r.info",
        failure_mode="missing_input",
    )
    message = context.to_user_message()

    assert "### Available Dataset Maps" in message
    assert "Available Rasters: [basins, elevation, lakes, landuse]" in message
    assert "Available Vectors: [boundary_state, roadsmajor, streams]" in message
    # The real map the model should have used is now visible...
    assert "lakes" in message
    # ...and the prompt is grounded, not merely informative.
    assert "ONLY maps that exist" in message


def test_inventory_is_a_separate_prompt_block_not_conflated_with_docs(monkeypatch):
    inventory = MapInventory(rasters=("elevation",), vectors=("streams",))
    context = _fake_healer(monkeypatch, inventory).build_context(
        original_prompt="p",
        previous_code="c",
        error_text="e",
        failing_tool=None,
        failure_mode="missing_input",
    )
    message = context.to_user_message()
    assert message.index("### Available Dataset Maps") > message.index(
        "Relevant GRASS tools documentation"
    )
    assert message.index("### Available Dataset Maps") < message.index(
        "The previous script failed"
    )


def test_missing_input_repair_without_inventory_is_incomplete():
    """SC-006a: for a missing_input repair the inventory is mandatory."""
    context = RepairContext(
        original_prompt="p",
        previous_code="c",
        error_text=_MISSING_INPUT_ERROR,
        tool_documentation="d",
        available_maps="",
    )
    assert "available dataset maps" in context.missing_elements("missing_input")


def test_other_failure_modes_do_not_require_inventory():
    """Grounding is mandatory only where it is the blocker.

    Requiring it everywhere would turn a cosmetic gap into a false SC-006
    failure for failure modes the inventory cannot help.
    """
    context = RepairContext(
        original_prompt="p",
        previous_code="c",
        error_text="e",
        tool_documentation="d",
        available_maps="",
    )
    assert context.missing_elements("schema_misuse") == []
    assert context.missing_elements("general_exception") == []
    assert context.missing_elements(None) == []


def test_four_elements_still_required_and_sufficient_withinventory():
    """No regression to the original FR-012/SC-006 contract."""
    context = RepairContext(
        original_prompt="p",
        previous_code="c",
        error_text="e",
        tool_documentation="d",
        available_maps="### Available Dataset Maps\nAvailable Rasters: [elevation]",
    )
    assert context.missing_elements("missing_input") == []


def test_empty_inventory_omits_the_block_entirely(monkeypatch):
    """An unreadable dataset yields no heading, not an empty one."""
    context = _fake_healer(monkeypatch, MapInventory()).build_context(
        original_prompt="p",
        previous_code="c",
        error_text="e",
        failing_tool="r.info",
        failure_mode="missing_input",
    )
    assert context.available_maps == ""
    assert "### Available Dataset Maps" not in context.to_user_message()


def test_inventory_provider_is_called_once_and_errors_are_swallowed(monkeypatch):
    """Reading the inventory is per-run, and must never be fatal."""
    calls = {"n": 0}

    def provider():
        calls["n"] += 1
        return MapInventory(rasters=("elevation",))

    healer = Healer(config=None, provider=None, retriever=None, inventory_provider=provider)
    monkeypatch.setattr(
        healer, "targeted_documentation", lambda *a, **k: ("d", [], False)
    )
    for _ in range(3):
        healer.build_context("p", "c", "e", None, "missing_input")
    assert calls["n"] == 1, "inventory must be read once per run and cached"

    def exploding():
        raise OSError("dataset vanished")

    broken = Healer(
        config=None, provider=None, retriever=None, inventory_provider=exploding
    )
    monkeypatch.setattr(broken, "targeted_documentation", lambda *a, **k: ("d", [], False))
    context = broken.build_context("p", "c", "e", None, "missing_input")
    assert context.available_maps == "", "a failure to read must degrade, not raise"


def test_read_inventory_reads_only_real_maps(tmp_path):
    """The inventory comes from the mapset on disk, never from the model."""
    permanent = tmp_path / "PERMANENT"
    (permanent / "cellhd").mkdir(parents=True)
    (permanent / "vector").mkdir(parents=True)
    for name in ("elevation", "lakes", "landuse"):
        (permanent / "cellhd" / name).write_bytes(b"")
    for name in ("roadsmajor", "streams"):
        (permanent / "vector" / name).mkdir()
    # Noise the reader must ignore: a directory among rasters, a stray file
    # among vectors, and a dotfile.
    (permanent / "cellhd" / "not_a_map").mkdir()
    (permanent / "vector" / "stray.txt").write_bytes(b"")
    (permanent / "cellhd" / ".hidden").write_bytes(b"")

    inventory = read_inventory(tmp_path)
    assert inventory.rasters == ("elevation", "lakes", "landuse")
    assert inventory.vectors == ("roadsmajor", "streams")


def test_read_inventory_tolerates_missing_dataset(tmp_path):
    assert read_inventory(tmp_path / "does_not_exist").is_empty()
