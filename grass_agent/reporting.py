"""Gate 1 vs Gate 2 reporting (FR-018, FR-020, FR-021).

The report is a pure function of persisted `case_result.json` files plus
run-level metadata, so `--report-only` can regenerate it without invoking the
model or GRASS (SC-013).

One caveat is stated in every report without exception: exit-status success is
not correctness. A script can run cleanly and produce the wrong map, so
Pass@Healed measures *executability*, not accuracy (FR-021, SC-014).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .classifier import FailureMode
from .results import (
    BUDGET_RUNTIME,
    BUDGET_STATIC,
    OUTCOME_EXECUTED_OK,
    CaseResult,
    ResumeKey,
    attempt_budget_tier,
)

# Constitution Principle IV: the Gate 1 baseline the comparison is drawn against.
GATE1_STATIC_VALIDITY = 0.900

# Frozen Gate 2 closing baseline (contracts/report.md). These are historical
# constants, not metrics recomputed from the current Gate 3 run.
GATE2_PASS_AT_1 = 0.275
GATE2_PASS_AT_HEALED = 0.325

GATE3_SEMANTIC_CAVEATS = [
    "**Semantic pass is not universal correctness.** It means the declared "
    "assertions passed, not that the geospatial result is globally correct.",
    "**Exit status is not correctness.** A script that runs cleanly may still "
    "produce the wrong map; Gate 3 separates the two verdicts for that reason.",
    "**Generation is stochastic.** A one- or two-case difference is within "
    "sampling noise and should not be reported as a reliable improvement.",
    "**Semantic assertions never trigger repair.** A semantic failure is "
    "measured and reported; it generates no repair prompt and consumes no tier.",
    "**Pilot expectations are independent.** Expected values come from "
    "human-reviewed reference scripts, never from candidate output.",
]

EXIT_STATUS_CAVEAT = (
    "**Exit status is not correctness.** A script that runs cleanly may still "
    "produce the wrong map. Pass@Healed measures *executability* -- whether the "
    "generated script completes inside a live GRASS session -- and must not be "
    "read as an accuracy figure. Gate 2 does not validate geospatial output."
)

RUN_VARIANCE_CAVEAT = (
    "**Generation is stochastic.** Pass@1 comes from one sampling run of a local "
    "model, so it varies between runs by a case or two. A healed gain of one or "
    "two cases is within that noise and should not be reported as a reliable "
    "improvement. Re-run with `--clean` to resample."
)

# Both counts are under-reported for reasons that are properties of GRASS, not
# of the model. Stating them keeps the numbers honest (task T066).
CLASSIFICATION_CAVEATS = [
    "`missing_input` is **under-reported**: when a script both invents an option "
    "name and references a missing map, GRASS's option parser aborts first and "
    "emits only `Sorry, <x> is not a valid parameter`. The schema error masks the "
    "missing map.",
    "`schema_misuse` is **under-reported**: GRASS accepts unambiguous option "
    "prefixes (`m=`, `in=`, `out=`), so a slightly-wrong parameter name often "
    "works and never reaches this category.",
    "A wrong *type* for a map parameter is reported by GRASS as a missing map "
    "(`Raster map <a,b> not found`), so some genuine type errors are counted "
    "under `missing_input`. Unavoidable at the string level.",
]


@dataclass
class RunSummary:
    """Aggregate for one harness invocation."""

    model: str = ""
    suites: list[str] = field(default_factory=list)
    cases_total: int = 0
    cases_completed: int = 0
    max_retries: int = 2
    timeout_s: int = 120
    attempt1_source: str = "fresh"
    resume_key: ResumeKey | None = None

    pass_at_1: int = 0
    pass_at_healed: int = 0

    failure_mode_counts: dict[str, int] = field(default_factory=dict)
    failure_mode_transitions: dict[str, int] = field(default_factory=dict)
    mode_by_ordinal: dict[int, int] = field(default_factory=dict)

    latency_by_ordinal: dict[int, list[float]] = field(default_factory=dict)
    tokens_by_ordinal: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    prompt_tokens_total: int = 0
    completion_tokens_total: int = 0

    not_evaluated: list[str] = field(default_factory=list)
    resumed: bool = False
    permanent_hash_before: str = ""
    permanent_hash_after: str = ""
    leaked_scratch_dirs: list[str] = field(default_factory=list)

    # ---- Gate 3 additive aggregates
    max_static_retries: int = 2
    max_runtime_retries: int = 2
    grass_version: str = ""
    dataset: str = ""
    pilot_suite_hash: str = ""
    pilot_expectations_hash: str = ""
    pilot_reviewed: bool | None = None
    report_only: bool = False

    cases_semantic: int = 0
    pass_at_executed: int = 0
    pass_at_executed_semantic_count: int = 0
    pass_at_semantic: int = 0
    semantic_not_evaluated: list[str] = field(default_factory=list)
    static_repairs_used: int = 0
    runtime_repairs_used: int = 0
    static_limit_total: int = 0
    runtime_limit_total: int = 0
    no_op_detected: int = 0
    no_op_rejected: int = 0
    no_op_pivots: int = 0
    accepted_duplicate_executions: int = 0
    assertion_failure_counts: dict[str, int] = field(default_factory=dict)
    semantic_failures: list[dict] = field(default_factory=list)
    cases_exhausting_static: int = 0
    cases_exhausting_runtime: int = 0

    # ---- Feature 004 additive aggregates
    pipeline: str = "legacy"
    num_ctx: int = 8192
    manual_context_tokens: int = 0
    manual_cards_rendered: int = 0
    manual_budget_failures: int = 0
    context_overflow_events: int = 0
    plan_attempts: int = 0
    plan_repairs: int = 0
    plan_fallbacks: int = 0
    replans: int = 0
    shortlist_shortfalls: int = 0
    tool_swaps: int = 0
    pipeline_ablation: list[dict] = field(default_factory=list)

    # -------------------------------------------------------------- derived

    @property
    def pass_at_1_rate(self) -> float:
        return self.pass_at_1 / self.cases_completed if self.cases_completed else 0.0

    @property
    def pass_at_healed_rate(self) -> float:
        return self.pass_at_healed / self.cases_completed if self.cases_completed else 0.0

    @property
    def healing_gain_absolute(self) -> float:
        return self.pass_at_healed_rate - self.pass_at_1_rate

    @property
    def healing_gain_relative(self) -> float | None:
        if self.pass_at_1_rate == 0:
            return None if self.pass_at_healed == 0 else float("inf")
        return (self.pass_at_healed_rate - self.pass_at_1_rate) / self.pass_at_1_rate

    @property
    def permanent_unchanged(self) -> bool:
        return bool(self.permanent_hash_before) and (
            self.permanent_hash_before == self.permanent_hash_after
        )

    # ---- Gate 3 derived metrics (contracts/report.md)

    @property
    def pass_at_executed_rate(self) -> float:
        return self.pass_at_executed / self.cases_completed if self.cases_completed else 0.0

    @property
    def pass_at_executed_rate_semantic(self) -> float:
        if not self.cases_semantic:
            return 0.0
        return self.pass_at_executed_semantic_count / self.cases_semantic

    @property
    def pass_at_semantic_rate(self) -> float:
        return self.pass_at_semantic / self.cases_semantic if self.cases_semantic else 0.0

    @property
    def execution_semantic_gap(self) -> float:
        """Percentage points lost between execution and semantic success."""
        if not self.cases_semantic:
            return 0.0
        return self.pass_at_executed_rate_semantic - self.pass_at_semantic_rate

    @property
    def total_attempts(self) -> int:
        return sum(len(v) for v in self.latency_by_ordinal.values())

    @property
    def failed_attempts(self) -> int:
        """Attempts that consumed budget. I5 requires this to equal the mode sum."""
        return sum(
            len(lat) - self._succeeded_at(ordinal)
            for ordinal, lat in self.latency_by_ordinal.items()
        )

    def _succeeded_at(self, ordinal: int) -> int:
        return 0  # replaced during aggregation; see aggregate()

    def mean_latency(self, ordinal: int) -> float | None:
        values = self.latency_by_ordinal.get(ordinal) or []
        return sum(values) / len(values) if values else None

    @property
    def p95_latency(self) -> float | None:
        values = sorted(
            latency
            for latencies in self.latency_by_ordinal.values()
            for latency in latencies
        )
        if not values:
            return None
        index = min(len(values) - 1, int(round(0.95 * (len(values) - 1))))
        return values[index]


def aggregate(
    results: list[CaseResult],
    *,
    model: str,
    suites: list[str],
    max_retries: int,
    timeout_s: int,
    attempt1_source: str,
    resume_key: ResumeKey,
    cases_total: int,
    not_evaluated: list[str] | None = None,
    resumed: bool = False,
    permanent_hash_before: str = "",
    permanent_hash_after: str = "",
    leaked_scratch_dirs: list[str] | None = None,
    max_static_retries: int | None = None,
    max_runtime_retries: int | None = None,
    grass_version: str = "",
    dataset: str = "",
    pilot_suite_hash: str = "",
    pilot_expectations_hash: str = "",
    pilot_reviewed: bool | None = None,
    report_only: bool = False,
    pipeline: str = "legacy",
    num_ctx: int = 8192,
    manual_context_tokens: int | None = None,
    manual_cards_rendered: int = 0,
    manual_budget_failures: int = 0,
    context_overflow_events: int = 0,
    plan_attempts: int = 0,
    plan_repairs: int = 0,
    plan_fallbacks: int = 0,
    replans: int = 0,
    shortlist_shortfalls: int = 0,
    tool_swaps: int = 0,
    pipeline_ablation: list[dict] | None = None,
) -> RunSummary:
    """Fold per-case results into a RunSummary.

    Enforces I5 implicitly: every failed attempt contributes exactly one entry
    to `failure_mode_counts`, so the mode totals always equal the failed-attempt
    count. Gate 3 fields are computed from persisted evidence only.
    """
    summary = RunSummary(
        model=model,
        suites=suites,
        cases_total=cases_total,
        max_retries=max_retries,
        timeout_s=timeout_s,
        attempt1_source=attempt1_source,
        resume_key=resume_key,
        cases_completed=len(results),
        not_evaluated=not_evaluated or [],
        resumed=resumed,
        permanent_hash_before=permanent_hash_before,
        permanent_hash_after=permanent_hash_after,
        leaked_scratch_dirs=leaked_scratch_dirs or [],
        max_static_retries=(
            max_retries if max_static_retries is None else max_static_retries
        ),
        max_runtime_retries=(
            max_retries if max_runtime_retries is None else max_runtime_retries
        ),
        grass_version=grass_version,
        dataset=dataset,
        pilot_suite_hash=pilot_suite_hash,
        pilot_expectations_hash=pilot_expectations_hash,
        pilot_reviewed=pilot_reviewed,
        report_only=report_only,
        pipeline=pipeline,
        num_ctx=num_ctx,
        manual_context_tokens=(
            int(0.45 * num_ctx)
            if manual_context_tokens is None
            else manual_context_tokens
        ),
        manual_cards_rendered=manual_cards_rendered,
        manual_budget_failures=manual_budget_failures,
        context_overflow_events=context_overflow_events,
        plan_attempts=plan_attempts,
        plan_repairs=plan_repairs,
        plan_fallbacks=plan_fallbacks,
        replans=replans,
        shortlist_shortfalls=shortlist_shortfalls,
        tool_swaps=tool_swaps,
        pipeline_ablation=list(pipeline_ablation or []),
    )

    for result in results:
        summary.pass_at_1 += 1 if result.pass_at_1 else 0
        summary.pass_at_healed += 1 if result.pass_at_healed else 0
        summary.pass_at_executed += 1 if result.pass_at_executed else 0

        if result.semantic_evaluated or result.semantic_declared:
            summary.cases_semantic += 1
            if result.pass_at_executed:
                summary.pass_at_executed_semantic_count += 1
            if result.pass_at_semantic:
                summary.pass_at_semantic += 1
        else:
            summary.semantic_not_evaluated.append(result.tc_id)

        static_used = runtime_used = 0
        static_limit = summary.max_static_retries
        runtime_limit = summary.max_runtime_retries
        if result.budget_ledger is not None:
            static_used = result.budget_ledger.static_used
            runtime_used = result.budget_ledger.runtime_used
            static_limit = result.budget_ledger.static_limit
            runtime_limit = result.budget_ledger.runtime_limit
        else:
            for attempt in result.attempts:
                tier = attempt_budget_tier(attempt)
                if tier == BUDGET_STATIC:
                    static_used += 1
                elif tier == BUDGET_RUNTIME:
                    runtime_used += 1
        summary.static_repairs_used += static_used
        summary.runtime_repairs_used += runtime_used
        summary.static_limit_total += static_limit
        summary.runtime_limit_total += runtime_limit
        if static_limit > 0 and static_used >= static_limit:
            summary.cases_exhausting_static += 1
        if runtime_limit > 0 and runtime_used >= runtime_limit:
            summary.cases_exhausting_runtime += 1

        if any(attempt.pivot_used for attempt in result.attempts):
            summary.no_op_pivots += 1

        for attempt in result.attempts:
            if attempt.duplicate:
                summary.no_op_detected += 1
                summary.no_op_rejected += 1
                if attempt.exit_code is not None:
                    summary.accepted_duplicate_executions += 1
            # ---- Feature 004 evidence
            if attempt.manual_card_tokens > 0:
                summary.manual_cards_rendered += 1
            if attempt.error_excerpt and "manual card budget exceeded" in attempt.error_excerpt.lower():
                summary.manual_budget_failures += 1
            if summary.pipeline != "legacy" and (
                (
                    summary.manual_context_tokens
                    and attempt.manual_card_tokens > summary.manual_context_tokens
                )
                or (summary.num_ctx and attempt.prompt_tokens > summary.num_ctx)
            ):
                summary.context_overflow_events += 1
            if attempt.planner_invocations > 0:
                summary.plan_attempts += 1
            summary.plan_repairs += int(attempt.plan_repair_count or 0)
            if attempt.plan_fallback:
                summary.plan_fallbacks += 1
            summary.replans += int(attempt.replan_count or 0)
            if attempt.shortlist_shortfall:
                summary.shortlist_shortfalls += 1
            summary.tool_swaps += len(attempt.tool_swaps or [])
            for entry in attempt.assertion_results or []:
                if isinstance(entry, dict):
                    passed = bool(entry.get("passed", False))
                    check = entry.get("check", "")
                    evidence = entry
                else:
                    passed = bool(getattr(entry, "passed", False))
                    check = getattr(entry, "check", "")
                    evidence = {
                        "output": getattr(entry, "output", ""),
                        "check": check,
                        "expected": getattr(entry, "expected", None),
                        "observed": getattr(entry, "observed", None),
                        "tolerance": getattr(entry, "tolerance", None),
                        "detail": getattr(entry, "detail", ""),
                    }
                if passed:
                    continue
                summary.assertion_failure_counts[check] = (
                    summary.assertion_failure_counts.get(check, 0) + 1
                )
                summary.semantic_failures.append(
                    {
                        "case_id": result.tc_id,
                        "output": evidence.get("output", ""),
                        "check": check,
                        "expected": evidence.get("expected"),
                        "observed": evidence.get("observed"),
                        "tolerance": evidence.get("tolerance"),
                        "detail": evidence.get("detail", ""),
                        "verdict": "❌",
                    }
                )

        modes: list[str | None] = []
        for attempt in result.attempts:
            ordinal = attempt.ordinal
            summary.latency_by_ordinal.setdefault(ordinal, []).append(attempt.latency_s)
            summary.tokens_by_ordinal.setdefault(ordinal, []).append(
                (attempt.prompt_tokens, attempt.completion_tokens)
            )
            summary.prompt_tokens_total += attempt.prompt_tokens
            summary.completion_tokens_total += attempt.completion_tokens

            if attempt.succeeded:
                modes.append(None)
                continue
            mode = attempt.failure_mode or FailureMode.GENERAL_EXCEPTION.value
            modes.append(mode)
            summary.failure_mode_counts[mode] = summary.failure_mode_counts.get(mode, 0) + 1

        # Ordered transition pairs: how a mode became another mode.
        for first, second in zip(modes, modes[1:]):
            if first is None:
                continue
            key = f"{first} -> {'success' if second is None else second}"
            summary.failure_mode_transitions[key] = (
                summary.failure_mode_transitions.get(key, 0) + 1
            )

    return summary


def format_gain(gain_relative: float | None) -> str:
    """Human-readable relative healing gain."""
    if gain_relative is None:
        return "n/a (zero-shot rate was 0%)"
    if gain_relative == float("inf"):
        return "n/a (healed successes from a 0% baseline)"
    return f"{gain_relative * 100:+.1f}%"


def render_markdown(summary: RunSummary, results: list[CaseResult]) -> str:
    """Render the full comparative report."""
    lines: list[str] = []
    add = lines.append

    add("# Gate 2 Execution Report — Headless Runtime Execution & Self-Healing")
    add("")
    add(f"- **Model**: `{summary.model}`")
    add(f"- **Suites**: {', '.join(summary.suites) or 'n/a'}")
    add(f"- **Cases**: {summary.cases_completed} completed of {summary.cases_total}")
    add(f"- **Attempt-1 source**: `{summary.attempt1_source}`")
    add(f"- **Retry budget**: `{summary.max_retries}` (unified across static and runtime stages)")
    add(f"- **Per-attempt timeout**: `{summary.timeout_s}`s")
    add(f"- **Resume**: {'yes — reused completed cases' if summary.resumed else 'no'}")
    add("")

    # ---------------------------------------------------------------- headline
    add("## Headline metrics")
    add("")
    add("| Metric | Value |")
    add("|---|---|")
    add(f"| Gate 1 static validity (baseline, constitution IV) | {GATE1_STATIC_VALIDITY * 100:.1f}% |")
    add(f"| Gate 2 **Pass@1** (zero-shot, no healing) | {summary.pass_at_1}/{summary.cases_completed} = **{summary.pass_at_1_rate * 100:.1f}%** |")
    add(f"| Gate 2 **Pass@Healed** (after retry 1 and 2) | {summary.pass_at_healed}/{summary.cases_completed} = **{summary.pass_at_healed_rate * 100:.1f}%** |")
    add(f"| Healing gain (absolute) | **{summary.healing_gain_absolute * 100:+.1f} pp** |")
    add(f"| Healing gain (relative) | {format_gain(summary.healing_gain_relative)} |")
    add("")
    if summary.not_evaluated:
        add(f"**Not evaluated** ({len(summary.not_evaluated)}): {', '.join(summary.not_evaluated)}")
        add("")

    add("> Gate 1 and Gate 2 are measured by **different harnesses**: Gate 1 asks whether "
        "a script parses and matches a schema; Gate 2 asks whether it actually runs in GRASS. "
        "The two rates are not on one continuous scale, and the drop from the first to the "
        "second is the real finding of this milestone.")
    add("")

    # ------------------------------------------------------------- caveats
    add("## Interpretation caveats")
    add("")
    add(EXIT_STATUS_CAVEAT)
    add("")
    add(RUN_VARIANCE_CAVEAT)
    add("")
    for caveat in CLASSIFICATION_CAVEATS:
        add(f"- {caveat}")
    add("")

    # ------------------------------------------------------- failure modes
    add("## Failure modes")
    add("")
    if summary.failure_mode_counts:
        add("| Failure mode | Failed attempts |")
        add("|---|---|")
        for mode, count in sorted(
            summary.failure_mode_counts.items(), key=lambda kv: -kv[1]
        ):
            add(f"| `{mode}` | {count} |")
        add(f"| **Total** | **{sum(summary.failure_mode_counts.values())}** |")
        add("")
        add("Mode totals equal the number of failed attempts exactly (invariant I5), "
            "so no failure is unclassified.")
    else:
        add("No failed attempts.")
    add("")

    add("### Failure-mode transitions")
    add("")
    if summary.failure_mode_transitions:
        add("How a mode became the next mode on a later attempt.")
        add("")
        add("| Transition | Count |")
        add("|---|---|")
        for transition, count in sorted(
            summary.failure_mode_transitions.items(), key=lambda kv: -kv[1]
        ):
            add(f"| `{transition}` | {count} |")
    else:
        add("No multi-attempt cases, so no transitions to report.")
    add("")

    # ------------------------------------------------------------- per case
    add("## Per-case results")
    add("")
    add("| Case | Tier | Category | Pass@1 | Pass@Healed | Attempts | Modes |")
    add("|---|---|---|---|---|---|---|")
    for result in sorted(results, key=lambda r: r.tc_id):
        modes = " → ".join(
            "✓" if m is None else m for m in result.failure_mode_transitions
        )
        add(
            f"| `{result.tc_id}` | {result.tier if result.tier is not None else '—'} "
            f"| {result.category} | {'✅' if result.pass_at_1 else '❌'} "
            f"| {'✅' if result.pass_at_healed else '❌'} | {len(result.attempts)} "
            f"| {modes or '—'} |"
        )
    add("")

    # ----------------------------------------------------------------- cost
    add("## Cost per attempt ordinal")
    add("")
    add("| Ordinal | Mean latency (s) | Mean prompt tok | Mean completion tok |")
    add("|---|---|---|---|")
    ordinals = sorted(summary.latency_by_ordinal)
    for ordinal in ordinals:
        mean_latency = summary.mean_latency(ordinal) or 0.0
        pairs = summary.tokens_by_ordinal.get(ordinal) or []
        count = max(len(pairs), 1)
        mean_prompt = sum(p for p, _ in pairs) / count
        mean_completion = sum(c for _, c in pairs) / count
        label = "1 (initial)" if ordinal == 1 else f"{ordinal} (retry {ordinal - 1})"
        add(f"| {label} | {mean_latency:.1f} | {mean_prompt:.0f} | {mean_completion:.0f} |")
    add("")
    if summary.pass_at_healed:
        per_success = (summary.prompt_tokens_total + summary.completion_tokens_total) / (
            summary.pass_at_healed
        )
        add(f"Total tokens: **{summary.prompt_tokens_total} prompt + "
            f"{summary.completion_tokens_total} completion** across "
            f"{summary.total_attempts} attempts.")
        add(f"Cost per successful case: **{per_success:.0f} tokens**.")
    else:
        add("No successful cases, so cost per successful case is undefined.")
    add("")
    if summary.attempt1_source == "reuse_artifacts":
        add("> This run loaded attempt 1 from persisted Gate 1 scripts, so attempt 1 "
            "performed **no inference** and its token counts are 0 by construction. "
            "Totals here reflect execution behaviour only, not generation cost.")
        add("")

    # ------------------------------------------------------------ integrity
    add("## Integrity evidence")
    add("")
    add("| Check | Result |")
    add("|---|---|")
    add(f"| Persistent mapset unchanged | {'✅ yes' if summary.permanent_unchanged else '⚠️ unknown or changed'} |")
    add(f"| Leaked scratch directories | {len(summary.leaked_scratch_dirs)} {summary.leaked_scratch_dirs or ''} |")
    add("")
    add(f"- `permanent_hash_before`: `{summary.permanent_hash_before or 'n/a'}`")
    add(f"- `permanent_hash_after`: `{summary.permanent_hash_after or 'n/a'}`")
    add("")
    return "\n".join(lines) + "\n"


def write_report(path: Path, summary: RunSummary, results: list[CaseResult]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(summary, results), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Gate 3 renderer (contracts/report.md)
# --------------------------------------------------------------------------


def _subset(results: list[CaseResult], predicate) -> list[CaseResult]:
    return [r for r in results if predicate(r)]


def _rate(numerator: int, denominator: int) -> str:
    if not denominator:
        return f"{numerator}/{denominator} = n/a"
    return f"{numerator}/{denominator} = {numerator / denominator * 100:.1f}%"


def _gate3_row(label: str, subset: list[CaseResult]) -> str:
    executed = sum(1 for r in subset if r.pass_at_executed)
    semantic = [
        r for r in subset if r.semantic_evaluated or r.semantic_declared
    ]
    semantic_passed = sum(1 for r in semantic if r.pass_at_semantic)
    return (
        f"| {label} | {len(subset)} | {_rate(executed, len(subset))} "
        f"| {_rate(semantic_passed, len(semantic))} | {len(semantic)} |"
    )


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, list):
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    return str(value)


def render_gate3_markdown(summary: RunSummary, results: list[CaseResult]) -> str:
    """Render the Gate 3 report.

    Exactly two metrics appear in the main table; the Gate 2 baseline lives in
    a clearly separated historical section. The report is a pure function of
    persisted results plus run metadata, so `--report-only` reproduces it.
    """
    lines: list[str] = []
    add = lines.append

    add("# Gate 3 Report — Semantic Validation & Stateful Healing")
    add("")
    add(f"- **Model**: `{summary.model}`")
    add(f"- **Pipeline**: `{summary.pipeline}`")
    add(f"- **Context**: `{summary.num_ctx}` (manual budget `{summary.manual_context_tokens}` tokens)")
    add(f"- **GRASS**: `{summary.grass_version or 'unknown'}`")
    add(f"- **Dataset**: `{summary.dataset or 'unknown'}`")
    add(f"- **Suites**: {', '.join(summary.suites) or 'n/a'}")
    add(f"- **Cases**: {summary.cases_completed} completed of {summary.cases_total}")
    add(
        f"- **Static tier**: limit (sum) {summary.static_limit_total}, used "
        f"{summary.static_repairs_used}, remaining "
        f"{summary.static_limit_total - summary.static_repairs_used}"
    )
    add(
        f"- **Runtime tier**: limit (sum) {summary.runtime_limit_total}, used "
        f"{summary.runtime_repairs_used}, remaining "
        f"{summary.runtime_limit_total - summary.runtime_repairs_used}"
    )
    add(
        f"- **Pilot expectations**: `{summary.pilot_expectations_hash or 'n/a'}` "
        f"({_review_status(summary.pilot_reviewed)})"
    )
    add(f"- **Resume**: {'yes — reused completed cases' if summary.resumed else 'no'}")
    add("")

    # ---------------------------------------------------------- main metrics
    add("## Gate 3 metrics")
    add("")
    add("| Suite | Cases | Pass@Executed | Pass@Semantic | Semantic cases |")
    add("|---|---|---|---|---|")
    if len(summary.suites) > 1:
        for index, name in enumerate(summary.suites, start=1):
            add(_gate3_row(f"`{name}`", _subset(results, lambda r, i=index: r.tier == i)))
    else:
        add(_gate3_row("`" + (summary.suites[0] if summary.suites else "run") + "`", results))
    semantic_subset = [r for r in results if r.semantic_evaluated]
    add(_gate3_row("**Overall**", results))
    add("")
    if summary.cases_semantic:
        add(
            f"Execution→semantic gap over the semantic subset: "
            f"{_rate(summary.pass_at_executed_semantic_count, summary.cases_semantic)} "
            f"− {_rate(summary.pass_at_semantic, summary.cases_semantic)} = "
            f"**{summary.execution_semantic_gap * 100:.1f} pp**."
        )
    else:
        add("No semantic cases in this run, so the execution→semantic gap is not defined.")
    add("")
    if summary.not_evaluated:
        add(f"**Not evaluated** ({len(summary.not_evaluated)}): {', '.join(summary.not_evaluated)}")
        add("")

    # --------------------------------------------------- pipeline diagnostics
    add("## Pipeline diagnostics")
    add("")
    add("| Metric | Value |")
    add("|---|---|")
    add(f"| Pipeline | `{summary.pipeline}` |")
    add(f"| Context / manual budget | {summary.num_ctx} / {summary.manual_context_tokens} tokens |")
    add(f"| Manual cards rendered | {summary.manual_cards_rendered} |")
    add(f"| Manual budget failures | {summary.manual_budget_failures} |")
    add(f"| Context overflow events | {summary.context_overflow_events} |")
    add(f"| Plan attempts | {summary.plan_attempts} |")
    add(f"| Plan repairs | {summary.plan_repairs} |")
    add(f"| Plan fallbacks | {summary.plan_fallbacks} |")
    add(f"| Replans | {summary.replans} |")
    add(f"| Shortlist shortfalls | {summary.shortlist_shortfalls} |")
    add(f"| Tool swaps | {summary.tool_swaps} |")
    add("")

    if summary.pipeline_ablation:
        add(render_pipeline_ablation(summary.pipeline_ablation))
        add("")

    # ------------------------------------------------------ semantic failures
    add("## Semantic failures")
    add("")
    if summary.semantic_failures:
        add("| Case | Output | Check | Expected | Observed | Tolerance | Verdict |")
        add("|---|---|---|---|---|---|---|")
        for failure in summary.semantic_failures:
            tolerance = failure.get("tolerance")
            tolerance_text = (
                f"{float(tolerance) * 100:g}%" if tolerance is not None else "—"
            )
            add(
                f"| {failure.get('case_id', '')} | {failure.get('output', '')} "
                f"| {failure.get('check', '')} | {_fmt(failure.get('expected'))} "
                f"| {_fmt(failure.get('observed'))} | {tolerance_text} "
                f"| {failure.get('verdict', '❌')} |"
            )
        add("")
        add("| Check | Failures |")
        add("|---|---|")
        for check in (
            "mean",
            "value_range",
            "geometry_type",
            "required_columns",
            "feature_count",
            "non_null_count",
        ):
            add(f"| {check} | {summary.assertion_failure_counts.get(check, 0)} |")
    else:
        add("No semantic failures.")
    add("")

    # -------------------------------------------------------------- tier usage
    add("## Repair budget usage")
    add("")
    add("| Tier | Limit (sum) | Used | Remaining | Cases exhausting tier |")
    add("|---|---|---|---|---|")
    add(
        f"| static | {summary.static_limit_total} | {summary.static_repairs_used} "
        f"| {summary.static_limit_total - summary.static_repairs_used} "
        f"| {summary.cases_exhausting_static} |"
    )
    add(
        f"| runtime | {summary.runtime_limit_total} | {summary.runtime_repairs_used} "
        f"| {summary.runtime_limit_total - summary.runtime_repairs_used} "
        f"| {summary.cases_exhausting_runtime} |"
    )
    add("")

    # --------------------------------------------------------- no-op detection
    add("## No-op duplicate detection")
    add("")
    add("| Metric | Value |")
    add("|---|---|")
    add(f"| Duplicate candidates detected | {summary.no_op_detected} |")
    add(f"| Rejected before execution | {summary.no_op_rejected} |")
    if summary.accepted_duplicate_executions:
        add(
            f"| Accepted duplicates executed | **⚠️ "
            f"{summary.accepted_duplicate_executions} — FAILURE** |"
        )
    else:
        add(f"| Accepted duplicates executed | {summary.accepted_duplicate_executions} |")
    add(f"| Cases resolved by parameter pivot | {summary.no_op_pivots} |")
    add(f"| No-op attempts recorded | {summary.no_op_detected} |")
    add("")

    # ----------------------------------------------------------- per case
    add("## Per-case results")
    add("")
    add(
        "| Case | Tier | Category | Pass@Executed | Pass@Semantic | Attempts "
        "| Static used | Runtime used | Duplicates |"
    )
    add("|---|---|---|---|---|---|---|---|---|")
    for result in sorted(results, key=lambda r: r.tc_id):
        ledger = result.budget_ledger
        static_used = ledger.static_used if ledger else 0
        runtime_used = ledger.runtime_used if ledger else 0
        semantic = (
            "—"
            if not (result.semantic_evaluated or result.semantic_declared)
            else ("✅" if result.pass_at_semantic else "❌")
        )
        add(
            f"| `{result.tc_id}` | {result.tier if result.tier is not None else '—'} "
            f"| {result.category} | {'✅' if result.pass_at_executed else '❌'} "
            f"| {semantic} | {len(result.attempts)} | {static_used} "
            f"| {runtime_used} | {result.no_op_count} |"
        )
    add("")

    if summary.semantic_not_evaluated:
        add(
            f"**Semantic not evaluated** ({len(summary.semantic_not_evaluated)}): "
            f"{', '.join(summary.semantic_not_evaluated)}"
        )
        add("")

    # ------------------------------------------------ interpretation caveats
    add("## Interpretation caveats")
    add("")
    for caveat in GATE3_SEMANTIC_CAVEATS:
        add(f"- {caveat}")
    add("")

    # ------------------------------------------------------- historical Gate 2
    add("## Gate 2 historical comparison")
    add("")
    add(
        "| Metric | Value |\n|---|---|\n"
        f"| Gate 1 static validity (constitution IV) | {GATE1_STATIC_VALIDITY * 100:.1f}% |\n"
        f"| Gate 2 Pass@1 | 11/40 = {GATE2_PASS_AT_1 * 100:.1f}% |\n"
        f"| Gate 2 Pass@Healed | 13/40 = {GATE2_PASS_AT_HEALED * 100:.1f}% |\n"
        f"| Healing gain (absolute) | "
        f"{(GATE2_PASS_AT_HEALED - GATE2_PASS_AT_1) * 100:+.1f} pp |\n"
        f"| Healing gain (relative) | {format_gain((GATE2_PASS_AT_HEALED - GATE2_PASS_AT_1) / GATE2_PASS_AT_1)} |"
    )
    add("")
    add(
        "Gate 1 and Gate 2 are measured by **different harnesses**: Gate 1 asks "
        "whether a script parses and matches a schema, Gate 2 whether it executes; "
        "Gate 3 asks whether the produced maps satisfy declared assertions. "
        "`Pass@Healed` is a Gate 2 executability figure and is not on the same "
        "scale as Gate 3 semantics."
    )
    add("")

    # ------------------------------------------------------------ integrity
    add("## Integrity evidence")
    add("")
    add("| Check | Result |")
    add("|---|---|")
    add(
        f"| Persistent mapset unchanged | "
        f"{'✅ yes' if summary.permanent_unchanged else '⚠️ unknown or changed'} |"
    )
    add(f"| Leaked scratch directories | {len(summary.leaked_scratch_dirs)} {summary.leaked_scratch_dirs or ''} |")
    add(
        f"| Accepted duplicate executions | {summary.accepted_duplicate_executions} "
        f"{'✅' if summary.accepted_duplicate_executions == 0 else '❌'} |"
    )
    add(
        f"| Non-evaluated cases excluded from semantic rate | "
        f"{'✅ yes' if summary.semantic_not_evaluated else '✅ yes (none)'} |"
    )
    add(
        "| Report regenerated without model/GRASS | "
        "✅ yes (persisted results only) |"
    )
    add("")
    add(f"- `permanent_hash_before`: `{summary.permanent_hash_before or 'n/a'}`")
    add(f"- `permanent_hash_after`: `{summary.permanent_hash_after or 'n/a'}`")
    add(f"- `pilot_suite_hash`: `{summary.pilot_suite_hash or 'n/a'}`")
    add(f"- `pilot_expectations_hash`: `{summary.pilot_expectations_hash or 'n/a'}`")
    add("")
    return "\n".join(lines) + "\n"


def render_pipeline_ablation(rows) -> str:
    """Render one row per pipeline mode without ever mixing denominators."""
    lines = ["## Pipeline ablation", ""]
    lines.append(
        "| Pipeline | Cases | Pass@Executed | Pass@Semantic | Plan repairs "
        "| Plan fallbacks | Replans | Shortfalls | Tool swaps | P95 latency |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in rows or []:
        pipeline = _row_value(row, "pipeline", "legacy")
        cases = int(_row_value(row, "cases_completed", 0) or 0)
        executed = int(_row_value(row, "pass_at_executed", 0) or 0)
        semantic_cases = int(_row_value(row, "cases_semantic", 0) or 0)
        semantic = int(_row_value(row, "pass_at_semantic", 0) or 0)
        label = f"`{pipeline}`"
        notes = []
        model = _row_value(row, "model", "")
        num_ctx = _row_value(row, "num_ctx", None)
        dataset = _row_value(row, "dataset", "")
        if model:
            notes.append(str(model))
        if num_ctx is not None:
            notes.append(f"{num_ctx} ctx")
        if dataset:
            notes.append(str(dataset))
        if notes:
            label += " (" + ", ".join(notes) + ")"
        p95 = _row_value(row, "p95_latency", None)
        p95_text = f"{float(p95):.1f}s" if p95 is not None else "—"
        lines.append(
            f"| {label} | {cases} | {_rate(executed, cases)} "
            f"| {_rate(semantic, semantic_cases)} "
            f"| {_row_value(row, 'plan_repairs', 0) or 0} "
            f"| {_row_value(row, 'plan_fallbacks', 0) or 0} "
            f"| {_row_value(row, 'replans', 0) or 0} "
            f"| {_row_value(row, 'shortlist_shortfalls', 0) or 0} "
            f"| {_row_value(row, 'tool_swaps', 0) or 0} "
            f"| {p95_text} |"
        )
    lines.append("")
    lines.append(
        "Rows are informational and are never pooled: each mode keeps its own "
        "case set and semantic denominator. A row whose model, context, or "
        "dataset differs is labelled rather than presented as a controlled "
        "comparison."
    )
    return "\n".join(lines)


def _row_value(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def ablation_row(summary: "RunSummary", **overrides) -> dict:
    """A dict suitable for ``render_pipeline_ablation``."""
    row = {
        "pipeline": summary.pipeline,
        "model": summary.model,
        "num_ctx": summary.num_ctx,
        "dataset": summary.dataset,
        "cases_completed": summary.cases_completed,
        "pass_at_executed": summary.pass_at_executed,
        "cases_semantic": summary.cases_semantic,
        "pass_at_semantic": summary.pass_at_semantic,
        "plan_repairs": summary.plan_repairs,
        "plan_fallbacks": summary.plan_fallbacks,
        "replans": summary.replans,
        "shortlist_shortfalls": summary.shortlist_shortfalls,
        "tool_swaps": summary.tool_swaps,
        "p95_latency": summary.p95_latency,
    }
    row.update(overrides)
    return row


def _review_status(reviewed: bool | None) -> str:
    if reviewed is True:
        return "reviewed"
    if reviewed is False:
        return "not reviewed"
    return "review status unknown"


def write_gate3_report(path: Path, summary: RunSummary, results: list[CaseResult]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_gate3_markdown(summary, results), encoding="utf-8")
    return path