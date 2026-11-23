# Phase 1 Data Model: Gate 3 Semantic Validation and Stateful Healing

**Date**: 2026-11-10 | **Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

This document defines every persisted and in-memory entity added or changed by Gate 3, the artifact layout, the tier state machine, and the invariants enforced on load. It is the authoritative shape reference for `grass_agent/results.py`, `grass_agent/semantic.py`, `grass_agent/healing.py`, and [contracts/case-result.md](./contracts/case-result.md).

Existing Gate 2 entities (`BenchmarkCase`, `Attempt`, `AttemptOutcome`, `FailureMode`, `CaseResult`, `ResumeKey`, `RunSummary`) are extended additively. No field is renamed or removed, and `schema_version` stays `1`.

## 1. Entity: BenchmarkCase (extended)

The unit of evaluation. Pilot cases use the same JSON file shape with additional fields.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Stable identifier. Pilot ids are `pilot_tc_XX`; benchmark ids remain `tc_XX` |
| `category` | string | yes | `single_tool` \| `multi_step` \| `edge_case` |
| `prompt` | string | yes | Natural-language task. Pilot prompts name every expected output |
| `expected_tools` | array | yes | Informational only; never used for a verdict |
| `auxiliary_inputs` | array of string | no | Fixtures resolved under `benchmarks/fixtures/` |
| `tier` | integer \| null | no | Benchmark tier (`1`, `2`); pilot cases also carry it |
| `source_id` | string | pilot only | Provenance, e.g. `tc_05`; the pilot id is derived from it |
| `source_suite` | string | pilot only | `tier1` \| `tier2` |
| `outputs` | array of OutputSpec | pilot only | Non-empty; every expected map is named here |
| `assertions` | array of AssertionSpec | pilot only | Non-empty; references a declared output |
| `target_dataset` | string | pilot only | Expected project family, e.g. `nc_basic_spm_grass7` |

**Validation rules**

- A pilot case MUST declare at least one output and at least one assertion.
- Every assertion's `output` MUST match a declared output name.
- Output names MUST be unique within a case and MUST appear verbatim in the prompt.
- Output names SHOULD start with `pilot_` to prevent collision with `PERMANENT` layers.
- `source_id` MUST resolve to an existing benchmark case in the declared `source_suite`.
- The pilot MUST contain exactly 10 cases, at least 4 per benchmark tier, at least one raster and one vector output, and at least 2 multi-step or mixed raster/vector cases.

## 2. Entity: OutputSpec

One declared output map.

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | GRASS map name |
| `type` | enum | yes | `raster` \| `vector` |
| `geometry` | enum \| null | vector only | `point` \| `line` \| `area` \| `boundary`; may instead be asserted by an AssertionSpec |

## 3. Entity: AssertionSpec

One declared check. The spec lives in the pilot suite; the expected value lives in `pilot_expectations.json`.

| Field | Type | Applies to | Meaning |
|---|---|---|---|
| `output` | string | both | Declared output name |
| `check` | enum | both | `non_null_count`, `value_range`, `mean`, `feature_count`, `geometry_type`, `required_columns` |
| `min` | number \| null | count checks | Minimum acceptable value; default `1` |
| `max` | number \| null | `value_range` | Maximum acceptable value |
| `min_value` | number \| null | `value_range` | Minimum acceptable value |
| `expected` | string \| null | `geometry_type` | Expected geometry |
| `columns` | array of string | `required_columns` | Case-sensitive required column names |
| `tolerance` | number \| null | `mean` | Relative tolerance; default `0.01` |
| `expected_source` | string | both | Only `reference`; forbids candidate-derived values |

**Check semantics**

| Check | Pass condition |
|---|---|
| `non_null_count` | `observed.n >= min` (default 1) |
| `value_range` | `observed.min >= min_value` and `observed.max <= max` |
| `mean` | `abs(observed.mean - expected.mean) <= tolerance * abs(expected.mean)` |
| `feature_count` | `observed.feature_count >= min` (default 1) |
| `geometry_type` | `observed.geometry == expected` |
| `required_columns` | every declared column is present in `observed.columns` |

`value_range` bounds may come from the expectations file instead of literal suite values; the contract requires one authoritative source per assertion. The suite MAY omit `min_value`/`max` and declare `"expected_source": "reference"`, in which case the reference bounds are used.

## 4. Entity: PilotExpectations

Frozen reference values, one file for the suite.

```jsonc
{
  "version": "1.0.0",
  "generated_at": "2026-11-10T12:00:00Z",
  "generator": "benchmarks/derive_pilot_expectations.py",
  "grass_version": "8.5.0",
  "dataset": {
    "project": "/home/.../nc_basic_spm_grass7",
    "permanent_hash": "f5290457…"
  },
  "cases": {
    "pilot_tc_05": {
      "reference_script": "benchmarks/pilot_reference/pilot_tc_05.py",
      "reference_script_sha256": "…",
      "outputs": {
        "pilot_slope": {
          "type": "raster",
          "n": 2025000,
          "min": 0.0,
          "max": 41.2,
          "mean": 4.81
        },
        "pilot_contours": {
          "type": "vector",
          "geometry": "line",
          "feature_count": 512,
          "columns": ["cat"]
        }
      }
    }
  }
}
```

**Rules**

- Generated only by `derive_pilot_expectations.py`, which executes reviewed golden scripts from `benchmarks/pilot_reference/`.
- The generator MUST NOT read `attempt_*.py`, `final.py`, or any candidate artifact.
- The file MUST be human-reviewed before a pilot run; `--validate-pilot` reports its hash and review status.
- A reference mismatch aborts the run before inference with exit `3`.
- Raster values are measured with `r.univar -g -r`; vector values with `v.info -t` and `v.info -c`.

## 5. Entity: Attempt (extended)

One generated candidate. Existing fields are unchanged.

| Field | Type | Required | Notes |
|---|---|---|---|
| `ordinal` | integer | yes | 1-based, contiguous |
| `script_path` / `log_path` / `stdout_path` / `stderr_path` | path | yes | As Gate 2 |
| `prompt_tokens` / `completion_tokens` / `latency_s` | numbers | yes | As Gate 2; duplicate attempts record `0` tokens |
| `static_issues` / `static_passed` | array / bool | yes | As Gate 2 |
| `stage` | enum | yes | `static` \| `runtime` \| `success` |
| `outcome` | enum | yes | As Gate 2, plus `no_op_duplicate` |
| `exit_code` / `signal_name` / `timed_out` | as Gate 2 | yes | A duplicate has `exit_code = null`, `signal_name = null`, `timed_out = false` |
| `failure_mode` / `failing_tool` / `error_excerpt` | as Gate 2 | yes | A duplicate uses `general_exception` and an excerpt naming the earlier duplicate ordinal |
| **`budget_tier`** | enum | yes | `initial` \| `static` \| `runtime`. Inferred on load for legacy records |
| **`duplicate`** | bool | yes | True iff rejected before execution |
| **`code_sha256`** | string \| null | yes | Hex digest; `null` only for a reused artifact with no readable code |
| **`ast_sha256`** | string \| null | yes | `null` when the code does not parse |
| **`new_maps`** | object | yes | `{"raster": [...], "vector": [...]}`, sorted; empty when not executed |
| **`semantic_evaluated`** | bool | yes | True only after a zero-exit attempt with a declared semantic spec |
| **`semantic_passed`** | bool \| null | yes | `null` when not evaluated |
| **`assertion_results`** | array of AssertionResult | yes | Serialized evidence; `[]` when not evaluated |
| **`pivot_used`** | bool | yes | True when the repair prompt for this attempt used parameter injection |

**Outcome extension**

| Value | Meaning | Reaches GRASS | Charges |
|---|---|---|---|
| `no_op_duplicate` | Candidate matched a previous byte/AST or both | no | Producing tier |

Existing outcomes (`static_rejected`, `executed_ok`, `runtime_failed`, `crashed`, `timeout`) are unchanged. `no_op_duplicate` is additive. A duplicate records `stage = "static"` because rejection happens before execution, while `budget_tier` still identifies the tier that produced it. If static validation ran, `static_passed`/`static_issues` record its result; a valid duplicate still has `static_passed = true` but is never executed.

## 6. Entity: AssertionResult

One evaluated check, persisted inside an attempt and copied to the case verdict evidence.

| Field | Type | Notes |
|---|---|---|
| `output` | string | Declared output name |
| `check` | enum | Same vocabulary as AssertionSpec |
| `expected` | number \| string \| array \| null | Frozen reference value or declared literal |
| `observed` | number \| string \| array \| null | Probe measurement |
| `tolerance` | number \| null | Relative mean tolerance |
| `passed` | bool | Verdict |
| `detail` | string | Bounded human-readable reason, especially on failure |
| `query` | string | Command or query id used, for reproducibility |

Assertion results are ordered by declared output order, then by declared check order. This ordering is persisted and rendered verbatim.

## 7. Entity: SemanticResult

The normalized outcome of the in-session probe.

| Field | Type | Notes |
|---|---|---|
| `evaluated` | bool | False when no spec was supplied or the attempt did not execute |
| `passed` | bool | True only when `evaluated` and every assertion passed |
| `case_id` | string | Pilot id |
| `new_maps` | object | Same shape as Attempt.new_maps |
| `outputs` | array of OutputResult | Per-output evidence |
| `error` | string \| null | `null`, `query_timeout`, `query_failed`, `no_values`, `missing_output`, `non_finite`, `probe_timeout` |
| `elapsed_s` | float | Probe wall-clock |

`OutputResult` carries `name`, `type`, `exists`, `observed` (n/min/max/mean or feature_count/geometry/columns), and `assertions`.

## 8. Entity: BudgetLedger

Persisted per case so used and remaining budget are reconstructible without rerunning.

```jsonc
{
  "static_limit": 2,
  "static_used": 1,
  "static_remaining": 1,
  "runtime_limit": 2,
  "runtime_used": 2,
  "runtime_remaining": 0
}
```

`*_remaining` is derived, persisted for report convenience, and must equal `limit - used`. `static_used` counts candidates with `budget_tier == "static"` (static repairs); `runtime_used` counts candidates with `budget_tier == "runtime"` (runtime repairs, including ones that failed static validation and never executed). The initial candidate is never counted. The ledger is recomputed from attempts on load and compared; a mismatch marks the record corrupt (not reusable).

## 9. Entity: CaseResult (extended)

| Field | Type | Required | Notes |
|---|---|---|---|
| Existing Gate 2 fields | unchanged | yes | `tc_id`, `tier`, `category`, `prompt`, `auxiliary_inputs`, `status`, `resume_key`, `pass_at_1`, `pass_at_healed`, `failure_mode_transitions`, `final_script`, `attempts`, `completed_at`, `schema_version` |
| **`pass_at_executed`** | bool | yes | A successful attempt exited 0 and created ≥1 new map |
| **`pass_at_semantic`** | bool \| null | yes | `null` iff not evaluated; otherwise true only when every assertion passed |
| **`semantic_evaluated`** | bool | yes | True iff a semantic spec was supplied and a successful attempt was probed |
| **`no_op_count`** | int | yes | Number of attempts with `duplicate == true`; equals the recomputed count |
| **`budget_ledger`** | BudgetLedger | yes | Per-tier used/remaining |
| **`harness_version`** | string | yes | `"gate3"`; `"gate2"` when loaded from a legacy record |

**Verdict derivation**

```text
pass_at_1        = attempts[0].outcome == executed_ok
pass_at_healed   = any(attempt.outcome == executed_ok)
pass_at_executed = any(attempt.outcome == executed_ok and attempt.new_maps != empty)
pass_at_semantic = null                       if not semantic_evaluated
                 = pass_at_executed and all assertions pass
failure_mode_transitions = [None if a.succeeded else a.failure_mode for a in attempts]
```

`pass_at_healed` remains the Gate 2 execution verdict for historical comparison and is **not** the Gate 3 `Pass@Executed` definition. A legacy record with no `new_maps` evidence has `pass_at_executed = pass_at_healed` and `harness_version = "gate2"`; it is never counted in Gate 3 semantic denominators.

**Important distinction**: an `executed_ok` attempt with an empty `new_maps` makes `pass_at_healed` true but leaves `pass_at_executed` false. The Gate 3 loop must terminate on `pass_at_executed`, not on `executed_ok` or `pass_at_healed`; otherwise a no-output success would end the case before the runtime repair. The existing `CaseResult.succeeded` property keeps its Gate 2 meaning and must not drive the Gate 3 loop.

## 10. Entity: ResumeKey (extended)

| Field | Type | Default | Notes |
|---|---|---|---|
| `model` | string | — | Existing |
| `max_retries` | int | — | Existing; retained as the legacy/shorthand value |
| `timeout` | int | — | Existing |
| `attempt1_source` | string | — | Existing |
| **`max_static_retries`** | int \| null | `null` | `null` normalises to `max_retries` for legacy matching |
| **`max_runtime_retries`** | int \| null | `null` | Same |
| **`harness`** | string | `"gate2"` | Gate 3 writes `"gate3"` |

`matches()` compares the effective tier values and the harness. A Gate 2 key never matches a Gate 3 key.

## 11. Entity: RepairTurn and RepairContext (extended)

`RepairTurn` is one entry in the ordered attempt history supplied to a repair prompt.

| Field | Type | Notes |
|---|---|---|
| `ordinal` | int | Attempt number |
| `budget_tier` | enum | `initial` \| `static` \| `runtime` |
| `code` | string | Full candidate code |
| `failure_mode` | string \| null | `null` on success |
| `error_excerpt` | string | Exact diagnostic |
| `stage` | enum | `static` \| `runtime` \| `success` |
| `duplicate` | bool | Whether the turn was rejected as a no-op |

`RepairContext` gains `attempt_history: list[RepairTurn]` (default `[]`) and `pivot: bool` (default false). The existing four constructor fields keep their order and meaning:
`prompt`, `code`, `error`, `docs`, then optional `inventory`, `history`, `pivot`.

**Rendering order**: task → tool documentation → inventory → previous attempts (metadata first, newest full code last) → no-repeat instruction → current failed code and error.

## 12. Entity: NoOpDigest

| Field | Type | Notes |
|---|---|---|
| `code_sha256` | string | Hex SHA-256 of line-ending-normalised bytes |
| `ast_sha256` | string \| null | Hex SHA-256 of the normalised AST dump; `null` if unparseable |
| `ordinal` | int | First attempt that produced this digest |

A case-level `NoOpIndex` holds two maps: `by_code[digest] -> ordinal` and `by_ast[digest] -> ordinal`. A candidate is a duplicate if either lookup hits. The index is seeded with the initial candidate and updated after every accepted or rejected attempt.

## 13. Entity: RunSummary (extended)

Additive aggregate fields:

| Field | Type | Notes |
|---|---|---|
| `cases_semantic` | int | Completed cases with `semantic_evaluated` |
| `pass_at_executed` | int | Count over all completed cases |
| `pass_at_semantic` | int | Count over semantic cases |
| `semantic_not_evaluated` | list[str] | Case ids excluded from the semantic denominator |
| `static_repairs_used` / `runtime_repairs_used` | int | Totals |
| `static_limit_total` / `runtime_limit_total` | int | Sum of per-case limits |
| `no_op_detected` / `no_op_rejected` / `no_op_pivots` | int | Duplicate lifecycle |
| `accepted_duplicate_executions` | int | Must be `0` |
| `assertion_failure_counts` | dict | Grouped by check type |
| `semantic_failures` | list[dict] | Per-case evidence for the report |

Derived properties: `pass_at_executed_rate`, `pass_at_executed_rate_semantic`, `pass_at_semantic_rate`, `execution_semantic_gap`.

## 14. Artifact layout

```text
benchmarks/output_execution/<case_id>/
├── case_result.json          # source of truth
├── attempt_1.py              # generated code, every attempt including duplicates
├── attempt_1.log             # combined human-readable log
├── attempt_1.stdout          # verbatim; may be zero bytes
├── attempt_1.stderr          # verbatim; may be zero bytes
├── attempt_1.maps.json       # new-map snapshot; only when executed
├── attempt_1.semantic.json   # probe result; only when a semantic spec was supplied and the child exited 0
├── status.json               # unchanged wrapper status
└── final.py                  # successful candidate, when any
```

Duplicate attempts MUST still have `.py`, `.log`, `.stdout`, and `.stderr` files so the existing artifact-presence rule (R10) holds. Their stdout/stderr are zero bytes by construction.

## 15. State machine

```text
CASE START
  │
  ▼
generate initial candidate  (budget_tier=initial, free)
  │
  ▼
static guard
  ├─ reject ──► static_limit > 0 ?
  │               ├─ yes: generate static repair (static_used = 1, budget_tier=static)
  │               │        └──────► static guard
  │               └─ no : TERMINAL static_exhausted
  └─ pass
       │
       ▼
  execute in fresh GRASS
       │
       ├─ fail / crash / timeout / exit 0 with empty new_maps
       │     │
       │     └─► runtime_limit > 0 ?
       │           ├─ yes: generate runtime repair (runtime_used += 1, budget_tier=runtime)
       │           │        └──────► static guard
       │           └─ no : TERMINAL runtime_exhausted
       │
       └─ exit 0 and new_maps non-empty
             │
             ▼
       semantic spec? ──no──► pass_at_executed=true, semantic_evaluated=false, TERMINAL success
             │ yes
             ▼
       probe (read-only, bounded) ──query failure──► semantic failure, no repair
             │
             ▼
       all assertions pass? ──yes──► pass_at_semantic=true, TERMINAL success
             │ no
             ▼
       pass_at_semantic=false, TERMINAL semantic_failed (no repair)
```

The same loop handles later candidates. A **static** repair that passes the static guard proceeds to execution; if it then fails at runtime, the next **runtime** repair is charged to `runtime_used` when generated. A **runtime** repair that fails the static guard does not execute and requests another runtime repair; the next candidate is still charged to `runtime_used`. `static_used` counts static repair candidates only, and `runtime_used` counts runtime repair candidates only.

Before every generated candidate enters the static guard, the no-op detector checks it. A duplicate:

```text
duplicate? ──yes──► charge producing tier, record no_op_duplicate, do not execute
                     │
                     ├─ budget remains → next prompt uses parameter pivot
                     └─ no budget       → TERMINAL no_op_exhausted
```

## 16. Invariants

| # | Invariant | Spec ref |
|---|---|---|
| I1 | `len(attempts) ≤ 1 + static_limit + runtime_limit` | FR-002b |
| I2 | Ordinals are contiguous `1..n` with no gaps or duplicates | FR-004a |
| I3 | `failure_mode_transitions.length == attempts.length` | FR-009d |
| I4 | Every failed attempt has a valid failure mode; `executed_ok` has `null`; a duplicate uses `general_exception` | FR-004 |
| I5 | `pass_at_1` and `pass_at_healed` agree with the attempts (legacy definitions) | Gate 2 |
| I6 | `status == "complete"` iff a terminal state was reached | FR-013 |
| I7 | Every referenced artifact exists, including zero-byte streams for duplicates | R10 |
| I8 | `error_excerpt` is a verbatim substring of a captured stream, the static diagnostic, or the harness's duplicate diagnostic | FR-004 |
| I9 | `budget_ledger.static_used ≤ static_limit` and `runtime_used ≤ runtime_limit` | FR-001 |
| I10 | `static_passed == false` implies `exit_code == null` (no GRASS launch). A `budget_tier == "runtime"` candidate with `static_passed == false` is charged to runtime and never executed. A `budget_tier == "static"` candidate with `static_passed == true` may execute; its execution outcome does not change its producing tier | FR-001a, FR-001c, FR-002a |
| I11 | `pass_at_semantic == true` implies `pass_at_executed == true` and `semantic_evaluated == true` | FR-009b |
| I12 | `semantic_evaluated == false` implies `pass_at_semantic is null` and `assertion_results == []` | FR-009f |
| I13 | Every declared output has exactly one existence check and at least one assertion result | FR-008b |
| I14 | `duplicate == true` implies `exit_code == null`, `timed_out == false`, and `new_maps` is empty. A duplicate is never executed even when `static_passed == true` | FR-006a |
| I15 | Recomputing verdicts, the ledger, and `no_op_count` from persisted attempts yields identical values | FR-013 |

**Enforcement**: `check_invariants()` raises `ResultValidationError` on any violation. `is_reusable()` treats a violation as corrupt and reruns the case from attempt 1.
