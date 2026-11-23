"""Two-tier budget accounting and the additive Gate 3 schema (T010).

The properties under test are the ones that make the two-tier budget
trustworthy without re-running a case: the ledger, the no-op count, and both
verdicts are pure functions of the persisted attempts, and a legacy Gate 2
record keeps its old ceiling and verdicts.
"""

import pytest

from grass_agent.classifier import FailureMode
from grass_agent.results import (
    BUDGET_INITIAL,
    BUDGET_RUNTIME,
    BUDGET_STATIC,
    HARNESS_GATE3,
    OUTCOME_EXECUTED_OK,
    OUTCOME_NO_OP_DUPLICATE,
    OUTCOME_RUNTIME_FAILED,
    OUTCOME_STATIC_REJECTED,
    OUTCOME_TIMEOUT,
    Attempt,
    BudgetLedger,
    CaseResult,
    ResumeKey,
    ResultValidationError,
    build_ledger,
    check_invariants,
    recompute_ledger,
    save,
    load,
)


def _attempt(
    ordinal,
    tier,
    outcome,
    *,
    stage="runtime",
    failure_mode=FailureMode.MISSING_INPUT,
    new_maps=None,
    duplicate=False,
    static_passed=True,
    exit_code=None,
    semantic_evaluated=False,
    semantic_passed=None,
    assertion_results=None,
):
    if outcome == OUTCOME_EXECUTED_OK:
        failure_mode = None
    if duplicate:
        failure_mode = FailureMode.GENERAL_EXCEPTION.value
        exit_code = None
        new_maps = {"raster": [], "vector": []}
    return Attempt(
        ordinal=ordinal,
        budget_tier=tier,
        stage=stage,
        outcome=outcome,
        failure_mode=failure_mode,
        static_passed=static_passed,
        exit_code=exit_code,
        duplicate=duplicate,
        new_maps=new_maps or {"raster": [], "vector": []},
        semantic_evaluated=semantic_evaluated,
        semantic_passed=semantic_passed,
        assertion_results=list(assertion_results or []),
    )


def _gate3_case(attempts, static_limit=2, runtime_limit=2):
    result = CaseResult(tc_id="tc_01", harness_version=HARNESS_GATE3)
    result.attempts = attempts
    result.recompute_verdicts()
    result.budget_ledger = recompute_ledger(result, static_limit, runtime_limit)
    return result


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------


def test_ledger_counts_only_repair_candidates_by_producing_tier():
    attempts = [
        _attempt(1, BUDGET_INITIAL, OUTCOME_RUNTIME_FAILED),
        _attempt(2, BUDGET_STATIC, OUTCOME_STATIC_REJECTED, stage="static"),
        _attempt(3, BUDGET_RUNTIME, OUTCOME_RUNTIME_FAILED),
    ]
    ledger = build_ledger(attempts, 2, 2)
    assert ledger.static_used == 1
    assert ledger.runtime_used == 1
    assert ledger.static_remaining == 1
    assert ledger.runtime_remaining == 1


def test_recomputing_the_ledger_is_idempotent():
    result = _gate3_case(
        [
            _attempt(1, BUDGET_INITIAL, OUTCOME_RUNTIME_FAILED),
            _attempt(2, BUDGET_RUNTIME, OUTCOME_RUNTIME_FAILED),
        ]
    )
    assert recompute_ledger(result) == result.budget_ledger


def test_persisted_ledger_mismatch_is_rejected():
    result = _gate3_case(
        [
            _attempt(1, BUDGET_INITIAL, OUTCOME_RUNTIME_FAILED),
            _attempt(2, BUDGET_RUNTIME, OUTCOME_RUNTIME_FAILED),
        ]
    )
    result.budget_ledger.static_used = 2
    with pytest.raises(ResultValidationError, match="I15"):
        check_invariants(result, max_retries=2)


def test_tier_ceiling_is_enforced():
    result = _gate3_case(
        [
            _attempt(1, BUDGET_INITIAL, OUTCOME_RUNTIME_FAILED),
            _attempt(2, BUDGET_RUNTIME, OUTCOME_RUNTIME_FAILED),
            _attempt(3, BUDGET_RUNTIME, OUTCOME_RUNTIME_FAILED),
            _attempt(4, BUDGET_RUNTIME, OUTCOME_RUNTIME_FAILED),
        ]
    )
    with pytest.raises(ResultValidationError, match="I9"):
        check_invariants(result, max_retries=2)


# --------------------------------------------------------------------------
# Legacy inference and compatibility
# --------------------------------------------------------------------------


def test_legacy_attempt_tier_is_inferred_on_load(tmp_path):
    result = CaseResult(tc_id="tc_01")
    result.attempts = [
        Attempt(ordinal=1, outcome=OUTCOME_RUNTIME_FAILED,
                failure_mode=FailureMode.MISSING_INPUT),
        Attempt(ordinal=2, outcome=OUTCOME_STATIC_REJECTED,
                stage="static", failure_mode="schema_misuse"),
        Attempt(ordinal=3, outcome=OUTCOME_RUNTIME_FAILED,
                failure_mode=FailureMode.MISSING_INPUT),
    ]
    result.recompute_verdicts()
    # Simulate a Gate 2 payload: strip the Gate 3 discriminator.
    payload = result.to_dict()
    payload.pop("harness_version")
    for attempt in payload["attempts"]:
        attempt.pop("budget_tier")
    loaded = CaseResult.from_dict(payload)
    assert [a.budget_tier for a in loaded.attempts] == [
        BUDGET_INITIAL,
        BUDGET_STATIC,
        BUDGET_RUNTIME,
    ]
    assert loaded.harness_version == "gate2"
    assert loaded.semantic_evaluated is False
    assert loaded.pass_at_semantic is None


def test_legacy_max_retries_ceiling_still_raises_i1():
    """A four-runtime-failure Gate 2 case still exceeds max_retries + 1."""
    result = CaseResult(tc_id="tc_01")
    result.attempts = [
        Attempt(ordinal=ordinal, outcome=OUTCOME_TIMEOUT,
                failure_mode="general_exception")
        for ordinal in range(1, 5)
    ]
    result.recompute_verdicts()
    with pytest.raises(ResultValidationError, match="I1"):
        check_invariants(result, max_retries=2)


def test_legacy_pass_at_executed_mirrors_pass_at_healed():
    result = CaseResult(tc_id="tc_01")
    result.attempts = [
        Attempt(ordinal=1, outcome=OUTCOME_EXECUTED_OK),
    ]
    result.recompute_verdicts()
    assert result.harness_version == "gate2"
    assert result.pass_at_executed is True


# --------------------------------------------------------------------------
# ResumeKey
# --------------------------------------------------------------------------


def test_resume_key_none_normalises_to_the_legacy_budget():
    legacy = ResumeKey(model="m", max_retries=2, timeout=60, attempt1_source="fresh")
    explicit = ResumeKey(
        model="m",
        max_retries=2,
        timeout=60,
        attempt1_source="fresh",
        max_static_retries=2,
        max_runtime_retries=2,
    )
    assert legacy.matches(explicit)
    assert explicit.matches(legacy)


def test_resume_key_tier_budgets_discriminate():
    base = ResumeKey("m", 2, 60, "fresh", max_static_retries=1,
                     max_runtime_retries=2)
    other = ResumeKey("m", 2, 60, "fresh", max_static_retries=2,
                      max_runtime_retries=2)
    assert not base.matches(other)


def test_resume_key_harness_discriminates():
    gate2 = ResumeKey("m", 2, 60, "fresh")
    gate3 = ResumeKey("m", 2, 60, "fresh", harness=HARNESS_GATE3)
    assert not gate2.matches(gate3)
    assert not gate3.matches(gate2)


# --------------------------------------------------------------------------
# Gate 3 verdicts and no-op accounting
# --------------------------------------------------------------------------


def test_no_op_count_equals_duplicate_attempts():
    result = _gate3_case(
        [
            _attempt(1, BUDGET_INITIAL, OUTCOME_RUNTIME_FAILED),
            _attempt(2, BUDGET_RUNTIME, OUTCOME_NO_OP_DUPLICATE, duplicate=True),
        ]
    )
    assert result.no_op_count == 1
    check_invariants(result, max_retries=2)


def test_no_op_count_mismatch_is_rejected():
    result = _gate3_case(
        [
            _attempt(1, BUDGET_INITIAL, OUTCOME_RUNTIME_FAILED),
            _attempt(2, BUDGET_RUNTIME, OUTCOME_NO_OP_DUPLICATE, duplicate=True),
        ]
    )
    result.no_op_count = 0
    with pytest.raises(ResultValidationError, match="I15"):
        check_invariants(result, max_retries=2)


def test_pass_at_executed_requires_a_new_map():
    result = _gate3_case(
        [
            _attempt(1, BUDGET_INITIAL, OUTCOME_EXECUTED_OK),
        ]
    )
    assert result.pass_at_healed is True
    assert result.pass_at_executed is False


def test_pass_at_executed_and_semantic_verdict():
    result = _gate3_case(
        [
            _attempt(
                1,
                BUDGET_INITIAL,
                OUTCOME_EXECUTED_OK,
                new_maps={"raster": ["pilot_slope"], "vector": []},
                semantic_evaluated=True,
                semantic_passed=False,
                assertion_results=[
                    {"output": "pilot_slope", "check": "mean", "passed": False}
                ],
            )
        ]
    )
    assert result.pass_at_executed is True
    assert result.semantic_evaluated is True
    assert result.pass_at_semantic is False
    check_invariants(result, max_retries=2)


def test_semantic_pass_implies_execution_pass():
    result = _gate3_case(
        [
            _attempt(
                1,
                BUDGET_INITIAL,
                OUTCOME_EXECUTED_OK,
                new_maps={"raster": ["pilot_slope"], "vector": []},
                semantic_evaluated=True,
                semantic_passed=True,
                assertion_results=[
                    {"output": "pilot_slope", "check": "mean", "passed": True}
                ],
            )
        ]
    )
    assert result.pass_at_semantic is True
    check_invariants(result, max_retries=2)


def test_duplicate_must_not_carry_execution_evidence():
    result = _gate3_case(
        [
            _attempt(1, BUDGET_INITIAL, OUTCOME_RUNTIME_FAILED),
            _attempt(2, BUDGET_RUNTIME, OUTCOME_NO_OP_DUPLICATE, duplicate=True),
        ]
    )
    result.attempts[1].timed_out = True
    with pytest.raises(ResultValidationError, match="I14"):
        check_invariants(result, max_retries=2)


def test_round_trip_preserves_gate3_fields(tmp_path):
    result = _gate3_case(
        [
            _attempt(1, BUDGET_INITIAL, OUTCOME_RUNTIME_FAILED),
            _attempt(
                2,
                BUDGET_RUNTIME,
                OUTCOME_EXECUTED_OK,
                new_maps={"raster": ["pilot_slope"], "vector": []},
                semantic_evaluated=True,
                semantic_passed=True,
                assertion_results=[
                    {"output": "pilot_slope", "check": "mean", "passed": True}
                ],
            ),
        ]
    )
    result.final_script = "final.py"
    save(tmp_path, result)
    loaded = load(tmp_path, "tc_01")
    assert loaded.harness_version == HARNESS_GATE3
    assert loaded.pass_at_executed is True
    assert loaded.pass_at_semantic is True
    assert loaded.budget_ledger == result.budget_ledger
    assert loaded.attempts[1].new_maps == {"raster": ["pilot_slope"], "vector": []}


# --------------------------------------------------------------------------
# Tier accounting through the real run_case loop (T040)
# --------------------------------------------------------------------------

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from benchmarks import run_gate2
from grass_agent.config import ExecutionConfig
from grass_agent.classifier import FailureMode
from grass_agent.executor import AttemptOutcome
from grass_agent.healing import RepairAttempt


class _Retriever:
    def get_tool(self, name):
        return None


class _Generator:
    retriever = _Retriever()
    provider = SimpleNamespace(last_stats={"prompt_tokens": 1, "completion_tokens": 1})

    def __init__(self, code):
        self.code = code

    def generate(self, prompt, inventory_block=""):
        return self.code


class _Healer:
    def __init__(self, codes):
        self.codes = list(codes)
        self.contexts = []
        self.pivots = []

    def build_context(self, **kwargs):
        self.contexts.append(kwargs)
        return kwargs

    def repair(self, context, pivot=False):
        self.pivots.append(pivot)
        code = self.codes.pop(0) if self.codes else "print('exhausted')\n"
        return RepairAttempt(code=code, pivot_used=pivot)


class _Execution:
    def __init__(self, outcome, new_maps=None, failure_mode=None):
        self.outcome = outcome
        self.exit_code = 0 if outcome is AttemptOutcome.EXECUTED_OK else 1
        self.signal_name = None
        self.timed_out = outcome is AttemptOutcome.TIMEOUT
        self.failure_mode = failure_mode
        self.failing_tool = None
        self.error_excerpt = "" if outcome is AttemptOutcome.EXECUTED_OK else "ERROR: boom"
        self.stdout = ""
        self.stderr = self.error_excerpt
        self.latency_s = 0.01
        self.new_maps = new_maps or {"raster": [], "vector": []}
        self.semantic = None

    @property
    def succeeded(self):
        return self.outcome is AttemptOutcome.EXECUTED_OK


class _Executor:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def execute(self, script, workdir, semantic_spec=None, case_id=None):
        self.calls += 1
        return self.results.pop(0) if self.results else _Execution(
            AttemptOutcome.EXECUTED_OK, {"raster": ["pilot_x"], "vector": []}
        )


def _run(case_id="pilot_tc_x", *, initial="print('initial')\n", healer_codes=(),
         executions=(), static=2, runtime=2, tmp_path=None):
    out = Path(tmp_path)
    config = ExecutionConfig(
        harness=HARNESS_GATE3,
        max_static_retries=static,
        max_runtime_retries=runtime,
        output_dir=str(out),
    )
    key = ResumeKey("m", 2, 120, "fresh", static, runtime, HARNESS_GATE3)
    case = {
        "id": case_id,
        "tier": 1,
        "category": "single_tool",
        "prompt": "Drive a stub case.",
        "auxiliary_inputs": [],
    }
    healer = _Healer(healer_codes)
    executor = _Executor(executions)
    result = run_gate2.run_case(
        case,
        config,
        _Generator(initial),
        healer,
        executor,
        out,
        out,
        key,
    )
    return result, executor, healer, out


def test_static_exhaustion_never_calls_the_executor(tmp_path):
    result, executor, _, _ = _run(
        initial="def broken(:\n",
        healer_codes=["def also_broken(:\n", "def still_broken(:\n"],
        static=2,
        runtime=2,
        tmp_path=tmp_path,
    )
    assert executor.calls == 0
    assert result.budget_ledger.static_used == 2
    assert result.budget_ledger.runtime_used == 0
    assert result.budget_ledger.runtime_remaining == 2
    assert all(a.outcome == OUTCOME_STATIC_REJECTED for a in result.attempts)


def test_two_static_repairs_leave_the_runtime_tier_untouched(tmp_path):
    result, executor, _, _ = _run(
        initial="def broken(:\n",
        healer_codes=["def also_broken(:\n", "print('valid now')\n"],
        executions=[_Execution(AttemptOutcome.EXECUTED_OK,
                               {"raster": ["pilot_x"], "vector": []})],
        static=2,
        runtime=2,
        tmp_path=tmp_path,
    )
    assert executor.calls == 1
    assert result.budget_ledger.static_used == 2
    assert result.budget_ledger.runtime_used == 0
    assert result.pass_at_executed is True


def test_runtime_failures_never_replenish_the_static_tier(tmp_path):
    result, executor, _, _ = _run(
        initial="print('initial')\n",
        healer_codes=["print('repair1')\n", "print('repair2')\n"],
        executions=[
            _Execution(AttemptOutcome.RUNTIME_FAILED, failure_mode=FailureMode.MISSING_INPUT),
            _Execution(AttemptOutcome.EXECUTED_OK,
                       {"raster": ["pilot_x"], "vector": []}),
        ],
        static=2,
        runtime=2,
        tmp_path=tmp_path,
    )
    assert executor.calls == 2
    assert result.budget_ledger.static_used == 0
    assert result.budget_ledger.runtime_used == 1
    assert result.budget_ledger.static_remaining == 2


def test_runtime_tier_static_invalid_candidate_is_charged_to_runtime(tmp_path):
    result, executor, _, _ = _run(
        initial="print('initial')\n",
        healer_codes=["def broken(:\n", "print('runtime repair')\n"],
        executions=[
            _Execution(AttemptOutcome.RUNTIME_FAILED, failure_mode=FailureMode.MISSING_INPUT),
            _Execution(AttemptOutcome.EXECUTED_OK,
                       {"raster": ["pilot_x"], "vector": []}),
        ],
        static=2,
        runtime=2,
        tmp_path=tmp_path,
    )
    # Executor sees only the initial candidate and the valid runtime repair.
    assert executor.calls == 2
    assert result.budget_ledger.static_used == 0
    assert result.budget_ledger.runtime_used == 2
    assert result.attempts[1].budget_tier == BUDGET_RUNTIME
    assert result.attempts[1].static_passed is False
    assert result.attempts[1].exit_code is None


def test_exit_zero_with_no_new_map_requests_a_runtime_repair(tmp_path):
    result, executor, _, _ = _run(
        initial="print('no map')\n",
        healer_codes=["print('makes a map')\n"],
        executions=[
            _Execution(AttemptOutcome.EXECUTED_OK),
            _Execution(AttemptOutcome.EXECUTED_OK,
                       {"raster": ["pilot_x"], "vector": []}),
        ],
        static=2,
        runtime=2,
        tmp_path=tmp_path,
    )
    assert executor.calls == 2
    assert result.budget_ledger.runtime_used == 1
    assert result.pass_at_executed is True


def test_maximum_candidates_at_defaults_is_five(tmp_path):
    result, executor, _, _ = _run(
        initial="def broken(:\n",
        healer_codes=[
            "def broken_repair(:\n",
            "print('static two executes')\n",
            "print('runtime one')\n",
            "print('runtime two')\n",
        ],
        executions=[
            _Execution(AttemptOutcome.RUNTIME_FAILED, failure_mode=FailureMode.MISSING_INPUT),
            _Execution(AttemptOutcome.RUNTIME_FAILED, failure_mode=FailureMode.MISSING_INPUT),
            _Execution(AttemptOutcome.RUNTIME_FAILED, failure_mode=FailureMode.MISSING_INPUT),
        ],
        static=2,
        runtime=2,
        tmp_path=tmp_path,
    )
    assert len(result.attempts) == 5
    assert len(result.attempts) <= 1 + 2 + 2


def test_gate2_result_never_matches_a_gate3_resume_key(tmp_path):
    from grass_agent.results import is_reusable, save, mark_complete

    result, _, _, out = _run(tmp_path=tmp_path)
    result.resume_key = ResumeKey("m", 2, 120, "fresh")
    result.harness_version = "gate2"
    mark_complete(out, result)
    gate3_key = ResumeKey("m", 2, 120, "fresh", 2, 2, HARNESS_GATE3)
    reasons = []
    assert is_reusable(out, result.tc_id, gate3_key, 2, reasons,
                       max_static_retries=2, max_runtime_retries=2) is None
    assert any("resume key" in reason for reason in reasons)


def _canonical(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["completed_at"] = None
    for attempt in payload["attempts"]:
        attempt["latency_s"] = 0.0
        attempt["prompt_tokens"] = 0
        attempt["completion_tokens"] = 0
    return json.dumps(payload, indent=2, sort_keys=True)


def test_tier_accounting_is_deterministic_for_identical_inputs(tmp_path):
    def sequence(root):
        return _run(
            case_id="pilot_tc_x",
            initial="def broken(:\n",
            healer_codes=["print('valid')\n", "def broken2(:\n", "print('valid2')\n"],
            executions=[
                _Execution(AttemptOutcome.RUNTIME_FAILED,
                           failure_mode=FailureMode.MISSING_INPUT),
                _Execution(AttemptOutcome.EXECUTED_OK,
                           {"raster": ["pilot_x"], "vector": []}),
            ],
            static=2,
            runtime=2,
            tmp_path=root,
        )

    first, _, _, first_root = sequence(tmp_path / "a")
    second, _, _, second_root = sequence(tmp_path / "b")
    assert _canonical(first_root / "pilot_tc_x" / "case_result.json") == _canonical(
        second_root / "pilot_tc_x" / "case_result.json"
    )
    assert first.budget_ledger == second.budget_ledger
