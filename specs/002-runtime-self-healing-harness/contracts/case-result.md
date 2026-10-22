# Contract: `case_result.json`

**Date**: 2026-10-06 | **Plan**: [../plan.md](../plan.md) | **Data model**: [../data-model.md](../data-model.md) | **CLI**: [cli.md](./cli.md)

Normative schema and persistence contract for the per-case record at `benchmarks/output_execution/<tc_id>/case_result.json`. This file is the resume unit (FR-006a) and the sole source of truth for report generation (SC-013).

## Schema

```jsonc
{
  "schema_version": 1,
  "tc_id": "tc_11",
  "tier": 2,
  "category": "multi_step",
  "prompt": "Import points.geojson vector features, extract the point where cat=1, …",
  "auxiliary_inputs": ["points.geojson"],

  "status": "complete",              // "in_progress" | "complete"
  "resume_key": {
    "model": "qwen2.5-coder:7b",
    "max_retries": 2,
    "timeout": 60,
    "attempt1_source": "fresh"       // "fresh" | "reuse_artifacts"
  },

  "pass_at_1": false,
  "pass_at_healed": true,

  "failure_mode_transitions": ["missing_input", null],   // null = recovered

  "final_script": "final.py",

  "attempts": [
    {
      "ordinal": 1,
      "script_path": "attempt_1.py",
      "log_path": "attempt_1.log",

      "prompt_tokens": 1842,
      "completion_tokens": 96,
      "latency_s": 44.2,

      "static_issues": [],
      "static_passed": true,

      "stage": "runtime",            // "static" | "runtime" | "success"
      "outcome": "runtime_failed",   // see data-model §3
      "exit_code": 1,
      "signal_name": null,
      "timed_out": false,

      "failure_mode": "missing_input",
      "failing_tool": "v_import",

      "error_excerpt": "ERROR: Unable to open input file <points.geojson>: No such file or directory",
      "stdout_path": "attempt_1.stdout",
      "stderr_path": "attempt_1.stderr"
    }
  ],

  "completed_at": "2026-10-06T14:22:31Z"
}
```

## Field semantics

| Field | Type | Required | Rules |
|---|---|---|---|
| `schema_version` | int | yes | Currently `1`. A persisted file with an unknown version is not reusable (treated as not completed) |
| `tc_id` | string | yes | Must equal the containing directory name |
| `tier` | int \| null | yes | `null` for tier-1 cases |
| `category` | string | yes | One of `single_tool`, `multi_step`, `edge_case` |
| `prompt` | string | yes | Echoed so the artifact set is self-describing |
| `auxiliary_inputs` | array of string | yes | May be `[]`. Mirrors the suite definition |
| `status` | enum | yes | `in_progress` until the case reaches a terminal state |
| `resume_key` | object | yes | All four fields required. See §Resume key |
| `pass_at_1` | bool | yes | `attempts[0].outcome == "executed_ok"` |
| `pass_at_healed` | bool | yes | `true` if **any** attempt reached `executed_ok` |
| `failure_mode_transitions` | array | yes | Length equals `attempts.length`. `null` marks the attempt that succeeded |
| `final_script` | path \| null | yes | Relative to the case directory |
| `attempts` | array | yes | Ordered by `ordinal`, ascending, contiguous from 1 |
| `completed_at` | ISO-8601 | yes when `status == "complete"` | `null` otherwise |

### Attempt fields

| Field | Type | Required | Rules |
|---|---|---|---|
| `ordinal` | int | yes | 1-based, contiguous |
| `script_path` / `log_path` | path | yes | Relative to the case directory; must exist |
| `prompt_tokens` / `completion_tokens` | int | yes | `≥ 0`. `0` when no inference occurred — never estimated (R11) |
| `latency_s` | float | yes | `≥ 0`. Generation plus execution |
| `static_issues` | array of string | yes | `validate_api` output; `[]` when clean |
| `static_passed` | bool | yes | `!static_issues` and `ast.parse` succeeded |
| `stage` | enum | yes | Which gate produced the outcome |
| `outcome` | enum | yes | `static_rejected`, `executed_ok`, `runtime_failed`, `crashed`, `timeout` |
| `exit_code` | int \| null | yes | From `status.json`. `null` if never executed |
| `signal_name` | string \| null | yes | Non-null only when `outcome == "crashed"` |
| `timed_out` | bool | yes | |
| `failure_mode` | enum \| null | yes | `null` iff `outcome == "executed_ok"` |
| `failing_tool` | string \| null | no | Parsed from the error; drives targeted RAG re-query (FR-011). `null` when no tool could be identified |
| `error_excerpt` | string \| null | yes | Verbatim failing line or the `ToolError` message. Feeds the repair prompt (FR-010) |
| `stdout_path` / `stderr_path` | path | yes | Full verbatim streams, written to **separate** files `attempt_<n>.stdout` and `attempt_<n>.stderr`. Both files must exist even when zero bytes |

## Invariants

These are assertions the harness enforces on load and the test suite verifies.

| # | Invariant | Spec ref |
|---|---|---|
| I1 | `len(attempts) ≤ max_retries + 1` | SC-017 |
| I2 | `ordinals` are contiguous `1..n` with no gaps or duplicates | data-model §2 |
| I3 | `failure_mode_transitions.length == attempts.length` | FR-018 |
| I4 | Every failed attempt has a non-null `failure_mode` from the four-value enum; `executed_ok` has `null` | FR-008 |
| I5 | Sum of per-mode counts across a suite equals the total failed attempts | SC-005a |
| I6 | `pass_at_healed` implies at least one `executed_ok`; `pass_at_1` implies `attempts[0].outcome == "executed_ok"` | SC-007 |
| I7 | `status == "complete"` iff the case reached a terminal state (budget exhausted or success) | FR-006a |
| I8 | `error_excerpt`, when present, is a verbatim substring of the captured `stderr` or `stdout` | FR-010 |

## Atomicity protocol

Writes are atomic. A reader never observes a partially written `case_result.json`.

```text
1. serialise to  case_result.json.part      (same directory ⇒ same filesystem)
2. f.flush(); os.fsync(f.fileno())
3. os.replace("case_result.json.part", "case_result.json")    # atomic on POSIX
4. fsync the containing directory                            # durability
```

**Write cadence**: once after each attempt completes, and once more when `status` becomes `complete`. Each write re-serialises the whole file — the document is small and whole-file replacement avoids partial-update ambiguity.

**`.part` files** are never read. Any `case_result.json.part` found at startup is deleted unconditionally.

## Recovery and resume rules

A persisted case is **reusable** only when all of the following hold. Any failure means the case is discarded and rerun from attempt 1.

| # | Condition | Rationale |
|---|---|---|
| R1 | `status == "complete"` | An `in_progress` file is a partial case — FR-006a requires restarting it from attempt 1 (clarification Q5) |
| R2 | `schema_version` is recognised | Forward/backward compatibility |
| R3 | `tc_id` matches the suite definition | Guards against a stale directory |
| R4 | `resume_key.model` equals the current `--model` | SC-019 |
| R5 | `resume_key.max_retries` equals the current `--max-retries` | SC-019 |
| R6 | `resume_key.timeout` equals the current `--timeout` | SC-019 |
| R7 | `resume_key.attempt1_source` equals the current mode | SC-019 |
| R8 | The file parses as JSON | A torn write from a hard kill yields `JSONDecodeError` → not reusable |
| R9 | Invariants I1–I8 hold | Structural corruption → not reusable |
| R10 | Every referenced artifact path exists and is readable | `final_script`, each `script_path`, `log_path`, `stdout_path`, `stderr_path`. Because reuse reads these paths, a case directory missing even a zero-byte `attempt_<n>.stdout` is **not** reusable |

Any single failure logs a reason at `INFO` and reruns the case. Rejection is silent-by-default to keep 40-case output readable; `--verbose` surfaces every reason.

The per-case artifact layout these paths resolve against is specified in [../data-model.md](../data-model.md) §9, which lists `attempt_<n>.stdout` and `attempt_<n>.stderr` as mandatory entries alongside the combined `attempt_<n>.log`.

## Initial-prompt inputs

The initial (attempt 1) prompt is built from the case definition plus the same run-level inventory snapshot used by repairs:

| Prompt element | Source |
|---|---|
| Original natural language task | `Benchmark Case.prompt` |
| Relevant tool documentation | RAG query keyed on the task (top-k) |
| Available dataset maps (FR-012b) | the run-level inventory snapshot, read once from `PERMANENT` |

**Map inventory in attempt 1 (FR-012b).** Attempt 1 is grounded with the `### Available Dataset Maps` block before any failure exists, because the dominant zero-shot failure is a hallucinated map name: the model cannot choose from maps it has never been shown. The block is identical to the repair block and is read once per run, then shared by the initial prompt and every repair prompt so the two can never disagree. Like FR-012a, it is best-effort: an unreadable dataset omits the block and the prompt is built without it.

## Repair-prompt inputs

The repair prompt (FR-012) is assembled from this record, never re-derived:

| Prompt element | Source field |
|---|---|
| Original natural language task | `CaseResult.prompt` |
| Previous failing script | contents of `attempts[n].script_path` |
| Exact error / traceback | `error_excerpt` plus the referenced `stderr_path` |
| Targeted tool documentation | fresh RAG query keyed on `attempts[n].failing_tool` (FR-011) |
| Available dataset maps (FR-012a) | live read of `PERMANENT/cellhd` (rasters) and `PERMANENT/vector` (vectors) on the target dataset |

When `failing_tool` is `null`, the retriever falls back to querying with `error_excerpt` itself. This fallback is required behaviour, not an error path: some failures (a bare `AttributeError` on a typo, a Python `TypeError`) carry no tool name.

**Map inventory (FR-012a).** The inventory is the dataset's actual raster and vector names, rendered into the repair prompt under `### Available Dataset Maps` with the lines `Available Rasters: [...]` and `Available Vectors: [...]`. It exists because a `missing_input` failure is otherwise unhealable: the four FR-012 elements name the task, the script, the error, and the tool docs, but never which maps exist, so a model that invents `bathymetry` learns only that the name was wrong and never that the intended map is `lakes`. The inventory is a property of the *dataset*, not of any case, so it is read once per run and cached. It is sourced from the project's `PERMANENT` mapset — the same source of truth GRASS uses — and is never model-generated. Reading is best-effort: if the dataset cannot be read, the block is omitted rather than the run failing. It is **required** for `missing_input` repairs (SC-006a) and **included whenever known** for every other failure mode. Via FR-012b the same block is also injected into every initial generation prompt (SC-006b), so attempt 1 is grounded against the dataset before a failure can occur.

## Report regeneration

`benchmarks/execution_report.md` is a pure function of the reusable `case_result.json` files plus run-level metadata. `--report-only` reconstructs every aggregate — pass rates, per-mode counts, transitions, latency, tokens — without invoking the model or GRASS (SC-013).

If a case directory is missing, corrupt, or non-reusable, it is reported as **not evaluated** in that run rather than silently omitted, so the denominator is always explicit.