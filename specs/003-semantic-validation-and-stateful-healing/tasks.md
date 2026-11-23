---
description: "Task list for Gate 3 semantic validation, stateful healing, and two-tier retry budget"
---

# Tasks: Semantic Validation, Stateful Healing, and Two-Tier Retry Budget (Gate 3)

**Input**: Design documents from `specs/003-semantic-validation-and-stateful-healing/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Included. SC-007 and the plan file matrix explicitly require new pytest coverage while keeping all 255 pre-existing tests unchanged.

**Organization**: Tasks are grouped by user story so each story can be implemented and verified independently. Setup and Foundational tasks are shared prerequisites.

**Baseline**: 255 pre-existing tests, `Pass@1` 27.5%, `Pass@Healed` 32.5%. Run everything with `.venv/bin/python`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: `[US1]`–`[US4]`, mapping to the four user stories in [spec.md](./spec.md)
- Every task names the exact file it creates or modifies

## Path Conventions

Single project: `grass_agent/`, `benchmarks/`, and `tests/` at repository root, matching [plan.md](./plan.md) Project Structure.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the frozen baseline and ratify the Gate 3 governance change before any code moves.

- [x] T001 Verify the zero-regression baseline by running `.venv/bin/python -m pytest -q` and recording that all 255 tests pass before any edit across `tests/`; confirm `.venv/bin/python -m pytest --collect-only -q` reports `255 tests collected`.
- [x] T002 Amend `.specify/memory/constitution.md` from v1.2.0 to v1.3.0: add the Gate 3 bullet under Principle IV (semantic validation of generated geospatial outputs, dual execution/semantic metrics, stateful healing memory, independent static/runtime repair tiers), keep Gate 2 metrics as the historical comparison, and add the migration note that no existing requirement changes.
- [x] T003 [P] Create `benchmarks/pilot_reference/README.md` documenting that these are human-reviewed golden scripts, that `derive_pilot_expectations.py` is the only consumer, and that candidate artifacts (`attempt_*.py`, `final.py`) are never valid value sources.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Additive schema, ledger, and configuration that every user story reads or writes.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. All changes are additive with defaults; no existing field is renamed or removed, and `SCHEMA_VERSION` stays `1`.

- [x] T004 Add Gate 3 settings to `grass_agent/config.py` on `ExecutionConfig`: `max_static_retries: int = 2`, `max_runtime_retries: int = 2`, `pilot_suite: str = "benchmarks/benchmark_prompts_pilot10.json"`, `pilot_expectations: str = "benchmarks/pilot_expectations.json"`, `semantic_query_timeout_s: int = 30`, `semantic_probe_timeout_s: int = 60`, `semantic_probe_grace_s: int = 5`, `harness: str = "gate2"` (overridden to `"gate3"` only by `run_gate3`), `semantic_enabled: bool = False`; also parse `GRASS_MAX_STATIC_RETRIES` and `GRASS_MAX_RUNTIME_RETRIES` alongside the existing `GRASS_MAX_RETRIES`.
- [x] T005 Extend `Attempt` in `grass_agent/results.py` with `budget_tier: str = "initial"` (exactly `"initial" | "static" | "runtime"`), `duplicate: bool = False`, `code_sha256: str | None = None`, `ast_sha256: str | None = None`, `new_maps: dict = field(default_factory=lambda: {"raster": [], "vector": []})`, `semantic_evaluated: bool = False`, `semantic_passed: bool | None = None`, `assertion_results: list = field(default_factory=list)`, and `pivot_used: bool = False`; append fields so positional construction used by existing tests is unaffected.
- [x] T006 Add `BudgetLedger` and extend `CaseResult` in `grass_agent/results.py` with `pass_at_executed: bool = False`, `pass_at_semantic: bool | None = None`, `semantic_evaluated: bool = False`, `no_op_count: int = 0`, `budget_ledger: BudgetLedger | None = None`, and `harness_version: str = "gate2"`; `no_op_count` must equal the number of attempts with `duplicate == true`, and `budget_ledger` must equal the value recomputed from attempts.
- [x] T007 Extend `ResumeKey` in `grass_agent/results.py` with `max_static_retries: int | None = None`, `max_runtime_retries: int | None = None`, and `harness: str = "gate2"`; in `matches()`, normalise `None` tier values to the legacy `max_retries` so old keys still compare correctly among themselves, and require `harness` equality so a Gate 2 key never matches a Gate 3 key.
- [x] T008 Update `recompute_verdicts()` and the load path in `grass_agent/results.py`: derive `pass_at_executed` only from an `executed_ok` attempt with non-empty `new_maps`, derive `pass_at_semantic` as `None` when `semantic_evaluated` is false and otherwise `pass_at_executed and every assertion passed`, and infer `budget_tier` for legacy records (`ordinal == 1` → `initial`; `stage == "static"` → `static`; otherwise `runtime`). Keep `pass_at_1` and `pass_at_healed` on their Gate 2 definitions; a legacy record with no `new_maps` sets `pass_at_executed = pass_at_healed` and `harness_version = "gate2"`.
- [x] T009 Update `check_invariants()` in `grass_agent/results.py` to enforce I1–I15 from [data-model.md](./data-model.md): `len(attempts) ≤ 1 + static_limit + runtime_limit`, contiguous ordinals, `static_used ≤ static_limit`, `runtime_used ≤ runtime_limit`, `static_passed == false` implies `exit_code is None`, `duplicate == true` implies `exit_code is None`, `timed_out == false`, and empty `new_maps`, plus `pass_at_semantic == true` implies `semantic_evaluated == true`. Keep the existing `check_invariants(result, max_retries)` signature working by interpreting `max_retries` as both tier budgets when no tier limits are supplied.
- [x] T010 [P] Create `tests/test_budget_tiers.py` with foundational ledger/invariant tests: ledger recomputation equality, legacy tier inference, legacy `max_retries` ceiling compatibility (a four-runtime-failure case still raises `ResultValidationError` matching `I1`), and `ResumeKey` `None`-normalisation plus harness discrimination.

**Checkpoint**: `pytest -q` passes with 255 existing tests plus T010; all new fields default cleanly on old artifacts.

---

## Phase 3: User Story 1 — Trust That a Successful Script Produced the Right Geospatial Result (Priority: P1) 🎯 MVP

**Goal**: Run a read-only semantic probe inside the same disposable GRASS session after a zero-exit candidate and report raster statistics or vector topology/columns against independently frozen expectations.

**Independent Test**: Run one pilot case whose script exits 0 but writes a raster outside the declared expected range; confirm `pass_at_executed = true`, `pass_at_semantic = false`, the failing assertion records expected/observed/tolerance, no repair is generated, and no tier unit is consumed.

### Tests for User Story 1

- [x] T011 [P] [US1] Create `tests/test_semantic_spec.py` covering `CaseSemantics`/`OutputSpec`/`AssertionSpec` validation: unknown `check` rejected, assertion naming an undeclared output rejected, duplicate output names rejected, output name absent from prompt rejected, and non-pilot cases producing `semantic_evaluated = false`.
- [x] T012 [P] [US1] Create `tests/test_semantic_probe.py` with fake `r.univar -g -r`/`v.info -t`/`v.info -c` output: parsed raster `n/min/max/mean`, geometry classification (`areas > 0 → area`, `lines > 0 → line`, `points > 0 → point`, otherwise `boundary`/`empty`), missing output → `missing_output`, a map created by a prior attempt but absent from the current snapshot is also `missing_output` and is never credited (FR-008d), zero features, wrong geometry, missing column, `n=0` → `no_values`, non-finite value, `query_failed`, `query_timeout`, and `probe_timeout`.
- [x] T013 [P] [US1] Create `tests/test_pilot_suite.py` asserting the pilot has exactly 10 cases, at least 4 from benchmark Tier 1 and at least 4 from benchmark Tier 2, at least 4 multi-step/mixed raster-vector cases, every output name follows the suite’s declared `pilot_*` convention and appears verbatim in its prompt, and every declared output has an existence check plus at least one assertion. Add a negative fixture containing a display-only or statistics-only case and assert `validate_pilot_suite()` rejects it as a composition violation (FR-007a).

### Implementation for User Story 1

- [x] T014 [US1] Create `grass_agent/semantic.py` with dataclasses `OutputSpec`, `AssertionSpec`, `CaseSemantics`, `PilotExpectations`, `AssertionResult`, and `SemanticResult` exactly as specified in [data-model.md](./data-model.md) sections 2, 3, 4, 6, and 7 (`check` enum is exactly `non_null_count | value_range | mean | feature_count | geometry_type | required_columns`).
- [x] T015 [US1] Add `load_pilot_suite()`, `load_expectations()`, and `validate_pilot_suite()` to `grass_agent/semantic.py`; validation must fail with a named violation when the suite is not 10 cases, either benchmark tier has fewer than 4, fewer than 2 cases are multi-step/mixed, an assertion names an undeclared output, an output name is missing from the prompt or lacks the `pilot_` prefix, an expectation is missing for a declared output, or a case is display-only or statistics-only with no persistent output (FR-007a exclusion lint). `--validate-pilot` MUST also exit `3` when `reference_script_sha256` does not match `benchmarks/pilot_reference/`, or when the recorded GRASS version or dataset identity differs from the current environment ([contracts/cli.md](./contracts/cli.md) pre-flight items 9–10).
- [x] T016 [US1] Add `resolve_assertions()` to `grass_agent/semantic.py`, merging suite checks/tolerances with `pilot_expectations.json` values and refusing any `expected_source` other than `"reference"`; default mean tolerance is `0.01` relative and default count minimum is `1`.
- [x] T017 [US1] Create `grass_agent/semantic_probe.py` as a standalone read-only query engine: snapshot with `g.list type=raster mapset=.` and `g.list type=vector mapset=.`, raster query `r.univar -g -r map=<name>` (the `-r` flag is mandatory so a candidate's `g.region` cannot move the reference target), vector count/geometry from `v.info -t`, and columns from `v.info -c` using the substring after the last `|`.
- [x] T018 [US1] Add assertion evaluation and atomic `semantic.json`/`maps.json` writing to `grass_agent/semantic_probe.py`: ordered by declared output then declared check, one failing output never hides another, every query bounded by `semantic_query_timeout_s` and the probe by `semantic_probe_timeout_s`, and no GRASS map is ever written. Resolve every declared output's existence exactly once before evaluating assertions and record `OutputResult.exists` (I13). Evaluation MUST read only the current attempt's snapshot/`new_maps`, never a mapset-wide name lookup, and MUST assert that a map present in attempt 1 but absent in attempt 2 cannot satisfy attempt 2's assertions (FR-008d).
- [x] T019 [P] [US1] Create `benchmarks/benchmark_prompts_pilot10.json` with the 10 cases from [plan.md](./plan.md) (`pilot_tc_01`, `_05`, `_06`, `_08`, `_09`, `_12`, `_14`, `_18`, `_32`, `_33`), each declaring `source_id`, `source_suite`, `tier` (benchmark tier), `category`, `target_dataset`, `outputs`, and `assertions`; every prompt names its `pilot_*` outputs and ends with `Do not change the computational region.` Exclude display-only and statistics-only tasks; every case must produce at least one persistent map (FR-007a).
- [x] T020 [P] [US1] Create the 10 human-reviewed golden scripts under `benchmarks/pilot_reference/` (`pilot_tc_01.py` … `pilot_tc_33.py`), each using modern `grass.tools` and producing exactly the declared outputs; use `r.viewshed -b` for `pilot_tc_08` binary visibility, assert no columns on `v.buffer` outputs, and use `-r`-compatible raster results.
- [x] T021 [P] [US1] Create `benchmarks/derive_pilot_expectations.py` that executes only `benchmarks/pilot_reference/*.py` in a disposable `grass --tmp-mapset` session, queries `r.univar -g -r`, `v.info -t`, and `v.info -c`, and writes `benchmarks/pilot_expectations.json` with `grass_version`, dataset path, `PERMANENT` hash, reference script SHA-256, and per-output values; it must raise if asked to read `attempt_*.py` or `final.py`.
- [x] T022 [US1] Run `benchmarks/derive_pilot_expectations.py`, inspect every expected value against task semantics, and commit `benchmarks/pilot_expectations.json` with its reviewed SHA-256 recorded for `run_summary.json`.
- [x] T023 [US1] Modify `grass_agent/inner_wrapper.py`: snapshot current-mapset rasters and vectors before forking the child, after a zero-exit child compute sorted `new_maps`, invoke the probe using `GRASS_AGENT_SEMANTIC_SPEC`, `GRASS_AGENT_MAPS_OUT`, and `GRASS_AGENT_SEMANTIC_OUT`, write `maps.json` and `semantic.json`, skip the probe on non-zero exit/crash, and leave child status and signal re-raise semantics unchanged.
- [x] T024 [US1] Modify `grass_agent/executor.py`: accept optional `semantic_spec` and `case_id`, copy `semantic_probe.py` and the spec into the workdir, set the probe environment variables, extend only the outer communicate deadline by `semantic_probe_grace_s` when a spec is present, and add `new_maps`/`semantic` to `ExecutionResult`; do not change process-group handling, timeout enforcement, `PERMANENT` hashing, or the `chmod -w` guard.
- [x] T025 [US1] Create `benchmarks/run_gate3.py` as the Gate 3 entry point. Default to `benchmark_prompts_pilot10.json`, enable semantic evaluation by default, reuse `run_gate2.resolve_config`/`load_selected_cases`, and add a Gate 3 parser exposing: `--all` (40 benchmark cases), `--semantic`/`--no-semantic` (default on), `--pilot-suite` (default `benchmarks/benchmark_prompts_pilot10.json`), `--expectations` (default `benchmarks/pilot_expectations.json`), `--validate-pilot`, `--report-path` (default `benchmarks/gate3_report.md`), `--report-only`, `--clean`, `-k`, and the tier-budget flags. Enforce the contracted conflicts: `--all` with `--pilot-suite` exits `2`, `--report-only` with `--clean` exits `2`, and `--validate-pilot` wins over execution flags. Run the contracted pre-flight checks once per run and exit `3` with the named dependency when GRASS, the dataset, Ollama, the knowledge base, or a declared fixture is unavailable.
- [x] T026 [US1] Extend `run_case` in `benchmarks/run_gate2.py` to pass the resolved semantic spec to `Executor.execute`, copy probe evidence into `Attempt.assertion_results`, set `semantic_evaluated`/`semantic_passed`, set `pass_at_executed` from non-empty `new_maps`, and terminate at the semantic verdict with no repair prompt and no budget charge (FR-001e, FR-008g).
- [x] T027 [US1] Create `tests/test_integration_semantic.py` marked `slow`: one live pilot case passes all assertions, one live script exits 0 but writes an empty raster → `pass_at_executed = false` and no semantic pass, and one live script writes an out-of-tolerance mean → `pass_at_executed = true`, `pass_at_semantic = false`, zero new attempts, unchanged ledger. Add a two-attempt live case where attempt 1 creates the declared output and fails at runtime, and attempt 2 exits 0 without creating it; assert attempt 2 is `pass_at_executed = false` and no stale map is credited (FR-008d). Add two cleanup cases: (a) send SIGINT during a live attempt and assert no scratch directory remains and `PERMANENT` is unchanged; (b) force a probe timeout/failure after a zero-exit child and assert the run completes, no scratch directory remains, and the case is a semantic failure rather than a harness fault (FR-014, SC-008).
- [x] T028 [US1] Checkpoint: run `.venv/bin/python -m pytest tests/test_semantic_spec.py tests/test_semantic_probe.py tests/test_pilot_suite.py -q` and `.venv/bin/python -m benchmarks.run_gate3 --validate-pilot`; confirm exit 0 with the 10-case/5+5/4-mixed summary and a named violation on an intentionally broken fixture.

**Checkpoint**: User Story 1 delivers a working oracle and pilot validation independently of tier accounting and no-op detection.

---

## Phase 4: User Story 2 — Escape the No-Op Repair Loop (Priority: P2)

**Goal**: Carry full ordered attempt history into repair prompts, reject byte-identical and AST-identical duplicates before execution, and pivot to explicit parameter-list injection.

**Independent Test**: Seed a case with a failed first attempt, force the model to return byte-identical code, and confirm the duplicate is rejected without execution, recorded as `no_op_duplicate`, and followed by a pivot prompt containing the failing tool's parameter list; confirm no accepted attempt is identical to a prior one.

**Dependency note**: Tier *charging* of duplicates is finalized in US3. US2 records `budget_tier` from the repair stage already known to `run_case`, so duplicate rejection and pivoting are testable before per-tier ceilings land.

### Tests for User Story 2

- [x] T029 [P] [US2] Create `tests/test_stateful_healing.py`: every prior attempt's ordinal, tier, failure mode, error excerpt, stage, and duplicate flag appears in the prompt; the verbatim instruction `DO NOT repeat previous scripts or failed parameter combinations.` is present; the newest failed attempt's full code is present; older code is replaced by digest plus a bounded excerpt once history exceeds 6000 characters; an empty history renders the existing four-element repair prompt unchanged.
- [x] T030 [P] [US2] Create `tests/test_noop_detection.py`: byte-identical duplicate rejected; CRLF-vs-LF duplicate rejected; comment-only duplicate rejected; docstring-only duplicate rejected; formatting-only duplicate rejected; a changed tool or parameter is not a duplicate; an unparseable candidate still participates via the byte digest; pivot prompt contains the knowledge-base parameter list; and a stub 40-case run records zero accepted duplicate executions. Add a determinism test that runs a fixed fixture sequence twice and asserts byte-identical `case_result.json` after zeroing volatile fields (`completed_at`, `latency_s`, token counts), with identical duplicate verdicts (FR-006d).

### Implementation for User Story 2

- [x] T031 [US2] Add `RepairTurn` (`ordinal`, `budget_tier`, `code`, `failure_mode`, `error_excerpt`, `stage`, `duplicate`) and `RepairContext.attempt_history: list[RepairTurn] = field(default_factory=list)` plus `pivot: bool = False` to `grass_agent/healing.py`, preserving the existing constructor field order `prompt, code, error, docs, inventory, history, pivot`.
- [x] T032 [US2] Extend `RepairContext.to_user_message()` in `grass_agent/healing.py`: render task → tool documentation → inventory → `### Previous Attempts` (metadata for all turns, full code only for the newest, digest plus bounded excerpt for older ones) → the exact no-repeat instruction → current failed code/error; cap history code/excerpts at 6000 characters, never truncate failure metadata, and keep the four existing FR-012 elements.
- [x] T033 [US2] Add `NoOpDigest` and a `NoOpIndex` to `grass_agent/healing.py`: byte digest is SHA-256 of `code.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")`; AST digest is SHA-256 of a normalized `ast.dump(tree, annotate_fields=False, include_attributes=False)` after recursively stripping module/class/function docstrings; a candidate is a duplicate if either digest matches any prior attempt; unparseable code yields `ast_sha256 = None` and participates by byte digest only.
- [x] T034 [US2] Add `Healer.parameter_list(tool)` in `grass_agent/healing.py`, reading the knowledge-base signature, required/optional parameters, and accepted options, and returning a deterministic parameter table; return `None` when the tool is unknown so the pivot degrades to the generic no-repeat instruction.
- [x] T035 [US2] Extend `Healer.build_context(..., history, pivot=False)` and `Healer.repair(..., pivot=False)` in `grass_agent/healing.py`; a pivot replaces the generic fix wording with the explicit parameter table plus the constraint `change the approach; do not resubmit a previous program`, and `RepairAttempt` records `pivot_used`.
- [x] T036 [US2] Modify `run_case` in `benchmarks/run_gate2.py` to maintain one ordered history across both tiers, seed the index with the initial candidate, check every generated candidate before execution, and on a duplicate write `attempt_N.py`, zero-byte `.stdout`/`.stderr`, `.log`, and a `no_op_duplicate` attempt with `duplicate = true`, `exit_code = null`, `timed_out = false`, empty `new_maps`, and an `error_excerpt` naming the matched ordinal; set `pivot = true` for the next prompt if budget remains.
- [x] T037 [US2] Terminate `run_case` in `benchmarks/run_gate2.py` as an unresolved no-op failure when the pivot is also a duplicate or no budget remains, preserving every duplicate in the history and in `case_result.json` (FR-006b).
- [x] T038 [US2] Checkpoint: run `.venv/bin/python -m pytest tests/test_stateful_healing.py tests/test_noop_detection.py -q` and a stub 40-case execution proving zero accepted duplicate executions and 100% duplicate detection.

**Checkpoint**: Repairs are history-aware and duplicate-free; a duplicate never reaches GRASS.

---

## Phase 5: User Story 3 — Spend Static and Runtime Effort Independently (Priority: P3)

**Goal**: Give static and runtime repairs independent limits, charge each generated repair to its producing tier, and keep `--max-retries` as a compatible both-tier shorthand.

**Independent Test**: Provide a case whose first two candidates fail static validation and whose third is valid but fails at runtime; confirm GRASS launched only for the third candidate, the runtime tier still has two repairs available, and `case_result.json` records used/remaining for both tiers separately.

### Tests for User Story 3

- [x] T039 [P] [US3] Create `tests/test_gate3_cli.py`: `--max-static-retries`/`--max-runtime-retries` parse and reject negatives with exit `2`; `--max-retries 3` sets both tiers to 3; `--max-retries 3 --max-static-retries 1` yields static 1/runtime 3; env `GRASS_MAX_RETRIES=1` plus `--max-runtime-retries 3` yields static 1/runtime 3; `run_gate2.build_parser().parse_args([])` still exposes `max_retries is None` and `resolve_config` still yields `max_retries == 2`; tier-specific env precedence (`GRASS_MAX_STATIC_RETRIES`, `GRASS_MAX_RUNTIME_RETRIES`). Add pre-flight failure tests asserting exit `3` with a named dependency for: missing/corrupted GRASS environment (`grass --version` fails), missing dataset (`PERMANENT/DEFAULT_WIND` or `PROJ_INFO` absent), unreachable Ollama, missing knowledge base, and an unresolved fixture.
- [x] T040 [US3] Extend `tests/test_budget_tiers.py` with tier-accounting tests: static exhaustion never calls `Executor.execute`; two static repairs leave the full runtime allowance; runtime failures never replenish the static repair tier; a runtime repair-tier candidate that fails static validation is charged to runtime and launches no GRASS; exit-0-with-no-new-map requests a runtime repair charged to runtime; the maximum is 5 candidates at defaults; a Gate 2 result never matches a Gate 3 resume key. Add a determinism test that replays the same fixed static/runtime sequence twice and asserts byte-identical canonicalised `case_result.json` (volatile fields zeroed) with identical per-tier used/remaining accounting (FR-013).

### Implementation for User Story 3

- [x] T041 [US3] Add `--max-static-retries` and `--max-runtime-retries` to `build_parser()` in `benchmarks/run_gate2.py` and resolve them in `resolve_config()` with precedence, highest first: repair-tier CLI flag > `--max-retries` > repair-tier env var > `GRASS_MAX_RETRIES` > default `2`; validate negatives/non-integers with exit `2` naming the flag, and keep `args.max_retries` present and unchanged.
- [x] T042 [US3] Replace the unified budget gate in `run_case` (`benchmarks/run_gate2.py`) with the charge-on-generate algorithm from [data-model.md](./data-model.md) section 15: the initial candidate is free; a static failure requests a static repair and the generated candidate consumes `static_used`; any runtime failure (non-zero exit, crash, timeout, or exit 0 with empty `new_maps`) requests a runtime repair that consumes `runtime_used`; a runtime-tier candidate failing static validation stays charged to runtime, is not executed, and requests another runtime repair; terminate when the requested tier has no remaining unit.
- [x] T043 [US3] Persist the ledger and harness identity from `run_case` in `benchmarks/run_gate2.py`: populate `budget_ledger` with `static_limit/static_used/static_remaining/runtime_limit/runtime_used/runtime_remaining`, set `harness_version` and `ResumeKey.harness` to `"gate3"` only in `run_gate3`, and build `ResumeKey` from both resolved tier budgets plus `harness`; `run_gate2` always writes `"gate2"`, including with `--semantic`, so Gate 2 results remain reusable and Gate 3 never reuses them.
- [x] T044 [US3] Extend `tests/test_gate3_cli.py` for `benchmarks/run_gate3.py`: `--all` conflicts with `--pilot-suite` (exit `2`), `-k` filters within the selected suite, `--max-static-retries 0` still executes a valid initial candidate with the full runtime budget, `--max-runtime-retries 0` still runs static repairs, and both zero yields exactly one candidate per case.
- [x] T045 [US3] Checkpoint: run `.venv/bin/python -m pytest tests/test_gate3_cli.py tests/test_budget_tiers.py -q` and a stub run proving a case with two static failures launches zero GRASS processes and retains two runtime repairs.

**Checkpoint**: Static and runtime budgets are provably independent; the existing CLI contract is preserved.

---

## Phase 6: User Story 4 — Compare Execution Success and Semantic Success in One Report (Priority: P4)

**Goal**: Render `Pass@Executed` and `Pass@Semantic` with explicit denominators, semantic failure evidence, duplicate and tier statistics, and a separated Gate 2 historical section.

**Independent Test**: Regenerate the report from persisted `case_result.json` files with `--report-only` and confirm identical metrics, both denominators, semantic failure rows with expected/observed/tolerance, duplicate and tier counters, and a Gate 2 section containing `Pass@Healed` but no `Pass@Healed` column in the main table.

### Tests for User Story 4

- [x] T046 [P] [US4] Create `tests/test_reporting_gate3.py`: main table contains exactly `Pass@Executed` and `Pass@Semantic`; `Pass@Semantic ≤ Pass@Executed` on the semantic subset; non-pilot cases listed as semantic-not-evaluated and excluded from the semantic denominator; execution→semantic gap computed only over semantic cases; semantic failure table names output/check/expected/observed/tolerance; tier and no-op counters rendered even when zero; Gate 2 section shows 27.5% and 32.5% and the main table contains no `Pass@Healed` column; all five interpretation caveats from [contracts/report.md](./contracts/report.md) are present, including “semantic pass is not universal correctness” and “semantic assertions never trigger repair.”

### Implementation for User Story 4

- [x] T047 [US4] Extend `RunSummary` and `aggregate()` in `grass_agent/reporting.py` with `cases_semantic`, `pass_at_executed`, `pass_at_semantic`, `semantic_not_evaluated`, `static_repairs_used`, `runtime_repairs_used`, `static_limit_total`, `runtime_limit_total`, `no_op_detected`, `no_op_rejected`, `no_op_pivots`, `accepted_duplicate_executions`, `assertion_failure_counts`, and `semantic_failures`, plus derived `pass_at_executed_rate`, `pass_at_executed_rate_semantic`, `pass_at_semantic_rate`, and `execution_semantic_gap`; keep every existing field and property.
- [x] T048 [US4] Add `render_gate3_markdown(summary, results)` to `grass_agent/reporting.py` with the header, the two-metric suite/overall table, the gap sentence over the semantic subset, and per-case rows showing both verdicts, attempts, static/runtime used, and duplicates.
- [x] T049 [US4] Add the semantic failure, tier usage, no-op detection, and interpretation caveats sections to `render_gate3_markdown()` in `grass_agent/reporting.py`; render `No semantic failures.` explicitly on a clean run and bold-warn when `accepted_duplicate_executions != 0`. The caveats MUST state that (1) a semantic pass covers only the declared assertions, not universal geospatial correctness; (2) exit status is not correctness; (3) generation is stochastic, so a one- or two-case difference is sampling noise; (4) semantic assertions never trigger repair; (5) pilot expectations come from reviewed reference scripts, not candidate output.
- [x] T050 [US4] Add the separated Gate 2 historical section and integrity evidence to `render_gate3_markdown()` in `grass_agent/reporting.py`: Gate 1 90.0%, `GATE2_PASS_AT_1 = 0.275`, `GATE2_PASS_AT_HEALED = 0.325`, healing gain via `format_gain`, a statement that Gate 2 used a different harness, `PERMANENT` hashes before/after, zero leaked scratch dirs, and the expectation-file hash; keep `render_markdown()` byte-compatible and preserve `EXIT_STATUS_CAVEAT`, `GATE1_STATIC_VALIDITY`, “different harnesses”, “Integrity evidence”, “Not evaluated”, and “1 completed of 3”.
- [x] T051 [US4] Wire reporting into `benchmarks/run_gate3.py`: write `benchmarks/gate3_report.md`, populate `benchmarks/output_execution/run_summary.json` with harness, model, GRASS version, dataset identity, tier budgets, suite and expectation hashes, review status, and `PERMANENT` before/after hashes, and implement `--report-only` to read only persisted results and produce byte-identical output with no model or GRASS.
- [x] T052 [US4] Extend `tests/test_reporting_gate3.py` with report-only reproducibility (live report vs regenerated report are identical), a semantic failure that contributes to `Pass@Executed` but not `Pass@Semantic`, and a zero-failure run that renders `No semantic failures.`
- [x] T053 [US4] Checkpoint: run `.venv/bin/python -m pytest tests/test_reporting_gate3.py -q`, then `--report-only` on a persisted pilot directory and `diff` the regenerated report against the live one.

**Checkpoint**: The dual-metric report is the delivery surface for Stories 1–3 and is reproducible without inference.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Prove the full contract on the real host and dataset.

- [x] T054 [P] Run the complete suite `.venv/bin/python -m pytest -q` against `tests/` and confirm all 255 pre-existing tests still pass unchanged plus every new Gate 3 test.
- [x] T055 [P] Run `.venv/bin/python -m benchmarks.run_gate3 --validate-pilot` (entry point `benchmarks/run_gate3.py`) and confirm the 10-case composition, 5/5 tier split, 4 mixed cases, raster/vector counts, expectation hash, and GRASS/dataset identity. Then break one reference-script hash and one environment field in a temporary expectations copy and confirm `--validate-pilot` exits `3` naming the drifted item.
- [x] T056 Run `.venv/bin/python -m benchmarks.run_gate3 --clean` (entry point `benchmarks/run_gate3.py`) (10-case pilot) and verify: both metrics present, `Pass@Semantic ≤ Pass@Executed`, 10 semantic cases, zero accepted duplicates, every semantic failure named with evidence, and no repair after a semantic verdict.
- [x] T057 Run `.venv/bin/python -m benchmarks.run_gate3 --all --clean` (entry point `benchmarks/run_gate3.py`) (40 cases) and verify 40 terminal cases, `Pass@Semantic` reported over the 10 semantic cases only, zero accepted duplicate executions, and no unhandled crash.
- [x] T058 Run `.venv/bin/python -m benchmarks.run_gate3 --report-only` (entry point `benchmarks/run_gate3.py`), diff against the live report, and confirm no diff and no model/GRASS invocation.
- [x] T059 Run `.venv/bin/python benchmarks/run_gate2.py --report-only` plus `.venv/bin/python -m pytest tests/test_cli_contract.py tests/test_reporting.py -q` and confirm Gate 2 wording and behaviour are unchanged.
- [x] T060 Verify `PERMANENT` hash under `~/grassdata/nc_basic_spm_grass7/` is byte-for-byte unchanged before/after and zero scratch directories leaked under `benchmarks/output_execution/` after each of: a completed pilot run, an operator-interrupted run (SIGINT), and a run containing a semantic-probe failure. Verify network isolation with a socket connection interceptor audit that records every `socket.connect` call and asserts zero outbound connections, run alongside execution in an offline environment (SC-009).
- [x] T061 Walk [quickstart.md](./quickstart.md) scenarios 1–10, record actual outputs against each expected result, and resolve every mismatch before declaring the feature done.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; T002 (constitution) should land before code review sign-off.
- **Foundational (Phase 2)**: Depends on Setup; **BLOCKS all user stories**.
- **US1 (Phase 3)**: Depends on Foundational. No dependency on US2–US4.
- **US2 (Phase 4)**: Depends on Foundational and US1's `run_case` structure. Final duplicate tier-charging depends on US3's ledger gate, but rejection, recording, and pivoting are independently testable before it.
- **US3 (Phase 5)**: Depends on Foundational and US2's history-aware `run_case` loop; replaces only the budget gate and resume-key construction.
- **US4 (Phase 6)**: Depends on US1 (semantic evidence) and US3 (ledger fields); renders correctly with empty evidence when run earlier.
- **Polish (Phase 7)**: Depends on all four stories.

### User Story Dependency Graph

```text
Setup → Foundational
                 ├─→ US1 (semantic oracle) ─────────────┐
                 ├─→ US2 (no-op memory) ─→ US3 (tiers) ─┤
                 └──────────────────────────────────────┴─→ US4 (report) → Polish
```

### Within Each User Story

- Tests first, expected to fail before implementation.
- Models/dataclasses before services; services before loop wiring; loop wiring before integration tests.
- Same-file tasks are strictly sequential: `results.py` (T005→T006→T007→T008→T009), `healing.py` (T031→T032→T033→T034→T035), `run_gate2.py` (T026→T036→T037→T041→T042→T043), `reporting.py` (T047→T048→T049→T050), `run_gate3.py` (T025→T051), `semantic.py` (T014→T015→T016), `semantic_probe.py` (T017→T018).

### Parallel Opportunities

- T003 runs alone in Setup.
- T011, T012, T013 are three independent new test files.
- T019, T020, T021 are three independent new pilot artifacts.
- T029 and T030 are two independent new test files.
- T039 (new CLI test file) and T040 (existing tier test file) are different files.
- T054 and T055 are independent verification commands.
- After Foundational, US1 can run in parallel with US2→US3 once `run_case` boundaries are agreed; avoid concurrent edits to `benchmarks/run_gate2.py`.

---

## Parallel Example: User Story 1

```bash
# Three independent test files, all first:
Task: "Create tests/test_semantic_spec.py for schema validation"
Task: "Create tests/test_semantic_probe.py with fake query output"
Task: "Create tests/test_pilot_suite.py for composition and naming"

# Three independent pilot artifacts:
Task: "Create benchmarks/benchmark_prompts_pilot10.json"
Task: "Create benchmarks/pilot_reference/*.py golden scripts"
Task: "Create benchmarks/derive_pilot_expectations.py"
```

## Parallel Example: User Story 2

```bash
Task: "Create tests/test_stateful_healing.py"
Task: "Create tests/test_noop_detection.py"
```

## Parallel Example: User Story 3

```bash
Task: "Create tests/test_gate3_cli.py"
Task: "Extend tests/test_budget_tiers.py with tier accounting"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 Setup and Phase 2 Foundational.
2. Complete Phase 3 US1: semantic models, probe, pilot suite, golden expectations, wrapper/executor handoff, and semantic-verdict termination.
3. **STOP and VALIDATE**: run the US1 independent test — a zero-exit script with a wrong raster mean must yield `Pass@Executed = true`, `Pass@Semantic = false`, a named assertion, and no repair.
4. This MVP already answers the Gate 3 question: did a successful script produce the right geospatial result?

### Incremental Delivery

1. Setup + Foundational → additive schema and config ready.
2. US1 → semantic correctness measured (MVP).
3. US2 → duplicate repairs eliminated and history-aware prompts.
4. US3 → static and runtime budgets independent, CLI compatible.
5. US4 → dual-metric report regenerable from persisted results.
6. Polish → full 10-case and 40-case evidence on the real dataset.

### Parallel Team Strategy

1. One developer owns Foundational schema (`results.py`, `config.py`) to avoid same-file conflicts.
2. After Foundational: Developer A takes US1 (pilot + probe + wrapper/executor), Developer B takes US2→US3 (`healing.py` then `run_gate2.py`), Developer C prepares US4 report tests and `reporting.py` against stub results.
3. Serialize all edits to `benchmarks/run_gate2.py` and `grass_agent/reporting.py`; everything else is file-disjoint.

---

## Notes

- `[P]` marks different files with no incomplete dependency.
- Existing 255 tests are never edited; new coverage lives in the new test files listed above (plus additive coverage in `tests/test_budget_tiers.py`).
- `case_result.json` stays at `schema_version: 1`; every new field is optional with a default.
- Semantic failures are report-only: no repair, no ledger charge, no script mutation.
- The semantic probe is read-only and runs inside the same scratch session before cleanup.
- Commit after each task or logical group; stop at every checkpoint to validate the story independently.

## Validation notes (2026-11-10)

- **T054/T060**: final suite is `394 passed`; `PERMANENT` hash before and after every run is
  `7ee9b49d11264d9497dd28358260dd5a7dccf719f2dbbc9a6c4d2b7fcd56630e`, matching
  `pilot_expectations.json`. No `tmp_*` mapsets and no `work_*` directories remained.
- **T055**: `--validate-pilot` prints the contracted summary and exits `0`; a deliberately
  drifted reference-script hash and a drifted GRASS version each exit `3` naming the item.
- **T056**: 10-case pilot (`qwen2.5-coder:7b`) → `Pass@Executed 8/10 (80.0%)`,
  `Pass@Semantic 6/10 (60.0%)`, 10 semantic cases, 0 accepted duplicate executions,
  20.0 pp execution→semantic gap. `pilot_tc_08` failed the binary-viewshed assertions
  (`value_range` observed 89.79–180 instead of 0–1) and `pilot_tc_33` missed
  `pilot_hospitals_raster`; both terminated at the semantic verdict with one attempt and
  an unchanged ledger. `pilot_tc_18` and `pilot_tc_32` exhausted the runtime tier with two
  rejected duplicate repairs each.
- **T057**: 40-case run (`qwen2.5-coder:3b`) → 40/40 terminal, `Pass@Executed 9/40 (22.5%)`,
  `Pass@Healed 11/40 (27.5%)`, 35 duplicates detected and 0 accepted for execution.
  `Pass@Semantic` is not defined in this run: every benchmark case is non-pilot and
  declares no assertions, so the semantic denominator is 0 and all 40 cases are reported
  as semantic-not-evaluated — exactly what `contracts/cli.md` ("--semantic with a
  non-pilot suite") and FR-009f require. The 10 semantically evaluated cases exist only in
  the pilot run.
- **T058**: `--report-only` reproduces both the pilot and the 40-case report byte-for-byte
  (`diff` empty) with no model or GRASS invocation.
- **T059**: the Gate 2 report-only run and `tests/test_cli_contract.py` +
  `tests/test_reporting.py` are unchanged.
