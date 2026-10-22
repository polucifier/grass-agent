"""Report aggregation and rendering (tasks T057, T058)."""

import pytest

from grass_agent.classifier import FailureMode
from grass_agent.reporting import (
    EXIT_STATUS_CAVEAT,
    GATE1_STATIC_VALIDITY,
    aggregate,
    format_gain,
    render_markdown,
)
from grass_agent.results import (
    OUTCOME_CRASHED,
    OUTCOME_EXECUTED_OK,
    OUTCOME_RUNTIME_FAILED,
    OUTCOME_STATIC_REJECTED,
    OUTCOME_TIMEOUT,
    Attempt,
    CaseResult,
    ResumeKey,
)

KEY = ResumeKey("qwen2.5-coder:3b", 2, 60, "fresh")


def _case(tc_id, outcomes, modes=None, latencies=None, tokens=None):
    result = CaseResult(tc_id=tc_id, category="single_tool", prompt="p", resume_key=KEY)
    modes = modes or {}
    for ordinal, outcome in enumerate(outcomes, start=1):
        result.attempts.append(
            Attempt(
                ordinal=ordinal,
                outcome=outcome,
                failure_mode=modes.get(ordinal),
                latency_s=(latencies or [1.0] * len(outcomes))[ordinal - 1],
                prompt_tokens=(tokens or [(100, 50)] * len(outcomes))[ordinal - 1][0],
                completion_tokens=(tokens or [(100, 50)] * len(outcomes))[ordinal - 1][1],
            )
        )
    result.recompute_verdicts()
    return result


def _summary(results, **kwargs):
    defaults = dict(
        model="qwen2.5-coder:3b",
        suites=["tier1", "tier2"],
        max_retries=2,
        timeout_s=60,
        attempt1_source="fresh",
        resume_key=KEY,
        cases_total=len(results),
    )
    defaults.update(kwargs)
    return aggregate(results, **defaults)


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


def test_pass_at_1_and_healed_differ_when_healing_works():
    results = [
        _case("tc_01", [OUTCOME_EXECUTED_OK]),
        _case("tc_02", [OUTCOME_RUNTIME_FAILED, OUTCOME_EXECUTED_OK]),
        _case("tc_03", [OUTCOME_RUNTIME_FAILED, OUTCOME_RUNTIME_FAILED]),
    ]
    summary = _summary(results)
    assert summary.pass_at_1 == 1
    assert summary.pass_at_healed == 2
    assert summary.pass_at_1_rate == pytest.approx(1 / 3)
    assert summary.pass_at_healed_rate == pytest.approx(2 / 3)
    assert summary.healing_gain_absolute == pytest.approx(1 / 3)


def test_failure_mode_counts_sum_to_failed_attempts():
    """Invariant I5: no failure is dropped from the counts."""
    results = [
        # 2 attempts, 1 succeeds -> 1 failed
        _case("tc_01", [OUTCOME_RUNTIME_FAILED, OUTCOME_EXECUTED_OK],
              {1: "missing_input"}),
        # 2 attempts, both fail -> 2 failed
        _case("tc_02", [OUTCOME_CRASHED, OUTCOME_TIMEOUT],
              {1: "general_exception", 2: "general_exception"}),
        # 3 attempts, all statically rejected -> 3 failed, never executed
        _case("tc_03", [OUTCOME_STATIC_REJECTED, OUTCOME_STATIC_REJECTED,
                        OUTCOME_STATIC_REJECTED],
              {1: "schema_misuse", 2: "schema_misuse", 3: "schema_misuse"}),
    ]
    summary = _summary(results)
    failed = sum(1 for r in results for a in r.attempts if not a.succeeded)
    assert failed == 6
    assert sum(summary.failure_mode_counts.values()) == failed
    assert summary.failure_mode_counts == {
        "missing_input": 1, "general_exception": 2, "schema_misuse": 3,
    }


def test_all_four_modes_are_countable():
    results = [
        _case("tc_01", [OUTCOME_RUNTIME_FAILED], {1: FailureMode.MISSING_INPUT.value}),
        _case("tc_02", [OUTCOME_RUNTIME_FAILED], {1: FailureMode.SCHEMA_MISUSE.value}),
        _case("tc_03", [OUTCOME_RUNTIME_FAILED], {1: FailureMode.UNKNOWN_METHOD.value}),
        _case("tc_04", [OUTCOME_CRASHED], {1: FailureMode.GENERAL_EXCEPTION.value}),
    ]
    summary = _summary(results)
    assert set(summary.failure_mode_counts) == {m.value for m in FailureMode}


def test_transitions_are_ordered_pairs():
    results = [
        _case("tc_01", [OUTCOME_RUNTIME_FAILED, OUTCOME_RUNTIME_FAILED, OUTCOME_EXECUTED_OK],
              {1: "missing_input", 2: "schema_misuse"}),
    ]
    summary = _summary(results)
    assert summary.failure_mode_transitions == {
        "missing_input -> schema_misuse": 1,
        "schema_misuse -> success": 1,
    }


def test_per_ordinal_latency_and_tokens():
    results = [
        _case("tc_01", [OUTCOME_RUNTIME_FAILED, OUTCOME_EXECUTED_OK],
              {1: "missing_input"}, latencies=[10.0, 20.0], tokens=[(200, 20), (400, 40)]),
    ]
    summary = _summary(results)
    assert summary.mean_latency(1) == pytest.approx(10.0)
    assert summary.mean_latency(2) == pytest.approx(20.0)
    assert summary.prompt_tokens_total == 600
    assert summary.completion_tokens_total == 60


def test_reuse_artifacts_reports_zero_tokens_for_attempt_one():
    results = [_case("tc_01", [OUTCOME_EXECUTED_OK], tokens=[(0, 0)])]
    summary = _summary(results, attempt1_source="reuse_artifacts")
    assert summary.prompt_tokens_total == 0
    assert summary.completion_tokens_total == 0


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def test_report_states_the_correctness_caveat():
    """SC-014: the exit-status caveat must appear unconditionally."""
    results = [_case("tc_01", [OUTCOME_EXECUTED_OK])]
    report = render_markdown(_summary(results), results)
    assert EXIT_STATUS_CAVEAT.split("\n")[0] in report
    assert "Exit status is not correctness" in report


def test_report_always_labels_attempt1_source():
    for source in ("fresh", "reuse_artifacts"):
        results = [_case("tc_01", [OUTCOME_EXECUTED_OK])]
        report = render_markdown(_summary(results, attempt1_source=source), results)
        assert source in report


def test_reuse_run_is_flagged_as_not_measured():
    """SC-015: reuse figures must not read as freshly measured."""
    results = [_case("tc_01", [OUTCOME_EXECUTED_OK], tokens=[(0, 0)])]
    report = render_markdown(_summary(results, attempt1_source="reuse_artifacts"), results)
    assert "no inference" in report


def test_report_labels_the_two_harnesses_distinctly():
    """The Gate 1 / Gate 2 rates are not one continuous scale."""
    results = [_case("tc_01", [OUTCOME_EXECUTED_OK])]
    report = render_markdown(_summary(results), results)
    assert "different harnesses" in report
    assert f"{GATE1_STATIC_VALIDITY * 100:.1f}%" in report


def test_report_never_misreports_zero_denominator():
    summary = RunSummaryEmpty = None
    from grass_agent.reporting import RunSummary

    empty = RunSummary(model="m", cases_completed=0)
    assert empty.pass_at_1_rate == 0.0
    assert empty.pass_at_healed_rate == 0.0
    assert format_gain(empty.healing_gain_relative) == "n/a (zero-shot rate was 0%)"


def test_report_records_integrity_evidence():
    results = [_case("tc_01", [OUTCOME_EXECUTED_OK])]
    summary = _summary(
        results, permanent_hash_before="abc123", permanent_hash_after="abc123"
    )
    report = render_markdown(summary, results)
    assert "abc123" in report
    assert summary.permanent_unchanged is True
    assert "Integrity evidence" in report
    assert "abc123" in report.split("permanent_hash_before")[1]


def test_changed_permanent_hash_is_surfaced():
    results = [_case("tc_01", [OUTCOME_EXECUTED_OK])]
    summary = _summary(results, permanent_hash_before="abc", permanent_hash_after="xyz")
    assert summary.permanent_unchanged is False
    assert "unknown or changed" in render_markdown(summary, results)


def test_leaked_scratch_dirs_are_listed():
    results = [_case("tc_01", [OUTCOME_EXECUTED_OK])]
    summary = _summary(results, leaked_scratch_dirs=["tmp_abc123"])
    report = render_markdown(summary, results)
    assert "tmp_abc123" in report


def test_not_evaluated_cases_keep_the_denominator_explicit():
    """A missing case is reported, never silently omitted."""
    results = [_case("tc_01", [OUTCOME_EXECUTED_OK])]
    summary = _summary(results, cases_total=3, not_evaluated=["tc_02", "tc_03"])
    report = render_markdown(summary, results)
    assert "Not evaluated" in report
    assert "tc_02" in report and "tc_03" in report
    assert "1 completed of 3" in report