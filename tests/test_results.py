"""Atomic persistence, invariants, and resume rules (task T036).

The properties under test are what make an interrupted 40-case run safe to
resume: a hard kill must never leave a half-written file that a later run
trusts, and a result produced under a different configuration must never be
carried forward.
"""

import json

import pytest

from grass_agent.results import (
    OUTCOME_EXECUTED_OK,
    OUTCOME_RUNTIME_FAILED,
    OUTCOME_TIMEOUT,
    STATUS_COMPLETE,
    STATUS_IN_PROGRESS,
    Attempt,
    CaseResult,
    ResultValidationError,
    ResumeKey,
    case_dir,
    check_invariants,
    discard_partials,
    is_reusable,
    load,
    mark_complete,
    result_path,
    save,
)

KEY = ResumeKey(model="qwen2.5-coder:3b", max_retries=2, timeout=60, attempt1_source="fresh")


def _write_artifacts(root, ordinal, outcome, failure_mode=None, stderr_text=""):
    """Write a full artifact set so reuse rule R10 is satisfied."""
    d = case_dir(root, f"tc_{ordinal:02d}")
    d.mkdir(parents=True, exist_ok=True)
    (d / f"attempt_{ordinal}.py").write_text("# script\n", encoding="utf-8")
    (d / f"attempt_{ordinal}.stdout").write_text("", encoding="utf-8")
    (d / f"attempt_{ordinal}.stderr").write_text(stderr_text, encoding="utf-8")
    (d / f"attempt_{ordinal}.log").write_text(stderr_text, encoding="utf-8")
    return Attempt(
        ordinal=ordinal,
        outcome=outcome,
        failure_mode=failure_mode,
        script_path=f"attempt_{ordinal}.py",
        stdout_path=f"attempt_{ordinal}.stdout",
        stderr_path=f"attempt_{ordinal}.stderr",
        log_path=f"attempt_{ordinal}.log",
        error_excerpt=stderr_text.strip().splitlines()[0] if stderr_text.strip() else None,
    )


def _build(root, tc_id, outcomes_and_modes):
    """Build a complete CaseResult whose attempts match the given outcomes."""
    result = CaseResult(tc_id=tc_id, category="single_tool", prompt="p", resume_key=KEY)
    for ordinal, (outcome, mode, text) in enumerate(outcomes_and_modes, start=1):
        result.attempts.append(_write_artifacts(root, ordinal, outcome, mode, text))
    result.recompute_verdicts()
    result.final_script = "final.py"
    return result


# --------------------------------------------------------------------------
# Atomicity
# --------------------------------------------------------------------------


def test_save_leaves_no_part_file(tmp_path):
    result = _build(tmp_path, "tc_01", [(OUTCOME_EXECUTED_OK, None, "")])
    mark_complete(tmp_path, result)
    assert not result_path(tmp_path, "tc_01").with_suffix(".json.part").exists()
    assert result_path(tmp_path, "tc_01").is_file()


def test_partial_files_are_discarded_and_never_read(tmp_path):
    result = _build(tmp_path, "tc_01", [(OUTCOME_EXECUTED_OK, None, "")])
    mark_complete(tmp_path, result)
    part = result_path(tmp_path, "tc_01").with_suffix(".json.part")
    part.write_text('{"tc_id": "tc_01", "status": "comp', encoding="utf-8")

    assert discard_partials(tmp_path) == 1
    assert not part.exists()
    # The real file is untouched by the presence of a stale .part.
    assert load(tmp_path, "tc_01").status == STATUS_COMPLETE


def test_write_is_atomic_via_part_then_replace(tmp_path, monkeypatch):
    """os.replace must be the final step -- it is what makes the swap atomic."""
    result = _build(tmp_path, "tc_01", [(OUTCOME_EXECUTED_OK, None, "")])
    seen = []
    real_replace = __import__("os").replace

    def spy(src, dst):
        seen.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr("grass_agent.results.os.replace", spy)
    save(tmp_path, result)
    assert seen and seen[-1][1].endswith("case_result.json")
    assert seen[-1][0].endswith(".part")


# --------------------------------------------------------------------------
# Resume rules R1-R10
# --------------------------------------------------------------------------


def test_complete_case_with_matching_key_is_reusable(tmp_path):
    result = _build(tmp_path, "tc_01", [(OUTCOME_EXECUTED_OK, None, "")])
    mark_complete(tmp_path, result)
    reasons = []
    assert is_reusable(tmp_path, "tc_01", KEY, 2, reasons) is not None
    assert reasons == []


def test_in_progress_case_is_not_reusable(tmp_path):
    """R1: a partial case restarts from attempt 1 (FR-006a)."""
    result = _build(tmp_path, "tc_01", [(OUTCOME_RUNTIME_FAILED, "missing_input", "x")])
    assert result.status == STATUS_IN_PROGRESS
    save(tmp_path, result)  # persisted mid-flight, never marked complete
    reasons = []
    assert is_reusable(tmp_path, "tc_01", KEY, 2, reasons) is None
    assert any("R1" in r for r in reasons)


def test_torn_json_is_not_reusable(tmp_path):
    """R8: a hard kill mid-write must be detectable, not silently trusted."""
    result = _build(tmp_path, "tc_01", [(OUTCOME_EXECUTED_OK, None, "")])
    mark_complete(tmp_path, result)
    result_path(tmp_path, "tc_01").write_text('{"tc_id": "tc_01", "att', encoding="utf-8")
    reasons = []
    assert is_reusable(tmp_path, "tc_01", KEY, 2, reasons) is None
    assert any("R8" in r for r in reasons)


@pytest.mark.parametrize(
    "changed",
    [
        ResumeKey("qwen2.5-coder:7b", 2, 60, "fresh"),
        ResumeKey("qwen2.5-coder:3b", 1, 60, "fresh"),
        ResumeKey("qwen2.5-coder:3b", 2, 30, "fresh"),
        ResumeKey("qwen2.5-coder:3b", 2, 60, "reuse_artifacts"),
    ],
    ids=["model", "max_retries", "timeout", "attempt1_source"],
)
def test_each_resume_key_field_must_match(tmp_path, changed):
    """SC-019: any single field differing invalidates the result."""
    result = _build(tmp_path, "tc_01", [(OUTCOME_EXECUTED_OK, None, "")])
    mark_complete(tmp_path, result)
    reasons = []
    assert is_reusable(tmp_path, "tc_01", changed, 2, reasons) is None
    assert any("R4-R7" in r for r in reasons)


def test_missing_empty_stderr_artifact_is_not_reusable(tmp_path):
    """R10: reuse reads these paths, so even a zero-byte capture must exist.

    Built as a budget-exhausted case so invariant I7 is satisfied and R10 is
    what actually rejects it.
    """
    result = _build(
        tmp_path,
        "tc_01",
        [(OUTCOME_RUNTIME_FAILED, "missing_input", "ERROR: x")] * 3,
    )
    mark_complete(tmp_path, result)
    (case_dir(tmp_path, "tc_01") / "attempt_1.stderr").unlink()
    reasons = []
    assert is_reusable(tmp_path, "tc_01", KEY, 2, reasons) is None
    assert any("R10" in r for r in reasons)


def test_zero_byte_stream_is_fine_when_present(tmp_path):
    result = _build(tmp_path, "tc_01", [(OUTCOME_EXECUTED_OK, None, "")])
    mark_complete(tmp_path, result)
    reasons = []
    assert is_reusable(tmp_path, "tc_01", KEY, 2, reasons) is not None


def test_unknown_schema_version_is_not_reusable(tmp_path):
    result = _build(tmp_path, "tc_01", [(OUTCOME_EXECUTED_OK, None, "")])
    mark_complete(tmp_path, result)
    result.schema_version = 999
    save(tmp_path, result)
    reasons = []
    assert is_reusable(tmp_path, "tc_01", KEY, 2, reasons) is None
    assert any("R2" in r for r in reasons)


# --------------------------------------------------------------------------
# Invariants
# --------------------------------------------------------------------------


def test_budget_ceiling_invariant(tmp_path):
    """I1 / SC-017: attempts never exceed max_retries + 1."""
    result = _build(tmp_path, "tc_01", [(OUTCOME_TIMEOUT, "general_exception", "x")] * 4)
    with pytest.raises(ResultValidationError, match="I1"):
        check_invariants(result, max_retries=2)


def test_ordinals_must_be_contiguous(tmp_path):
    """I2."""
    result = _build(tmp_path, "tc_01", [(OUTCOME_EXECUTED_OK, None, "")])
    result.attempts[0].ordinal = 7
    with pytest.raises(ResultValidationError, match="I2"):
        check_invariants(result, max_retries=2)


def test_failed_attempt_must_carry_a_valid_mode(tmp_path):
    """I4 -- the zero-unclassified guarantee (SC-005)."""
    result = _build(tmp_path, "tc_01", [(OUTCOME_RUNTIME_FAILED, None, "x")])
    with pytest.raises(ResultValidationError, match="I4"):
        check_invariants(result, max_retries=2)


def test_successful_attempt_must_not_carry_a_mode(tmp_path):
    result = _build(tmp_path, "tc_01", [(OUTCOME_EXECUTED_OK, None, "")])
    result.attempts[0].failure_mode = "missing_input"
    with pytest.raises(ResultValidationError, match="I4"):
        check_invariants(result, max_retries=2)


def test_complete_requires_a_terminal_state(tmp_path):
    """I7."""
    result = _build(tmp_path, "tc_01", [(OUTCOME_RUNTIME_FAILED, "missing_input", "x")])
    result.status = STATUS_COMPLETE
    with pytest.raises(ResultValidationError, match="I7"):
        check_invariants(result, max_retries=2)


def test_error_excerpt_must_be_verbatim(tmp_path):
    """I8: the excerpt is fed to the repair prompt, so it cannot be paraphrased."""
    result = _build(tmp_path, "tc_01", [(OUTCOME_RUNTIME_FAILED, "missing_input", "ERROR: real")])
    result.attempts[0].error_excerpt = "ERROR: invented text"
    with pytest.raises(ResultValidationError, match="I8"):
        check_invariants(result, max_retries=2, root=case_dir(tmp_path, "tc_01"))


def test_excerpt_in_either_stream_is_acceptable(tmp_path):
    """A traceback lives on stderr only; stdout may be empty.

    Requiring the excerpt in *both* streams would reject every real failure.
    """
    result = _build(tmp_path, "tc_01", [(OUTCOME_RUNTIME_FAILED, "missing_input", "ERROR: real")])
    check_invariants(result, max_retries=2, root=case_dir(tmp_path, "tc_01"))


def test_verdict_derived_from_attempts(tmp_path):
    """I6."""
    healed = _build(
        tmp_path,
        "tc_01",
        [(OUTCOME_RUNTIME_FAILED, "missing_input", "ERROR: x"), (OUTCOME_EXECUTED_OK, None, "")],
    )
    assert healed.pass_at_1 is False
    assert healed.pass_at_healed is True
    assert healed.failure_mode_transitions == ["missing_input", None]
    check_invariants(healed, max_retries=2)

    zero_shot = _build(tmp_path, "tc_02", [(OUTCOME_EXECUTED_OK, None, "")])
    assert zero_shot.pass_at_1 is True and zero_shot.pass_at_healed is True


def test_round_trip_preserves_content(tmp_path):
    result = _build(tmp_path, "tc_01", [(OUTCOME_RUNTIME_FAILED, "schema_misuse", "ERROR: y")])
    save(tmp_path, result)
    loaded = load(tmp_path, "tc_01")
    assert loaded.tc_id == result.tc_id
    assert loaded.attempts[0].failure_mode == "schema_misuse"
    assert loaded.resume_key == KEY


def test_persisted_file_is_valid_json_with_expected_shape(tmp_path):
    result = _build(tmp_path, "tc_01", [(OUTCOME_EXECUTED_OK, None, "")])
    mark_complete(tmp_path, result)
    payload = json.loads(result_path(tmp_path, "tc_01").read_text(encoding="utf-8"))
    for field in (
        "schema_version", "tc_id", "status", "resume_key", "attempts",
        "pass_at_1", "pass_at_healed", "failure_mode_transitions",
    ):
        assert field in payload
    assert payload["status"] == STATUS_COMPLETE
    assert payload["completed_at"]