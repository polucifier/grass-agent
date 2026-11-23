# Gate 3 Report — Semantic Validation & Stateful Healing

- **Model**: `qwen2.5-coder:32b`
- **GRASS**: `8.5.0`
- **Dataset**: `nc_basic_spm_grass7`
- **Suites**: benchmark_prompts_pilot10.json
- **Cases**: 10 completed of 10
- **Static tier**: limit (sum) 20, used 1, remaining 19
- **Runtime tier**: limit (sum) 20, used 4, remaining 16
- **Pilot expectations**: `550a956c298ab9c76a36ce62dfd439ace0fef8feab6a0a4ad449b9f5f76403c4` (reviewed)
- **Resume**: no

## Gate 3 metrics

| Suite | Cases | Pass@Executed | Pass@Semantic | Semantic cases |
|---|---|---|---|---|
| `benchmark_prompts_pilot10.json` | 10 | 8/10 = 80.0% | 7/10 = 70.0% | 10 |
| **Overall** | 10 | 8/10 = 80.0% | 7/10 = 70.0% | 10 |

Execution→semantic gap over the semantic subset: 8/10 = 80.0% − 7/10 = 70.0% = **10.0 pp**.

## Semantic failures

| Case | Output | Check | Expected | Observed | Tolerance | Verdict |
|---|---|---|---|---|---|---|
| pilot_tc_08 | pilot_viewshed | value_range | [0, 1] | 89.7900390625–180.0 | — | ❌ |
| pilot_tc_08 | pilot_viewshed | mean | 0.0271605 | 94.8088 | 5% | ❌ |

| Check | Failures |
|---|---|
| mean | 1 |
| value_range | 1 |
| geometry_type | 0 |
| required_columns | 0 |
| feature_count | 0 |
| non_null_count | 0 |

## Repair budget usage

| Tier | Limit (sum) | Used | Remaining | Cases exhausting tier |
|---|---|---|---|---|
| static | 20 | 1 | 19 | 0 |
| runtime | 20 | 4 | 16 | 2 |

## No-op duplicate detection

| Metric | Value |
|---|---|
| Duplicate candidates detected | 1 |
| Rejected before execution | 1 |
| Accepted duplicates executed | 0 |
| Cases resolved by parameter pivot | 0 |
| No-op attempts recorded | 1 |

## Per-case results

| Case | Tier | Category | Pass@Executed | Pass@Semantic | Attempts | Static used | Runtime used | Duplicates |
|---|---|---|---|---|---|---|---|---|
| `pilot_tc_01` | 1 | single_tool | ✅ | ✅ | 1 | 0 | 0 | 0 |
| `pilot_tc_05` | 1 | multi_step | ✅ | ✅ | 1 | 0 | 0 | 0 |
| `pilot_tc_06` | 1 | multi_step | ✅ | ✅ | 2 | 1 | 0 | 0 |
| `pilot_tc_08` | 1 | edge_case | ✅ | ❌ | 1 | 0 | 0 | 0 |
| `pilot_tc_09` | 1 | edge_case | ✅ | ✅ | 1 | 0 | 0 | 0 |
| `pilot_tc_12` | 2 | single_tool | ✅ | ✅ | 1 | 0 | 0 | 0 |
| `pilot_tc_14` | 2 | single_tool | ❌ | ❌ | 3 | 0 | 2 | 1 |
| `pilot_tc_18` | 2 | single_tool | ✅ | ✅ | 1 | 0 | 0 | 0 |
| `pilot_tc_32` | 2 | multi_step | ❌ | ❌ | 3 | 0 | 2 | 0 |
| `pilot_tc_33` | 2 | multi_step | ✅ | ✅ | 1 | 0 | 0 | 0 |

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

