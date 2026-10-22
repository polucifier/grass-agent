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

from code_generator import GrassCodeGenerator, validate_api, validate_syntax  # noqa: E402
from config import GenerationConfig  # noqa: E402
from grass_agent.classifier import FailureMode  # noqa: E402
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
from grass_agent.healing import Healer, legacy_interface_issues, write_script  # noqa: E402
from grass_agent.inventory import MapInventory, read_inventory  # noqa: E402
from grass_agent.preflight import (  # noqa: E402
    EXIT_ARG,
    EXIT_FAULT,
    EXIT_MISSING_DEPENDENCY,
    run_preflight,
)
from grass_agent.reporting import aggregate, write_report  # noqa: E402
from grass_agent.results import (  # noqa: E402
    OUTCOME_STATIC_REJECTED,
    Attempt,
    CaseResult,
    ResumeKey,
    case_dir,
    discard_partials,
    is_reusable,
    load,
    load_run_meta,
    mark_complete,
    save,
    save_run_meta,
)
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
    parser.add_argument("--timeout", type=int, default=None, help="Per-attempt wall-clock bound in seconds (default 120)")
    parser.add_argument("--resume", dest="resume", action="store_true", default=None, help="Skip completed cases (default)")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Rerun every case, reusing nothing")
    parser.add_argument("--clean", action="store_true", help="Wipe output_execution/ and run from scratch")
    parser.add_argument("--reuse-artifacts", action="store_true", help="Load Gate 1 scripts as attempt 1")
    parser.add_argument("--report-only", action="store_true", help="Re-render the report from persisted results")
    parser.add_argument("--verbose", action="store_true", help="Explain every resume rejection")
    return parser


def resolve_config(args: argparse.Namespace) -> ExecutionConfig:
    """Merge CLI arguments over environment variables over defaults."""
    case_filter = tuple(
        part.strip() for part in (args.case or "").split(",") if part.strip()
    )
    return ExecutionConfig.from_env(
        model=args.model,
        max_retries=args.max_retries,
        timeout_s=args.timeout,
        dataset_project=args.dataset,
        resume=args.resume,
        attempt1_source="reuse_artifacts" if args.reuse_artifacts else None,
        case_filter=case_filter,
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

    def __init__(self, message: str, code: str = ""):
        self.code = code
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


def static_guard(code: str, retriever: GrassToolsRetriever) -> list[str]:
    """Gate 1 barrier, re-run before every attempt (FR-001, FR-014, FR-015).

    A static rejection costs one unit of the unified budget and skips
    execution entirely (FR-002).
    """
    issues: list[str] = []
    try:
        validate_syntax(code)
    except ValueError as exc:
        return [str(exc)]
    issues.extend(validate_api(code, retriever))
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
) -> CaseResult:
    """Run one case to a terminal state under the unified budget."""
    tc_id = case["id"]
    out_dir = case_dir(output_root, tc_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = CaseResult(
        tc_id=tc_id,
        tier=case.get("tier"),
        category=case.get("category", ""),
        prompt=case["prompt"],
        auxiliary_inputs=list(case.get("auxiliary_inputs", []) or []),
        resume_key=key,
    )

    reuse = reuse_artifact_path(config, tc_id) if config.attempt1_source == "reuse_artifacts" else None
    if config.attempt1_source == "reuse_artifacts" and reuse is None:
        print(f"    no Gate 1 artifact for {tc_id}; generating instead", file=sys.stderr)

    budget = config.max_retries
    code = ""
    previous_code = ""
    previous_failure_mode: str | None = None

    for ordinal in range(1, budget + 2):
        if _INTERRUPTED:
            raise Interrupted()

        attempt = Attempt(ordinal=ordinal)
        started = time.monotonic()

        # ---- produce code for this attempt
        generation_error: str | None = None
        if ordinal == 1:
            try:
                code, prompt_tokens, completion_tokens = generate_attempt(
                    generator, case["prompt"], reuse, inventory_block
                )
            except GenerationFailed as exc:
                # The model returned nothing parseable. Record it as a static
                # rejection so the retry budget still governs it (FR-002).
                code = exc.code
                prompt_tokens = completion_tokens = 0
                generation_error = str(exc)
        else:
            repair = healer.repair(
                healer.build_context(
                    original_prompt=case["prompt"],
                    previous_code=previous_code,
                    error_text=previous_error,
                    failing_tool=previous_failing_tool,
                    failure_mode=previous_failure_mode,
                )
            )
            code = repair.code
            prompt_tokens = repair.prompt_tokens
            completion_tokens = repair.completion_tokens

        script_path = out_dir / f"attempt_{ordinal}.py"
        write_script(script_path, code)
        attempt.script_path = script_path.name
        attempt.prompt_tokens = prompt_tokens
        attempt.completion_tokens = completion_tokens

        # ---- Gate 1 barrier
        issues = [generation_error] if generation_error else static_guard(
            code, generator.retriever
        )
        attempt.static_issues = issues
        attempt.static_passed = not issues

        if issues:
            attempt.stage = "static"
            attempt.outcome = OUTCOME_STATIC_REJECTED
            attempt.failure_mode = FailureMode.SCHEMA_MISUSE.value
            attempt.failing_tool = None
            attempt.error_excerpt = issues[0]
            attempt.latency_s = time.monotonic() - started
            result.attempts.append(attempt)
            previous_code = code
            previous_error = issues[0]
            previous_failing_tool = None
            previous_failure_mode = FailureMode.SCHEMA_MISUSE.value
            save(output_root, result)
            print(f"    attempt {ordinal}  static: FAIL  "
                  f"{FailureMode.SCHEMA_MISUSE.value}  {attempt.latency_s:.1f}s")
            continue

        # ---- execute
        workdir = out_dir / f"work_{ordinal}"
        workdir.mkdir(parents=True, exist_ok=True)
        if result.auxiliary_inputs:
            try:
                stage_fixtures(fixtures_root, workdir, result.auxiliary_inputs)
            except FixtureError as exc:
                print(f"    fixture staging failed for {tc_id}: {exc}", file=sys.stderr)

        execution = executor.execute(script_path, workdir)
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
        attempt.latency_s = time.monotonic() - started

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

        result.attempts.append(attempt)
        result.recompute_verdicts()

        print(
            f"    attempt {ordinal}  execute: "
            f"{'OK' if execution.succeeded else 'FAIL'}  "
            f"{attempt.failure_mode or '—'}  {attempt.latency_s:.1f}s  "
            f"{prompt_tokens}+{completion_tokens} tok"
        )

        if execution.succeeded:
            previous_code = code
            break

        previous_code = code
        previous_error = execution.error_excerpt or execution.stderr[-400:]
        previous_failing_tool = execution.failing_tool
        previous_failure_mode = attempt.failure_mode
        save(output_root, result)

    result.recompute_verdicts()
    final_source = next(
        (a for a in reversed(result.attempts) if a.succeeded), None
    ) or result.attempts[0]
    if final_source is not None:
        source = out_dir / final_source.script_path
        if source.is_file():
            (out_dir / "final.py").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            result.final_script = "final.py"

    return mark_complete(output_root, result)


# --------------------------------------------------------------------------
# Report-only mode
# --------------------------------------------------------------------------


def rebuild_report(config: ExecutionConfig, key: ResumeKey) -> int:
    """Regenerate the report from persisted results only (SC-013)."""
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
    )
    report_path = Path(config.report_path)
    if not report_path.is_absolute():
        report_path = REPO_ROOT / report_path
    write_report(report_path, summary, results)
    print(f"Report regenerated from {len(results)} case results: {report_path}")
    return 0


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.max_retries is not None and args.max_retries < 0:
        print("Error: --max-retries must be >= 0", file=sys.stderr)
        return EXIT_ARG
    if args.timeout is not None and args.timeout <= 0:
        print("Error: --timeout must be > 0", file=sys.stderr)
        return EXIT_ARG

    config = resolve_config(args)
    key = ResumeKey(
        model=config.model,
        max_retries=config.max_retries,
        timeout=config.timeout_s,
        attempt1_source=config.attempt1_source,
    )

    if args.report_only:
        return rebuild_report(config, key)

    try:
        cases, suites = load_selected_cases(args)
    except SystemExit as exc:
        return int(exc.code or EXIT_ARG)

    output_root = Path(config.output_dir)
    if not output_root.is_absolute():
        output_root = REPO_ROOT / output_root

    if args.clean and output_root.exists():
        shutil.rmtree(output_root)
        print(f"--clean: wiped {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    discarded = discard_partials(output_root)
    if discarded:
        print(f"Discarded {discarded} partial result file(s) from a prior run.")

    # ---- pre-flight
    report = run_preflight(
        config,
        required_fixtures=required_fixtures(cases),
        need_reuse_artifacts=config.attempt1_source == "reuse_artifacts",
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
        f"model={config.model} retries={config.max_retries} timeout={config.timeout_s}s"
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
    )
    permanent_before = executor.permanent_hash(dataset_project)

    fixtures_root = Path(config.fixtures_dir)
    if not fixtures_root.is_absolute():
        fixtures_root = REPO_ROOT / fixtures_root

    # One inventory read per run, shared by the initial prompt (FR-012b) and
    # every repair prompt (FR-012a). Reading once keeps the two paths grounded
    # on the same snapshot and costs nothing for --max-retries 0 runs beyond a
    # directory listing.
    inventory = read_inventory_safely(dataset_project)
    inventory_block = inventory.format_block()
    if inventory_block:
        print(
            f"Inventory grounding: {len(inventory.rasters)} raster(s), "
            f"{len(inventory.vectors)} vector(s)"
        )
    else:
        print("Inventory grounding unavailable; prompts will omit map names.", file=sys.stderr)

    # ---- shared generation stack
    gen_config = GenerationConfig()
    gen_config.model = config.model
    gen_config.ollama_base_url = config.ollama_base_url
    gen_config.rag_db_path = config.knowledge_db
    # num_predict caps generation length. Without it a small local model can
    # degenerate into an unbounded repeat loop -- observed at 19,579 generated
    # tokens for a 15-line script, which stalled the suite for ~50 minutes.
    # The per-attempt execution timeout does not help: the model never reaches
    # execution. A correct GRASS script is far under this cap.
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
        # Grounds the repair prompt with the dataset's real map names. The
        # provider returns the run-level snapshot already read above, so the
        # initial and repair prompts can never disagree.
        inventory_provider=lambda: inventory,
    )

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
                f"\n--- [{tc_id}] {case.get('category', '?')}: "
                f"\"{case['prompt'][:80]}\"",
                flush=True,
            )

            if config.resume:
                reused = is_reusable(output_root, tc_id, key, config.max_retries, reasons)
                if reused is not None:
                    results.append(reused)
                    reused_any = True
                    verdict = "PASS@HEALED" if reused.pass_at_healed else "UNHEALED"
                    print(
                        f"    resuming: {verdict} "
                        f"({len(reused.attempts)} attempt(s) already recorded)"
                    )
                    continue
                if reasons and reasons[-1].startswith(f"{tc_id}:"):
                    if args.verbose:
                        print(f"    not resuming — {reasons[-1]}")
                    reasons.pop()

            if _INTERRUPTED:
                raise Interrupted()

            result = run_case(
                case, config, generator, healer, executor, fixtures_root, output_root, key,
                inventory_block=inventory_block,
            )
            results.append(result)
            if result.pass_at_healed:
                print(f"    => PASS@HEALED (recovered on attempt {len(result.attempts)})")
            elif result.pass_at_1:
                print("    => PASS@1 (succeeded without healing)")
            else:
                modes = " -> ".join(
                    m for m in result.failure_mode_transitions if m
                ) or "n/a"
                print(f"    => UNHEALED ({modes})")

    except Interrupted:
        print("\nInterrupted. Cleaning up scratch state...", file=sys.stderr)
        permanent_after = executor.permanent_hash(dataset_project)
        summary = aggregate(
            results,
            model=config.model, suites=suites, max_retries=config.max_retries,
            timeout_s=config.timeout_s, attempt1_source=config.attempt1_source,
            resume_key=key, cases_total=len(cases),
            not_evaluated=[c["id"] for c in cases if c["id"] not in {r.tc_id for r in results}],
            resumed=reused_any,
            permanent_hash_before=permanent_before,
            permanent_hash_after=permanent_after,
        )
        write_report(REPO_ROOT / config.report_path, summary, results)
        print("Partial report written.", file=sys.stderr)
        return 1

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
        not_evaluated=not_evaluated,
        resumed=reused_any,
        permanent_hash_before=permanent_before,
        permanent_hash_after=permanent_after,
    )

    save_run_meta(
        output_root,
        {
            "model": config.model,
            "suites": suites,
            "max_retries": config.max_retries,
            "timeout_s": config.timeout_s,
            "attempt1_source": config.attempt1_source,
            "cases_total": len(cases),
            "not_evaluated": not_evaluated,
            "resumed": reused_any,
            "permanent_hash_before": permanent_before,
            "permanent_hash_after": permanent_after,
            "leaked_scratch_dirs": summary.leaked_scratch_dirs,
        },
    )
    report_path = REPO_ROOT / config.report_path
    write_report(report_path, summary, results)
    retriever.close()

    elapsed = time.time() - started_at
    print(f"\n=== Gate 2 run complete in {elapsed / 60:.1f} min ===")
    print(f"Pass@1      {summary.pass_at_1}/{summary.cases_completed} "
          f"({summary.pass_at_1_rate * 100:.1f}%)")
    print(f"Pass@Healed {summary.pass_at_healed}/{summary.cases_completed} "
          f"({summary.pass_at_healed_rate * 100:.1f}%)")
    print(f"PERMANENT unchanged: {summary.permanent_unchanged}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)