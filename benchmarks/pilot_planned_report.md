# Gate 3 Report — Semantic Validation & Stateful Healing

- **Model**: `qwen2.5-coder:3b`
- **Pipeline**: `planned`
- **Context**: `8192` (manual budget `3686` tokens)
- **GRASS**: `8.5.0`
- **Dataset**: `nc_basic_spm_grass7`
- **Suites**: benchmark_prompts_pilot10.json
- **Cases**: 2 completed of 2
- **Static tier**: limit (sum) 4, used 4, remaining 0
- **Runtime tier**: limit (sum) 4, used 0, remaining 4
- **Pilot expectations**: `550a956c298ab9c76a36ce62dfd439ace0fef8feab6a0a4ad449b9f5f76403c4` (reviewed)
- **Resume**: no

## Gate 3 metrics

| Suite | Cases | Pass@Executed | Pass@Semantic | Semantic cases |
|---|---|---|---|---|
| `benchmark_prompts_pilot10.json` | 2 | 0/2 = 0.0% | 0/2 = 0.0% | 2 |
| **Overall** | 2 | 0/2 = 0.0% | 0/2 = 0.0% | 2 |

Execution→semantic gap over the semantic subset: 0/2 = 0.0% − 0/2 = 0.0% = **0.0 pp**.

## Pipeline diagnostics

| Metric | Value |
|---|---|
| Pipeline | `planned` |
| Context / manual budget | 8192 / 3686 tokens |
| Manual cards rendered | 2 |
| Manual budget failures | 0 |
| Context overflow events | 0 |
| Plan attempts | 1 |
| Plan repairs | 0 |
| Plan fallbacks | 0 |
| Replans | 0 |
| Shortlist shortfalls | 0 |
| Tool swaps | 0 |

## Semantic failures

No semantic failures.

## Repair budget usage

| Tier | Limit (sum) | Used | Remaining | Cases exhausting tier |
|---|---|---|---|---|
| static | 4 | 4 | 0 | 2 |
| runtime | 4 | 0 | 4 | 0 |

## No-op duplicate detection

| Metric | Value |
|---|---|
| Duplicate candidates detected | 2 |
| Rejected before execution | 2 |
| Accepted duplicates executed | 0 |
| Cases resolved by parameter pivot | 1 |
| No-op attempts recorded | 2 |

## Per-case results

| Case | Tier | Category | Pass@Executed | Pass@Semantic | Attempts | Static used | Runtime used | Duplicates |
|---|---|---|---|---|---|---|---|---|
| `pilot_tc_32` | 2 | multi_step | ❌ | ❌ | 3 | 2 | 0 | 2 |
| `pilot_tc_33` | 2 | multi_step | ❌ | ❌ | 3 | 2 | 0 | 0 |

## Interpretation caveats

- **Semantic pass is not universal correctness.** It means the declared assertions passed, not that the geospatial result is globally correct.
- **Exit status is not correctness.** A script that runs cleanly may still produce the wrong map; Gate 3 separates the two verdicts for that reason.
- **Generation is stochastic.** A one- or two-case difference is within sampling noise and should not be reported as a reliable improvement.
- **Semantic assertions never trigger repair.** A semantic failure is measured and reported; it generates no repair prompt and consumes no tier.
- **Pilot expectations are independent.** Expected values come from human-reviewed reference scripts, never from candidate output.

## Gate 2 historical comparison

| Metric | Value |
|---|---|
| Gate 1 static validity (constitution IV) | 90.0% |
| Gate 2 Pass@1 | 11/40 = 27.5% |
| Gate 2 Pass@Healed | 13/40 = 32.5% |
| Healing gain (absolute) | +5.0 pp |
| Healing gain (relative) | +18.2% |

Gate 1 and Gate 2 are measured by **different harnesses**: Gate 1 asks whether a script parses and matches a schema, Gate 2 whether it executes; Gate 3 asks whether the produced maps satisfy declared assertions. `Pass@Healed` is a Gate 2 executability figure and is not on the same scale as Gate 3 semantics.

## Integrity evidence

| Check | Result |
|---|---|
| Persistent mapset unchanged | ✅ yes |
| Leaked scratch directories | 0  |
| Accepted duplicate executions | 0 ✅ |
| Non-evaluated cases excluded from semantic rate | ✅ yes (none) |
| Report regenerated without model/GRASS | ✅ yes (persisted results only) |

- `permanent_hash_before`: `7ee9b49d11264d9497dd28358260dd5a7dccf719f2dbbc9a6c4d2b7fcd56630e`
- `permanent_hash_after`: `7ee9b49d11264d9497dd28358260dd5a7dccf719f2dbbc9a6c4d2b7fcd56630e`
- `pilot_suite_hash`: `8cbcac67a45be0952900c8d614f76c007e5cd1b13bc92fc54ea6ae8d09182e37`
- `pilot_expectations_hash`: `550a956c298ab9c76a36ce62dfd439ace0fef8feab6a0a4ad449b9f5f76403c4`

