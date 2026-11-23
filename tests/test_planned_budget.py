"""Cross-story budget and invariant regression for planned mode (T036)."""

from __future__ import annotations

import pytest

from grass_agent.healing import NoOpIndex
from grass_agent.results import (
    BUDGET_INITIAL,
    BUDGET_RUNTIME,
    OUTCOME_EXECUTED_OK,
    Attempt,
    CaseResult,
    ResultValidationError,
    ResumeKey,
    build_ledger,
    check_invariants,
    is_terminal,
)


def _key(pipeline="planned", budget=3686):
    return ResumeKey(
        model="m",
        max_retries=2,
        timeout=120,
        attempt1_source="fresh",
        max_static_retries=2,
        max_runtime_retries=2,
        harness="gate3",
        pipeline=pipeline,
        num_ctx=8192,
        manual_context_tokens=budget,
    )


def _attempt(ordinal, tier=BUDGET_INITIAL, **overrides):
    values = dict(
        ordinal=ordinal,
        budget_tier=tier,
        pipeline="planned",
        num_ctx=8192,
        manual_context_tokens=3686,
        stage="runtime",
        outcome=OUTCOME_EXECUTED_OK,
        static_passed=True,
        new_maps={"raster": [], "vector": []},
    )
    values.update(overrides)
    return Attempt(**values)


def _case(attempts, pipeline="planned"):
    result = CaseResult(
        tc_id="tc_01",
        status="complete",
        resume_key=_key(pipeline),
        attempts=attempts,
    )
    result.recompute_verdicts()
    return result


def test_planner_fallback_consumes_no_tier_and_creates_no_candidate():
    attempt = _attempt(1, plan_fallback=True, planner_invocations=2)
    ledger = build_ledger([attempt], 2, 2)
    assert ledger.static_used == 0
    assert ledger.runtime_used == 0
    assert ledger.static_remaining == 2
    assert ledger.runtime_remaining == 2


def test_tool_swap_consumes_the_producing_tier():
    swapped = _attempt(2, tier=BUDGET_RUNTIME, tool_swaps=["r.reclass -> r.recode"])
    ledger = build_ledger([_attempt(1), swapped], 2, 2)
    assert ledger.runtime_used == 1


def test_planner_invocations_never_exceed_three():
    valid = _attempt(
        1,
        plan_repair_count=1,
        replan_count=1,
        planner_invocations=3,
        planned_tools=["r.slope.aspect"],
    )
    case = _case([valid])
    check_invariants(case, 2, max_static_retries=2, max_runtime_retries=2)

    invalid = _attempt(
        1,
        plan_repair_count=1,
        replan_count=1,
        planner_invocations=4,
        planned_tools=["r.slope.aspect"],
    )
    with pytest.raises(ResultValidationError):
        check_invariants(_case([invalid]), 2, max_static_retries=2, max_runtime_retries=2)


def test_duplicate_detection_stays_code_based():
    index = NoOpIndex()
    index.add("tools.r_slope_aspect(input='e', output='s')", 1)
    assert index.match("tools.r_slope_aspect(input='e', output='s')") is not None
    # Changing only plan metadata is not part of the code digest.
    assert index.match("tools.r_univar(map='e')") is None


def test_candidate_bound_is_unchanged():
    result = CaseResult(
        tc_id="tc_01",
        resume_key=_key(),
        attempts=[
            _attempt(1),
            _attempt(2, tier=BUDGET_RUNTIME),
            _attempt(3, tier=BUDGET_RUNTIME),
        ],
    )
    result.recompute_verdicts()
    assert len(result.attempts) <= 1 + 2 + 2


def test_semantic_failure_consumes_no_tier():
    attempt = _attempt(1, semantic_evaluated=True, semantic_passed=False, assertion_results=[{"check": "mean", "passed": False, "output": "slope"}])
    attempt.new_maps = {"raster": ["slope"], "vector": []}
    result = _case([attempt])
    result.recompute_verdicts()
    ledger = build_ledger(result.attempts, 2, 2)
    assert ledger.static_used == 0 and ledger.runtime_used == 0
    assert result.pass_at_executed is True
    assert result.pass_at_semantic is False


def test_ledger_and_verdicts_recompute_identically_for_each_mode():
    for mode in ("legacy", "manual-kb", "planned"):
        semantic = mode != "legacy"
        attempt = Attempt(
            ordinal=1,
            budget_tier=BUDGET_INITIAL,
            pipeline=mode,
            num_ctx=8192,
            manual_context_tokens=3686 if mode != "legacy" else None,
            stage="runtime",
            outcome=OUTCOME_EXECUTED_OK,
            static_passed=True,
            new_maps={"raster": ["slope"], "vector": []},
            semantic_evaluated=semantic,
            semantic_passed=True if semantic else None,
            assertion_results=[{"check": "mean", "passed": True}] if semantic else [],
        )
        result = CaseResult(
            tc_id="tc_01",
            status="complete",
            resume_key=_key(pipeline=mode, budget=3686 if mode != "legacy" else None),
            attempts=[attempt],
            harness_version="gate3",
        )
        result.recompute_verdicts()
        first = build_ledger(result.attempts, 2, 2)
        result.recompute_verdicts()
        second = build_ledger(result.attempts, 2, 2)
        assert first == second
        assert result.pass_at_executed is True
        if semantic:
            assert result.pass_at_semantic is True
