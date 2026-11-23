# Implementation Plan: Semantic Validation, Stateful Healing, and Two-Tier Retry Budget (Gate 3)

**Branch**: `003-semantic-validation-and-stateful-healing` | **Date**: 2026-11-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/003-semantic-validation-and-stateful-healing/spec.md`

## Summary

Gate 3 turns the Gate 2 execution harness into a geospatial semantic validator without weakening its isolation or breaking its 255-test contract. The plan makes four coordinated changes:

1. **Two independent repair budgets** — static (syntax/import/schema/output-contract) and runtime (non-zero exit, crash, timeout, missing/empty output). `--max-retries` remains a both-tier shorthand; new tier-specific flags override it.
2. **Stateful healing memory** — every case carries an ordered attempt history across both tiers, repair prompts include that history with an explicit no-repeat constraint, and deterministic byte/AST no-op detection rejects duplicate candidates before execution and pivots to parameter-list injection.
3. **A 10-case semantic pilot** — deterministic, output-producing cases drawn from both benchmark tiers, with an independent oracle that runs after successful execution inside the same scratch GRASS session and asserts raster statistics or vector topology/columns.
4. **Dual-metric reporting** — the main table shows `Pass@Executed` and `Pass@Semantic` with explicit denominators; Gate 2's `Pass@Healed` moves to a clearly separated historical comparison section.

The design deliberately keeps `case_result.json` at `schema_version: 1`, using additive optional fields and a new resume-key discriminator so all 255 existing tests remain green while old Gate 2 results are not silently reused for Gate 3.

## Technical Context

**Language/Version**: Python 3.11+ (repository virtual environment runs 3.13)

**Primary Dependencies**: Python standard library (`argparse`, `dataclasses`, `json`, `sqlite3`, `subprocess`, `hashlib`, `ast`), GRASS 8.5/8.6 CLI with `--tmp-mapset`, `grass.tools` for generated scripts, local Ollama (`qwen2.5-coder:7b`, `nomic-embed-text`), pytest

**Storage**: JSON per-case results (`benchmarks/output_execution/<case_id>/case_result.json`), run metadata (`run_summary.json`), attempt artifacts (`attempt_N.py`, `.stdout`, `.stderr`, `.log`, `semantic.json`), pilot definition (`benchmarks/benchmark_prompts_pilot10.json`), reference expectations (`benchmarks/pilot_expectations.json`), SQLite tool knowledge base (`data/grass_knowledge.db`), GRASS datasets/mapsets

**Testing**: pytest; 255 existing tests collected (`.venv/bin/python -m pytest --collect-only -q`); live-GRASS tests marked `slow`

**Target Platform**: Linux headless host; local GRASS installation; no network access

**Project Type**: CLI benchmark harness plus importable Python library

**Performance Goals**: 40-case benchmark completes with bounded attempts; max 5 generated candidates per case (1 initial + 2 static repairs + 2 runtime repairs); 120 s per execution attempt; 30 s per semantic query and 60 s per semantic probe; report regeneration from persisted results without model or GRASS

**Constraints**: 100% offline; all 255 pre-existing tests green; process isolation and `PERMANENT` read-only guard unchanged; `case_result.json` schema version 1 preserved; no external network calls; deterministic budget accounting and duplicate decisions

**Scale/Scope**: 40 benchmark cases across two tiers; 10 pilot cases for semantic assertions; 2 independent repair tiers; 1 local model stack; 1 target dataset (North Carolina sample)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Assessment |
|---|---|---|
| I. Core Mission & Scope | Offline, local, fully autonomous | **PASS** — no network path is introduced; oracle and repair use local GRASS and Ollama only. |
| II. Technology Stack & API Standards | Generated scripts use `grass.tools` exclusively | **PASS for generated code** — the static guard continues to reject legacy `grass.script`, `subprocess`, and raw CLI calls. The harness-side semantic probe may use `grass.script` read-only queries because it is infrastructure, not model output; this exemption is recorded in Complexity Tracking. |
| III. Zero-Chat & Pure Script Contract | Executable Python only | **PASS** — repair prompts and extraction retain the Zero-Chat system prompt; history rendering adds no prose to generated code. |
| IV. Phased Development Gates | Strictly ordered, verifiable milestones | **PASS** — the Gate 3 milestone is ratified by the applied MINOR amendment to constitution v1.3.0 (Gate 2 is now listed as completed, Gate 3 as current, and Gate 2 metrics remain historical). No code requirement is blocked. |
| V. Code Quality & Pre-flight Execution Safety | Self-contained scripts, ephemeral mapsets, zero mutation | **PASS** — `Executor` process isolation and the `PERMANENT` `chmod -w` guard are untouched. The semantic probe is read-only (`g.list`, `r.univar -g`, `v.info -t`, `v.info -c`) and runs in the same ephemeral session before cleanup. |

**Governance note**: The proposed amendment adds one bullet to Principle IV: Gate 3 — semantic validation of generated geospatial outputs, dual execution/semantic metrics, stateful healing memory, and independent static/runtime repair tiers. Gate 2's execution metrics remain reported in a historical comparison section. The constitution version becomes 1.3.0 with a migration note that no existing requirement changes.

## Project Structure

### Documentation (this feature)

```text
specs/003-semantic-validation-and-stateful-healing/
├── plan.md                       # This file
├── research.md                   # Phase 0 decisions and evidence
├── data-model.md                 # Entities, fields, invariants, state transitions
├── quickstart.md                 # Runnable validation scenarios
├── contracts/
│   ├── cli.md                    # Gate 3 CLI surface and precedence
│   ├── case-result.md            # Additive result schema and invariants
│   ├── pilot-suite.md            # Pilot JSON and assertion specification
│   ├── semantic-result.md        # In-session probe output contract
│   └── report.md                 # Metric definitions and report sections
└── tasks.md                      # Phase 2 output (not created here)
```

### Source Code (repository root)

```text
grass_agent/
├── config.py                     # MODIFY: tier budgets, pilot path, semantic timeout
├── results.py                    # MODIFY: additive attempt/case fields, per-tier invariants
├── healing.py                    # MODIFY: attempt history, no-op detector, pivot prompt
├── executor.py                   # MODIFY: semantic spec handoff, new-map capture
├── inner_wrapper.py              # MODIFY: map snapshot, in-session probe invocation
├── semantic.py                   # NEW: pilot/assertion models and result normalization
├── semantic_probe.py             # NEW: standalone read-only query engine
└── reporting.py                  # MODIFY: dual metrics, historical baseline, no-op/tier stats

benchmarks/
├── run_gate2.py                  # MODIFY: tier-aware loop, new flags, semantic integration
├── run_gate3.py                  # NEW: Gate 3 entry point and pilot defaults
├── benchmark_prompts_pilot10.json# NEW: 10-case semantic pilot
├── pilot_reference/              # NEW: human-reviewed golden scripts, one per pilot case
├── derive_pilot_expectations.py  # NEW: independent reference-run expectation generator
├── pilot_expectations.json       # NEW (generated, human-reviewed): frozen expected values
├── execution_report.md           # UNCHANGED: Gate 2 report
└── gate3_report.md               # GENERATED: Gate 3 report with Gate 2 historical section

config.py                         # NO CHANGE: remains Gate 1 GenerationConfig; Gate 3 settings live in grass_agent/config.py

tests/
├── test_budget_tiers.py          # NEW: tier accounting and independence
├── test_stateful_healing.py      # NEW: history rendering and prompt constraints
├── test_noop_detection.py        # NEW: byte/AST duplicates, pivot, zero accepted duplicates
├── test_gate3_cli.py             # NEW: new flags, precedence, backward compatibility
├── test_semantic_spec.py         # NEW: pilot schema validation and assertion models
├── test_semantic_probe.py        # NEW: parser/result logic with fake sessions
├── test_pilot_suite.py           # NEW: composition, output naming, assertions
├── test_reporting_gate3.py       # NEW: dual metrics, denominators, historical section
├── test_integration_semantic.py  # NEW (slow): live GRASS semantic pass/fail
└── existing 255 tests            # UNCHANGED
```

**Structure Decision**: Keep the existing single-project layout. Gate 3 adds modules beside the Gate 2 modules rather than introducing a new package or service. The CLI remains under `benchmarks/`, and the reusable logic remains under `grass_agent/`. This minimizes import churn and preserves the existing test topology.

### File change matrix

| File | Action | Phase | Purpose |
|---|---|---|---|
| `grass_agent/config.py` | Modify | 1 | Tier budgets, semantic timeouts, pilot paths, harness discriminator, env parsing |
| `config.py` (repository root) | **No change** | — | This is Gate 1's `GenerationConfig`; Gate 3 adds no generation parameters. Confirmed by reading the file: model/RAG settings only |
| `grass_agent/results.py` | Modify | 1, 2 | Additive attempt/case fields, per-tier invariants, ledger, verdicts, legacy inference |
| `grass_agent/healing.py` | Modify | 2 | Attempt history, history rendering, no-op detector, parameter pivot |
| `benchmarks/run_gate2.py` | Modify | 1, 2, 4 | Tier flags, tier-aware loop, duplicate handshake, optional `--semantic`; public API preserved |
| `benchmarks/run_gate3.py` | New | 1, 3, 4 | Gate 3 entry point, pilot defaults, semantic mode, validation, Gate 3 report |
| `benchmarks/benchmark_prompts_pilot10.json` | New | 3 | Exactly 10 deterministic pilot cases with outputs and assertions |
| `benchmarks/derive_pilot_expectations.py` | New | 3 | Independent reference-run generator; refuses candidate artifacts |
| `benchmarks/pilot_reference/*.py` | New | 3 | Human-reviewed golden scripts, one per pilot case |
| `benchmarks/pilot_expectations.json` | New (generated) | 3 | Frozen, reviewed expected values plus environment identity |
| `grass_agent/semantic.py` | New | 3 | Pilot/assertion models, suite validation, probe-result normalization |
| `grass_agent/semantic_probe.py` | New | 3 | Standalone read-only query engine run inside the GRASS session |
| `grass_agent/inner_wrapper.py` | Modify | 3 | Map snapshot, probe invocation, `maps.json`/`semantic.json` |
| `grass_agent/executor.py` | Modify | 3 | Semantic spec handoff, probe grace, `new_maps`/`semantic` on the result |
| `grass_agent/reporting.py` | Modify | 4 | Gate 3 renderer, dual metrics, tier/no-op stats, Gate 2 historical section |
| `tests/test_budget_tiers.py` | New | 1 | Tier accounting and independence |
| `tests/test_gate3_cli.py` | New | 1 | Flags, precedence, backward compatibility |
| `tests/test_stateful_healing.py` | New | 2 | History rendering and no-repeat instruction |
| `tests/test_noop_detection.py` | New | 2 | Byte/AST duplicates, pivot, zero accepted duplicates |
| `tests/test_semantic_spec.py` | New | 3 | Pilot schema and assertion models |
| `tests/test_semantic_probe.py` | New | 3 | Query parsing and failure modes with fake sessions |
| `tests/test_pilot_suite.py` | New | 3 | Composition, output naming, expectation coverage |
| `tests/test_integration_semantic.py` | New (`slow`) | 3 | Live GRASS semantic pass/fail and report-only verdict |
| `tests/test_reporting_gate3.py` | New | 4 | Dual metrics, denominators, Gate 2 section |
| Existing 255 tests | **Unchanged** | — | Zero-regression contract |

## Complexity Tracking

| Violation / Extra Complexity | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Gate 3 is not named in Constitution Principle IV | Gate 3 is a distinct milestone with its own semantic oracle and metrics | Calling the work a Gate 2 extension would obscure the new correctness contract and conflict with the user's explicit Gate 3 scope. Resolution: MINOR amendment to v1.3.0. |
| Harness-side probe uses `grass.script` for read-only queries | Stable text parsing for `r.univar -g`, `v.info -t`, and `v.info -c` inside the same session | `grass.tools` is mandated for **generated** scripts; its structured return surface is less stable for these metadata queries. The probe never writes and never sees model output. |
| `case_result.json` stays at schema version 1 | Existing `test_integration_smoke.py` asserts `schema_version == 1`; zero regression forbids a bump | Bumping to version 2 would break an existing test. Additive optional fields plus a `harness` discriminator in `ResumeKey` prevent old Gate 2 results from being reused for Gate 3. |
| Semantic probe is embedded in the execution wrapper | Assertions must see the exact scratch mapset produced by the candidate | A second `grass` session cannot see the destroyed temp mapset; preserving the mapset would weaken cleanup and isolation guarantees. |
| History renderer truncates older code under a context budget | Full history can crowd out the current error and the model's context | Dropping old attempts loses failure evidence. The renderer keeps every failure mode, error excerpt, and duplicate status, truncating only old code to a deterministic digest/excerpt. |

## Phase 0: Outline & Research

Phase 0 resolved every technical unknown. The full decision log, alternatives, and evidence are in [research.md](./research.md). Key decisions:

- **In-session oracle**: the forked `inner_wrapper.py` snapshots map names before the child, and after a zero-exit child runs a read-only probe in the same GRASS session. No second session, no mapset preservation.
- **New-map detection**: `g.list` restricted to the current scratch mapset before and after execution; set difference is the `new_maps` evidence for `Pass@Executed`.
- **No-op detection**: SHA-256 of line-ending-normalized bytes plus SHA-256 of a normalized AST dump (docstrings stripped); the detector sees the initial candidate and every attempt from both tiers.
- **Compatibility strategy**: additive fields with defaults, per-tier invariant inference from the existing `stage`/`outcome` fields, `max_retries` as both-tier shorthand, and a `harness` discriminator in `ResumeKey`.
- **Pilot feasibility**: the North Carolina dataset provides the required rasters (`elevation`, `elevation_shade`, `landuse`, `geology`, `lakes`, `soils`, `basins`) and vectors (`streams`, `roadsmajor`, `geology`, `hospitals`, `elev_points`, `census`, `schools`, `firestations`). The 10 selected cases are all deterministic and output-producing.
- **Oracle authority**: expected values come from human-reviewed golden scripts run independently of the candidate, frozen into `pilot_expectations.json`; default mean tolerance is 1% relative, with per-case overrides.
- **Vector semantics**: feature count and geometry come from topology (`v.info -t`); required columns come from `v.info -c`. The two checks are deliberately separate.

**Output**: `research.md` with all decisions and no unresolved `NEEDS CLARIFICATION` markers.

## Phase 1: Design & Contracts

Phase 1 produced the following artifacts:

- [data-model.md](./data-model.md) — entity fields, relationships, validation rules, invariants I1–I12, and the case state machine.
- [contracts/cli.md](./contracts/cli.md) — flag surface, budget precedence, exit codes, and backward-compatibility rules.
- [contracts/case-result.md](./contracts/case-result.md) — additive JSON fields, schema-version policy, per-tier ledger, semantic evidence.
- [contracts/pilot-suite.md](./contracts/pilot-suite.md) — pilot JSON schema, assertion semantics, expected-value authority.
- [contracts/semantic-result.md](./contracts/semantic-result.md) — in-session probe output, query commands, failure modes.
- [contracts/report.md](./contracts/report.md) — metric definitions, denominators, report sections, historical baseline.
- [quickstart.md](./quickstart.md) — prerequisites, commands, and four end-to-end validation scenarios.

### Gate 3 metric definitions

| Metric | Definition | Denominator |
|---|---|---|
| `Pass@Executed` | The successful candidate exits 0 **and** creates at least one new map in the scratch mapset. | All completed cases in the run. |
| `Pass@Executed` (semantic subset) | Same definition, restricted to cases that declare semantic assertions. | Completed pilot cases. |
| `Pass@Semantic` | `Pass@Executed` is true **and** every declared assertion passes. | Completed pilot cases only. |
| `Pass@1` | First candidate succeeds under the legacy execution definition. | All completed cases (historical comparison). |
| `Pass@Healed` | Any candidate succeeds under the legacy execution definition. | All completed cases (historical comparison). |

A semantic assertion failure is report-only. It terminates the case at the semantic verdict, never generates a repair prompt, and never consumes either budget.

## Implementation Phases

### Phase 1 — Two-tier budget and CLI contract

**Goal**: Separate static and runtime repair accounting and expose it without breaking the existing CLI contract.

**Changes**:

- `grass_agent/config.py`
  - Add `max_static_retries: int = 2`, `max_runtime_retries: int = 2`, `pilot_suite: str = "benchmarks/benchmark_prompts_pilot10.json"`, `semantic_query_timeout_s: int = 30`, `semantic_probe_timeout_s: int = 60`, `semantic_probe_grace_s: int = 5`, `harness: str = "gate2"`, `pilot_expectations: str = "benchmarks/pilot_expectations.json"`, and `semantic_enabled: bool = False`.
  - `run_gate3` overrides `harness` to `"gate3"`; `run_gate2` keeps `"gate2"` even when `--semantic` is supplied, so Gate 2 results remain reusable by Gate 2 and are never mistaken for Gate 3.
  - Add `GRASS_MAX_STATIC_RETRIES` and `GRASS_MAX_RUNTIME_RETRIES` environment parsing.
  - Implement resolved precedence: CLI tier flags > CLI `--max-retries` > env tier vars > `GRASS_MAX_RETRIES` > defaults. `max_retries` remains stored for compatibility but is not the effective runtime ceiling.
- `grass_agent/results.py`
  - Add `Attempt.budget_tier` (`"initial"`, `"static"`, `"runtime"`), `duplicate`, `code_sha256`, `ast_sha256`, `new_maps`, `semantic_evaluated`, `semantic_passed`, `assertion_results`, `pivot_used`.
  - Add `CaseResult.pass_at_executed`, `pass_at_semantic`, `semantic_evaluated`, `no_op_count`, `budget_ledger`, `harness_version`.
  - Add `ResumeKey.max_static_retries`, `ResumeKey.max_runtime_retries`, `ResumeKey.harness` (all defaulted for old callers).
  - Update `recompute_verdicts()` to derive the two new verdicts; keep `pass_at_1` and `pass_at_healed` unchanged.
  - Update `check_invariants()` to enforce per-tier ceilings. Old attempts infer their tier from `stage`/`outcome`; the legacy `max_retries` argument is interpreted as both tier budgets, which preserves every existing invariant test.
  - Keep `SCHEMA_VERSION = 1`.
- `benchmarks/run_gate2.py`
  - Add `--max-static-retries` and `--max-runtime-retries`; validate negatives with exit code 2.
  - Resolve `--max-retries` as both-tier shorthand, then apply tier overrides.
  - Replace the single-budget loop with the charge-on-generate algorithm:
    - the initial candidate is free;
    - a static failure requests a static repair, and the generated static repair consumes one static unit;
    - a runtime failure or exit-0-with-no-new-map requests a runtime repair, and the generated runtime repair consumes one runtime unit;
    - a runtime-tier repair that fails static validation remains charged to runtime, is not executed, and never launches GRASS;
    - terminal when the requested tier has no remaining unit; the maximum is one initial candidate plus both tier limits.
  - Build the resume key with both tier budgets and `harness="gate2"` for `run_gate2` (`"gate3"` for `run_gate3`), so Gate 2 results remain reusable by Gate 2 while Gate 3 runs never reuse Gate 2 results.
- `tests/test_budget_tiers.py` (new)
  - static exhaustion never calls the executor;
  - static repairs do not reduce runtime repairs;
  - runtime repairs do not replenish static;
  - a runtime-tier static-invalid repair is charged to runtime and does not launch GRASS;
  - exit-0-with-no-new-map triggers a runtime repair that consumes the runtime tier;
  - max 5 candidates per case.
- `tests/test_gate3_cli.py` (new)
  - new flags parse and validate;
  - `--max-retries` shorthand sets both tiers;
  - tier overrides win;
  - existing 255 tests remain untouched and green.

**Checkpoint**: `pytest -q` is green (255 existing + new); a stub run proves a static-only failure never invokes `Executor.execute`.

### Phase 2 — Stateful healing memory and no-op prevention

**Goal**: Make repair prompts history-aware and reject deterministic duplicates before execution.

**Changes**:

- `grass_agent/healing.py`
  - Add `RepairTurn` (attempt number, budget tier, code, failure mode, error excerpt, static/runtime status, duplicate flag) and `RepairContext.attempt_history`.
  - Extend `RepairContext.to_user_message()` with a bounded `### Previous Attempts` block and the exact instruction: `DO NOT repeat previous scripts or failed parameter combinations.`
  - Add `NoOpDetector`:
    - normalize line endings;
    - SHA-256 byte digest;
    - AST parse, strip module/class/function docstrings, dump with `annotate_fields=False, include_attributes=False`, SHA-256;
    - duplicate if either digest matches any prior attempt.
  - Add `Healer.build_context(..., history, pivot=False)` and `Healer.parameter_list(tool)`; the pivot prompt injects the knowledge-base parameter list and a “change the approach” constraint.
  - Add `Healer.repair(..., pivot=False)` and record the pivot flag in `RepairAttempt`.
  - Preserve the existing four FR-012 elements and the inventory block; existing `RepairContext` tests must pass.
- `benchmarks/run_gate2.py`
  - Maintain `history` across both tiers.
  - Before executing any candidate, check the detector. A duplicate is written as an attempt artifact but is **not executed**; it records `duplicate=True`, consumes the reserved tier unit, and sets the next prompt to pivot.
  - If the pivot is also a duplicate, or no budget remains, terminate as an unresolved no-op failure.
- `grass_agent/results.py`
  - Persist `duplicate`, `code_sha256`, `ast_sha256`, and `pivot_used`; the generated code remains the `attempt_N.py` artifact referenced by `script_path`.
- `tests/test_stateful_healing.py` (new)
  - full history appears in the prompt;
  - the no-repeat instruction is present verbatim;
  - each prior failure mode/error excerpt survives;
  - context truncation preserves metadata and the newest full code.
- `tests/test_noop_detection.py` (new)
  - byte-identical duplicate rejected;
  - formatting/comment-only duplicate rejected;
  - docstring-only duplicate rejected;
  - a genuinely changed parameter is not a duplicate;
  - pivot prompt includes the parameter list;
  - duplicate consumes the correct tier;
  - a 40-case stub run accepts zero duplicates for execution.

**Checkpoint**: injected duplicate tests pass; a 40-case stub run reports zero accepted duplicates.

### Phase 3 — Pilot suite and semantic oracle

**Goal**: Add a trustworthy, independent geospatial oracle for 10 cases.

**Changes**:

- `benchmarks/benchmark_prompts_pilot10.json` (new)
  - Exactly 10 cases, 5 from benchmark Tier 1 and 5 from Tier 2.
  - At least two multi-step or mixed raster/vector cases; the selected set has four.
  - Every prompt names its `pilot_*` output maps and their types.
  - Each case declares `source_id`, `tier`, `category`, `outputs`, and assertions.
- `benchmarks/derive_pilot_expectations.py` (new)
  - Runs human-reviewed golden scripts in a disposable GRASS session.
  - Queries `r.univar -g -r` and `v.info -t/-c`; `-r` is mandatory so expectations are measured over each raster's own region rather than the session's computational region.
  - Emits `benchmarks/pilot_expectations.json` for human review; never uses the candidate script as the oracle.
  - Records GRASS version and dataset identity with the expectations.
- `grass_agent/semantic.py` (new)
  - Dataclasses: `RasterAssertion`, `VectorAssertion`, `OutputSpec`, `CaseSemantics`, `AssertionResult`, `SemanticResult`.
  - `load_pilot_suite()` and `validate_pilot_suite()` enforce composition, unique output names, prompt naming, and valid assertion fields.
  - `normalize_probe_result()` converts the standalone probe JSON into harness entities.
- `grass_agent/semantic_probe.py` (new, standalone)
  - Read-only query engine executed inside the GRASS session after a zero-exit child.
  - Raster: `r.univar -g -r map=<name>` → `n`, `min`, `max`, `mean`, computed over the map's own region so a candidate's `g.region` calls cannot move the reference target.
  - Vector: `v.info -t map=<name>` → topology counts and geometry; `v.info -c map=<name>` → column names.
  - Checks: non-null count > 0; min/max within declared bounds; mean within declared tolerance; vector feature count > 0; geometry type matches; required columns present; declared outputs exist.
  - Writes structured JSON with expected/observed evidence and a bounded error field; never writes maps.
- `grass_agent/inner_wrapper.py` (modify)
  - Snapshot `g.list type=raster mapset=.` and `g.list type=vector mapset=.` before forking the child.
  - After a zero-exit child, compute `new_maps`, run the probe with `semantic_probe_timeout_s`, and write `maps.json` and `semantic.json`.
  - If the child exits non-zero or crashes, skip the probe and leave `new_maps` empty.
  - Always return the child's status so crash detection is unchanged.
- `grass_agent/executor.py` (modify)
  - Accept an optional `semantic_spec` and `case_id`.
  - Copy `semantic_probe.py` and the spec into the workdir, build the wrapper command, and read `maps.json`/`semantic.json` into `ExecutionResult`.
  - When a semantic spec is present, extend the outer communicate deadline by `semantic_probe_grace_s` so a successful child followed by a bounded probe is not misclassified as a timeout. The generated script's own bound remains `timeout_s`; the added grace is only large enough for the probe.
  - Add `ExecutionResult.new_maps` and `ExecutionResult.semantic`.
  - Do not change process group handling, timeout enforcement, crash interpretation, `PERMANENT` hashing, or the guard.
- `benchmarks/run_gate2.py` / `benchmarks/run_gate3.py`
  - `run_gate3.py` is a thin Gate 3 entry point: defaults to the pilot suite, enables semantic evaluation, and writes the Gate 3 report.
  - The shared `run_case` passes the case's semantic spec to the executor, records `new_maps` and assertion results, sets `pass_at_executed`/`pass_at_semantic`, and stops at a semantic failure without a repair.
  - Non-pilot cases run with no semantic spec and report `semantic_evaluated=False`.
- `tests/test_semantic_spec.py`, `tests/test_semantic_probe.py`, `tests/test_pilot_suite.py` (new)
  - schema/composition validation;
  - raster and vector parser tests with fake `r.univar`/`v.info` output;
  - missing output, zero features, wrong geometry, missing column, out-of-range mean, query timeout;
  - pilot composition and prompt/output naming.
- `tests/test_integration_semantic.py` (new, `slow`)
  - one live pilot case passes all assertions;
  - one live script exits 0 but writes an empty raster → `Pass@Executed=false`, semantic not evaluated or failed as appropriate;
  - one live script writes a wrong mean → `Pass@Executed=true`, `Pass@Semantic=false`, no repair attempt.

**Pilot selection**:

| Pilot ID | Source | Tier | Workflow | Declared outputs | Assertions |
|---|---|---|---|---|---|
| `pilot_tc_01` | `tc_01` | 1 | single-tool | `pilot_streams_buffer` (vector area) | feature count > 0; geometry area (the buffer output has no attribute table, so no column assertion) |
| `pilot_tc_05` | `tc_05` | 1 | multi-step, mixed | `pilot_slope` (raster), `pilot_contours` (vector line) | slope non-null > 0, range 0–90, expected mean; contours count > 0, geometry line, `cat` |
| `pilot_tc_06` | `tc_06` | 1 | multi-step, mixed | `pilot_streams_buffer_100m` (vector area), `pilot_streams_buffer_raster` (raster) | vector count > 0, geometry area (buffer has no attribute table); raster non-null > 0 |
| `pilot_tc_08` | `tc_08` | 1 | single-tool edge | `pilot_viewshed` (raster) | non-null > 0; range 0–1; expected mean (prompt requires binary visibility, golden script uses `-b`) |
| `pilot_tc_09` | `tc_09` | 1 | single-tool edge | `pilot_elevation_double` (raster) | non-null > 0; reference range ≈115–305; mean = 2× the default-region `elevation` mean |
| `pilot_tc_12` | `tc_12` | 2 | single-tool | `pilot_relief` (raster) | non-null > 0; range 0–255; expected mean |
| `pilot_tc_14` | `tc_14` | 2 | single-tool | `pilot_roads_clean` (vector line) | count > 0; geometry line; required `cat`, `ROAD_NAME` |
| `pilot_tc_18` | `tc_18` | 2 | single-tool | `pilot_geology_dissolved` (vector area) | count > 0; geometry area; required `cat`, `GEO_NAME` |
| `pilot_tc_32` | `tc_32` | 2 | multi-step, mixed | `pilot_steep_slope` (raster), `pilot_steep` (vector area) | slope non-null > 0, expected mean; steep count > 0, geometry area, `cat` |
| `pilot_tc_33` | `tc_33` | 2 | multi-step, mixed | `pilot_hospitals_raster` (raster), `pilot_distance` (raster) | both non-null > 0; distance min ≥ 0; expected mean |

**Checkpoint**: pilot validator passes; a live pilot case produces `semantic.json`; a semantic failure does not create a repair prompt or consume either budget.

### Phase 4 — Reporting, integration, and verification

**Goal**: Deliver the dual-metric report and prove the invariants end to end.

**Changes**:

- `grass_agent/reporting.py`
  - Keep `render_markdown()` byte-compatible for the Gate 2 renderer so the existing reporting tests and `--report-only` Gate 2 behaviour are unchanged.
  - Add `render_gate3_markdown()`: dual metrics, semantic evidence, tier/no-op statistics, and a separate Gate 2 historical section.
  - Extend `RunSummary` with `pass_at_executed`, `pass_at_semantic`, `semantic_evaluated`, `static_repairs`, `runtime_repairs`, `no_op_detected`, `no_op_rejected`, `no_op_pivots`, `accepted_duplicate_executions`, and rates.
  - Main Gate 3 table: exactly `Pass@Executed` (all completed) and `Pass@Semantic` (semantic subset), each with its denominator, plus the execution→semantic gap computed over the semantic subset, duplicate counts, and tier usage. The semantic-subset execution rate is stated in the gap note, not as a third named metric column.
  - Semantic failure section: output, check, expected, observed, tolerance, verdict.
  - Separate Gate 2 historical section: Gate 1 90.0%, `Pass@1`, `Pass@Healed`, healing gain.
  - Preserve existing constants and strings required by tests: `EXIT_STATUS_CAVEAT` first line, `GATE1_STATIC_VALIDITY`, `GATE2_PASS_AT_1 = 0.275`, `GATE2_PASS_AT_HEALED = 0.325`, `format_gain`, “different harnesses”, “Integrity evidence”, “Not evaluated”, “1 completed of 3”.
- `benchmarks/run_gate3.py` (new)
  - `python -m benchmarks.run_gate3` defaults to the pilot suite and semantic mode.
  - Passes `harness="gate3"`, tier budgets, pilot suite identity, GRASS version, and dataset identity into `run_summary.json`.
  - Supports `--report-only`, `--clean`, `-k`, `--max-static-retries`, `--max-runtime-retries`, and `--validate-pilot`.
- `benchmarks/run_gate2.py`
  - Keep all public functions/classes used by existing tests: `build_parser`, `resolve_config`, `load_selected_cases`, `static_guard`, `main`.
  - Accept `--semantic` (default off) so Gate 2 behavior is unchanged unless requested.
- `tests/test_reporting_gate3.py` (new)
  - dual metrics and denominators;
  - `Pass@Semantic ≤ Pass@Executed` on the semantic subset;
  - non-pilot cases excluded from the semantic denominator;
  - Gate 2 historical section present;
  - no-op and tier counters rendered;
  - report regenerated from persisted results.
- `tests/test_integration_semantic.py` (extend new file)
  - end-to-end pilot case with persisted semantic evidence.
- Full verification:
  - `pytest -q` — 255 existing + new tests.
  - `python -m benchmarks.run_gate3 --clean` — 10-case pilot, dual metrics, zero accepted duplicates.
  - `python -m benchmarks.run_gate3 --suite benchmarks/benchmark_prompts_tier1.json --suite benchmarks/benchmark_prompts_tier2.json` or the 40-case default — zero accepted no-op duplicates.
  - `python -m benchmarks.run_gate3 --report-only` — identical metrics without model/GRASS.
  - `PERMANENT` hash before/after unchanged; zero leaked scratch directories; a socket connection interceptor audit records zero `socket.connect` calls during an offline-environment run.

**Checkpoint**: all success criteria met; report shows both metrics and the Gate 2 baseline; no-op count is zero.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Existing tests encode the old unified-budget wording | Do not edit existing tests. The per-tier invariant infers tiers from legacy `stage`/`outcome`, so the 4-runtime-failure ceiling test still raises, while mixed static/runtime sequences become valid. New tests cover the new semantics. |
| Schema bump breaks `test_integration_smoke.py` | Keep `schema_version: 1`; add optional fields and a `harness` discriminator in `ResumeKey`. Old Gate 2 results are not reused for Gate 3. |
| Semantic probe perturbs the scratch session | Probe runs only after a zero-exit child, uses read-only queries, has its own timeout, and never writes maps. Any probe failure is a semantic failure, not a harness crash. |
| Duplicate detection produces false positives | Byte/AST equality is deterministic; a changed tool or parameter changes the AST and is not a duplicate. Only formatting, comments, and docstrings are normalized away. |
| Context window overflow from full history | Keep every failure mode/error excerpt; truncate only older code to a digest/excerpt; always include the newest full code. |
| Pilot expected values drift with GRASS/dataset revisions | Freeze expectations with GRASS version and dataset identity; default 1% relative tolerance; treat reference mismatch as a suite defect, not a model failure. |
| Semantic failures accidentally trigger healing | `run_case` stops at the semantic verdict; `FR-001e`/`FR-008g` tests assert no repair prompt and no budget consumption. |
| Report refactor breaks existing assertions | Additive sections; keep existing constants, headings, and phrases; new tests assert compatibility. |
| `run_gate2` refactor breaks CLI tests | Keep public function signatures and aliases; add optional flags with defaults; run existing CLI contract tests unchanged. |

## Post-Design Constitution Check

| Principle | Post-design result |
|---|---|
| I. Offline | **PASS** — no network code; pilot oracle and probe are local. |
| II. Modern API | **PASS** — generated/repaired code is still statically rejected for legacy imports; the read-only probe is harness infrastructure and is documented as such. |
| III. Zero-Chat | **PASS** — repair system prompt and extraction unchanged; history is context, not prose. |
| IV. Phased Gates | **PASS with amendment** — Gate 3 is ratified by the v1.3.0 amendment; Gate 2 metrics remain in the historical section. |
| V. Safety | **PASS** — `Executor` process isolation, timeout/killpg, `PERMANENT` hashing, and the `chmod -w` guard are untouched; probe is read-only. |

## Definition of Done

- [ ] All 255 pre-existing tests pass unchanged; new tests cover tiers, history, no-op detection, pilot schema, semantic assertions, and dual reporting.
- [ ] `case_result.json` separates static and runtime attempts and records used/remaining budgets per tier.
- [ ] A 40-case stub/benchmark run accepts zero duplicate repairs for execution; every duplicate is recorded and rejected before execution.
- [ ] The 10-case pilot contains at least four benchmark Tier 1 and four benchmark Tier 2 cases, at least two multi-step/mixed cases, and every prompt names its outputs.
- [ ] Semantic assertions cover raster non-null count, min/max range, and mean tolerance; vector feature count, geometry type, and required columns.
- [ ] Semantic failures are report-only: no repair prompt, no tier consumption, no script mutation.
- [ ] The Gate 3 report shows `Pass@Executed` and `Pass@Semantic` with both denominators and a separate Gate 2 `Pass@Healed` comparison.
- [ ] `PERMANENT` is byte-for-byte unchanged and no scratch artifacts remain after success, failure, interrupt, or probe failure.
- [ ] All validation, repair, and reporting paths run offline through local GRASS and Ollama; a socket connection interceptor audit records zero `socket.connect` calls, and every case reports its benchmark tier and repair-tier usage separately.
