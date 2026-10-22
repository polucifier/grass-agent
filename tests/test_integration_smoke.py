"""End-to-end smoke: one case through the whole pipeline.

Uses a stub generator so the test exercises the harness (static guard,
execution, classification, artifact layout, persistence) without requiring a
running model. Marked slow because it executes a real GRASS session.
"""

import json
from pathlib import Path

import pytest

from grass_agent.classifier import FailureMode
from grass_agent.executor import Executor
from grass_agent.results import (
    OUTCOME_EXECUTED_OK,
    OUTCOME_STATIC_REJECTED,
    ResumeKey,
    case_dir,
    is_reusable,
    load,
    result_path,
)
from benchmarks.run_gate2 import static_guard

pytestmark = pytest.mark.slow

KEY = ResumeKey("stub-model", 2, 60, "fresh")


def _write(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_static_guard_accepts_a_correct_script():
    class EmptyRetriever:
        def get_tool(self, name):
            return None

    code = "from grass.tools import Tools\ntools = Tools()\nprint(1)\n"
    assert static_guard(code, EmptyRetriever()) == []


def test_static_guard_rejects_unparsable_code():
    class EmptyRetriever:
        def get_tool(self, name):
            return None

    issues = static_guard("def broken(:\n", EmptyRetriever())
    assert issues
    assert "not valid Python" in issues[0]


def test_static_guard_rejects_legacy_interface():
    class EmptyRetriever:
        def get_tool(self, name):
            return None

    code = "import grass.script as gs\ngs.run_command('r.info', map='elevation')\n"
    issues = static_guard(code, EmptyRetriever())
    assert any("legacy interface" in i for i in issues)


def test_static_guard_rejects_dotted_chain():
    """A dotted method chain is normalised at generation time, but if one
    survives it must be caught rather than executed."""
    class Retriever:
        def get_tool(self, name):
            return None

    code = "from grass.tools import Tools\ntools = Tools()\ntools.v.buffer(input='x')\n"
    issues = static_guard(code, Retriever())
    assert any("dotted method call" in i for i in issues)


# --------------------------------------------------------------------------
# Live execution
# --------------------------------------------------------------------------


def test_one_case_executes_and_is_persisted(dataset_project, tmp_path):
    """Scenario C in miniature: verdict plus a complete artifact set."""
    executor = Executor(dataset_project=dataset_project, timeout_s=60)
    out_dir = case_dir(tmp_path, "tc_01")
    out_dir.mkdir(parents=True)

    script = _write(
        out_dir,
        "attempt_1.py",
        "from grass.tools import Tools\nimport grass.script as gs\n"
        "print('MAPSET=' + gs.gisenv()['MAPSET'])\n",
    )
    result = executor.execute(script, out_dir)
    assert result.outcome.value == OUTCOME_EXECUTED_OK
    assert "MAPSET=tmp_" in result.stdout

    # Every referenced artifact must exist for the case to be reusable.
    (out_dir / "attempt_1.stdout").write_text(result.stdout, encoding="utf-8")
    (out_dir / "attempt_1.stderr").write_text(result.stderr, encoding="utf-8")
    (out_dir / "attempt_1.log").write_text(result.stderr, encoding="utf-8")
    (out_dir / "final.py").write_text(script.read_text(), encoding="utf-8")

    from grass_agent.results import Attempt, CaseResult, mark_complete

    case = CaseResult(
        tc_id="tc_01", tier=1, category="single_tool", prompt="p", resume_key=KEY
    )
    case.attempts.append(
        Attempt(
            ordinal=1,
            outcome=OUTCOME_EXECUTED_OK,
            script_path="attempt_1.py",
            stdout_path="attempt_1.stdout",
            stderr_path="attempt_1.stderr",
            log_path="attempt_1.log",
            error_excerpt=None,
        )
    )
    case.recompute_verdicts()
    case.final_script = "final.py"
    mark_complete(tmp_path, case)

    reasons = []
    assert is_reusable(tmp_path, "tc_01", KEY, 2, reasons) is not None, reasons
    assert load(tmp_path, "tc_01").pass_at_healed is True


def test_missing_map_case_classifies_and_is_not_healed(dataset_project, tmp_path):
    out_dir = case_dir(tmp_path, "tc_11")
    out_dir.mkdir(parents=True)
    executor = Executor(dataset_project=dataset_project, timeout_s=60)
    script = _write(
        out_dir,
        "attempt_1.py",
        "from grass.tools import Tools\n"
        "Tools().r_slope_aspect(elevation='no_such_map', slope='s', aspect='a')\n",
    )
    result = executor.execute(script, out_dir)
    assert result.failure_mode is FailureMode.MISSING_INPUT
    assert result.failing_tool == "r.slope.aspect"
    assert "no_such_map" in result.error_excerpt


def test_case_result_json_shape(dataset_project, tmp_path):
    """The persisted schema is normative in contracts/case-result.md."""
    from grass_agent.results import Attempt, CaseResult, mark_complete

    case = CaseResult(tc_id="tc_01", tier=2, category="multi_step", prompt="p", resume_key=KEY)
    case.attempts.append(
        Attempt(ordinal=1, outcome=OUTCOME_STATIC_REJECTED, failure_mode="schema_misuse")
    )
    case.recompute_verdicts()
    mark_complete(tmp_path, case)

    payload = json.loads(result_path(tmp_path, "tc_01").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["status"] == "complete"
    assert payload["resume_key"]["attempt1_source"] == "fresh"
    assert payload["failure_mode_transitions"] == ["schema_misuse"]
    assert payload["pass_at_1"] is False and payload["pass_at_healed"] is False