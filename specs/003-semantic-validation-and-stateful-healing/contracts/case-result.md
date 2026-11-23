# Contract: `case_result.json` (Gate 3 additive extension)

**Date**: 2026-11-10 | **Plan**: [../plan.md](../plan.md) | **Data model**: [../data-model.md](../data-model.md) | **CLI**: [cli.md](./cli.md)

Normative schema and persistence contract for the per-case record at `benchmarks/output_execution/<case_id>/case_result.json`. This file remains the resume unit and the sole source of truth for report generation.

## Compatibility policy

- `schema_version` stays **`1`**. A version bump would break the existing smoke test, so Gate 3 evolves the document additively.
- Every new field has a default and is optional on load. Old records load unchanged.
- No existing field is renamed, removed, or repurposed.
- Legacy attempts without `budget_tier` infer it: ordinal `1` → `initial`; `stage == "static"` → `static`; otherwise `runtime`.
- Legacy cases without `harness_version` load as `"gate2"`, have `semantic_evaluated = false`, `pass_at_semantic = null`, and `pass_at_executed = pass_at_healed`.
- The file remains atomic: write `.part`, `fsync`, `os.replace`, `fsync` the directory.

## Schema

```jsonc
{
  "schema_version": 1,
  "harness_version": "gate3",
  "tc_id": "pilot_tc_05",
  "tier": 1,
  "category": "multi_step",
  "prompt": "Compute slope ... write pilot_slope (raster) and pilot_contours (vector) ...",
  "auxiliary_inputs": [],

  "status": "complete",
  "resume_key": {
    "model": "qwen2.5-coder:7b",
    "max_retries": 2,
    "max_static_retries": 2,
    "max_runtime_retries": 2,
    "timeout": 120,
    "attempt1_source": "fresh",
    "harness": "gate3"
  },

  "pass_at_1": false,
  "pass_at_healed": true,
  "pass_at_executed": true,
  "pass_at_semantic": false,
  "semantic_evaluated": true,
  "no_op_count": 0,

  "budget_ledger": {
    "static_limit": 2,
    "static_used": 1,
    "static_remaining": 1,
    "runtime_limit": 2,
    "runtime_used": 1,
    "runtime_remaining": 1
  },

  "failure_mode_transitions": ["missing_input", null],

  "final_script": "final.py",

  "attempts": [
    {
      "ordinal": 1,
      "budget_tier": "initial",
      "script_path": "attempt_1.py",
      "log_path": "attempt_1.log",
      "stdout_path": "attempt_1.stdout",
      "stderr_path": "attempt_1.stderr",

      "prompt_tokens": 1842,
      "completion_tokens": 96,
      "latency_s": 44.2,

      "static_issues": [],
      "static_passed": true,
      "stage": "runtime",
      "outcome": "runtime_failed",
      "exit_code": 1,
      "signal_name": null,
      "timed_out": false,

      "failure_mode": "missing_input",
      "failing_tool": "v_import",
      "error_excerpt": "ERROR: Raster map <hospitals> not found",

      "duplicate": false,
      "code_sha256": "3f2a…",
      "ast_sha256": "9b41…",
      "pivot_used": false,

      "new_maps": {"raster": [], "vector": []},
      "semantic_evaluated": false,
      "semantic_passed": null,
      "assertion_results": []
    }
  ],

  "completed_at": "2026-11-10T14:22:31Z"
}
```

## Field semantics

### Case fields

| Field | Type | Required | Rules |
|---|---|---|---|
| `schema_version` | int | yes | `1`; an unknown version is not reusable |
| `harness_version` | string | yes | `"gate2"` or `"gate3"`; written by the entry point |
| `tc_id` | string | yes | Equals the containing directory name |
| `tier` | int \| null | yes | Benchmark tier; `null` for legacy tier-1 records |
| `category` | string | yes | `single_tool` \| `multi_step` \| `edge_case` |
| `prompt` | string | yes | Echoed verbatim |
| `auxiliary_inputs` | array of string | yes | May be `[]` |
| `status` | enum | yes | `in_progress` until terminal |
| `resume_key` | object | yes | See below |
| `pass_at_1` | bool | yes | `attempts[0].outcome == "executed_ok"` |
| `pass_at_healed` | bool | yes | Any attempt reached `executed_ok` (Gate 2 verdict) |
| `pass_at_executed` | bool | yes | Any attempt exited 0 **and** produced a new map |
| `pass_at_semantic` | bool \| null | yes | `null` iff not evaluated; otherwise all assertions passed **and** `pass_at_executed` |
| `semantic_evaluated` | bool | yes | True iff a semantic spec was supplied and a successful attempt was probed |
| `no_op_count` | int | yes | Number of duplicate attempts for the case |
| `budget_ledger` | object | yes | Per-tier used/remaining; must equal the recomputed value |
| `failure_mode_transitions` | array | yes | Length equals `attempts.length`; `null` marks success |
| `final_script` | path \| null | yes | `final.py` on success, else `null` or the last candidate |
| `attempts` | array | yes | Ordered by ordinal, contiguous from 1 |
| `completed_at` | ISO-8601 \| null | yes | Set when `status == "complete"` |

### Resume key

| Field | Type | Default | Rules |
|---|---|---|---|
| `model` | string | — | Current model id |
| `max_retries` | int | — | Legacy/shorthand budget, retained for Gate 2 callers |
| `max_static_retries` | int \| null | `null` | `null` normalises to `max_retries` |
| `max_runtime_retries` | int \| null | `null` | Same |
| `timeout` | int | — | Current per-attempt timeout |
| `attempt1_source` | string | — | `fresh` \| `reuse_artifacts` |
| `harness` | string | `"gate2"` | `"gate3"` for Gate 3 runs |

### Attempt fields

| Field | Type | Required | Rules |
|---|---|---|---|
| `ordinal` | int | yes | 1-based, contiguous |
| `budget_tier` | enum | yes | `initial` \| `static` \| `runtime`; inferred for legacy records |
| `script_path` / `log_path` / `stdout_path` / `stderr_path` | path | yes | Relative; all must exist, even at zero bytes |
| `prompt_tokens` / `completion_tokens` | int | yes | `≥ 0`; `0` when no inference occurred |
| `latency_s` | float | yes | `≥ 0`; generation plus execution |
| `static_issues` | array of string | yes | `[]` when clean |
| `static_passed` | bool | yes | Syntax and API/schema checks passed |
| `stage` | enum | yes | `static` \| `runtime` \| `success` |
| `outcome` | enum | yes | `static_rejected`, `executed_ok`, `runtime_failed`, `crashed`, `timeout`, `no_op_duplicate` |
| `exit_code` | int \| null | yes | `null` when never executed, including duplicates |
| `signal_name` | string \| null | yes | Non-null only when `outcome == "crashed"` |
| `timed_out` | bool | yes | False for duplicates |
| `failure_mode` | enum \| null | yes | `null` iff `executed_ok`; duplicates use `general_exception` |
| `failing_tool` | string \| null | no | Drives targeted RAG and the parameter pivot |
| `error_excerpt` | string \| null | yes | Verbatim diagnostic; for duplicates it names the matched ordinal |
| `duplicate` | bool | yes | True iff rejected before execution |
| `code_sha256` | string \| null | yes | Hex SHA-256 of line-ending-normalised bytes |
| `ast_sha256` | string \| null | yes | Hex SHA-256 of the normalised AST dump; `null` if unparseable |
| `pivot_used` | bool | yes | True when this candidate's repair prompt used parameter injection |
| `new_maps` | object | yes | `{"raster": [...], "vector": [...]}`, sorted; empty when not executed |
| `semantic_evaluated` | bool | yes | True only after a probed successful attempt |
| `semantic_passed` | bool \| null | yes | `null` when not evaluated |
| `assertion_results` | array | yes | Ordered; `[]` when not evaluated |

## Invariants

| # | Invariant | Spec ref |
|---|---|---|
| I1 | `len(attempts) ≤ 1 + static_limit + runtime_limit` | FR-002b |
| I2 | Ordinals contiguous `1..n` | FR-004a |
| I3 | `failure_mode_transitions.length == attempts.length` | FR-009d |
| I4 | Failed attempts have a valid failure mode; `executed_ok` has `null`; duplicates use `general_exception` | FR-004 |
| I5 | `pass_at_1` and `pass_at_healed` agree with the attempts | Gate 2 |
| I6 | `status == "complete"` iff terminal | FR-013 |
| I7 | Every referenced artifact exists | Gate 2 R10 |
| I8 | `error_excerpt` is a verbatim substring of a captured stream, the static diagnostic, or the harness's duplicate diagnostic | FR-004 |
| I9 | `static_used ≤ static_limit` and `runtime_used ≤ runtime_limit` | FR-001 |
| I10 | `static_passed == false` implies `exit_code == null`. A `budget_tier == "runtime"` candidate with `static_passed == false` is charged to runtime and never executed; a `budget_tier == "static"` candidate with `static_passed == true` may execute, and its execution outcome does not change its producing tier | FR-001a, FR-001c, FR-002a |
| I11 | `pass_at_semantic == true` implies `pass_at_executed == true` and `semantic_evaluated == true` | FR-009b |
| I12 | `semantic_evaluated == false` implies `pass_at_semantic == null` and no assertion results | FR-009f |
| I13 | Every declared output has an existence result and at least one assertion result | FR-008b |
| I14 | `duplicate == true` implies `exit_code == null`, `timed_out == false`, and empty `new_maps` | FR-006a |
| I15 | Recomputing the ledger, `no_op_count`, and verdicts from attempts yields identical values | FR-013 |

Violations raise `ResultValidationError`. The record is then treated as corrupt and is not reusable.

## Atomicity protocol

Unchanged from Gate 2:

```text
1. serialise to case_result.json.part   (same directory)
2. flush + os.fsync
3. os.replace(part, case_result.json)   (atomic on POSIX)
4. fsync the containing directory
```

Write cadence: after each attempt, and once more when `status` becomes `complete`. Any stale `.part` file is deleted at startup.

## Recovery and resume rules

A persisted case is reusable only when all hold. Any failure reruns from the initial candidate.

| # | Condition |
|---|---|
| R1 | `status == "complete"` |
| R2 | `schema_version` is recognised |
| R3 | `tc_id` matches the suite definition |
| R4 | `resume_key.model` matches |
| R5 | Effective `max_static_retries` matches |
| R6 | Effective `max_runtime_retries` matches |
| R7 | `resume_key.timeout` matches |
| R8 | `resume_key.attempt1_source` matches |
| R9 | `resume_key.harness` matches the current entry point |
| R10 | The file parses as JSON |
| R11 | I1–I15 hold |
| R12 | Every referenced artifact exists and is readable |
| R13 | `budget_ledger` equals the recomputed ledger |

`--verbose` surfaces every rejection reason. Rejection is otherwise silent per case.

## Prompt inputs

### Initial prompt

Unchanged from Gate 2: task, retrieved tool documentation, and the run-level dataset inventory.

### Repair prompt

| Element | Source |
|---|---|
| Original task | `CaseResult.prompt` |
| Complete attempt history | `attempts[0..n]`, ordered |
| Previous code | Full for the newest attempt; digest + bounded excerpt for older ones |
| Exact error / diagnostic | `error_excerpt` and the referenced stream |
| Targeted tool docs | Fresh RAG query keyed on `failing_tool`, falling back to the error text |
| Dataset inventory | Live read of `PERMANENT/cellhd` and `PERMANENT/vector` |
| No-repeat instruction | `DO NOT repeat previous scripts or failed parameter combinations.` |
| Pivot parameter table | Included only when `pivot == true`; knowledge-base signature, required/allowed parameters, and options |

The prompt never includes candidate output as an expected value, and never includes the semantic assertions. Semantic verification is not a repair channel.

## Example: duplicate attempt

```jsonc
{
  "ordinal": 3,
  "budget_tier": "runtime",
  "script_path": "attempt_3.py",
  "log_path": "attempt_3.log",
  "stdout_path": "attempt_3.stdout",
  "stderr_path": "attempt_3.stderr",
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "latency_s": 0.0,
  "static_issues": [],
  "static_passed": true,
  "stage": "runtime",
  "outcome": "no_op_duplicate",
  "exit_code": null,
  "signal_name": null,
  "timed_out": false,
  "failure_mode": "general_exception",
  "failing_tool": "v_buffer",
  "error_excerpt": "duplicate of attempt 2 (AST digest 9b41…)",
  "duplicate": true,
  "code_sha256": "3f2a…",
  "ast_sha256": "9b41…",
  "pivot_used": true,
  "new_maps": {"raster": [], "vector": []},
  "semantic_evaluated": false,
  "semantic_passed": null,
  "assertion_results": []
}
```
