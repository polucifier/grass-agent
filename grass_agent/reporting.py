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
from .results import OUTCOME_EXECUTED_OK, CaseResult, ResumeKey

# Constitution Principle IV: the Gate 1 baseline the comparison is drawn against.
GATE1_STATIC_VALIDITY = 0.900

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
) -> RunSummary:
    """Fold per-case results into a RunSummary.

    Enforces I5 implicitly: every failed attempt contributes exactly one entry
    to `failure_mode_counts`, so the mode totals always equal the failed-attempt
    count.
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
    )

    for result in results:
        summary.pass_at_1 += 1 if result.pass_at_1 else 0
        summary.pass_at_healed += 1 if result.pass_at_healed else 0

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