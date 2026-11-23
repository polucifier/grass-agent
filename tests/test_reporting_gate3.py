"""Gate 3 dual-metric reporting (T046, T052).

The report is the delivery surface for the semantic oracle, the tier ledger,
and no-op detection. These tests pin the two-metric contract and the separated
Gate 2 historical section.
"""

import pytest

from grass_agent.classifier import FailureMode
from grass_agent.reporting import (
    GATE1_STATIC_VALIDITY,
    GATE2_PASS_AT_1,
    GATE2_PASS_AT_HEALED,
    aggregate,
    render_gate3_markdown,
    render_markdown,
)
from grass_agent.results import (
    BUDGET_INITIAL,
    BUDGET_RUNTIME,
    HARNESS_GATE3,
    OUTCOME_EXECUTED_OK,
    OUTCOME_NO_OP_DUPLICATE,
    OUTCOME_RUNTIME_FAILED,
    Attempt,
    CaseResult,
    ResumeKey,
    build_ledger,
)

KEY = ResumeKey("qwen2.5-coder:7b", 2, 120, "fresh", 2, 2, HARNESS_GATE3)


def _case(
    tc_id,
    *,
    executed=True,
    semantic=True,
    semantic_passed=True,
    duplicate=False,
    runtime_used=0,
    static_used=0,
    failure=None,
    tier=1,
    category="single_tool",
):
    result = CaseResult(
        tc_id=tc_id,
        tier=tier,
        category=category,
        prompt="p",
        resume_key=KEY,
        harness_version=HARNESS_GATE3,
    )
    attempts = []
    if failure:
        attempts.append(
            Attempt(
                ordinal=1,
                budget_tier=BUDGET_INITIAL,
                outcome=OUTCOME_RUNTIME_FAILED,
                stage="runtime",
                static_passed=True,
                failure_mode=failure,
                exit_code=1,
            )
        )
    attempts.append(
        Attempt(
            ordinal=len(attempts) + 1,
            budget_tier=BUDGET_INITIAL if not attempts else BUDGET_RUNTIME,
            outcome=OUTCOME_EXECUTED_OK if executed else OUTCOME_RUNTIME_FAILED,
            stage="success" if executed else "runtime",
            static_passed=True,
            failure_mode=None if executed else (failure or "missing_input"),
            exit_code=0 if executed else 1,
            new_maps={"raster": ["pilot_x"] if executed else [], "vector": []},
            semantic_evaluated=semantic and executed,
            semantic_passed=(semantic_passed if semantic and executed else None),
            assertion_results=(
                [{"output": "pilot_x", "check": "mean", "expected": 5.0,
                  "observed": 9.0 if not semantic_passed else 5.0,
                  "tolerance": 0.01, "passed": semantic_passed}]
                if semantic and executed
                else []
            ),
        )
    )
    if duplicate:
        attempts.append(
            Attempt(
                ordinal=len(attempts) + 1,
                budget_tier=BUDGET_RUNTIME,
                outcome=OUTCOME_NO_OP_DUPLICATE,
                stage="static",
                static_passed=False,
                failure_mode=FailureMode.GENERAL_EXCEPTION.value,
                duplicate=True,
                exit_code=None,
                new_maps={"raster": [], "vector": []},
            )
        )
    result.attempts = attempts
    result.recompute_verdicts()
    result.budget_ledger = build_ledger(attempts, 2, 2)
    result.budget_ledger.static_used = max(static_used, result.budget_ledger.static_used)
    result.budget_ledger.runtime_used = max(runtime_used, result.budget_ledger.runtime_used)
    result.budget_ledger.static_remaining = 2 - result.budget_ledger.static_used
    result.budget_ledger.runtime_remaining = 2 - result.budget_ledger.runtime_used
    return result


def _summary(results, **kwargs):
    defaults = dict(
        model="qwen2.5-coder:7b",
        suites=["benchmark_prompts_pilot10.json"],
        max_retries=2,
        timeout_s=120,
        attempt1_source="fresh",
        resume_key=KEY,
        cases_total=len(results),
        grass_version="8.5.0",
        dataset="nc_basic_spm_grass7",
        permanent_hash_before="abc",
        permanent_hash_after="abc",
        pilot_expectations_hash="deadbeef",
        pilot_reviewed=True,
        max_static_retries=2,
        max_runtime_retries=2,
    )
    defaults.update(kwargs)
    return aggregate(results, **defaults)


def _main_table(report):
    """The text between the Gate 3 metric heading and the Gate 2 section."""
    start = report.index("## Gate 3 metrics")
    end = report.index("## Gate 2 historical comparison")
    return report[start:end]


def test_main_table_has_exactly_the_two_metrics():
    results = [_case("pilot_tc_01")]
    report = render_gate3_markdown(_summary(results), results)
    table = _main_table(report)
    assert "Pass@Executed" in table
    assert "Pass@Semantic" in table
    assert "Pass@Healed" not in table
    assert "Pass@1" not in table


def test_semantic_never_exceeds_executed_on_the_semantic_subset():
    results = [
        _case("pilot_tc_01", executed=True, semantic_passed=True),
        _case("pilot_tc_02", executed=True, semantic_passed=False),
        _case("pilot_tc_03", executed=False, semantic=False, failure="missing_input"),
    ]
    summary = _summary(results)
    assert summary.pass_at_semantic <= summary.pass_at_executed_semantic_count
    assert summary.pass_at_semantic <= summary.pass_at_executed


def test_non_pilot_cases_are_excluded_from_the_semantic_denominator():
    results = [
        _case("pilot_tc_01", semantic_passed=True),
        _case("tc_01", semantic=False),
        _case("tc_02", semantic=False),
    ]
    summary = _summary(results)
    assert summary.cases_semantic == 1
    assert summary.semantic_not_evaluated == ["tc_01", "tc_02"]
    report = render_gate3_markdown(summary, results)
    assert "Semantic not evaluated" in report
    assert "tc_01" in report


def test_gap_is_computed_over_semantic_cases_only():
    results = [
        _case("pilot_tc_01", semantic_passed=True),
        _case("pilot_tc_02", semantic_passed=False),
        _case("tc_01", semantic=False),
        _case("tc_02", semantic=False),
    ]
    summary = _summary(results)
    assert summary.cases_semantic == 2
    assert summary.pass_at_executed_semantic_count == 2
    assert summary.execution_semantic_gap == pytest.approx(0.5)
    report = render_gate3_markdown(summary, results)
    assert "Execution→semantic gap over the semantic subset" in report


def test_semantic_failure_table_names_the_evidence():
    results = [_case("pilot_tc_09", semantic_passed=False)]
    report = render_gate3_markdown(_summary(results), results)
    assert "| Case | Output | Check | Expected | Observed | Tolerance | Verdict |" in report
    assert "pilot_x" in report
    assert "mean" in _main_table(report) or "mean" in report
    assert "5" in report and "9" in report
    assert "1%" in report


def test_semantic_failure_contributes_to_executed_not_semantic():
    results = [_case("pilot_tc_09", semantic_passed=False)]
    summary = _summary(results)
    assert summary.pass_at_executed == 1
    assert summary.pass_at_semantic == 0


def test_clean_run_explicitly_states_no_semantic_failures():
    results = [_case("pilot_tc_05")]
    report = render_gate3_markdown(_summary(results), results)
    assert "No semantic failures." in report


def test_tier_and_no_op_counters_render_even_when_zero():
    results = [_case("pilot_tc_01")]
    report = render_gate3_markdown(_summary(results), results)
    assert "## Repair budget usage" in report
    assert "## No-op duplicate detection" in report
    assert "Accepted duplicates executed | 0" in report


def test_duplicate_counters_and_pivot_are_rendered():
    results = [_case("pilot_tc_03", duplicate=True, semantic=False)]
    summary = _summary(results)
    assert summary.no_op_detected == 1
    assert summary.no_op_rejected == 1
    report = render_gate3_markdown(summary, results)
    assert "Duplicate candidates detected | 1" in report


def test_accepted_duplicate_execution_is_boldly_warned():
    result = _case("pilot_tc_03")
    # Corrupt the persisted evidence on purpose: the report must surface it.
    result.attempts.append(
        Attempt(
            ordinal=len(result.attempts) + 1,
            budget_tier=BUDGET_RUNTIME,
            outcome=OUTCOME_NO_OP_DUPLICATE,
            duplicate=True,
            failure_mode=FailureMode.GENERAL_EXCEPTION.value,
            exit_code=1,
        )
    )
    summary = _summary([result])
    assert summary.accepted_duplicate_executions == 1
    report = render_gate3_markdown(summary, [result])
    assert "FAILURE" in report


def test_gate2_historical_section_is_separate_and_frozen():
    results = [_case("pilot_tc_01")]
    report = render_gate3_markdown(_summary(results), results)
    section = report[report.index("## Gate 2 historical comparison"):]
    assert f"{GATE2_PASS_AT_1 * 100:.1f}%" in section
    assert f"{GATE2_PASS_AT_HEALED * 100:.1f}%" in section
    assert f"{GATE1_STATIC_VALIDITY * 100:.1f}%" in section
    assert "Pass@Healed" in section
    assert "different harnesses" in section


def test_all_five_caveats_are_present():
    results = [_case("pilot_tc_01")]
    report = render_gate3_markdown(_summary(results), results)
    assert "Semantic pass is not universal correctness." in report
    assert "Exit status is not correctness." in report
    assert "Generation is stochastic." in report
    assert "Semantic assertions never trigger repair." in report
    assert "Pilot expectations are independent." in report


def test_integrity_evidence_and_expectation_hash():
    results = [_case("pilot_tc_01")]
    report = render_gate3_markdown(_summary(results), results)
    assert "## Integrity evidence" in report
    assert "deadbeef" in report
    assert "abc" in report


def test_report_only_regeneration_is_byte_identical():
    results = [_case("pilot_tc_01"), _case("pilot_tc_02", semantic_passed=False)]
    live = render_gate3_markdown(_summary(results), results)
    regenerated = render_gate3_markdown(_summary(results), results)
    assert live == regenerated


def test_gate2_renderer_is_untouched():
    results = [_case("tc_01", semantic=False)]
    report = render_markdown(_summary(results), results)
    assert report.startswith("# Gate 2 Execution Report")
    assert "Pass@Healed" in report


def test_report_only_rebuilds_from_persisted_results(tmp_path):
    from benchmarks import run_gate3
    from grass_agent.config import ExecutionConfig
    from grass_agent.results import mark_complete, save, save_run_meta

    results = [_case("pilot_tc_01"), _case("pilot_tc_02", semantic_passed=False)]
    for result in results:
        save(tmp_path, result)
        mark_complete(tmp_path, result)
    save_run_meta(
        tmp_path,
        {
            "harness": "gate3",
            "model": KEY.model,
            "suites": ["benchmark_prompts_pilot10.json"],
            "max_retries": 2,
            "max_static_retries": 2,
            "max_runtime_retries": 2,
            "timeout_s": 120,
            "attempt1_source": "fresh",
            "cases_total": 2,
            "not_evaluated": [],
            "resumed": False,
            "permanent_hash_before": "abc",
            "permanent_hash_after": "abc",
            "leaked_scratch_dirs": [],
            "grass_version": "8.5.0",
            "dataset": "nc_basic_spm_grass7",
            "pilot_expectations_hash": "deadbeef",
            "pilot_reviewed": True,
        },
    )
    config = ExecutionConfig(output_dir=str(tmp_path), harness="gate3")
    report_path = tmp_path / "gate3_report.md"
    code = run_gate3.report_only(config, KEY, report_path)
    assert code == 0
    report = report_path.read_text(encoding="utf-8")
    assert "Pass@Executed" in report
    assert "Pass@Semantic" in report
    assert "Pass@Healed" not in _main_table(report)
    assert "deadbeef" in report


def test_declared_but_unexecuted_pilot_case_stays_in_the_denominator():
    """A pilot case that never executed cannot pass semantics, but it is not
    'semantic not evaluated' — it declared assertions, so it belongs in the
    denominator as a failure (FR-009f, T056)."""
    result = _case(
        "pilot_tc_18", executed=False, semantic=False, failure="missing_input"
    )
    result.semantic_declared = True
    result.recompute_verdicts()
    summary = _summary([result])
    assert summary.cases_semantic == 1
    assert summary.semantic_not_evaluated == []
    assert summary.pass_at_semantic == 0
    report = render_gate3_markdown(summary, [result])
    assert "pilot_tc_18" in report
    assert "| `pilot_tc_18`" in report
    assert "❌" in report
