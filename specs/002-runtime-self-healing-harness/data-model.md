# Phase 1 Data Model: Gate 2 Execution Harness

**Date**: 2026-10-06 | **Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

This document defines the entities the harness persists, the artifact directory layout, the attempt state machine, and the atomicity/resumption rules. It is the authoritative shape reference for `grass_agent/results.py` and for [contracts/case-result.md](./contracts/case-result.md).

## 1. Entity: BenchmarkCase

The unit of evaluation. One per row in `benchmarks/benchmark_prompts_tier{1,2}.json`.

| Field | Type | Required | Source | Notes |
|---|---|---|---|---|
| `id` | string | yes | existing | Stable identifier, e.g. `tc_01`. Primary key within a suite. |
| `category` | string | yes | existing | `single_tool` \| `multi_step` \| `edge_case` |
| `prompt` | string | yes | existing | Natural-language task; fed verbatim to the model and to every repair prompt (FR-012) |
| `expected_tools` | array | yes | existing | Tier 1 flat list; tier 2 may nest lists of alternatives. **Not used for verdict** — FR-021 forbids correctness checking |
| `auxiliary_inputs` | array of string | no | **new (FR-001b)** | Filenames resolved under `benchmarks/fixtures/`. Absent means `[]` |
| `tier` | integer | no | tier-2 file header | Present in `benchmark_prompts_tier2.json`, absent in tier 1 |

**Auxiliary inputs** are the only sanctioned source of files beyond the dataset. A script that references a file which is neither in the dataset nor listed here MUST fail as *missing input map or layer* — the harness never synthesises it (clarification Q2).

**Fixture resolution rules**
- A bare filename resolves to `benchmarks/fixtures/<filename>`.
- A relative path resolves to `benchmarks/fixtures/<path>`.
- Any name escaping `benchmarks/fixtures/` (absolute path, or `..` traversal after normalisation) is rejected as a harness configuration error, not a benchmark failure.
- A directory-like fixture (shapefile) resolves every sibling sharing its stem: `boundary.shp` → `boundary.shp`, `.shx`, `.dbf`, `.prj`.
- CRS must match the dataset's. Fixtures are authored in EPSG:3358 (NAD83/HARN North Carolina, LCC, meters) to match `nc_basic_spm_*`; [contracts/cli.md](./contracts/cli.md) records the pre-flight check.

## 2. Entity: Attempt

One generation-and-evaluation cycle. Ordinals are 1-based: `attempt_1` is the initial generation, `attempt_2` and `attempt_3` are retries under the default budget.

| Field | Type | Notes |
|---|---|---|
| `ordinal` | integer | 1-based |
| `script_path` | path | `attempt_<n>.py` under the case dir |
| `prompt_tokens` | integer | `prompt_eval_count` from the local service; `0` when no inference occurred |
| `completion_tokens` | integer | `eval_count`; `0` when no inference occurred |
| `latency_s` | float | Wall-clock for generation **and** execution for this attempt (FR-018) |
| `static_issues` | array of string | Output of `validate_api`; non-empty means statically rejected |
| `outcome` | enum | See §3 |
| `exit_code` | integer \| null | From the inner wrapper status file; `null` if never executed |
| `signal_name` | string \| null | e.g. `SIGSEGV`; `null` unless crashed |
| `timed_out` | boolean | Whether the per-attempt wall-clock bound was hit |
| `failure_mode` | enum \| null | See §4; `null` on success |
| `failing_tool` | string \| null | Tool name parsed from the error, used to target RAG re-query (FR-011) |
| `stdout` / `stderr` | string | Full captured streams, verbatim |

**Ordering rule**: `prompt_tokens`/`completion_tokens` are `0` when the attempt reused a persisted Gate 1 script (`--reuse-artifacts`) or when generation failed before inference. Never estimated (R11).

## 3. Entity: AttemptOutcome

Four states. `static_rejected` and `runtime_failed` both consume one unit of the unified retry budget (FR-009a).

| Value | Meaning | Consumes budget | Reaches GRASS |
|---|---|---|---|
| `static_rejected` | `ast.parse` or `validate_api` failed | yes | no |
| `executed_ok` | Exit code 0, no signal, no timeout | no — terminal success | yes |
| `runtime_failed` | Non-zero exit with a classified failure mode | yes | yes |
| `crashed` | Terminated by a signal (SIGSEGV, SIGABRT, …) | yes | yes |
| `timeout` | Per-attempt wall-clock bound exceeded | yes | yes |

`crashed` and `timeout` are distinguished from `runtime_failed` for reporting because SC-003 and SC-012 assert on them specifically, but all three map to **failure mode `general_exception`** per FR-008 (the catch-all). The distinction lives in the outcome, not the failure mode.

**Detection note**: a crash inside a GRASS *module* is converted by `grass.script` to `CalledModuleError` and surfaces as an ordinary non-zero exit (R5). `crashed` therefore covers crashes in the Python layer, which is where Gate 2's generated code runs.

## 4. Entity: FailureMode

Exactly one of four values, assigned per failed attempt. Resolution is deterministic and follows the precedence in FR-008a, with the documented ordering refinement from R9/D8.

| Value | Trigger |
|---|---|
| `missing_input` | Raster/vector map not found, missing mapset, missing DB connection for a layer, missing table, `Invalid map <x>`, unreadable/unopenable input file or datasource, GDAL `ERROR <n>: … No such file` |
| `schema_misuse` | `Required parameter <x> not set`, `Sorry, <x> is not a valid parameter/option`, `Value <x> out of range for parameter <y>`, `option <x>: <y> exists. To overwrite`, mutually-exclusive-option errors, `Parse error` |
| `unknown_method` | `AttributeError: Tool <x> (…) not found`, `AttributeError: Tool or attribute <x> (…) not found`, `OSError: Cannot find the executable …`, positional-argument `TypeError` from the resolver, `module grass.tools has no attribute …` |
| `general_exception` | Everything else: Python exceptions, `ToolError` with no recognisable content, timeout, crash |

**Ordering decision (D8)**: `unknown_method` signatures are tested *before* the content categories. Rationale in R9 — the wording never collides with `ToolError` text, whereas leaving it until last would misfile every hallucinated method into the catch-all. Within the content categories the mandated precedence applies unchanged: `missing_input` → `schema_misuse` → `general_exception`.

**Invariant**: per-mode counts across a suite sum **exactly** to the number of failed attempts (SC-005a). Re-running classification over identical captured output yields the identical mode.

## 5. Entity: CaseResult

The persisted, resumable record of one case. One file: `benchmarks/output_execution/<tc_id>/case_result.json`. Schema in [contracts/case-result.md](./contracts/case-result.md).

| Field | Type | Notes |
|---|---|---|
| `tc_id` | string | |
| `tier` | integer \| null | |
| `category` | string | |
| `prompt` | string | Echoed so the artifact set is self-describing |
| `status` | enum | `in_progress` \| `complete` — see §6 |
| `resume_key` | object | `{model, max_retries, timeout, attempt1_source}` — see §7 |
| `attempts` | array of Attempt | Ordered, `ordinal` ascending |
| `pass_at_1` | boolean | `attempts[0].outcome == "executed_ok"` |
| `pass_at_healed` | boolean | Any attempt reached `executed_ok` |
| `failure_mode_transitions` | array of enum \| null | The ordered `failure_mode` of each failed attempt (SC-018 visibility) |
| `final_script` | path \| null | `final.py` when healed; `attempt_1.py` otherwise |
| `completed_at` | ISO-8601 string \| null | Set when `status` becomes `complete` |

**Invariant**: `len(attempts) ≤ max_retries + 1` (SC-017). `pass_at_healed` implies `pass_at_1` is `false` only when at least one later attempt succeeded.

## 6. State machine

```text
                  ┌──────────────────────────────────────────┐
                  │            CASE START                    │
                  │  attempt 1: generate (or reuse artifact) │
                  └───────────────────┬──────────────────────┘
                                      ▼
                            ┌───────────────────┐
              ┌────────────►│  static guard     │
              │             │  FR-001           │
              │             └─────────┬─────────┘
              │         rejected      │ pass
              │     ┌────────────────┘
              │     ▼                 ▼
              │ ┌──────────────┐  ┌────────────────────┐
              │ │stage: static │  │ execute in GRASS   │  FR-003..FR-007
              │ └──────┬───────┘  └─────────┬──────────┘
              │        │                    │
              │        │        executed_ok ┌┼──── crashed ─── timeout ───┐
              │        │              ┌─────┘│                          │
              │        │              ▼      ▼                          ▼
              │        │      ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
              │        │      │stage: success│  │stage: runtime│  │stage: runtime│
              │        │      │ TERMINAL     │  └──────┬───────┘  └──────┬───────┘
              │        │      └──────────────┘         │                 │
              │        │                              └────────┬────────┘
              │        ▼                                       ▼
              │   budget remaining? ── no ──► ┌──────────────────────────┐
              │        │ yes                  │ CASE COMPLETE (unhealed) │
              │        ▼                      └──────────────────────────┘
              │ ┌────────────────────────────┐
              └─┤ heal: re-query RAG (FR-011)│
                │ build repair prompt (FR-012)│  attempt n+1
                └────────────────────────────┘

  A case is only marked status=complete after its final attempt reaches a terminal
  state. Any attempt interrupted mid-flight leaves the file at status=in_progress,
  which the resume logic treats as "discard and restart from attempt 1" (FR-006a).
```

**Unified budget (FR-009a)**: `static_rejected`, `runtime_failed`, `crashed`, and `timeout` each decrement the same counter. A case may therefore exhaust its budget without ever executing — an intended, reported outcome (Assumptions).

## 7. Resume key

`CaseResult.resume_key` = `{model, max_retries, timeout, attempt1_source}`.

A persisted case is reused on resume **only if** all four fields match the current run exactly (SC-019). `attempt1_source` ∈ `{fresh, reuse_artifacts}`. Any mismatch → the case is discarded and rerun from attempt 1.

Rationale: a result produced under a different model, budget, timeout, or attempt-1 source is not comparable and must not be silently carried forward.

## 8. Atomic write protocol

Satisfies FR-006a and SC-018.

1. Write to `case_result.json.part` in the **same directory** (same filesystem, so `os.replace` is atomic).
2. `flush()` then `os.fsync()`.
3. `os.replace(part, case_result.json)` — atomic on POSIX.
4. Optionally fsync the containing directory for durability across power loss.

**Recovery**: on load, a `.part` file is discarded unconditionally. `case_result.json` is parsed with `json.loads`; a `JSONDecodeError` (torn write from a hard kill) causes the case to be treated as not completed and rerun from attempt 1. A case is reusable only when `status == "complete"`, the resume key matches, and every referenced artifact path exists.

**Write cadence**: `case_result.json` is written once per attempt (so an interrupted run preserves work up to the last completed attempt) and again at `complete`. `status` is `in_progress` until the final write. Per §6, an `in_progress` file is discarded on resume regardless of how many attempts it holds — this is what makes "restart the partial case from attempt 1" (clarification Q5) implementable.

## 9. Artifact directory layout

```text
benchmarks/output_execution/<tc_id>/
├── case_result.json        # atomic per-case record (resume key)
├── attempt_1.py            # initial script
├── attempt_1.stdout        # verbatim stdout stream, captured separately
├── attempt_1.stderr        # verbatim stderr stream, captured separately
├── attempt_1.log           # combined human-readable stdout + stderr + outcome header
├── attempt_2.py            # retry 1 (only if attempt 1 failed)
├── attempt_2.stdout
├── attempt_2.stderr
├── attempt_2.log
├── attempt_3.py            # retry 2
├── attempt_3.stdout
├── attempt_3.stderr
├── attempt_3.log
├── inner_wrapper.py        # copied in per attempt (D3)
├── status.json             # fork/waitpid crash record for the latest attempt
├── scratch/                # per-attempt working dir; fixtures staged here
│   └── points.geojson      #   (FR-001b) staged copies, never the originals
└── final.py                # copy of the last verified script, or attempt_1.py
```

The separate `.stdout` and `.stderr` files are **required**, not optional: [contracts/case-result.md](./contracts/case-result.md) records `stdout_path`/`stderr_path` per attempt and reuse rule R10 requires every referenced path to exist. Either file may be zero bytes — a successful run that printed nothing is valid — but both files must always be present, since the classifier operates on the same bytes the report cites (invariant I8). `attempt_<n>.log` is derived from them for human reading and is never the classification input.

Retains everything FR-019 requires: the final verified script, every intermediate failed attempt, and the execution logs, grouped per case so they can be found together.

`scratch/` is removed after each attempt; `inner_wrapper.py` and `status.json` are retained for diagnosis of the last attempt. If `attempt_<n>.log` shows a `crashed` outcome, `status.json` is the authoritative record of the signal.

## 10. Entity: RunSummary

Aggregate for one harness invocation. `benchmarks/execution_report.md` is rendered from it, and the persisted per-case `CaseResult` files are the source of truth — the report is regenerable without re-executing anything (FR-020, SC-013).

| Field | Type | Notes |
|---|---|---|
| `model` | string | e.g. `qwen2.5-coder:7b` |
| `suites` | array of string | Which tier files were covered |
| `cases_total` / `cases_completed` | integer | SC-018: `cases_total` may exceed `cases_completed` after an interrupt |
| `max_retries` / `timeout_s` | integer | Echoed from CLI |
| `attempt1_source` | enum | `fresh` \| `reuse_artifacts` — SC-015 requires this be stated |
| `pass_at_1` | float | `attempts[0].outcome == executed_ok` count / completed |
| `pass_at_healed` | float | Any `executed_ok` / completed |
| `failure_mode_counts` | object | Per-mode totals across all failed attempts |
| `failure_mode_transitions` | object | `mode_n → mode_{n+1}` counts, per SC/FR-018 reporting |
| `latency_s` | object | Per-attempt-ordinal mean, plus total |
| `tokens` | object | Prompt/completion totals and per-ordinal means |
| `resumed` | boolean | Whether any case was loaded rather than executed |
| `permanent_hash_before` / `permanent_hash_after` | string | SC-002 assertion evidence |
| `leaked_scratch_dirs` | array of string | SC-004: must be empty in a clean run |
| `limitations` | array of string | Always includes the FR-021 exit-status-not-correctness caveat (SC-014) |

**Gate 1 comparison** (FR-020): `gate1_static_validity` is read from the existing Gate 1 baseline (90.0% across the 40-case suite, constitution IV) and rendered beside `pass_at_1` and `pass_at_healed` for the same cases. Because the two are measured under different harnesses, the report labels them explicitly rather than presenting them as a single continuous scale.

**Invariant**: `failure_mode_counts` sum to the total number of failed attempts across all cases (SC-005a).

## 11. Regeneration

`benchmarks/execution_report.md` is a pure function of the persisted `case_result.json` files plus `RunSummary` metadata. `--report-only` (see [contracts/cli.md](./contracts/cli.md)) re-renders it without invoking the model or GRASS, satisfying SC-013's "without recomputing anything".