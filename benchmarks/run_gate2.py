#!/usr/bin/env python3
"""Gate 2 — headless runtime execution and bounded self-healing.

Runs LLM-generated GRASS scripts for real inside an isolated headless GRASS
session, classifies every failure, and repairs failing scripts under a bounded
budget.

    python -m benchmarks.run_gate2 --model qwen2.5-coder:3b --max-retries 2

Governance: constitution v1.2.0. Generated and repaired code uses the
`grass.tools` interface exclusively and must contain nothing but executable
Python; all inference and embeddings stay on the local model service.
"""

from __future__ import annotations

import argparse
import signal
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from code_generator import (  # noqa: E402
    GrassCodeGenerator,
    PipelineGenerationResult,
    validate_api,
    validate_syntax,
)
from config import GenerationConfig  # noqa: E402
from grass_agent.classifier import FailureMode  # noqa: E402
from grass_agent.agentic import AgenticPipeline  # noqa: E402
from grass_agent.config import ExecutionConfig, grass_config  # noqa: E402
from grass_agent.executor import Executor  # noqa: E402
from grass_agent.fixtures import (  # noqa: E402
    FixtureError,
    filter_cases,
    load_suite,
    required_fixtures,
    stage_fixtures,
    unmatched_ids,
)
from grass_agent.healing import (  # noqa: E402
    NoOpIndex,
    RepairTurn,
    Healer,
    ast_digest,
    byte_digest,
    legacy_interface_issues,
    write_script,
)
from grass_agent.inventory import MapInventory, read_inventory  # noqa: E402
from grass_agent.manual_context import ManualBudgetExceeded  # noqa: E402
from grass_agent.planner import Planner  # noqa: E402
from grass_agent.preflight import (  # noqa: E402
    EXIT_ARG,
    EXIT_FAULT,
    EXIT_MISSING_DEPENDENCY,
    run_preflight,
)
from grass_agent.reporting import aggregate, write_report  # noqa: E402
from grass_agent.results import (  # noqa: E402
    BUDGET_INITIAL,
    BUDGET_RUNTIME,
    BUDGET_STATIC,
    BudgetLedger,
    OUTCOME_NO_OP_DUPLICATE,
    OUTCOME_STATIC_REJECTED,
    Attempt,
    CaseResult,
    ResumeKey,
    build_ledger,
    case_dir,
    discard_partials,
    is_reusable,
    load,
    load_run_meta,
    mark_complete,
    save,
    save_manuals_artifact,
    save_plan_artifact,
    save_run_meta,
)
from grass_agent.semantic import build_semantic_spec, load_expectations  # noqa: E402
from llm_provider import DEFAULT_NUM_PREDICT, OllamaProvider  # noqa: E402
from rag_retriever import GrassToolsRetriever  # noqa: E402

TIER_FILES = (
    "benchmarks/benchmark_prompts_tier1.json",
    "benchmarks/benchmark_prompts_tier2.json",
)

_INTERRUPTED = False


class Interrupted(Exception):
    """Raised when SIGINT arrives; the harness unwinds and cleans up."""


def _install_sigint_handler() -> None:
    """Turn SIGINT into a cooperative unwind so the sweep still runs (FR-006)."""

    def handler(signum, frame):  # noqa: ARG001
        global _INTERRUPTED
        _INTERRUPTED = True
        raise Interrupted()

    signal.signal(signal.SIGINT, handler)


# --------------------------------------------------------------------------
# Argument parsing (contracts/cli.md)
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Gate 2 headless execution and self-healing harness.",
    )
    parser.add_argument("--model", default=None, help="Local Ollama model (default: from env or qwen2.5-coder:3b)")
    parser.add_argument("-s", "--suite", default=None, help="Benchmark JSON file. Omit to cover both tiers")
    parser.add_argument("-k", "--case", default=None, help="Comma-separated case-id filter, e.g. -k tc_01,tc_11")
    parser.add_argument("--dataset", default=None, help="GRASS project directory. Omit to auto-detect")
    parser.add_argument("--max-retries", type=int, default=None, help="Unified retry budget per case (default 2; 0 disables healing)")
    parser.add_argument("--max-static-retries", type=int, default=None, help="Static (pre-execution) repair budget; overrides --max-retries for this tier")
    parser.add_argument("--max-runtime-retries", type=int, default=None, help="Runtime (execution) repair budget; overrides --max-retries for this tier")
    parser.add_argument("--timeout", type=int, default=None, help="Per-attempt wall-clock bound in seconds (default 120)")
    parser.add_argument("--semantic", dest="semantic", action="store_true", default=None, help="Enable semantic probing (Gate 2 default: off)")
    parser.add_argument("--no-semantic", dest="semantic", action="store_false", help="Disable semantic probing")
    parser.add_argument("--resume", dest="resume", action="store_true", default=None, help="Skip completed cases (default)")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Rerun every case, reusing nothing")
    parser.add_argument("--clean", action="store_true", help="Wipe output_execution/ and run from scratch")
    parser.add_argument("--reuse-artifacts", action="store_true", help="Load Gate 1 scripts as attempt 1")
    parser.add_argument("--report-only", action="store_true", help="Re-render the report from persisted results")
    parser.add_argument("--verbose", action="store_true", help="Explain every resume rejection")
    # ---- Feature 004 pipeline selection
    parser.add_argument(
        "--pipeline",
        default=None,
        help="Pipeline mode: legacy (default), manual-kb, or planned",
    )
    parser.add_argument(
        "--num-ctx", type=int, default=None, help="Model context used for the manual budget (default 8192)"
    )
    parser.add_argument(
        "--manual-context-tokens",
        type=int,
        default=None,
        help="Explicit documentation budget; default int(0.45 * num_ctx)",
    )
    parser.add_argument(
        "--strict-options",
        action="store_true",
        default=None,
        help="Legacy-only opt-in for strict closed-enum validation",
    )
    parser.add_argument(
        "--planner-model",
        default=None,
        help="Planner model override (validated only in planned mode)",
    )
    parser.add_argument(
        "--planner-timeout",
        type=int,
        default=None,
        help="Planner timeout in seconds (default 60)",
    )
    return parser


def resolve_config(args: argparse.Namespace) -> ExecutionConfig:
    """Merge CLI arguments over environment variables over defaults.

    Budget precedence, highest first: a tier-specific CLI flag, then the
    `--max-retries` shorthand, then the tier-specific environment variable,
    then `GRASS_MAX_RETRIES`, then the built-in default. `ExecutionConfig.from_env`
    applies the environment/default layers; the CLI layers are passed only when
    supplied, so an unset flag never erases an environment value.
    """
    case_filter = tuple(
        part.strip() for part in (args.case or "").split(",") if part.strip()
    )
    max_static = getattr(args, "max_static_retries", None)
    max_runtime = getattr(args, "max_runtime_retries", None)
    if max_static is None:
        max_static = args.max_retries
    if max_runtime is None:
        max_runtime = args.max_retries
    return ExecutionConfig.from_env(
        model=args.model,
        max_retries=args.max_retries,
        max_static_retries=max_static,
        max_runtime_retries=max_runtime,
        timeout_s=args.timeout,
        dataset_project=args.dataset,
        resume=args.resume,
        attempt1_source="reuse_artifacts" if args.reuse_artifacts else None,
        case_filter=case_filter,
        semantic_enabled=getattr(args, "semantic", None),
        pipeline=getattr(args, "pipeline", None),
        num_ctx=getattr(args, "num_ctx", None),
        manual_context_tokens=getattr(args, "manual_context_tokens", None),
        strict_options=getattr(args, "strict_options", None),
        planner_model=getattr(args, "planner_model", None),
        planner_timeout=getattr(args, "planner_timeout", None),
    )


def load_selected_cases(args: argparse.Namespace) -> tuple[list[dict], list[str]]:
    """Load the selected suite(s) and apply the -k filter."""
    paths = [Path(args.suite)] if args.suite else [REPO_ROOT / p for p in TIER_FILES]
    cases: list[dict] = []
    suites: list[str] = []
    for path in paths:
        resolved = path if path.is_absolute() else REPO_ROOT / path
        if not resolved.is_file():
            print(f"Error: benchmark suite not found: {resolved}", file=sys.stderr)
            raise SystemExit(EXIT_ARG)
        cases.extend(load_suite(resolved))
        suites.append(resolved.name)

    wanted = args_case_filter(args)
    missing = unmatched_ids(cases, wanted)
    if missing:
        print(
            f"Error: -k/--case matched no case: {', '.join(missing)}", file=sys.stderr
        )
        raise SystemExit(EXIT_ARG)
    return filter_cases(cases, wanted), suites


def args_case_filter(args: argparse.Namespace) -> tuple[str, ...]:
    return tuple(part.strip() for part in (args.case or "").split(",") if part.strip())


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


class GenerationFailed(Exception):
    """Generation produced nothing usable.

    Carries whatever text the model did return so the failure can be recorded
    as a static rejection and handed to the healing loop (FR-002) rather than
    terminating the suite.
    """

    def __init__(self, message: str, code: str = "", generation=None):
        self.code = code
        self.generation = generation
        super().__init__(message)


def read_inventory_safely(dataset_project: Path | str) -> MapInventory:
    """Read the dataset inventory, degrading to empty on any failure.

    FR-012a/FR-012b require the inventory to be an enhancement, never a
    dependency: a dataset that cannot be read must yield no block rather than
    abort the run. ``read_inventory`` already promises not to raise; this
    wrapper makes that guarantee structural.
    """
    try:
        return read_inventory(dataset_project)
    except Exception:  # noqa: BLE001 - grounding must never be fatal
        return MapInventory()


def generate_attempt(
    generator: GrassCodeGenerator,
    prompt: str,
    reuse_path: Path | None,
    inventory_block: str = "",
) -> tuple[str, int, int]:
    """Produce attempt-1 code, either freshly or from a persisted artifact.

    Reuse performs no inference, so token counts are 0 by construction and the
    report labels the run so those figures are never read as measured (FR-001a,
    SC-015).
    """
    if reuse_path and reuse_path.is_file():
        return reuse_path.read_text(encoding="utf-8"), 0, 0

    try:
        if inventory_block:
            code = generator.generate(prompt, inventory_block=inventory_block)
        else:
            code = generator.generate(prompt)
    except ValueError as exc:
        # Gate 1's validate_syntax raises rather than returning. An unparsable
        # generation is an ordinary model failure -- it must become a static
        # rejection with a retry turn, not kill the suite (FR-002).
        code = getattr(generator, "last_code", "") or ""
        raise GenerationFailed(str(exc), code) from exc

    # GrassCodeGenerator.generate() returns only the code, so the provider
    # recorded the counters as a side effect. Re-issuing the request to read
    # them would double inference cost for every single attempt.
    stats = getattr(generator.provider, "last_stats", None) or {}
    return code, int(stats.get("prompt_tokens", 0) or 0), int(stats.get("completion_tokens", 0) or 0)


def generate_attempt_result(
    generator: GrassCodeGenerator,
    prompt: str,
    reuse_path: Path | None,
    inventory_block: str = "",
    agentic_pipeline: AgenticPipeline | None = None,
    inventory_maps=None,
) -> PipelineGenerationResult:
    """Produce attempt-1 code plus Feature 004 pipeline diagnostics.

    Legacy behavior is exactly :func:`generate_attempt`; the richer result
    simply wraps its three values so existing callers stay unchanged.
    """
    if reuse_path and reuse_path.is_file():
        return PipelineGenerationResult(
            code=reuse_path.read_text(encoding="utf-8"),
            prompt_tokens=0,
            completion_tokens=0,
        )

    config = getattr(generator, "config", None)
    if getattr(config, "pipeline", "legacy") == "legacy" or not hasattr(
        generator, "generate_result"
    ):
        code, prompt_tokens, completion_tokens = generate_attempt(
            generator, prompt, None, inventory_block
        )
        return PipelineGenerationResult(
            code=code,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    try:
        return generator.generate_result(
            prompt,
            inventory_block=inventory_block,
            agentic_pipeline=agentic_pipeline,
            inventory_maps=inventory_maps,
        )
    except (ValueError, ManualBudgetExceeded) as exc:
        code = getattr(generator, "last_code", "") or ""
        partial = getattr(generator, "last_generation_result", None)
        if partial is None:
            cards = list(getattr(generator, "last_manual_cards", []) or [])
            partial = PipelineGenerationResult(
                code=code,
                manual_cards=cards,
                manual_tokens=sum(
                    int(getattr(card, "token_estimate", 0) or 0) for card in cards
                ),
            )
        partial.code = code
        raise GenerationFailed(str(exc), code, generation=partial) from exc


def model_slug(model: str) -> str:
    return model.replace(":", "_")


def reuse_artifact_path(config: ExecutionConfig, tc_id: str) -> Path | None:
    directory = Path(config.reuse_artifacts_dir)
    if not directory.is_absolute():
        directory = REPO_ROOT / directory
    if not directory.is_dir():
        return None
    preferred = directory / f"{tc_id}_{model_slug(config.model)}.py"
    if preferred.is_file():
        return preferred
    matches = sorted(directory.glob(f"{tc_id}_*.py"))
    return matches[0] if matches else None


# --------------------------------------------------------------------------
# Per-case execution
# --------------------------------------------------------------------------


def static_guard(
    code: str,
    retriever: GrassToolsRetriever,
    strict_options: bool | None = None,
    pipeline: str | None = None,
) -> list[str]:
    """Gate 1 barrier, re-run before every attempt (FR-001, FR-014, FR-015).

    A static rejection costs one unit of the unified budget and skips
    execution entirely (FR-002).
    """
    issues: list[str] = []
    try:
        validate_syntax(code)
    except ValueError as exc:
        return [str(exc)]
    issues.extend(
        validate_api(
            code,
            retriever,
            strict_options=strict_options,
            pipeline=pipeline,
        )
    )
    issues.extend(legacy_interface_issues(code))
    return issues


def run_case(
    case: dict,
    config: ExecutionConfig,
    generator: GrassCodeGenerator,
    healer: Healer,
    executor: Executor,
    fixtures_root: Path,
    output_root: Path,
    key: ResumeKey,
    inventory_block: str = "",
    semantic_spec: dict | None = None,
    agentic_pipeline: AgenticPipeline | None = None,
    inventory_maps=None,
) -> CaseResult:
    """Run one case to a terminal state under two independent repair tiers.

    The charge-on-generate rule (research R1) bounds candidates at
    `1 + static_limit + runtime_limit`: the initial candidate is free, and each
    generated repair consumes a unit of the tier that produced it. The loop
    terminates on `pass_at_executed`, never on the Gate 2 `executed_ok` verdict,
    so an exit-0 run that created no map still requests a runtime repair.
    """
    tc_id = case["id"]
    out_dir = case_dir(output_root, tc_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    static_limit = config.max_static_retries
    runtime_limit = config.max_runtime_retries
    result = CaseResult(
        tc_id=tc_id,
        tier=case.get("tier"),
        category=case.get("category", ""),
        prompt=case["prompt"],
        auxiliary_inputs=list(case.get("auxiliary_inputs", []) or []),
        resume_key=key,
        harness_version=config.harness,
    )
    result.budget_ledger = build_ledger([], static_limit, runtime_limit)
    result.semantic_declared = semantic_spec is not None

    reuse = reuse_artifact_path(config, tc_id) if config.attempt1_source == "reuse_artifacts" else None
    if config.attempt1_source == "reuse_artifacts" and reuse is None:
        print(f"    no Gate 1 artifact for {tc_id}; generating instead", file=sys.stderr)

    index = NoOpIndex()
    history: list[RepairTurn] = []
    next_tier = BUDGET_INITIAL
    pivot = False
    previous_code = ""
    previous_error = ""
    previous_failing_tool: str | None = None
    previous_failure_mode: str | None = None
    # Feature 004 repair-escalation state.
    tool_failure_counts: dict[str, int] = {}
    swap_used = False
    replanned = False
    last_plan = None
    last_planned_tools: list[str] = []
    last_plan_repair_count = 0
    last_planner_invocations = 0
    last_plan_fallback = False
    last_shortlist_shortfall = False
    last_shortlist: list[str] = []

    def used(tier: str) -> int:
        return sum(1 for a in result.attempts if a.budget_tier == tier)

    def remaining(tier: str) -> int:
        limit = static_limit if tier == BUDGET_STATIC else runtime_limit
        return limit - used(tier)

    max_candidates = 1 + static_limit + runtime_limit
    for ordinal in range(1, max_candidates + 1):
        if _INTERRUPTED:
            raise Interrupted()

        tier = BUDGET_INITIAL if ordinal == 1 else next_tier
        attempt = Attempt(ordinal=ordinal, budget_tier=tier)
        started = time.monotonic()

        # ---- produce code for this attempt
        generation_error: str | None = None
        pivot_used = False
        if ordinal == 1:
            try:
                generation = generate_attempt_result(
                    generator,
                    case["prompt"],
                    reuse,
                    inventory_block,
                    agentic_pipeline=agentic_pipeline,
                    inventory_maps=inventory_maps,
                )
            except GenerationFailed as exc:
                # The model returned nothing parseable. Record it as a static
                # rejection so the tier budget still governs it (FR-002).
                generation = exc.generation or PipelineGenerationResult(code=exc.code)
                generation.code = exc.code
                generation_error = str(exc)
        else:
            desired_swap = None
            swap_candidates: list[str] = []
            failure_tool = previous_failing_tool
            if config.pipeline != "legacy" and failure_tool:
                count = tool_failure_counts.get(failure_tool, 0)
                if count == 1:
                    pivot = True
                elif count >= 2:
                    candidates = healer.tool_swap_candidates(failure_tool)
                    if candidates and not swap_used:
                        swap_candidates = candidates
                        desired_swap = f"{failure_tool} -> {candidates[0]}"
                        swap_used = True
                    else:
                        pivot = True
                tool_failure_counts[failure_tool] = count + 1

            # One constrained post-failure re-plan, distinct from the
            # pre-execution plan repair.
            if (
                config.pipeline == "planned"
                and agentic_pipeline is not None
                and not replanned
                and last_plan is not None
                and desired_swap is None
                and previous_error
                and (swap_used or pivot)
            ):
                shortlist = getattr(agentic_pipeline, "last_shortlist", [])
                if shortlist:
                    outcome = agentic_pipeline.planner.replan(
                        case["prompt"],
                        inventory_block,
                        shortlist,
                        last_plan,
                        previous_error,
                        inventory_maps=inventory_maps,
                    )
                    replanned = True
                    if outcome.valid and not outcome.fallback:
                        try:
                            generation = agentic_pipeline.synthesize_plan(
                                case["prompt"],
                                inventory_block,
                                shortlist,
                                outcome,
                                inventory_maps=inventory_maps,
                            )
                        except ManualBudgetExceeded as exc:
                            generation = PipelineGenerationResult(code="")
                            generation_error = str(exc)
                        pivot_used = False
                    else:
                        generation = None
                else:
                    generation = None
            else:
                generation = None

            if generation is None:
                context = healer.build_context(
                    original_prompt=case["prompt"],
                    previous_code=previous_code,
                    error_text=previous_error,
                    failing_tool=previous_failing_tool,
                    failure_mode=previous_failure_mode,
                    history=history,
                    pivot=pivot,
                    plan=last_plan,
                    planned_tools=last_planned_tools,
                    tool_swap_candidates=swap_candidates,
                    tool_swap=desired_swap,
                )
                repair = healer.repair(context, pivot=pivot)
                generation = PipelineGenerationResult(
                    code=repair.code,
                    prompt_tokens=repair.prompt_tokens,
                    completion_tokens=repair.completion_tokens,
                    plan=last_plan,
                    plan_repair_count=last_plan_repair_count,
                    replan_count=1 if replanned else 0,
                    planner_invocations=last_planner_invocations,
                    plan_fallback=last_plan_fallback,
                    shortlist_shortfall=last_shortlist_shortfall,
                    shortlist=list(last_shortlist),
                    planned_tools=list(last_planned_tools),
                )
                pivot_used = repair.pivot_used

        code = generation.code
        prompt_tokens = generation.prompt_tokens
        completion_tokens = generation.completion_tokens
        last_plan = generation.plan or last_plan
        last_planned_tools = (
            list(generation.plan.tools)
            if generation.plan is not None
            else last_planned_tools
        )
        last_plan_repair_count = int(generation.plan_repair_count or 0)
        last_planner_invocations = int(generation.planner_invocations or 0)
        last_plan_fallback = bool(generation.plan_fallback)
        last_shortlist_shortfall = bool(generation.shortlist_shortfall)
        last_shortlist = list(generation.shortlist or last_shortlist)
        if config.pipeline == "planned" and generation.shortlist:
            print(
                "    shortlist: "
                + ", ".join(list(generation.shortlist)[:12])
                + (" (shortfall)" if generation.shortlist_shortfall else "")
            )
            if generation.plan is not None:
                print(
                    f"    plan: {len(generation.plan.steps)} steps "
                    f"(revision {generation.plan.revision})"
                )
            if generation.plan_fallback:
                print("    plan: fallback to manual-kb (no tier charged)")
        if generation.manual_cards:
            summary_cards = ", ".join(
                f"{card.tool} ({card.token_estimate} tok)"
                for card in generation.manual_cards[:8]
                if hasattr(card, "tool")
            )
            if summary_cards:
                print(f"    cards: {summary_cards}")

        script_path = out_dir / f"attempt_{ordinal}.py"
        write_script(script_path, code)
        attempt.script_path = script_path.name
        attempt.prompt_tokens = prompt_tokens
        attempt.completion_tokens = completion_tokens
        attempt.pivot_used = pivot_used
        attempt.code_sha256 = byte_digest(code)
        attempt.ast_sha256 = ast_digest(code)
        _apply_generation_metadata(attempt, generation, config)
        _save_generation_artifacts(output_root, tc_id, ordinal, generation, config)

        # ---- deterministic no-op detection before anything executes
        match = index.match(code)
        index.add(code, ordinal)
        if match is not None:
            attempt.stage = "static"
            attempt.outcome = OUTCOME_NO_OP_DUPLICATE
            attempt.duplicate = True
            attempt.static_passed = False
            attempt.failure_mode = FailureMode.GENERAL_EXCEPTION.value
            attempt.failing_tool = previous_failing_tool
            digest = match.ast_sha256 or match.code_sha256
            attempt.error_excerpt = (
                f"duplicate of attempt {match.ordinal} "
                f"(AST digest {digest[:8]})"
            )
            attempt.exit_code = None
            attempt.timed_out = False
            attempt.new_maps = {"raster": [], "vector": []}
            attempt.latency_s = time.monotonic() - started
            _write_duplicate_artifacts(out_dir, ordinal, attempt)
            result.attempts.append(attempt)
            result.recompute_verdicts()
            result.budget_ledger = build_ledger(
                result.attempts, static_limit, runtime_limit
            )
            save(output_root, result)
            print(
                f"    attempt {ordinal}  tier={tier}  static: DUPLICATE  "
                f"matches attempt {match.ordinal}"
            )
            history.append(
                RepairTurn(
                    ordinal=ordinal,
                    budget_tier=tier,
                    code=code,
                    failure_mode=attempt.failure_mode,
                    error_excerpt=attempt.error_excerpt,
                    stage="static",
                    duplicate=True,
                )
            )
            previous_code = code
            previous_error = attempt.error_excerpt
            previous_failing_tool = attempt.failing_tool
            previous_failure_mode = attempt.failure_mode
            # A duplicate requests the parameter pivot in the same tier.
            next_tier = tier
            pivot = True
            if remaining(next_tier) <= 0:
                break
            continue

        # ---- Gate 1 barrier
        issues = [generation_error] if generation_error else static_guard(
            code,
            generator.retriever,
            strict_options=config.effective_strict_options(),
            pipeline=config.pipeline,
        )
        attempt.static_issues = issues
        attempt.static_passed = not issues
        pivot = False

        if issues:
            attempt.stage = "static"
            attempt.outcome = OUTCOME_STATIC_REJECTED
            attempt.failure_mode = FailureMode.SCHEMA_MISUSE.value
            attempt.failing_tool = None
            attempt.error_excerpt = issues[0]
            attempt.latency_s = time.monotonic() - started
            result.attempts.append(attempt)
            result.recompute_verdicts()
            result.budget_ledger = build_ledger(
                result.attempts, static_limit, runtime_limit
            )
            save(output_root, result)
            print(f"    attempt {ordinal}  tier={tier}  static: FAIL  "
                  f"{FailureMode.SCHEMA_MISUSE.value}  {attempt.latency_s:.1f}s")
            history.append(
                RepairTurn(
                    ordinal=ordinal,
                    budget_tier=tier,
                    code=code,
                    failure_mode=attempt.failure_mode,
                    error_excerpt=attempt.error_excerpt,
                    stage="static",
                    duplicate=False,
                )
            )
            previous_code = code
            previous_error = issues[0]
            previous_failing_tool = None
            previous_failure_mode = FailureMode.SCHEMA_MISUSE.value
                    # A runtime-tier candidate that fails static stays runtime; a
            # static candidate requests another static repair.
            next_tier = BUDGET_RUNTIME if tier == BUDGET_RUNTIME else BUDGET_STATIC
            if remaining(next_tier) <= 0:
                break
            continue

        # ---- execute
        workdir = out_dir / f"work_{ordinal}"
        workdir.mkdir(parents=True, exist_ok=True)
        if result.auxiliary_inputs:
            try:
                stage_fixtures(fixtures_root, workdir, result.auxiliary_inputs)
            except FixtureError as exc:
                print(f"    fixture staging failed for {tc_id}: {exc}", file=sys.stderr)

        execution = executor.execute(
            script_path,
            workdir,
            semantic_spec=semantic_spec,
            case_id=tc_id,
        )
        attempt.stage = execution.outcome.stage
        attempt.outcome = execution.outcome.value
        attempt.exit_code = execution.exit_code
        attempt.signal_name = execution.signal_name
        attempt.timed_out = execution.timed_out
        attempt.failure_mode = (
            execution.failure_mode.value if execution.failure_mode else None
        )
        attempt.failing_tool = execution.failing_tool
        attempt.error_excerpt = execution.error_excerpt or None
        attempt.new_maps = {
            "raster": sorted((execution.new_maps or {}).get("raster") or []),
            "vector": sorted((execution.new_maps or {}).get("vector") or []),
        }
        attempt.latency_s = time.monotonic() - started
        pivot = False

        (out_dir / f"attempt_{ordinal}.stdout").write_text(
            execution.stdout, encoding="utf-8"
        )
        (out_dir / f"attempt_{ordinal}.stderr").write_text(
            execution.stderr, encoding="utf-8"
        )
        (out_dir / f"attempt_{ordinal}.log").write_text(
            f"# outcome: {attempt.outcome}\n"
            f"# exit_code: {attempt.exit_code}\n"
            f"# signal: {attempt.signal_name}\n"
            f"# failure_mode: {attempt.failure_mode}\n"
            f"# failing_tool: {attempt.failing_tool}\n\n"
            f"--- stdout ---\n{execution.stdout}\n--- stderr ---\n{execution.stderr}\n",
            encoding="utf-8",
        )
        attempt.stdout_path = f"attempt_{ordinal}.stdout"
        attempt.stderr_path = f"attempt_{ordinal}.stderr"
        attempt.log_path = f"attempt_{ordinal}.log"

        shutil.rmtree(workdir, ignore_errors=True)

        # ---- semantic evidence only after a real execution success. An exit 0
        # with no new map is a repairable runtime failure, not a semantic
        # verdict (FR-001b, FR-009a).
        executed_with_maps = execution.succeeded and attempt.has_new_maps
        semantic = execution.semantic
        if executed_with_maps and semantic_spec is not None and semantic is not None:
            attempt.semantic_evaluated = bool(semantic.evaluated)
            attempt.semantic_passed = (
                semantic.passed if semantic.evaluated else False
            )
            attempt.assertion_results = list(semantic.assertion_results)

        result.attempts.append(attempt)
        result.recompute_verdicts()
        result.budget_ledger = build_ledger(
            result.attempts, static_limit, runtime_limit
        )

        history.append(
            RepairTurn(
                ordinal=ordinal,
                budget_tier=tier,
                code=code,
                failure_mode=attempt.failure_mode,
                error_excerpt=attempt.error_excerpt or "",
                stage=attempt.stage,
                duplicate=False,
            )
        )
        previous_code = code

        print(
            f"    attempt {ordinal}  tier={tier}  execute: "
            f"{'OK' if execution.succeeded else 'FAIL'}  "
            f"{attempt.failure_mode or '—'}  new_maps={len(attempt.new_maps['raster']) + len(attempt.new_maps['vector'])}  "
            f"{attempt.latency_s:.1f}s  {prompt_tokens}+{completion_tokens} tok"
        )
        if attempt.semantic_evaluated:
            print(
                f"    attempt {ordinal}  semantic: "
                f"{'PASS' if attempt.semantic_passed else 'FAIL'} "
                f"({len(attempt.assertion_results)} assertions)"
            )

        if executed_with_maps:
            # Success (and, when a spec was supplied, the terminal semantic
            # verdict). A semantic failure never generates a repair.
            break

        if execution.succeeded:
            # exit 0 with no new map: repairable runtime failure
            previous_error = (
                "the script exited 0 but created no new map in the scratch mapset"
            )
            previous_failing_tool = None
            previous_failure_mode = None
        else:
            previous_error = execution.error_excerpt or execution.stderr[-400:]
            previous_failing_tool = execution.failing_tool
            previous_failure_mode = attempt.failure_mode
        next_tier = BUDGET_RUNTIME
        if remaining(next_tier) <= 0:
            save(output_root, result)
            break
        save(output_root, result)

    result.recompute_verdicts()
    result.budget_ledger = build_ledger(result.attempts, static_limit, runtime_limit)
    final_source = next(
        (
            a
            for a in reversed(result.attempts)
            if a.succeeded and a.has_new_maps
        ),
        None,
    ) or next((a for a in reversed(result.attempts) if a.succeeded), None) or result.attempts[0]
    if final_source is not None:
        source = out_dir / final_source.script_path
        if source.is_file():
            (out_dir / "final.py").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            result.final_script = "final.py"

    return mark_complete(output_root, result)


def _apply_generation_metadata(
    attempt: Attempt, generation: PipelineGenerationResult, config: ExecutionConfig
) -> None:
    """Copy pipeline diagnostics onto the persisted attempt."""
    attempt.pipeline = config.pipeline
    attempt.num_ctx = config.num_ctx
    attempt.manual_context_tokens = config.resolve_manual_budget()
    plan = generation.plan
    attempt.plan_revision = int(getattr(plan, "revision", 0) or 0) if plan is not None else 0
    attempt.plan_repair_count = int(generation.plan_repair_count or 0)
    attempt.replan_count = int(generation.replan_count or 0)
    attempt.planner_invocations = int(generation.planner_invocations or 0)
    attempt.shortlist_shortfall = bool(generation.shortlist_shortfall)
    attempt.planned_tools = list(getattr(plan, "tools", []) or [])
    attempt.tool_swaps = list(generation.tool_swaps or [])
    attempt.plan_fallback = bool(generation.plan_fallback)
    attempt.manual_card_tokens = int(generation.manual_tokens or 0)
    attempt.manual_omissions = list(generation.manual_omissions or [])
    attempt.planner_prompt_tokens = int(generation.planner_prompt_tokens or 0)
    attempt.planner_completion_tokens = int(
        generation.planner_completion_tokens or 0
    )


def _save_generation_artifacts(
    output_root: Path,
    tc_id: str,
    ordinal: int,
    generation: PipelineGenerationResult,
    config: ExecutionConfig,
) -> None:
    """Write additive plan/manual evidence beside the attempt artifacts."""
    if config.pipeline == "planned":
        plan = generation.plan
        payload = {
            "pipeline": "planned",
            "revision": int(getattr(plan, "revision", 0) or 0) if plan is not None else 0,
            "fallback": bool(generation.plan_fallback),
            "shortlist": list(generation.shortlist or []),
            "shortlist_shortfall": bool(generation.shortlist_shortfall),
            "plan_repair_count": int(generation.plan_repair_count or 0),
            "replan_count": int(generation.replan_count or 0),
            "planner_invocations": int(generation.planner_invocations or 0),
            "plan": plan.to_dict() if hasattr(plan, "to_dict") else None,
            "validation": generation.plan_validation or {"ok": plan is not None, "errors": []},
            "planner_prompt_tokens": int(generation.planner_prompt_tokens or 0),
            "planner_completion_tokens": int(
                generation.planner_completion_tokens or 0
            ),
        }
        save_plan_artifact(output_root, tc_id, ordinal, payload)
    if generation.manual_cards:
        cards = []
        for card in generation.manual_cards:
            if hasattr(card, "to_dict"):
                cards.append(card.to_dict())
            elif isinstance(card, dict):
                cards.append(card)
        save_manuals_artifact(
            output_root,
            tc_id,
            ordinal,
            {
                "tool": None,
                "tokens": int(generation.manual_tokens or 0),
                "omissions": list(generation.manual_omissions or []),
                "cards": cards,
            },
        )


def _write_duplicate_artifacts(out_dir: Path, ordinal: int, attempt: Attempt) -> None:
    """R10 requires the full artifact set even for a rejected duplicate."""
    for suffix in ("stdout", "stderr", "log"):
        (out_dir / f"attempt_{ordinal}.{suffix}").write_text("", encoding="utf-8")
    attempt.stdout_path = f"attempt_{ordinal}.stdout"
    attempt.stderr_path = f"attempt_{ordinal}.stderr"
    attempt.log_path = f"attempt_{ordinal}.log"


# --------------------------------------------------------------------------
# Report-only mode
# --------------------------------------------------------------------------


def rebuild_report(config: ExecutionConfig, key: ResumeKey) -> int:
    """Regenerate the Gate 2 report from persisted results only (SC-013)."""
    output_root = Path(config.output_dir)
    if not output_root.is_absolute():
        output_root = REPO_ROOT / output_root
    results = []
    for case_dir_path in sorted(output_root.iterdir() if output_root.is_dir() else []):
        loaded = load(output_root, case_dir_path.name)
        if loaded is not None and loaded.status == "complete":
            results.append(loaded)
    if not results:
        print("No completed case results found; nothing to report.", file=sys.stderr)
        return EXIT_ARG

    meta = load_run_meta(output_root)
    summary = aggregate(
        results,
        model=meta.get("model", config.model),
        suites=meta.get("suites", ["(regenerated)"]),
        max_retries=meta.get("max_retries", config.max_retries),
        timeout_s=meta.get("timeout_s", config.timeout_s),
        attempt1_source=meta.get("attempt1_source", config.attempt1_source),
        resume_key=key,
        cases_total=meta.get("cases_total", len(results)),
        not_evaluated=meta.get("not_evaluated", []),
        resumed=meta.get("resumed", False),
        # Restored rather than recomputed: the hash pair is evidence of what
        # happened during the original run and cannot be re-derived afterwards.
        permanent_hash_before=meta.get("permanent_hash_before", ""),
        permanent_hash_after=meta.get("permanent_hash_after", ""),
        leaked_scratch_dirs=meta.get("leaked_scratch_dirs", []),
        pipeline=meta.get("pipeline", config.pipeline),
        num_ctx=meta.get("num_ctx", config.num_ctx),
        manual_context_tokens=meta.get(
            "manual_context_tokens", config.resolve_manual_budget()
        ),
        manual_cards_rendered=meta.get("manual_cards_rendered", 0),
        manual_budget_failures=meta.get("manual_budget_failures", 0),
        context_overflow_events=meta.get("context_overflow_events", 0),
        plan_attempts=meta.get("plan_attempts", 0),
        plan_repairs=meta.get("plan_repairs", 0),
        plan_fallbacks=meta.get("plan_fallbacks", 0),
        replans=meta.get("replans", 0),
        shortlist_shortfalls=meta.get("shortlist_shortfalls", 0),
        tool_swaps=meta.get("tool_swaps", 0),
        pipeline_ablation=meta.get("pipeline_ablation", []),
    )
    report_path = Path(config.report_path)
    if not report_path.is_absolute():
        report_path = REPO_ROOT / report_path
    write_report(report_path, summary, results)
    print(f"Report regenerated from {len(results)} case results: {report_path}")
    return 0


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


def execute_suite(
    cases: list[dict],
    suites: list[str],
    config: ExecutionConfig,
    key: ResumeKey,
    report_path: Path,
    renderer=write_report,
    args: argparse.Namespace | None = None,
    extra_meta: dict | None = None,
    preflight_report=None,
) -> int:
    """Run a selected suite to completion and render its report.

    Shared by the Gate 2 and Gate 3 entry points so there is exactly one
    execution loop. The only differences are the resolved `config` (harness
    identity, semantic mode, tier budgets) and the report renderer.
    """
    verbose = bool(getattr(args, "verbose", False))
    clean = bool(getattr(args, "clean", False))
    global _INTERRUPTED
    _INTERRUPTED = False

    output_root = Path(config.output_dir)
    if not output_root.is_absolute():
        output_root = REPO_ROOT / output_root

    if clean and output_root.exists():
        shutil.rmtree(output_root)
        print(f"--clean: wiped {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    discarded = discard_partials(output_root)
    if discarded:
        print(f"Discarded {discarded} partial result file(s) from a prior run.")

    # ---- pre-flight
    report = preflight_report
    if report is None:
        report = run_preflight(
            config,
            required_fixtures=required_fixtures(cases),
            need_reuse_artifacts=config.attempt1_source == "reuse_artifacts",
            pipeline=config.pipeline,
        )
    if not report.ok:
        for failure in report.failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY
    if not report.tmp_mapset_supported:
        print(
            "WARNING: this GRASS build does not expose --tmp-mapset; "
            "falling back to the grass.script.setup.init() worker.",
            file=sys.stderr,
        )
    print(
        f"Pre-flight OK. GRASS={grass_config('path', config.grass_bin)} "
        f"dataset={report.dataset_project} cases={len(cases)} "
        f"model={config.model} static={config.max_static_retries} "
        f"runtime={config.max_runtime_retries} timeout={config.timeout_s}s"
    )

    dataset_project = report.dataset_project
    if dataset_project is None:
        print("Error: dataset could not be resolved", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY

    executor = Executor(
        dataset_project=dataset_project,
        python_bin=config.python_bin,
        grass_bin=config.grass_bin,
        timeout_s=config.timeout_s,
        semantic_probe_grace_s=config.semantic_probe_grace_s,
    )
    permanent_before = executor.permanent_hash(dataset_project)
    tmp_before = {p.name for p in Path(dataset_project).glob("tmp_*")}

    fixtures_root = Path(config.fixtures_dir)
    if not fixtures_root.is_absolute():
        fixtures_root = REPO_ROOT / fixtures_root

    # One inventory read per run, shared by the initial prompt (FR-012b) and
    # every repair prompt (FR-012a).
    inventory = read_inventory_safely(dataset_project)
    inventory_block = inventory.format_block()
    if inventory_block:
        print(
            f"Inventory grounding: {len(inventory.rasters)} raster(s), "
            f"{len(inventory.vectors)} vector(s)"
        )
    else:
        print("Inventory grounding unavailable; prompts will omit map names.", file=sys.stderr)

    # Semantic expectations are needed only when probing is enabled. A suite
    # without declared assertions simply produces no semantic spec per case.
    expectations = None
    if config.semantic_enabled:
        expectations_path = Path(config.pilot_expectations)
        if not expectations_path.is_absolute():
            expectations_path = REPO_ROOT / expectations_path
        if expectations_path.is_file():
            try:
                expectations = load_expectations(expectations_path)
            except (OSError, ValueError, KeyError) as exc:
                print(
                    f"Error: could not read pilot expectations {expectations_path}: {exc}",
                    file=sys.stderr,
                )
                return EXIT_MISSING_DEPENDENCY
        else:
            print(
                f"WARNING: semantic mode is on but {expectations_path} is missing; "
                "cases with mean/value_range assertions cannot be evaluated.",
                file=sys.stderr,
            )

    # ---- shared generation stack
    gen_config = GenerationConfig()
    gen_config.model = config.model
    gen_config.ollama_base_url = config.ollama_base_url
    gen_config.rag_db_path = config.knowledge_db
    gen_config.pipeline = config.pipeline
    gen_config.num_ctx = config.num_ctx
    gen_config.manual_context_tokens = config.resolve_manual_budget()
    gen_config.strict_options = config.effective_strict_options()
    gen_config.shortlist_k = config.shortlist_k
    gen_config.planner_model = config.resolved_planner_model()
    gen_config.planner_timeout = config.planner_timeout
    provider = OllamaProvider(
        gen_config, default_options={"num_predict": DEFAULT_NUM_PREDICT}
    )
    retriever = GrassToolsRetriever(gen_config.rag_db_path)
    generator = GrassCodeGenerator(gen_config, provider, retriever)
    healer = Healer(
        gen_config,
        provider,
        retriever,
        top_k=gen_config.rag_top_k,
        inventory_provider=lambda: inventory,
        pipeline=config.pipeline,
        manual_budget=config.resolve_manual_budget(),
    )
    agentic = None
    if config.pipeline == "planned":
        planner = Planner(
            provider,
            model=config.resolved_planner_model(),
            timeout=config.planner_timeout,
            retriever=retriever,
        )
        agentic = AgenticPipeline(
            gen_config, provider, retriever, generator=generator, planner=planner
        )
    inventory_maps = set(inventory.rasters) | set(inventory.vectors)

    results = []
    reused_any = False
    not_evaluated: list[str] = []
    reasons: list[str] = []
    started_at = time.time()

    _install_sigint_handler()

    try:
        for case in cases:
            tc_id = case["id"]
            print(
                f"\n--- [{tc_id}] {case.get('category', '?')} "
                f"(pipeline={config.pipeline}): "
                f"\"{case['prompt'][:80]}\"",
                flush=True,
            )

            if config.resume:
                reused = is_reusable(
                    output_root,
                    tc_id,
                    key,
                    config.max_retries,
                    reasons,
                    max_static_retries=config.max_static_retries,
                    max_runtime_retries=config.max_runtime_retries,
                )
                if reused is not None:
                    results.append(reused)
                    reused_any = True
                    verdict = (
                        "PASS@EXECUTED" if reused.pass_at_executed else "UNEXECUTED"
                    )
                    print(
                        f"    resuming: {verdict} "
                        f"({len(reused.attempts)} attempt(s) already recorded)"
                    )
                    continue
                if reasons and reasons[-1].startswith(f"{tc_id}:"):
                    if verbose:
                        print(f"    not resuming — {reasons[-1]}")
                    reasons.pop()

            if _INTERRUPTED:
                raise Interrupted()

            semantic_spec = None
            if config.semantic_enabled and case.get("assertions"):
                try:
                    semantic_spec = build_semantic_spec(
                        case,
                        expectations,
                        query_timeout_s=config.semantic_query_timeout_s,
                        probe_timeout_s=config.semantic_probe_timeout_s,
                    )
                except (KeyError, ValueError, TypeError) as exc:
                    print(
                        f"Error: invalid semantic declaration for {tc_id}: {exc}",
                        file=sys.stderr,
                    )
                    return EXIT_MISSING_DEPENDENCY

            result = run_case(
                case,
                config,
                generator,
                healer,
                executor,
                fixtures_root,
                output_root,
                key,
                inventory_block=inventory_block,
                semantic_spec=semantic_spec,
                agentic_pipeline=agentic,
                inventory_maps=inventory_maps,
            )
            results.append(result)
            if result.pass_at_executed and result.pass_at_semantic is True:
                print(
                    f"    => PASS@EXECUTED  PASS@SEMANTIC "
                    f"({len(result.attempts)} attempt(s))"
                )
            elif result.pass_at_executed and result.pass_at_semantic is False:
                print(
                    "    => PASS@EXECUTED  FAIL@SEMANTIC "
                    "(no repair: semantic is report-only)"
                )
            elif result.pass_at_executed:
                print(f"    => PASS@EXECUTED ({len(result.attempts)} attempt(s))")
            elif result.pass_at_healed:
                print("    => PASS@HEALED (Gate 2 execution verdict; no new map)")
            elif result.pass_at_1:
                print("    => PASS@1 (succeeded without healing)")
            else:
                modes = " -> ".join(
                    m for m in result.failure_mode_transitions if m
                ) or "n/a"
                print(f"    => UNHEALED ({modes})")

    except Interrupted:
        print("\nInterrupted. Cleaning up scratch state...", file=sys.stderr)
        leaked = executor.sweep(tmp_before, started_at)
        permanent_after = executor.permanent_hash(dataset_project)
        summary = aggregate(
            results,
            model=config.model,
            suites=suites,
            max_retries=config.max_retries,
            timeout_s=config.timeout_s,
            attempt1_source=config.attempt1_source,
            resume_key=key,
            cases_total=len(cases),
            not_evaluated=[
                c["id"] for c in cases if c["id"] not in {r.tc_id for r in results}
            ],
            resumed=reused_any,
            permanent_hash_before=permanent_before,
            permanent_hash_after=permanent_after,
            leaked_scratch_dirs=leaked,
            max_static_retries=config.max_static_retries,
            max_runtime_retries=config.max_runtime_retries,
            grass_version=(extra_meta or {}).get("grass_version", ""),
            dataset=(extra_meta or {}).get("dataset", ""),
            pilot_suite_hash=(extra_meta or {}).get("pilot_suite_hash", ""),
            pilot_expectations_hash=(extra_meta or {}).get(
                "pilot_expectations_hash", ""
            ),
            pilot_reviewed=(extra_meta or {}).get("pilot_reviewed"),
            pipeline=config.pipeline,
            num_ctx=config.num_ctx,
            manual_context_tokens=config.resolve_manual_budget(),
        )
        renderer(report_path, summary, results)
        print("Partial report written.", file=sys.stderr)
        return 1

    permanent_after = executor.permanent_hash(dataset_project)
    leaked = executor.sweep(tmp_before, started_at)

    summary = aggregate(
        results,
        model=config.model,
        suites=suites,
        max_retries=config.max_retries,
        timeout_s=config.timeout_s,
        attempt1_source=config.attempt1_source,
        resume_key=key,
        cases_total=len(cases),
        not_evaluated=not_evaluated,
        resumed=reused_any,
        permanent_hash_before=permanent_before,
        permanent_hash_after=permanent_after,
        max_static_retries=config.max_static_retries,
        max_runtime_retries=config.max_runtime_retries,
        grass_version=(extra_meta or {}).get("grass_version", ""),
        dataset=(extra_meta or {}).get("dataset", ""),
        pilot_suite_hash=(extra_meta or {}).get("pilot_suite_hash", ""),
        pilot_expectations_hash=(extra_meta or {}).get(
            "pilot_expectations_hash", ""
        ),
        pilot_reviewed=(extra_meta or {}).get("pilot_reviewed"),
        leaked_scratch_dirs=leaked,
        pipeline=config.pipeline,
        num_ctx=config.num_ctx,
        manual_context_tokens=config.resolve_manual_budget(),
    )

    save_run_meta(
        output_root,
        {
            "harness": config.harness,
            "model": config.model,
            "suites": suites,
            "max_retries": config.max_retries,
            "max_static_retries": config.max_static_retries,
            "max_runtime_retries": config.max_runtime_retries,
            "timeout_s": config.timeout_s,
            "attempt1_source": config.attempt1_source,
            "cases_total": len(cases),
            "cases_completed": summary.cases_completed,
            "cases_semantic": summary.cases_semantic,
            "pipeline": config.pipeline,
            "num_ctx": config.num_ctx,
            "manual_context_tokens": config.resolve_manual_budget(),
            "manual_cards_rendered": summary.manual_cards_rendered,
            "manual_budget_failures": summary.manual_budget_failures,
            "context_overflow_events": summary.context_overflow_events,
            "plan_attempts": summary.plan_attempts,
            "plan_repairs": summary.plan_repairs,
            "plan_fallbacks": summary.plan_fallbacks,
            "replans": summary.replans,
            "shortlist_shortfalls": summary.shortlist_shortfalls,
            "tool_swaps": summary.tool_swaps,
            "not_evaluated": not_evaluated,
            "resumed": reused_any,
            "permanent_hash_before": permanent_before,
            "permanent_hash_after": permanent_after,
            "leaked_scratch_dirs": summary.leaked_scratch_dirs,
            **(extra_meta or {}),
        },
    )
    renderer(report_path, summary, results)
    retriever.close()

    elapsed = time.time() - started_at
    print(f"\n=== {config.harness} run complete in {elapsed / 60:.1f} min ===")
    print(f"Pass@Executed {summary.pass_at_executed}/{summary.cases_completed} "
          f"({summary.pass_at_executed_rate * 100:.1f}%)")
    if summary.cases_semantic:
        print(f"Pass@Semantic {summary.pass_at_semantic}/{summary.cases_semantic} "
              f"({summary.pass_at_semantic_rate * 100:.1f}%)")
    print(f"Pass@1      {summary.pass_at_1}/{summary.cases_completed} "
          f"({summary.pass_at_1_rate * 100:.1f}%)")
    print(f"Pass@Healed {summary.pass_at_healed}/{summary.cases_completed} "
          f"({summary.pass_at_healed_rate * 100:.1f}%)")
    print(f"PERMANENT unchanged: {summary.permanent_unchanged}")
    print(f"Report: {report_path}")
    return 0


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.max_retries is not None and args.max_retries < 0:
        print("Error: --max-retries must be >= 0", file=sys.stderr)
        return EXIT_ARG
    for flag, value in (
        ("--max-static-retries", getattr(args, "max_static_retries", None)),
        ("--max-runtime-retries", getattr(args, "max_runtime_retries", None)),
    ):
        if value is not None and value < 0:
            print(f"Error: {flag} must be >= 0", file=sys.stderr)
            return EXIT_ARG
    if args.timeout is not None and args.timeout <= 0:
        print("Error: --timeout must be > 0", file=sys.stderr)
        return EXIT_ARG

    config = resolve_config(args)
    if getattr(args, "strict_options", None) and config.pipeline != "legacy":
        print(
            "Error: --strict-options is a legacy-only opt-in and cannot be "
            f"combined with --pipeline {config.pipeline}",
            file=sys.stderr,
        )
        return EXIT_ARG
    errors = config.config_errors()
    if errors:
        for error in errors:
            print(f"Error: {error}", file=sys.stderr)
        return EXIT_ARG
    for warning in config.config_warnings():
        print(f"WARNING: {warning}", file=sys.stderr)

    key = ResumeKey(
        model=config.model,
        max_retries=config.max_retries,
        timeout=config.timeout_s,
        attempt1_source=config.attempt1_source,
        max_static_retries=config.max_static_retries,
        max_runtime_retries=config.max_runtime_retries,
        harness=config.harness,
        pipeline=config.pipeline,
        num_ctx=config.num_ctx,
        manual_context_tokens=config.resolve_manual_budget(),
    )

    if args.report_only:
        return rebuild_report(config, key)

    try:
        cases, suites = load_selected_cases(args)
    except SystemExit as exc:
        return int(exc.code or EXIT_ARG)

    return execute_suite(
        cases,
        suites,
        config,
        key,
        REPO_ROOT / config.report_path,
        write_report,
        args,
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
