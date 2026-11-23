# Contract: Gate 3 Report

**Date**: 2026-11-10 | **Plan**: [../plan.md](../plan.md) | **Data model**: [../data-model.md](../data-model.md) | **CLI**: [cli.md](./cli.md)

Normative contract for `benchmarks/gate3_report.md` and the summary object that feeds it. The report is a pure function of persisted `case_result.json` files plus `run_summary.json`; `--report-only` must reproduce it without model inference or GRASS execution.

## Renderer split

| Function | Output | Purpose |
|---|---|---|
| `render_markdown(summary, results)` | unchanged Gate 2 report | Kept byte-compatible for existing tests and Gate 2 report-only runs |
| `render_gate3_markdown(summary, results)` | Gate 3 report | Dual metrics, semantic evidence, tier/no-op statistics, Gate 2 historical section |
| `aggregate(results, ...)` | `RunSummary` | Additive aggregation; existing fields and properties preserved |

Gate 3 selects `render_gate3_markdown`; Gate 2 keeps `render_markdown`. A report states which renderer produced it.

## Metric definitions

| Metric | Definition | Numerator | Denominator |
|---|---|---|---|
| `Pass@Executed` | The successful attempt exited 0 and created at least one new map in the scratch mapset | Cases with `pass_at_executed = true` | All completed cases |
| `Pass@Executed` (semantic subset) | Same definition, restricted to cases with `semantic_evaluated = true` | Semantic cases with `pass_at_executed = true` | Completed semantic cases |
| `Pass@Semantic` | `pass_at_executed = true` **and** every declared assertion passed | Cases with `pass_at_semantic = true` | Completed semantic cases only |
| Execution→semantic gap | `Pass@Executed` (semantic subset) − `Pass@Semantic` | Difference | Percentage points over the semantic subset |
| `Pass@1` | Legacy Gate 2 zero-shot verdict | `attempts[0].pass_at_executed` | All completed cases |
| `Pass@Healed` | Legacy Gate 2 any-attempt execution verdict | Any attempt `pass_at_executed` | All completed cases |

**Hard invariants**

- `Pass@Semantic ≤ Pass@Executed` over the semantic subset.
- A case with `semantic_evaluated = false` is never in the semantic numerator or denominator.
- A semantic failure is not counted as an execution failure.
- No metric depends on filesystem iteration order.

## Report layout

### Header

```markdown
# Gate 3 Report — Semantic Validation & Stateful Healing

- **Model**: `qwen2.5-coder:7b`
- **GRASS**: `8.5.0`
- **Dataset**: `nc_basic_spm_grass7` (`permanent_hash`: `f529…`)
- **Suites**: `benchmark_prompts_pilot10.json`
- **Cases**: 10 completed of 10
- **Static tier**: limit 2, used 3, remaining 7 case-slots
- **Runtime tier**: limit 2, used 5, remaining 15 case-slots
- **Pilot expectations**: `sha256:…` (reviewed)
- **Resume**: yes / no
```

### Main Gate 3 metric table

Exactly the two required metrics. No `Pass@Healed` column and no third named rate.

```markdown
## Gate 3 metrics

| Suite | Cases | Pass@Executed | Pass@Semantic | Semantic cases |
|---|---|---|---|---|
| benchmark_prompts_pilot10.json | 10 | 7/10 = 70.0% | 5/10 = 50.0% | 10 |
| **Overall** | **10** | **7/10 = 70.0%** | **5/10 = 50.0%** | **10** |

Execution→semantic gap over the semantic subset: 7/10 (70.0%) − 5/10 (50.0%) = **20.0 pp**.
```

If a run includes non-pilot cases, the table still shows exactly the two metrics and states both denominators:

```markdown
| Suite | Cases | Pass@Executed (all) | Pass@Semantic (semantic cases) | Semantic cases |
|---|---|---|---|---|
| tier1 + tier2 | 40 | 13/40 = 32.5% | 5/10 = 50.0% | 10 |
```

`Pass@Semantic` is always shown with its own denominator, never over all cases. The semantic-subset execution rate appears only in the gap sentence, because it is the comparison basis, not a third headline metric.

### Semantic failures

One row per failed assertion, grouped by check type.

```markdown
## Semantic failures

| Case | Output | Check | Expected | Observed | Tolerance | Verdict |
|---|---|---|---|---|---|---|
| pilot_tc_33 | pilot_distance | mean | 40470.5 | 31022.9 | 1% | ❌ |
| pilot_tc_08 | pilot_viewshed | value_range | 0–1 | 0–180 | — | ❌ |
```

Then a summary:

```markdown
| Check | Failures |
|---|---|
| mean | 2 |
| value_range | 1 |
| geometry_type | 0 |
| required_columns | 0 |
| feature_count | 0 |
| non_null_count | 1 |
```

An empty table is rendered as `No semantic failures.` so a clean run is explicit.

### Tier usage

```markdown
## Repair budget usage

| Tier | Limit (sum) | Used | Remaining | Cases exhausting tier |
|---|---|---|---|---|
| static | 20 | 3 | 17 | 0 |
| runtime | 20 | 5 | 15 | 1 |
```

Limits are summed across completed cases. Used counts attempts whose `budget_tier` matches. Additional rows show attempts by ordinal and by benchmark tier.

### No-op detection

```markdown
## No-op duplicate detection

| Metric | Value |
|---|---|
| Duplicate candidates detected | 4 |
| Rejected before execution | 4 |
| Accepted duplicates executed | 0 |
| Cases resolved by parameter pivot | 3 |
| Cases ending as no-op exhausted | 1 |
```

`Accepted duplicates executed` MUST be `0`. A non-zero value is a report-level failure and is rendered in bold with a warning.

### Per-case results

```markdown
| Case | Tier | Category | Pass@Executed | Pass@Semantic | Attempts | Static used | Runtime used | Duplicates |
|---|---|---|---|---|---|---|---|---|
| pilot_tc_05 | 1 | multi_step | ✅ | ✅ | 1 | 0 | 0 | 0 |
| pilot_tc_33 | 2 | multi_step | ✅ | ❌ | 3 | 1 | 1 | 0 |
```

A non-semantic case shows `—` for `Pass@Semantic` and is listed under semantic-not-evaluated.

### Semantic-not-evaluated

```markdown
**Semantic not evaluated** (30): tc_01, tc_02, …
```

These cases are excluded from the semantic denominator and are never counted as semantic passes or failures.

### Gate 2 historical comparison

Clearly separated from the Gate 3 table. This is the only place `Pass@Healed` appears. The values are the frozen Gate 2 closing baseline (`Pass@1` 11/40, `Pass@Healed` 13/40), not metrics recomputed from the current Gate 3 run.

```markdown
## Gate 2 historical comparison

| Metric | Value |
|---|---|
| Gate 1 static validity (constitution IV) | 90.0% |
| Gate 2 Pass@1 | 11/40 = 27.5% |
| Gate 2 Pass@Healed | 13/40 = 32.5% |
| Healing gain (absolute) | +5.0 pp |
| Healing gain (relative) | +18.2% |
```

The section states that Gate 2 measured executability under a different harness and is not on the same scale as Gate 3 semantics.

### Interpretation caveats

The Gate 3 report MUST state:

1. **Semantic pass is not universal correctness.** It means the declared assertions passed, not that the geospatial result is globally correct.
2. **Exit status is not correctness** (the Gate 2 caveat, reworded for Gate 3).
3. **Generation is stochastic.** A one- or two-case difference is within sampling noise.
4. **Semantic assertions never trigger repair.** A semantic failure is measured, not healed.
5. **Pilot expectations are independent.** Values came from reviewed reference scripts, not candidate output.

### Integrity evidence

```markdown
## Integrity evidence

| Check | Result |
|---|---|
| Persistent mapset unchanged | ✅ yes |
| Leaked scratch directories | 0 |
| Accepted duplicate executions | 0 |
| Non-evaluated cases excluded from semantic rate | ✅ yes |
| Report regenerated without model/GRASS | ✅ yes (`--report-only`) |
```

Plus `permanent_hash_before`, `permanent_hash_after`, and the expectation-file hash.

## `run_summary.json`

Run-level metadata, written once per run:

```jsonc
{
  "harness": "gate3",
  "model": "qwen2.5-coder:7b",
  "grass_version": "8.5.0",
  "dataset": "nc_basic_spm_grass7",
  "permanent_hash_before": "…",
  "permanent_hash_after": "…",
  "suites": ["benchmark_prompts_pilot10.json"],
  "cases_total": 10,
  "cases_completed": 10,
  "cases_semantic": 10,
  "max_static_retries": 2,
  "max_runtime_retries": 2,
  "timeout_s": 120,
  "pilot_suite_hash": "…",
  "pilot_expectations_hash": "…",
  "pilot_reviewed": true,
  "attempt1_source": "fresh",
  "resumed": false
}
```

## Report-only reproducibility

`--report-only` MUST:

- read only `case_result.json`, `run_summary.json`, and `pilot_expectations.json`;
- invoke neither the model nor GRASS;
- produce byte-identical tables to the run that wrote the results;
- preserve the same denominators and the same Gate 2 historical section.

A metric that changes between the live report and the report-only regeneration is a defect.

## Compatibility strings

The Gate 2 renderer and `run_gate2` tests continue to rely on these constants and phrases. They remain exported and unchanged:

- `EXIT_STATUS_CAVEAT` (first line and the phrase "Exit status is not correctness")
- `GATE1_STATIC_VALIDITY = 0.900`
- `GATE2_PASS_AT_1 = 0.275` and `GATE2_PASS_AT_HEALED = 0.325` (frozen historical baseline)
- `format_gain()`
- “different harnesses”
- “Integrity evidence”
- “Not evaluated”
- “1 completed of 3”

The Gate 3 renderer may reuse the constants but must not alter their text.
