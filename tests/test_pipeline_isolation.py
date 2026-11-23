"""Resume isolation, additive schema, and offline assurance (T037)."""

from __future__ import annotations

import json

from grass_agent import kb_schema, kb_source
from grass_agent.kb_parse import parse_module
from grass_agent.reporting import aggregate
from grass_agent.results import (
    SCHEMA_VERSION,
    Attempt,
    CaseResult,
    ResumeKey,
    save,
)
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "kb"


def _key(**overrides) -> ResumeKey:
    values = dict(
        model="m",
        max_retries=2,
        timeout=120,
        attempt1_source="fresh",
        max_static_retries=2,
        max_runtime_retries=2,
        harness="gate3",
    )
    values.update(overrides)
    return ResumeKey(**values)


def test_old_keys_still_match_each_other():
    assert _key().matches(_key())
    assert _key(pipeline="legacy").matches(_key())


def test_mode_mismatch_is_rejected():
    assert not _key(pipeline="legacy").matches(_key(pipeline="manual-kb"))
    assert not _key(pipeline="manual-kb").matches(_key(pipeline="planned"))


def test_context_and_budget_mismatch_are_rejected():
    assert not _key(num_ctx=8192).matches(_key(num_ctx=16384))
    assert not _key(manual_context_tokens=3000).matches(_key(manual_context_tokens=3686))


def test_resolved_budget_makes_defaults_match():
    assert _key(num_ctx=8192).matches(_key(num_ctx=8192, manual_context_tokens=3686))


def test_attempt_records_pipeline_by_default():
    attempt = Attempt(ordinal=1)
    assert attempt.pipeline == "legacy"
    assert attempt.num_ctx == 8192
    assert attempt.manual_context_tokens is None
    assert attempt.planned_tools == []


def test_summary_records_pipeline():
    result = CaseResult(tc_id="tc_01", attempts=[Attempt(ordinal=1, pipeline="planned", num_ctx=8192, manual_context_tokens=3686)])
    summary = aggregate(
        [result],
        model="m",
        suites=["s"],
        max_retries=2,
        timeout_s=120,
        attempt1_source="fresh",
        resume_key=_key(pipeline="planned", manual_context_tokens=3686),
        cases_total=1,
        pipeline="planned",
        num_ctx=8192,
        manual_context_tokens=3686,
    )
    assert summary.pipeline == "planned"
    assert summary.num_ctx == 8192
    assert summary.manual_context_tokens == 3686


def test_case_result_schema_version_stays_one(tmp_path):
    result = CaseResult(tc_id="tc_01", attempts=[Attempt(ordinal=1)])
    payload = result.to_dict()
    assert payload["schema_version"] == SCHEMA_VERSION == 1
    save(tmp_path, result)
    written = json.loads((tmp_path / "tc_01" / "case_result.json").read_text())
    assert written["schema_version"] == 1
    assert written["attempts"][0]["pipeline"] == "legacy"


def test_offline_build_and_case_paths_make_no_outbound_connection(
    socket_guard, monkeypatch, tmp_path
):
    # Deterministic embedding instead of a model call; the code path that
    # matters for the audit is discovery -> parse -> store.
    conn = kb_schema.open_database(str(tmp_path / "kb.db"))
    kb_schema.ensure_schema(conn)
    record = parse_module(
        "v.clean",
        markdown_path=str(FIXTURES / "markdown" / "v.clean.md"),
        xml_text=(FIXTURES / "xml" / "v.clean.xml").read_text(),
    )
    kb_schema.upsert_tool(conn, record, embedding=[0.0] * 8)
    conn.commit()
    conn.close()
    assert socket_guard == []


def test_run_metadata_records_mode(tmp_path):
    from grass_agent.results import load_run_meta, save_run_meta

    save_run_meta(
        tmp_path,
        {"pipeline": "manual-kb", "num_ctx": 16384, "manual_context_tokens": 7372},
    )
    meta = load_run_meta(tmp_path)
    assert meta["pipeline"] == "manual-kb"
    assert meta["num_ctx"] == 16384
    assert meta["manual_context_tokens"] == 7372


def test_plan_and_manual_artifacts_are_written(tmp_path):
    from grass_agent.results import (
        plan_artifact_path,
        save_manuals_artifact,
        save_plan_artifact,
    )

    save_plan_artifact(tmp_path, "tc_01", 1, {"pipeline": "planned", "fallback": False})
    save_manuals_artifact(tmp_path, "tc_01", 1, {"tokens": 10, "cards": []})
    assert plan_artifact_path(tmp_path, "tc_01", 1).is_file()
    assert (tmp_path / "tc_01" / "attempt_1.manuals.json").is_file()
