"""Persisted per-case results, atomicity, and resume (FR-006a, FR-018, FR-019).

`case_result.json` is the resume unit and the sole source of truth for report
generation. The schema is normative in contracts/case-result.md; the invariants
this module enforces are I1-I8 in data-model.md.

Atomicity matters because a hard kill can land between any two writes. Every
save goes to a `.part` sibling, is fsynced, then `os.replace`d -- atomic on
POSIX -- so a reader never observes a half-written file, and a torn file is
always detectable as `in_progress` or as a JSON error.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .classifier import FailureMode

SCHEMA_VERSION = 1

STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETE = "complete"

OUTCOME_STATIC_REJECTED = "static_rejected"
OUTCOME_EXECUTED_OK = "executed_ok"
OUTCOME_RUNTIME_FAILED = "runtime_failed"
OUTCOME_CRASHED = "crashed"
OUTCOME_TIMEOUT = "timeout"

ATTEMPT1_SOURCES = ("fresh", "reuse_artifacts")


class ResultValidationError(Exception):
    """A persisted case file violates an invariant and cannot be reused."""


# --------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------


@dataclass
class Attempt:
    """One generation-and-evaluation cycle (data-model section 2)."""

    ordinal: int
    script_path: str = ""
    log_path: str = ""
    stdout_path: str = ""
    stderr_path: str = ""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0

    static_issues: list[str] = field(default_factory=list)
    static_passed: bool = False

    stage: str = "runtime"  # "static" | "runtime" | "success"
    outcome: str = OUTCOME_RUNTIME_FAILED
    exit_code: int | None = None
    signal_name: str | None = None
    timed_out: bool = False

    failure_mode: str | None = None
    failing_tool: str | None = None
    error_excerpt: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome == OUTCOME_EXECUTED_OK

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class ResumeKey:
    """The four fields that decide whether a persisted case may be reused.

    A result produced under a different model, budget, timeout, or attempt-1
    source is not comparable and must not be carried forward (SC-019).
    """

    model: str
    max_retries: int
    timeout: int
    attempt1_source: str

    def matches(self, other: "ResumeKey") -> bool:
        return (
            self.model == other.model
            and self.max_retries == other.max_retries
            and self.timeout == other.timeout
            and self.attempt1_source == other.attempt1_source
        )


@dataclass
class CaseResult:
    """The persisted record for one benchmark case."""

    tc_id: str
    tier: int | None = None
    category: str = ""
    prompt: str = ""
    auxiliary_inputs: list[str] = field(default_factory=list)

    status: str = STATUS_IN_PROGRESS
    resume_key: ResumeKey | None = None

    pass_at_1: bool = False
    pass_at_healed: bool = False
    failure_mode_transitions: list[str | None] = field(default_factory=list)

    final_script: str | None = None
    attempts: list[Attempt] = field(default_factory=list)
    completed_at: str | None = None
    schema_version: int = SCHEMA_VERSION

    # ------------------------------------------------------------ derived

    @property
    def succeeded(self) -> bool:
        return self.pass_at_healed

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    def recompute_verdicts(self) -> None:
        """Derive pass_at_1 / pass_at_healed / transitions from the attempts."""
        self.pass_at_1 = bool(self.attempts) and self.attempts[0].succeeded
        self.pass_at_healed = any(a.succeeded for a in self.attempts)
        self.failure_mode_transitions = [
            None if a.succeeded else a.failure_mode for a in self.attempts
        ]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["resume_key"] = asdict(self.resume_key) if self.resume_key else None
        payload["attempts"] = [asdict(a) for a in self.attempts]
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> "CaseResult":
        attempts = [Attempt(**a) for a in payload.get("attempts", [])]
        key = payload.get("resume_key")
        return cls(
            tc_id=payload["tc_id"],
            tier=payload.get("tier"),
            category=payload.get("category", ""),
            prompt=payload.get("prompt", ""),
            auxiliary_inputs=list(payload.get("auxiliary_inputs", [])),
            status=payload.get("status", STATUS_IN_PROGRESS),
            resume_key=ResumeKey(**key) if key else None,
            pass_at_1=payload.get("pass_at_1", False),
            pass_at_healed=payload.get("pass_at_healed", False),
            failure_mode_transitions=list(payload.get("failure_mode_transitions", [])),
            final_script=payload.get("final_script"),
            attempts=attempts,
            completed_at=payload.get("completed_at"),
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )


# --------------------------------------------------------------------------
# Invariants (data-model, I1-I8)
# --------------------------------------------------------------------------


def check_invariants(result: CaseResult, max_retries: int, root: Path | None = None) -> None:
    """Raise ResultValidationError on any violation.

    Checked on every load so a corrupt file is rerun rather than silently
    folded into the metrics.
    """
    attempts = result.attempts

    # I1 -- budget ceiling
    if len(attempts) > max_retries + 1:
        raise ResultValidationError(
            f"I1: {len(attempts)} attempts exceeds max_retries+1 ({max_retries + 1})"
        )

    # I2 -- ordinals contiguous from 1
    for index, attempt in enumerate(attempts, start=1):
        if attempt.ordinal != index:
            raise ResultValidationError(
                f"I2: attempt {index} has ordinal {attempt.ordinal}, expected {index}"
            )

    # I3 -- transitions track attempts one-for-one
    if result.failure_mode_transitions and len(result.failure_mode_transitions) != len(attempts):
        raise ResultValidationError(
            f"I3: {len(result.failure_mode_transitions)} transitions for {len(attempts)} attempts"
        )

    # I4 -- every failure carries a valid mode; success carries none
    valid_modes = {m.value for m in FailureMode}
    for attempt in attempts:
        if attempt.succeeded:
            if attempt.failure_mode is not None:
                raise ResultValidationError(
                    f"I4: successful attempt {attempt.ordinal} carries failure_mode"
                )
            continue
        if attempt.failure_mode not in valid_modes:
            raise ResultValidationError(
                f"I4: attempt {attempt.ordinal} has invalid failure_mode "
                f"{attempt.failure_mode!r}; unclassified failures must be "
                f"'general_exception'"
            )

    # I6 -- verdicts agree with the attempts
    if attempts:
        if result.pass_at_1 != (attempts[0].outcome == OUTCOME_EXECUTED_OK):
            raise ResultValidationError("I6: pass_at_1 disagrees with attempts[0]")
        if result.pass_at_healed != any(a.succeeded for a in attempts):
            raise ResultValidationError("I6: pass_at_healed disagrees with attempts")

    # I7 -- complete means terminal
    if result.status == STATUS_COMPLETE:
        terminal = any(a.succeeded for a in attempts) or len(attempts) >= max_retries + 1
        if not terminal:
            raise ResultValidationError(
                "I7: status=complete but the case neither succeeded nor exhausted its budget"
            )

    if root is None:
        return

    # R10 -- every referenced capture must exist, even when zero bytes.
    captured = []
    for attempt in attempts:
        for path_attr in ("stdout_path", "stderr_path", "log_path", "script_path"):
            path_value = getattr(attempt, path_attr)
            if not path_value:
                continue
            path = root / path_value
            if not path.is_file():
                raise ResultValidationError(f"R10: missing artifact {path_value}")
            if path_attr in ("stdout_path", "stderr_path"):
                captured.append(path.read_text(encoding="utf-8", errors="replace"))

    # I8 -- the excerpt is fed verbatim to the repair prompt (FR-010), so it must
    # be a substring of *something that was captured*. It lives in one stream,
    # not both: a traceback on stderr has no counterpart on stdout.
    for attempt in attempts:
        if attempt.error_excerpt and not any(
            attempt.error_excerpt in stream for stream in captured
        ):
            raise ResultValidationError(
                f"I8: attempt {attempt.ordinal} error_excerpt is not a substring "
                f"of the captured stdout or stderr"
            )


# --------------------------------------------------------------------------
# Atomic persistence
# --------------------------------------------------------------------------


def _fsync_dir(directory: Path) -> None:
    """Persist the rename itself, not just the file contents."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def case_dir(output_root: Path, tc_id: str) -> Path:
    return output_root / tc_id


def result_path(output_root: Path, tc_id: str) -> Path:
    return case_dir(output_root, tc_id) / "case_result.json"


def write_atomic(path: Path, payload: dict) -> None:
    """Serialise to a `.part` sibling, fsync, then os.replace (FR-006a)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def save(output_root: Path, result: CaseResult) -> Path:
    """Persist one case atomically."""
    path = result_path(output_root, result.tc_id)
    write_atomic(path, result.to_dict())
    return path


def discard_partials(output_root: Path) -> int:
    """Delete every `case_result.json.part` at startup; never read one (R8)."""
    removed = 0
    if not output_root.is_dir():
        return 0
    for part in output_root.glob("*/case_result.json.part"):
        try:
            part.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def load(output_root: Path, tc_id: str) -> CaseResult | None:
    """Read a case file, returning None when absent or unreadable (R8)."""
    path = result_path(output_root, tc_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return CaseResult.from_dict(payload)
    except (KeyError, TypeError, ValueError):
        return None


def mark_complete(output_root: Path, result: CaseResult) -> CaseResult:
    """Stamp completion and persist (I7)."""
    result.status = STATUS_COMPLETE
    result.completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(output_root, result)
    return result


RUN_META_NAME = "run_summary.json"


def save_run_meta(output_root: Path, meta: dict) -> Path:
    """Persist run-level metadata beside the per-case results.

    Integrity evidence (the PERMANENT hash pair, leaked scratch dirs, model,
    budget) is a property of the *run*, not of any single case. Without this
    file, `--report-only` could reconstruct the rates but not the SC-002/SC-004
    assertions -- and a regenerated report would silently show "unknown".
    """
    path = output_root / RUN_META_NAME
    write_atomic(path, meta)
    return path


def load_run_meta(output_root: Path) -> dict:
    """Read run-level metadata, returning {} when absent."""
    path = output_root / RUN_META_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def is_reusable(
    output_root: Path,
    tc_id: str,
    current_key: ResumeKey,
    max_retries: int,
    reason_sink: list[str] | None = None,
) -> CaseResult | None:
    """Return a persisted case when every reuse rule holds, else None.

    Implements R1-R10 of contracts/case-result.md. Any single failure discards
    the case and reruns it from attempt 1. `reason_sink` collects why, so a
    resume run can explain itself without per-case noise on stdout.
    """

    def reject(reason: str) -> None:
        if reason_sink is not None:
            reason_sink.append(f"{tc_id}: {reason}")

    path = result_path(output_root, tc_id)
    if not path.is_file():
        return None

    result = load(output_root, tc_id)
    if result is None:  # R8 -- torn write from a hard kill
        reject("unreadable case_result.json (R8)")
        return None

    if result.schema_version != SCHEMA_VERSION:  # R2
        reject(f"schema_version {result.schema_version} != {SCHEMA_VERSION} (R2)")
        return None
    if result.tc_id != tc_id:  # R3
        reject(f"tc_id {result.tc_id!r} != {tc_id!r} (R3)")
        return None
    if result.status != STATUS_COMPLETE:  # R1 -- partial case, restart from attempt 1
        reject(f"status={result.status}, not complete (R1)")
        return None
    if result.resume_key is None or not result.resume_key.matches(current_key):  # R4-R7
        reject(f"resume key mismatch (R4-R7): {result.resume_key} vs {current_key}")
        return None

    try:
        check_invariants(result, max_retries, root=case_dir(output_root, tc_id))  # R9, R10
    except ResultValidationError as exc:
        reject(str(exc))
        return None

    return result