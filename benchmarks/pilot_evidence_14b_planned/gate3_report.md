# Gate 3 Report — Semantic Validation & Stateful Healing

- **Model**: `qwen2.5-coder:14b`
- **Pipeline**: `planned`
- **Context**: `8192` (manual budget `3686` tokens)
- **GRASS**: `8.5.0`
- **Dataset**: `nc_basic_spm_grass7`
- **Suites**: benchmark_prompts_pilot10.json
- **Cases**: 10 completed of 10
- **Static tier**: limit (sum) 20, used 1, remaining 19
- **Runtime tier**: limit (sum) 20, used 2, remaining 18
- **Pilot expectations**: `c6206ae806aab01d47b27318637a49397dcf54d4cd7edfc74a76d51584843810` (reviewed)
- **Resume**: no

## Gate 3 metrics

| Suite | Cases | Pass@Executed | Pass@Semantic | Semantic cases |
|---|---|---|---|---|
| `benchmark_prompts_pilot10.json` | 10 | 9/10 = 90.0% | 8/10 = 80.0% | 10 |
| **Overall** | 10 | 9/10 = 90.0% | 8/10 = 80.0% | 10 |

Execution→semantic gap over the semantic subset: 9/10 = 90.0% − 8/10 = 80.0% = **10.0 pp**.

## Pipeline diagnostics

| Metric | Value |
|---|---|
| Pipeline | `planned` |
| Context / manual budget | 8192 / 3686 tokens |
| Manual cards rendered | 10 |
| Manual budget failures | 0 |
| Context overflow events | 0 |
| Plan attempts | 13 |
| Plan repairs | 6 |
| Plan fallbacks | 5 |
| Replans | 0 |
| Shortlist shortfalls | 0 |
| Tool swaps | 0 |

## Semantic failures

| Case | Output | Check | Expected | Observed | Tolerance | Verdict |
|---|---|---|---|---|---|---|
| pilot_tc_14 | pilot_roads_clean | required_columns | [cat, ROAD_NAME] | [cat, STSEG, STID, STNAME, DIR_PRE, DIR_SUF, STYPE, CLASS, F_ELEV, T_ELEV, MAP, PRIV, FRLEFT, TOLEFT, FRRIGHT, TORIGHT, FRLEFT_A, TOLEFT_A, FRRIGHT_A, TORIGHT_A, STATEROAD, CARTONAME, CORP, SPEED, ONE_WAY, CLASSNAME, L_ZIPNAME, R_ZIPNAME, FT_COST, TF_COST, LABELNAME, F_NODE, T_NODE, CARTOLEVEL, SHAPE_LEN] | — | ❌ |

| Check | Failures |
|---|---|
| mean | 0 |
| value_range | 0 |
| geometry_type | 0 |
| required_columns | 1 |
| feature_count | 0 |
| non_null_count | 0 |

## Repair budget usage

| Tier | Limit (sum) | Used | Remaining | Cases exhausting tier |
|---|---|---|---|---|
| static | 20 | 1 | 19 | 0 |
| runtime | 20 | 2 | 18 | 1 |

## No-op duplicate detection

| Metric | Value |
|---|---|
| Duplicate candidates detected | 1 |
| Rejected before execution | 1 |
| Accepted duplicates executed | 0 |
| Cases resolved by parameter pivot | 1 |
| No-op attempts recorded | 1 |

## Per-case results

| Case | Tier | Category | Pass@Executed | Pass@Semantic | Attempts | Static used | Runtime used | Duplicates |
|---|---|---|---|---|---|---|---|---|
| `pilot_tc_01` | 1 | single_tool | ✅ | ✅ | 1 | 0 | 0 | 0 |
| `pilot_tc_05` | 1 | multi_step | ✅ | ✅ | 1 | 0 | 0 | 0 |
| `pilot_tc_06` | 1 | multi_step | ✅ | ✅ | 2 | 1 | 0 | 0 |
| `pilot_tc_08` | 1 | edge_case | ✅ | ✅ | 1 | 0 | 0 | 0 |
| `pilot_tc_09` | 1 | edge_case | ✅ | ✅ | 1 | 0 | 0 | 0 |
| `pilot_tc_12` | 2 | single_tool | ✅ | ✅ | 1 | 0 | 0 | 0 |
| `pilot_tc_14` | 2 | single_tool | ✅ | ❌ | 1 | 0 | 0 | 0 |
| `pilot_tc_18` | 2 | single_tool | ✅ | ✅ | 1 | 0 | 0 | 0 |
| `pilot_tc_32` | 2 | multi_step | ❌ | ❌ | 3 | 0 | 2 | 1 |
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

- `permanent_hash_before`: `d6bbd2d2ac0c841c70b432a2b841467b685d4b8637966249eeb31b9bc83473b3`
- `permanent_hash_after`: `d6bbd2d2ac0c841c70b432a2b841467b685d4b8637966249eeb31b9bc83473b3`
- `pilot_suite_hash`: `8cbcac67a45be0952900c8d614f76c007e5cd1b13bc92fc54ea6ae8d09182e37`
- `pilot_expectations_hash`: `c6206ae806aab01d47b27318637a49397dcf54d4cd7edfc74a76d51584843810`

