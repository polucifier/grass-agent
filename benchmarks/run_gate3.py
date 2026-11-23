#!/usr/bin/env python3
"""Gate 3 — geospatial semantic validation and stateful healing.

Runs the 10-case semantic pilot by default, or the full 40-case benchmark with
`--all`. Two metrics are reported side by side: `Pass@Executed` (exit 0 and at
least one new map) and `Pass@Semantic` (every declared assertion passed).

    python -m benchmarks.run_gate3                # 10-case pilot
    python -m benchmarks.run_gate3 --all          # 40 benchmark cases
    python -m benchmarks.run_gate3 --validate-pilot
    python -m benchmarks.run_gate3 --report-only

Governance: constitution v1.3.0. Generated code still uses `grass.tools`
exclusively; all inference stays local. The semantic probe is read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks import run_gate2  # noqa: E402
from grass_agent.config import ExecutionConfig  # noqa: E402
from grass_agent.executor import Executor  # noqa: E402
from grass_agent.fixtures import required_fixtures  # noqa: E402
from grass_agent.preflight import (  # noqa: E402
    EXIT_ARG,
    EXIT_FAULT,
    EXIT_MISSING_DEPENDENCY,
    run_preflight,
)
from grass_agent.reporting import (  # noqa: E402
    ablation_row,
    aggregate,
    write_gate3_report,
)
from grass_agent.results import (  # noqa: E402
    ResumeKey,
    load,
    load_run_meta,
)
from grass_agent.semantic import (  # noqa: E402
    load_expectations,
    load_pilot_suite,
    pilot_cases,
    validate_pilot_suite,
)

DEFAULT_PILOT_SUITE = "benchmarks/benchmark_prompts_pilot10.json"
DEFAULT_EXPECTATIONS = "benchmarks/pilot_expectations.json"
DEFAULT_REPORT_PATH = "benchmarks/gate3_report.md"
REFERENCE_DIR = REPO_ROOT / "benchmarks" / "pilot_reference"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = run_gate2.build_parser()
    parser.description = (
        "Run the Gate 3 semantic validation and stateful healing harness."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run both benchmark tiers (40 cases) instead of the pilot",
    )
    parser.add_argument(
        "--pilot-suite",
        default=None,
        help=f"Pilot definition (default {DEFAULT_PILOT_SUITE})",
    )
    parser.add_argument(
        "--expectations",
        default=None,
        help=f"Frozen reference values (default {DEFAULT_EXPECTATIONS})",
    )
    parser.add_argument(
        "--validate-pilot",
        action="store_true",
        help="Validate the pilot and expectations; no inference and no GRASS run",
    )
    parser.add_argument(
        "--report-path",
        default=None,
        help=f"Gate 3 report destination (default {DEFAULT_REPORT_PATH})",
    )
    parser.add_argument(
        "--ablation-dirs",
        default=None,
        help="Comma-separated output directories for a per-mode ablation (requires --report-only)",
    )
    # Gate 3 probes by default; `--no-semantic` turns it off.
    parser.set_defaults(semantic=True)
    return parser


def _resolve(path_value: str | None, default: str) -> Path:
    path = Path(path_value or default)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _grass_version(grass_bin: str) -> str:
    completed = subprocess.run(
        [grass_bin, "--version"], capture_output=True, text=True, timeout=30
    )
    lines = (completed.stdout or completed.stderr or "").strip().splitlines()
    if not lines:
        return ""
    parts = lines[0].split()
    return parts[1] if len(parts) > 1 else lines[0]


def _environment_identity(config: ExecutionConfig, require_grass: bool = True) -> dict:
    """Resolve GRASS version and dataset identity for validation and metadata."""
    identity: dict = {
        "grass_version": "",
        "dataset": "",
        "permanent_hash": "",
        "project": "",
    }
    if require_grass:
        identity["grass_version"] = _grass_version(config.grass_bin)
    project = config.dataset_project
    if project is None:
        project = str(ExecutionConfig.detect_dataset(config.grass_bin).dataset_project)
    project_path = Path(project)
    identity["project"] = str(project_path)
    identity["dataset"] = project_path.name
    identity["permanent_hash"] = Executor.permanent_hash(project_path)
    return identity


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate_pilot(config: ExecutionConfig, suite_path: Path, expectations_path: Path) -> int:
    """`--validate-pilot`: no inference, no GRASS execution."""
    if not suite_path.is_file():
        print(f"ERROR: pilot suite not found: {suite_path}", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY
    if not expectations_path.is_file():
        print(f"ERROR: expectations file not found: {expectations_path}", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY

    try:
        suite = load_pilot_suite(suite_path)
        expectations = load_expectations(expectations_path)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: could not read the pilot or expectations: {exc}", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY

    try:
        identity = _environment_identity(config)
    except Exception as exc:  # noqa: BLE001 - report the named dependency
        print(f"ERROR: could not resolve the GRASS/dataset identity: {exc}", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY

    violations = validate_pilot_suite(
        suite,
        expectations,
        reference_dir=REFERENCE_DIR,
        current_grass_version=identity["grass_version"],
        current_dataset={
            "project": identity["project"],
            "permanent_hash": identity["permanent_hash"],
        },
    )

    cases = pilot_cases(suite)
    tier1 = sum(1 for c in cases if c.get("tier") == 1)
    tier2 = sum(1 for c in cases if c.get("tier") == 2)
    multi = sum(
        1
        for c in cases
        if c.get("category") == "multi_step"
        or {o.get("type") for o in c.get("outputs") or []} == {"raster", "vector"}
    )
    raster = sum(
        1 for c in cases for o in c.get("outputs") or [] if o.get("type") == "raster"
    )
    vector = sum(
        1 for c in cases for o in c.get("outputs") or [] if o.get("type") == "vector"
    )

    print(f"Pilot: {suite_path.name}")
    print(f"Cases: {len(cases)} (tier1={tier1}, tier2={tier2})")
    print(f"Multi-step/mixed: {multi}")
    print(f"Outputs: raster={raster}, vector={vector}")
    print(f"Expectations: {expectations_path.relative_to(REPO_ROOT) if expectations_path.is_relative_to(REPO_ROOT) else expectations_path} sha256:{_sha256(expectations_path)}")
    print(f"Dataset: {identity['dataset']}  GRASS: {identity['grass_version']}")

    if violations:
        for violation in violations:
            print(f"VIOLATION: {violation}", file=sys.stderr)
        print("Pilot validation: FAILED", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY
    print("Pilot validation: OK")
    return 0


# --------------------------------------------------------------------------
# Report-only
# --------------------------------------------------------------------------


def _summary_for_directory(directory: Path, config: ExecutionConfig, key: ResumeKey, results=None):
    results = results if results is not None else []
    meta = load_run_meta(directory)
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
        permanent_hash_before=meta.get("permanent_hash_before", ""),
        permanent_hash_after=meta.get("permanent_hash_after", ""),
        leaked_scratch_dirs=meta.get("leaked_scratch_dirs", []),
        max_static_retries=meta.get(
            "max_static_retries", config.max_static_retries
        ),
        max_runtime_retries=meta.get(
            "max_runtime_retries", config.max_runtime_retries
        ),
        grass_version=meta.get("grass_version", ""),
        dataset=meta.get("dataset", ""),
        pilot_suite_hash=meta.get("pilot_suite_hash", ""),
        pilot_expectations_hash=meta.get("pilot_expectations_hash", ""),
        pilot_reviewed=meta.get("pilot_reviewed"),
        report_only=True,
        pipeline=meta.get("pipeline", "legacy"),
        num_ctx=meta.get("num_ctx", 8192),
        manual_context_tokens=meta.get("manual_context_tokens", None),
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
    return summary, meta


def _load_results(directory: Path):
    results = []
    for case_dir_path in sorted(directory.iterdir() if directory.is_dir() else []):
        loaded = load(directory, case_dir_path.name)
        if loaded is not None and loaded.status == "complete":
            results.append(loaded)
    return results


def report_only(config: ExecutionConfig, key: ResumeKey, report_path: Path, ablation_dirs=None) -> int:
    output_root = Path(config.output_dir)
    if not output_root.is_absolute():
        output_root = REPO_ROOT / output_root

    if ablation_dirs:
        directories = [
            Path(part.strip())
            for part in str(ablation_dirs).split(",")
            if part.strip()
        ]
        if len(directories) < 2:
            print("Error: --ablation-dirs needs at least two directories", file=sys.stderr)
            return EXIT_ARG
        resolved = []
        for directory in directories:
            if not directory.is_absolute():
                directory = REPO_ROOT / directory
            if not (directory / "run_summary.json").is_file():
                print(
                    f"Error: {directory} has no run_summary.json", file=sys.stderr
                )
                return EXIT_ARG
            resolved.append(directory)

        rows = []
        seen_modes: set[str] = set()
        primary_summary = None
        primary_results = None
        for directory in resolved:
            results = _load_results(directory)
            summary, _ = _summary_for_directory(directory, config, key, results)
            if summary.pipeline in seen_modes:
                print(
                    f"Error: duplicate pipeline mode {summary.pipeline!r} in "
                    "--ablation-dirs",
                    file=sys.stderr,
                )
                return EXIT_ARG
            seen_modes.add(summary.pipeline)
            rows.append(ablation_row(summary))
            if primary_summary is None:
                primary_summary = summary
                primary_results = results
        if primary_summary is None or primary_results is None:
            print("No completed case results found; nothing to report.", file=sys.stderr)
            return EXIT_ARG
        primary_summary.pipeline_ablation = rows
        write_gate3_report(report_path, primary_summary, primary_results)
        print(
            f"Ablation report rendered from {len(resolved)} directories: {report_path}"
        )
        return 0

    results = _load_results(output_root)
    if not results:
        print("No completed case results found; nothing to report.", file=sys.stderr)
        return EXIT_ARG
    summary, _ = _summary_for_directory(output_root, config, key, results)
    write_gate3_report(report_path, summary, results)
    print(f"Report regenerated from {len(results)} case results: {report_path}")
    return 0


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # ---- argument conflicts
    if args.all and args.pilot_suite is not None:
        print("Error: --all and --pilot-suite are mutually exclusive", file=sys.stderr)
        return EXIT_ARG
    if args.report_only and args.clean:
        print("Error: --report-only cannot be combined with --clean", file=sys.stderr)
        return EXIT_ARG
    if args.ablation_dirs and not args.report_only:
        print("Error: --ablation-dirs requires --report-only", file=sys.stderr)
        return EXIT_ARG
    if args.max_retries is not None and args.max_retries < 0:
        print("Error: --max-retries must be >= 0", file=sys.stderr)
        return EXIT_ARG
    for flag, value in (
        ("--max-static-retries", args.max_static_retries),
        ("--max-runtime-retries", args.max_runtime_retries),
    ):
        if value is not None and value < 0:
            print(f"Error: {flag} must be >= 0", file=sys.stderr)
            return EXIT_ARG
    if args.timeout is not None and args.timeout <= 0:
        print("Error: --timeout must be > 0", file=sys.stderr)
        return EXIT_ARG

    suite_path = _resolve(
        args.pilot_suite if args.pilot_suite is not None else None,
        DEFAULT_PILOT_SUITE,
    )
    expectations_path = _resolve(args.expectations, DEFAULT_EXPECTATIONS)
    report_path = _resolve(args.report_path, DEFAULT_REPORT_PATH)

    config = run_gate2.resolve_config(args).with_overrides(
        harness="gate3",
        semantic_enabled=args.semantic,
        pilot_suite=str(suite_path),
        pilot_expectations=str(expectations_path),
    )
    key = ResumeKey(
        model=config.model,
        max_retries=config.max_retries,
        timeout=config.timeout_s,
        attempt1_source=config.attempt1_source,
        max_static_retries=config.max_static_retries,
        max_runtime_retries=config.max_runtime_retries,
        harness="gate3",
        pipeline=config.pipeline,
        num_ctx=config.num_ctx,
        manual_context_tokens=config.resolve_manual_budget(),
    )

    # `--validate-pilot` wins over every execution flag.
    if args.validate_pilot:
        return validate_pilot(config, suite_path, expectations_path)

    if args.report_only:
        return report_only(config, key, report_path, ablation_dirs=args.ablation_dirs)

    # ---- selected suite(s)
    if args.all:
        args.suite = None
    else:
        args.suite = str(suite_path)
    try:
        cases, suites = run_gate2.load_selected_cases(args)
    except SystemExit as exc:
        return int(exc.code or EXIT_ARG)

    # ---- one pre-flight per run
    preflight = run_preflight(
        config,
        required_fixtures=required_fixtures(cases),
        need_reuse_artifacts=config.attempt1_source == "reuse_artifacts",
        pipeline=config.pipeline,
    )
    if not preflight.ok:
        for failure in preflight.failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY
    if preflight.dataset_project is None:
        print("Error: dataset could not be resolved", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY

    extra_meta: dict = {
        "harness": "gate3",
        "dataset": Path(preflight.dataset_project).name,
        "report_path": str(report_path),
    }
    if config.semantic_enabled:
        if not expectations_path.is_file():
            print(
                f"ERROR: semantic mode requires {expectations_path}",
                file=sys.stderr,
            )
            return EXIT_MISSING_DEPENDENCY
        try:
            suite_doc = load_pilot_suite(suite_path) if not args.all else None
            expectations = load_expectations(expectations_path)
        except (OSError, ValueError, KeyError) as exc:
            print(f"ERROR: could not read pilot metadata: {exc}", file=sys.stderr)
            return EXIT_MISSING_DEPENDENCY

        identity = _environment_identity(
            config.with_overrides(dataset_project=str(preflight.dataset_project))
        )
        extra_meta.update(
            {
                "grass_version": identity["grass_version"],
                "pilot_suite_hash": (
                    _sha256(suite_path) if suite_path.is_file() else ""
                ),
                "pilot_expectations_hash": _sha256(expectations_path),
                "pilot_reviewed": True,
            }
        )
        if not args.all and suite_doc is not None:
            violations = validate_pilot_suite(
                suite_doc,
                expectations,
                reference_dir=REFERENCE_DIR,
                current_grass_version=identity["grass_version"],
                current_dataset={
                    "project": identity["project"],
                    "permanent_hash": identity["permanent_hash"],
                },
            )
            if violations:
                for violation in violations:
                    print(f"VIOLATION: {violation}", file=sys.stderr)
                return EXIT_MISSING_DEPENDENCY

    try:
        return run_gate2.execute_suite(
            cases,
            suites,
            config,
            key,
            report_path,
            write_gate3_report,
            args,
            extra_meta=extra_meta,
            preflight_report=preflight,
        )
    except SystemExit as exc:
        return int(exc.code or EXIT_ARG)
    except Exception as exc:  # noqa: BLE001 - a harness fault is exit 1
        print(f"HARNESS FAULT: {exc}", file=sys.stderr)
        return EXIT_FAULT


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
