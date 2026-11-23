"""Persisted per-case results, atomicity, and resume (FR-006a, FR-018, FR-019).

`case_result.json` is the resume unit and the sole source of truth for report
generation. The schema is normative in contracts/case-result.md; the invariants
this module enforces are I1-I15 in data-model.md.

Gate 3 evolves the document additively: `schema_version` stays `1`, every new
field has a default, and a legacy Gate 2 record still loads. The two repair
tiers are reconstructed from the attempts, so the ledger, the no-op count, and
both verdicts can always be recomputed without re-running the model.

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
OUTCOME_NO_OP_DUPLICATE = "no_op_duplicate"

ATTEMPT1_SOURCES = ("fresh", "reuse_artifacts")

BUDGET_INITIAL = "initial"
BUDGET_STATIC = "static"
BUDGET_RUNTIME = "runtime"
BUDGET_TIERS = (BUDGET_INITIAL, BUDGET_STATIC, BUDGET_RUNTIME)

HARNESS_GATE2 = "gate2"
HARNESS_GATE3 = "gate3"

# Harness diagnostics that are valid `error_excerpt` values by construction.
DUPLICATE_EXCERPT_PREFIX = "duplicate of attempt "


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

    # ---- Gate 3 additions (appended so positional construction still works)
    budget_tier: str = BUDGET_INITIAL  # "initial" | "static" | "runtime"
    duplicate: bool = False
    code_sha256: str | None = None
    ast_sha256: str | None = None
    new_maps: dict = field(
        default_factory=lambda: {"raster": [], "vector": []}
    )
    semantic_evaluated: bool = False
    semantic_passed: bool | None = None
    assertion_results: list = field(default_factory=list)
    pivot_used: bool = False

    # ---- Feature 004 additive fields (all defaulted; old records load clean)
    pipeline: str = "legacy"
    num_ctx: int = 8192
    manual_context_tokens: int | None = None
    plan_revision: int = 0
    plan_repair_count: int = 0
    replan_count: int = 0
    planner_invocations: int = 0
    shortlist_shortfall: bool = False
    planned_tools: list[str] = field(default_factory=list)
    tool_swaps: list[str] = field(default_factory=list)
    plan_fallback: bool = False
    manual_card_tokens: int = 0
    manual_omissions: list[str] = field(default_factory=list)
    planner_prompt_tokens: int = 0
    planner_completion_tokens: int = 0

    @property
    def succeeded(self) -> bool:
        return self.outcome == OUTCOME_EXECUTED_OK

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def has_new_maps(self) -> bool:
        """True when this attempt created at least one map of either type."""
        return bool(new_map_names(self.new_maps))


@dataclass
class BudgetLedger:
    """Per-tier used/remaining accounting (data-model section 8)."""

    static_limit: int = 0
    static_used: int = 0
    static_remaining: int = 0
    runtime_limit: int = 0
    runtime_used: int = 0
    runtime_remaining: int = 0


@dataclass
class ResumeKey:
    """The fields that decide whether a persisted case may be reused.

    A result produced under a different model, budget, timeout, attempt-1
    source, or harness is not comparable and must not be carried forward
    (SC-019). The tier fields are `None` for legacy Gate 2 keys and normalise to
    the legacy `max_retries` value, so old keys still compare correctly among
    themselves.
    """

    model: str
    max_retries: int
    timeout: int
    attempt1_source: str

    # ---- Gate 3 additions
    max_static_retries: int | None = None
    max_runtime_retries: int | None = None
    harness: str = HARNESS_GATE2

    # ---- Feature 004 additions (old keys default to legacy/8K/no budget)
    pipeline: str = "legacy"
    num_ctx: int = 8192
    manual_context_tokens: int | None = None

    @property
    def effective_manual_budget(self) -> int:
        if self.manual_context_tokens is not None:
            return self.manual_context_tokens
        return int(0.45 * self.num_ctx)

    @property
    def effective_static_retries(self) -> int:
        if self.max_static_retries is None:
            return self.max_retries
        return self.max_static_retries

    @property
    def effective_runtime_retries(self) -> int:
        if self.max_runtime_retries is None:
            return self.max_retries
        return self.max_runtime_retries

    def matches(self, other: "ResumeKey") -> bool:
        return (
            self.model == other.model
            and self.effective_static_retries == other.effective_static_retries
            and self.effective_runtime_retries == other.effective_runtime_retries
            and self.timeout == other.timeout
            and self.attempt1_source == other.attempt1_source
            and self.harness == other.harness
            and self.pipeline == other.pipeline
            and self.num_ctx == other.num_ctx
            and self.effective_manual_budget == other.effective_manual_budget
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

    # ---- Gate 3 additions (appended; all default cleanly on old artifacts)
    pass_at_executed: bool = False
    pass_at_semantic: bool | None = None
    semantic_evaluated: bool = False
    no_op_count: int = 0
    budget_ledger: BudgetLedger | None = None
    harness_version: str = HARNESS_GATE2
    # True when a semantic spec was supplied for the case, even if no attempt
    # executed far enough to be probed. Such a case still belongs to the
    # semantic denominator (it cannot be a semantic pass), but it must never be
    # reported as "semantic not evaluated" (FR‑009f).
    semantic_declared: bool = False

    # ------------------------------------------------------------ derived

    @property
    def succeeded(self) -> bool:
        return self.pass_at_healed

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    def recompute_verdicts(self) -> None:
        """Derive every verdict, transition, no-op count from the attempts."""
        self.pass_at_1 = bool(self.attempts) and self.attempts[0].succeeded
        self.pass_at_healed = any(a.succeeded for a in self.attempts)
        self.failure_mode_transitions = [
            None if a.succeeded else a.failure_mode for a in self.attempts
        ]
        self.no_op_count = sum(1 for a in self.attempts if a.duplicate)

        # Gate 3 defines execution success by the new-map evidence. A legacy
        # Gate 2 record has none, so it keeps the Gate 2 meaning exactly.
        has_map_evidence = any(a.has_new_maps for a in self.attempts)
        if self.harness_version == HARNESS_GATE3 or has_map_evidence:
            self.pass_at_executed = any(
                a.succeeded and a.has_new_maps for a in self.attempts
            )
        else:
            self.pass_at_executed = self.pass_at_healed

        probed = [a for a in self.attempts if a.semantic_evaluated]
        self.semantic_evaluated = bool(probed)
        if not probed:
            self.pass_at_semantic = None
        else:
            self.pass_at_semantic = self.pass_at_executed and all(
                a.semantic_passed is not False and _assertions_passed(a)
                for a in probed
            )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["resume_key"] = asdict(self.resume_key) if self.resume_key else None
        payload["budget_ledger"] = (
            asdict(self.budget_ledger) if self.budget_ledger else None
        )
        payload["attempts"] = [asdict(a) for a in self.attempts]
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> "CaseResult":
        attempts = [_attempt_from_dict(a) for a in payload.get("attempts", [])]
        key = payload.get("resume_key")
        ledger_payload = payload.get("budget_ledger")
        ledger = BudgetLedger(**ledger_payload) if ledger_payload else None

        # A record written before Gate 3 has no harness discriminator. It keeps
        # the Gate 2 meaning of every verdict and is never counted in a Gate 3
        # semantic denominator (contracts/case-result.md compatibility policy).
        legacy = "harness_version" not in payload
        harness = payload.get("harness_version", HARNESS_GATE2)
        pass_at_healed = payload.get("pass_at_healed", False)
        pass_at_executed = payload.get(
            "pass_at_executed", pass_at_healed if legacy else False
        )

        result = cls(
            tc_id=payload["tc_id"],
            tier=payload.get("tier"),
            category=payload.get("category", ""),
            prompt=payload.get("prompt", ""),
            auxiliary_inputs=list(payload.get("auxiliary_inputs", [])),
            status=payload.get("status", STATUS_IN_PROGRESS),
            resume_key=ResumeKey(**key) if key else None,
            pass_at_1=payload.get("pass_at_1", False),
            pass_at_healed=pass_at_healed,
            failure_mode_transitions=list(payload.get("failure_mode_transitions", [])),
            final_script=payload.get("final_script"),
            attempts=attempts,
            completed_at=payload.get("completed_at"),
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
            pass_at_executed=pass_at_executed,
            pass_at_semantic=payload.get("pass_at_semantic") if not legacy else None,
            semantic_evaluated=payload.get("semantic_evaluated", False) if not legacy else False,
            no_op_count=payload.get("no_op_count", 0),
            budget_ledger=ledger,
            harness_version=harness,
            semantic_declared=payload.get("semantic_declared", False),
        )
        if legacy:
            result.semantic_evaluated = any(a.semantic_evaluated for a in result.attempts)
            result.pass_at_semantic = (
                None
                if not result.semantic_evaluated
                else result.pass_at_executed
            )
        return result


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def new_map_names(new_maps: dict | None) -> list[str]:
    """Flatten the `new_maps` object into a deterministic sorted list."""
    if not isinstance(new_maps, dict):
        return []
    names: list[str] = []
    for kind in ("raster", "vector"):
        values = new_maps.get(kind) or []
        names.extend(str(v) for v in values)
    return sorted(names)


def _assertions_passed(attempt: Attempt) -> bool:
    """True when every recorded assertion result for an attempt passed."""
    for entry in attempt.assertion_results or []:
        if isinstance(entry, dict):
            if not entry.get("passed", False):
                return False
        elif not getattr(entry, "passed", False):
            return False
    return True


def infer_budget_tier(payload: dict) -> str:
    """Infer a legacy attempt's producing tier.

    Legacy attempts carry no `budget_tier`: ordinal 1 is the free initial
    candidate, a static-stage rejection belongs to the static tier, and
    everything else was produced by a runtime repair.
    """
    if int(payload.get("ordinal", 1) or 1) == 1:
        return BUDGET_INITIAL
    if payload.get("stage") == "static":
        return BUDGET_STATIC
    return BUDGET_RUNTIME


def attempt_budget_tier(attempt: Attempt) -> str:
    tier = attempt.budget_tier
    if tier in BUDGET_TIERS:
        return tier
    return infer_budget_tier(
        {"ordinal": attempt.ordinal, "stage": attempt.stage}
    )


def _attempt_from_dict(payload: dict) -> Attempt:
    data = dict(payload)
    if "budget_tier" not in data or data.get("budget_tier") not in BUDGET_TIERS:
        data["budget_tier"] = infer_budget_tier(data)
    data.setdefault("new_maps", {"raster": [], "vector": []})
    data.setdefault("assertion_results", [])
    return Attempt(**data)


def build_ledger(
    attempts: list[Attempt], static_limit: int, runtime_limit: int
) -> BudgetLedger:
    """Recompute the per-tier ledger from the attempts themselves."""
    static_used = sum(
        1 for a in attempts if attempt_budget_tier(a) == BUDGET_STATIC
    )
    runtime_used = sum(
        1 for a in attempts if attempt_budget_tier(a) == BUDGET_RUNTIME
    )
    return BudgetLedger(
        static_limit=static_limit,
        static_used=static_used,
        static_remaining=static_limit - static_used,
        runtime_limit=runtime_limit,
        runtime_used=runtime_used,
        runtime_remaining=runtime_limit - runtime_used,
    )


def recompute_ledger(
    result: CaseResult,
    static_limit: int | None = None,
    runtime_limit: int | None = None,
) -> BudgetLedger:
    """Rebuild the ledger, defaulting to the persisted limits when present."""
    ledger = result.budget_ledger
    if static_limit is None:
        static_limit = ledger.static_limit if ledger else 0
    if runtime_limit is None:
        runtime_limit = ledger.runtime_limit if ledger else 0
    return build_ledger(result.attempts, static_limit, runtime_limit)


# --------------------------------------------------------------------------
# Invariants (data-model, I1-I15)
# --------------------------------------------------------------------------


def _tier_limits(
    result: CaseResult,
    max_retries: int,
    max_static_retries: int | None,
    max_runtime_retries: int | None,
) -> tuple[int, int] | None:
    """Resolve the budget mode.

    Returns `(static_limit, runtime_limit)` in two-tier mode, or `None` for a
    legacy Gate 2 record. When no tier limits are supplied explicitly, the
    stored ledger is authoritative; only a record with neither is legacy.
    """
    if max_static_retries is not None or max_runtime_retries is not None:
        return (
            max_static_retries if max_static_retries is not None else max_retries,
            max_runtime_retries if max_runtime_retries is not None else max_retries,
        )
    if result.harness_version == HARNESS_GATE3 or result.budget_ledger is not None:
        ledger = result.budget_ledger or BudgetLedger(max_retries, 0, max_retries, max_retries, 0, max_retries)
        return (ledger.static_limit, ledger.runtime_limit)
    return None


def _requests_tier(attempt: Attempt) -> str | None:
    """Which repair tier the last attempt requests, or None on success."""
    if attempt.succeeded and attempt.has_new_maps:
        return None
    if attempt.succeeded:
        # exit 0 with no new map is a repairable runtime failure (FR-001b)
        return BUDGET_RUNTIME
    if attempt.budget_tier == BUDGET_RUNTIME or attempt.duplicate and attempt.budget_tier == BUDGET_RUNTIME:
        return BUDGET_RUNTIME
    if attempt.stage == "static" or not attempt.static_passed:
        return BUDGET_STATIC
    return BUDGET_RUNTIME


def is_terminal(
    result: CaseResult,
    static_limit: int | None = None,
    runtime_limit: int | None = None,
    max_retries: int = 2,
) -> bool:
    """True when no further candidate may be generated for this case."""
    if not result.attempts:
        return False
    if result.pass_at_executed or result.semantic_evaluated:
        return True
    if static_limit is None and runtime_limit is None:
        return any(a.succeeded for a in result.attempts) or len(
            result.attempts
        ) >= max_retries + 1

    static_limit = static_limit or 0
    runtime_limit = runtime_limit or 0
    if len(result.attempts) >= 1 + static_limit + runtime_limit:
        return True
    ledger = build_ledger(result.attempts, static_limit, runtime_limit)
    next_tier = _requests_tier(result.attempts[-1])
    if next_tier is None:
        return True
    used = ledger.static_used if next_tier == BUDGET_STATIC else ledger.runtime_used
    limit = static_limit if next_tier == BUDGET_STATIC else runtime_limit
    return used >= limit


def _check_pipeline_invariants(result: CaseResult) -> None:
    """Feature 004 invariants, applied only to non-legacy records.

    Old Gate 2/Gate 3 records carry every new field at its default and are
    therefore never subjected to these rules (compatibility policy R7).
    """
    attempts = result.attempts
    if not attempts:
        return
    run_pipeline = (
        result.resume_key.pipeline
        if result.resume_key is not None
        else attempts[0].pipeline
    )
    if run_pipeline == "legacy" and all(a.pipeline == "legacy" for a in attempts):
        return

    if run_pipeline not in ("legacy", "manual-kb", "planned"):
        raise ResultValidationError(
            f"P7: invalid pipeline {run_pipeline!r} on the run"
        )
    run_num_ctx = (
        result.resume_key.num_ctx
        if result.resume_key is not None
        else attempts[0].num_ctx
    )
    run_budget = (
        result.resume_key.effective_manual_budget
        if result.resume_key is not None
        else (
            attempts[0].manual_context_tokens
            if attempts[0].manual_context_tokens is not None
            else int(0.45 * attempts[0].num_ctx)
        )
    )

    for attempt in attempts:
        if attempt.pipeline != run_pipeline:
            raise ResultValidationError(
                f"P7: attempt {attempt.ordinal} pipeline {attempt.pipeline!r} "
                f"does not match the run ({run_pipeline!r})"
            )
        if attempt.num_ctx != run_num_ctx:
            raise ResultValidationError(
                f"P7: attempt {attempt.ordinal} num_ctx {attempt.num_ctx} "
                f"does not match the run ({run_num_ctx})"
            )
        attempt_budget = (
            attempt.manual_context_tokens
            if attempt.manual_context_tokens is not None
            else int(0.45 * attempt.num_ctx)
        )
        if attempt_budget != run_budget:
            raise ResultValidationError(
                f"P7: attempt {attempt.ordinal} manual budget {attempt_budget} "
                f"does not match the run ({run_budget})"
            )
        if attempt.plan_revision not in (0, 1):
            raise ResultValidationError(
                f"P11: attempt {attempt.ordinal} plan_revision "
                f"{attempt.plan_revision} is not 0 or 1"
            )
        for field_name in ("plan_repair_count", "replan_count"):
            value = getattr(attempt, field_name)
            if value not in (0, 1):
                raise ResultValidationError(
                    f"P11: attempt {attempt.ordinal} {field_name} {value} "
                    "is not 0 or 1"
                )
        if attempt.plan_repair_count + attempt.replan_count > 2:
            raise ResultValidationError(
                f"P11: attempt {attempt.ordinal} uses more than two planner "
                "repair/replan events"
            )
        if attempt.planner_invocations > 3:
            raise ResultValidationError(
                f"P11: attempt {attempt.ordinal} has "
                f"{attempt.planner_invocations} planner invocations (max 3)"
            )
        if attempt.planned_tools and run_pipeline in ("legacy", "manual-kb"):
            raise ResultValidationError(
                f"P11: attempt {attempt.ordinal} records planned tools in "
                f"{run_pipeline} mode"
            )
        if attempt.planner_invocations < (
            1 + attempt.plan_repair_count + attempt.replan_count
            ) and attempt.planned_tools:
            raise ResultValidationError(
                f"P11: attempt {attempt.ordinal} planner invocation count is "
                "inconsistent with its repair counters"
            )


def check_invariants(
    result: CaseResult,
    max_retries: int,
    root: Path | None = None,
    max_static_retries: int | None = None,
    max_runtime_retries: int | None = None,
) -> None:
    """Raise ResultValidationError on any violation.

    Checked on every load so a corrupt file is rerun rather than silently
    folded into the metrics. The legacy `check_invariants(result, max_retries)`
    signature is preserved: a record with no tier evidence is still held to the
    Gate 2 ceiling of `max_retries + 1` attempts.
    """
    attempts = result.attempts
    limits = _tier_limits(
        result, max_retries, max_static_retries, max_runtime_retries
    )

    # I1 -- budget ceiling
    if limits is None:
        if len(attempts) > max_retries + 1:
            raise ResultValidationError(
                f"I1: {len(attempts)} attempts exceeds max_retries+1 ({max_retries + 1})"
            )
        static_limit = runtime_limit = max_retries
    else:
        static_limit, runtime_limit = limits
        ceiling = 1 + static_limit + runtime_limit
        if len(attempts) > ceiling:
            raise ResultValidationError(
                f"I1: {len(attempts)} attempts exceeds 1 + static + runtime ({ceiling})"
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
        if attempt.duplicate and attempt.failure_mode != FailureMode.GENERAL_EXCEPTION.value:
            raise ResultValidationError(
                f"I4: duplicate attempt {attempt.ordinal} must use "
                f"'general_exception'"
            )

    # I5 -- legacy verdicts agree with the attempts
    if attempts:
        if result.pass_at_1 != (attempts[0].outcome == OUTCOME_EXECUTED_OK):
            raise ResultValidationError("I5: pass_at_1 disagrees with attempts[0]")
        if result.pass_at_healed != any(a.succeeded for a in attempts):
            raise ResultValidationError("I5: pass_at_healed disagrees with attempts")

    # I6 -- complete means terminal
    if result.status == STATUS_COMPLETE:
        if limits is None:
            terminal = any(a.succeeded for a in attempts) or len(attempts) >= max_retries + 1
        else:
            terminal = is_terminal(result, static_limit, runtime_limit, max_retries)
        if not terminal:
            raise ResultValidationError(
                "I7: status=complete but the case is not in a terminal state"
            )

    if limits is not None:
        # I9 -- per-tier ceilings
        ledger = build_ledger(attempts, static_limit, runtime_limit)
        if ledger.static_used > static_limit:
            raise ResultValidationError(
                f"I9: static_used {ledger.static_used} exceeds static_limit {static_limit}"
            )
        if ledger.runtime_used > runtime_limit:
            raise ResultValidationError(
                f"I9: runtime_used {ledger.runtime_used} exceeds runtime_limit {runtime_limit}"
            )

        # I15 -- the persisted ledger and no-op count are reproducible
        persisted = result.budget_ledger
        if persisted is not None and asdict(persisted) != asdict(ledger):
            raise ResultValidationError(
                f"I15: budget_ledger {asdict(persisted)} does not match the "
                f"recomputed {asdict(ledger)}"
            )
        expected_noops = sum(1 for a in attempts if a.duplicate)
        if result.no_op_count != expected_noops:
            raise ResultValidationError(
                f"I15: no_op_count {result.no_op_count} does not match "
                f"{expected_noops}"
            )

    for attempt in attempts:
        # I10 -- a static rejection never launches GRASS
        if not attempt.static_passed and attempt.exit_code is not None:
            raise ResultValidationError(
                f"I10: attempt {attempt.ordinal} failed static validation but has "
                f"exit_code {attempt.exit_code}"
            )

        # I12 -- no semantic verdict without an evaluation
        if not result.semantic_evaluated and attempt.assertion_results:
            raise ResultValidationError(
                f"I12: attempt {attempt.ordinal} carries assertion results without "
                f"a semantic evaluation"
            )
        if not attempt.semantic_evaluated and attempt.assertion_results:
            raise ResultValidationError(
                f"I12: attempt {attempt.ordinal} carries assertion results but is "
                f"not marked evaluated"
            )

        # I13 -- an evaluated attempt has evidence for its outputs
        if attempt.semantic_evaluated and not attempt.assertion_results:
            raise ResultValidationError(
                f"I13: attempt {attempt.ordinal} is evaluated but has no "
                f"assertion results"
            )

        # I14 -- a duplicate never executed
        if attempt.duplicate:
            if attempt.exit_code is not None:
                raise ResultValidationError(
                    f"I14: duplicate attempt {attempt.ordinal} has exit_code "
                    f"{attempt.exit_code}"
                )
            if attempt.timed_out:
                raise ResultValidationError(
                    f"I14: duplicate attempt {attempt.ordinal} is marked timed_out"
                )
            if attempt.has_new_maps:
                raise ResultValidationError(
                    f"I14: duplicate attempt {attempt.ordinal} carries new maps"
                )

    # I11 -- semantic pass implies execution pass and an evaluation
    if result.pass_at_semantic:
        if not result.pass_at_executed:
            raise ResultValidationError(
                "I11: pass_at_semantic is true without pass_at_executed"
            )
        if not result.semantic_evaluated:
            raise ResultValidationError(
                "I11: pass_at_semantic is true without semantic_evaluated"
            )
    if not result.semantic_evaluated and result.pass_at_semantic is not None:
        raise ResultValidationError(
            "I12: pass_at_semantic must be null when nothing was evaluated"
        )

    _check_pipeline_invariants(result)

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

    # I8 -- the excerpt is fed verbatim to the repair prompt (FR-010), so it
    # must be a substring of *something that was captured*, a static
    # diagnostic, or the harness's own duplicate diagnostic.
    for attempt in attempts:
        if not attempt.error_excerpt:
            continue
        if any(attempt.error_excerpt in stream for stream in captured):
            continue
        if any(attempt.error_excerpt in issue for issue in attempt.static_issues):
            continue
        if attempt.duplicate and attempt.error_excerpt.startswith(
            DUPLICATE_EXCERPT_PREFIX
        ):
            continue
        raise ResultValidationError(
            f"I8: attempt {attempt.ordinal} error_excerpt is not a substring "
            f"of the captured output, a static diagnostic, or a duplicate "
            f"diagnostic"
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
    """Stamp completion and persist (I6)."""
    result.status = STATUS_COMPLETE
    result.completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(output_root, result)
    return result


RUN_META_NAME = "run_summary.json"


def plan_artifact_path(output_root: Path, tc_id: str, ordinal: int) -> Path:
    return case_dir(output_root, tc_id) / f"attempt_{ordinal}.plan.json"


def manuals_artifact_path(output_root: Path, tc_id: str, ordinal: int) -> Path:
    return case_dir(output_root, tc_id) / f"attempt_{ordinal}.manuals.json"


def save_plan_artifact(
    output_root: Path, tc_id: str, ordinal: int, payload: dict
) -> Path:
    """Persist ``attempt_N.plan.json`` (contracts/planner.md section 7)."""
    path = plan_artifact_path(output_root, tc_id, ordinal)
    write_atomic(path, payload)
    return path


def save_manuals_artifact(
    output_root: Path, tc_id: str, ordinal: int, payload: dict
) -> Path:
    """Persist ``attempt_N.manuals.json`` card/token evidence."""
    path = manuals_artifact_path(output_root, tc_id, ordinal)
    write_atomic(path, payload)
    return path


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
    max_static_retries: int | None = None,
    max_runtime_retries: int | None = None,
) -> CaseResult | None:
    """Return a persisted case when every reuse rule holds, else None.

    Implements R1-R13 of contracts/case-result.md. Any single failure discards
    the case and reruns it from the initial candidate. `reason_sink` collects
    why, so a resume run can explain itself without per-case noise on stdout.
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
    if result.resume_key is None or not result.resume_key.matches(current_key):  # R4-R9
        reject(f"resume key mismatch (R4-R7): {result.resume_key} vs {current_key}")
        return None

    try:
        check_invariants(
            result,
            max_retries,
            root=case_dir(output_root, tc_id),
            max_static_retries=max_static_retries,
            max_runtime_retries=max_runtime_retries,
        )  # R11, R12, R13
    except ResultValidationError as exc:
        reject(str(exc))
        return None

    return result
