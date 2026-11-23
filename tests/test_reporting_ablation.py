"""Pipeline metadata and per-mode ablation reporting (T038)."""

from __future__ import annotations

import json
from pathlib import Path

from grass_agent.reporting import (
    aggregate,
    render_gate3_markdown,
    render_pipeline_ablation,
)
from grass_agent.results import (
    ATTEMPT1_SOURCES,
    OUTCOME_EXECUTED_OK,
    Attempt,
    CaseResult,
    ResumeKey,
    save,
    save_run_meta,
)


def _key(pipeline="legacy", num_ctx=8192, budget=None):
    return ResumeKey(
        model="m",
        max_retries=2,
        timeout=120,
        attempt1_source="fresh",
        max_static_retries=2,
        max_runtime_retries=2,
        harness="gate3",
        pipeline=pipeline,
        num_ctx=num_ctx,
        manual_context_tokens=budget,
    )


def _result(tc_id: str, pipeline="manual-kb", executed=True) -> CaseResult:
    attempt = Attempt(
        ordinal=1,
        stage="runtime",
        outcome=OUTCOME_EXECUTED_OK if executed else "runtime_failed",
        static_passed=True,
        pipeline=pipeline,
        num_ctx=8192,
        manual_context_tokens=3686,
        manual_card_tokens=400,
        plan_repair_count=1 if pipeline == "planned" else 0,
        replan_count=0,
        planner_invocations=2 if pipeline == "planned" else 0,
        plan_fallback=False,
        shortlist_shortfall=False,
        tool_swaps=["r.reclass -> r.recode"] if pipeline == "planned" else [],
        new_maps={"raster": ["slope"] if executed else [], "vector": []},
    )
    result = CaseResult(
        tc_id=tc_id,
        tier=1,
        category="single_tool",
        status="complete",
        resume_key=_key(pipeline),
        attempts=[attempt],
    )
    result.recompute_verdicts()
    return result


def test_report_header_includes_pipeline_metadata():
    result = _result("tc_01", pipeline="planned")
    summary = aggregate(
        [result],
        model="m",
        suites=["pilot"],
        max_retries=2,
        timeout_s=120,
        attempt1_source="fresh",
        resume_key=_key("planned"),
        cases_total=1,
        pipeline="planned",
        num_ctx=8192,
        manual_context_tokens=3686,
    )
    report = render_gate3_markdown(summary, [result])
    assert "**Pipeline**: `planned`" in report
    assert "**Context**: `8192`" in report
    assert "Plan repairs" in report
    assert "Plan fallbacks" in report
    assert "Replans" in report
    assert "Shortlist shortfalls" in report
    assert "Tool swaps" in report
    assert "Context overflow events" in report


def test_ablation_has_one_row_per_mode():
    rows = [
        {
            "pipeline": "legacy",
            "model": "m",
            "num_ctx": 8192,
            "dataset": "nc",
            "cases_completed": 10,
            "pass_at_executed": 8,
            "cases_semantic": 10,
            "pass_at_semantic": 7,
            "p95_latency": 12.5,
        },
        {
            "pipeline": "manual-kb",
            "model": "m",
            "num_ctx": 8192,
            "dataset": "nc",
            "cases_completed": 10,
            "pass_at_executed": 9,
            "cases_semantic": 10,
            "pass_at_semantic": 8,
            "p95_latency": 14.0,
        },
        {
            "pipeline": "planned",
            "model": "m",
            "num_ctx": 8192,
            "dataset": "nc",
            "cases_completed": 10,
            "pass_at_executed": 9,
            "cases_semantic": 10,
            "pass_at_semantic": 9,
            "plan_repairs": 1,
            "plan_fallbacks": 1,
            "replans": 1,
            "shortlist_shortfalls": 0,
            "tool_swaps": 2,
            "p95_latency": 20.0,
        },
    ]
    table = render_pipeline_ablation(rows)
    assert "| `legacy`" in table
    assert "| `manual-kb`" in table
    assert "| `planned`" in table
    # Each row keeps its own denominator.
    assert table.count("8/10") >= 1
    assert "9/10" in table
    assert "never pooled" in table


def test_ablation_labels_a_different_configuration():
    rows = [
        {
            "pipeline": "legacy",
            "model": "qwen2.5-coder:7b",
            "num_ctx": 8192,
            "dataset": "nc",
            "cases_completed": 1,
            "pass_at_executed": 1,
            "cases_semantic": 1,
            "pass_at_semantic": 1,
        },
        {
            "pipeline": "planned",
            "model": "qwen2.5-coder:32b",
            "num_ctx": 16384,
            "dataset": "other",
            "cases_completed": 1,
            "pass_at_executed": 1,
            "cases_semantic": 1,
            "pass_at_semantic": 1,
        },
    ]
    table = render_pipeline_ablation(rows)
    assert "qwen2.5-coder:32b" in table
    assert "16384 ctx" in table


def test_duplicate_modes_exit_2(tmp_path, monkeypatch):
    from benchmarks import run_gate3
    from grass_agent.config import ExecutionConfig

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for directory in (first, second):
        save_run_meta(directory, {"pipeline": "legacy", "num_ctx": 8192})

    config = ExecutionConfig(output_dir=str(first))
    code = run_gate3.report_only(
        config,
        _key(),
        tmp_path / "report.md",
        ablation_dirs=f"{first},{second}",
    )
    assert code == 2


def test_report_only_is_byte_reproducible_and_defaults_old_metadata(tmp_path):
    from benchmarks import run_gate3
    from grass_agent.config import ExecutionConfig

    directory = tmp_path / "run"
    directory.mkdir()
    result = _result("tc_01", pipeline="legacy")
    save(directory, result)
    # An old run summary deliberately lacks the new keys.
    save_run_meta(directory, {"model": "m", "suites": ["s"], "cases_total": 1})

    config = ExecutionConfig(output_dir=str(directory))
    first = tmp_path / "a.md"
    second = tmp_path / "b.md"
    assert run_gate3.report_only(config, _key(), first) == 0
    assert run_gate3.report_only(config, _key(), second) == 0
    assert first.read_bytes() == second.read_bytes()
    report = first.read_text()
    assert "**Pipeline**: `legacy`" in report
    assert "**Context**: `8192`" in report
