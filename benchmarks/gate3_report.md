# Gate 3 Report — Semantic Validation & Stateful Healing

- **Model**: `qwen2.5-coder:3b`
- **GRASS**: `8.5.0`
- **Dataset**: `nc_basic_spm_grass7`
- **Suites**: benchmark_prompts_tier1.json, benchmark_prompts_tier2.json
- **Cases**: 40 completed of 40
- **Static tier**: limit (sum) 80, used 18, remaining 62
- **Runtime tier**: limit (sum) 80, used 50, remaining 30
- **Pilot expectations**: `550a956c298ab9c76a36ce62dfd439ace0fef8feab6a0a4ad449b9f5f76403c4` (reviewed)
- **Resume**: no

## Gate 3 metrics

| Suite | Cases | Pass@Executed | Pass@Semantic | Semantic cases |
|---|---|---|---|---|
| `benchmark_prompts_tier1.json` | 10 | 5/10 = 50.0% | 0/0 = n/a | 0 |
| `benchmark_prompts_tier2.json` | 30 | 4/30 = 13.3% | 0/0 = n/a | 0 |
| **Overall** | 40 | 9/40 = 22.5% | 0/0 = n/a | 0 |

No semantic cases in this run, so the execution→semantic gap is not defined.

## Semantic failures

No semantic failures.

## Repair budget usage

| Tier | Limit (sum) | Used | Remaining | Cases exhausting tier |
|---|---|---|---|---|
| static | 80 | 18 | 62 | 8 |
| runtime | 80 | 50 | 30 | 24 |

## No-op duplicate detection

| Metric | Value |
|---|---|
| Duplicate candidates detected | 35 |
| Rejected before execution | 35 |
| Accepted duplicates executed | 0 |
| Cases resolved by parameter pivot | 18 |
| No-op attempts recorded | 35 |

## Per-case results

| Case | Tier | Category | Pass@Executed | Pass@Semantic | Attempts | Static used | Runtime used | Duplicates |
|---|---|---|---|---|---|---|---|---|
| `tc_01` | 1 | single_tool | ✅ | — | 2 | 0 | 1 | 0 |
| `tc_02` | 1 | single_tool | ✅ | — | 1 | 0 | 0 | 0 |
| `tc_03` | 1 | single_tool | ❌ | — | 3 | 0 | 2 | 1 |
| `tc_04` | 1 | single_tool | ❌ | — | 3 | 0 | 2 | 2 |
| `tc_05` | 1 | multi_step | ✅ | — | 2 | 1 | 0 | 0 |
| `tc_06` | 1 | multi_step | ❌ | — | 3 | 0 | 2 | 2 |
| `tc_07` | 1 | multi_step | ❌ | — | 3 | 0 | 2 | 1 |
| `tc_08` | 1 | edge_case | ✅ | — | 1 | 0 | 0 | 0 |
| `tc_09` | 1 | edge_case | ✅ | — | 1 | 0 | 0 | 0 |
| `tc_10` | 1 | edge_case | ❌ | — | 3 | 0 | 2 | 2 |
| `tc_11` | 2 | multi_step | ❌ | — | 5 | 2 | 2 | 0 |
| `tc_12` | 2 | single_tool | ✅ | — | 1 | 0 | 0 | 0 |
| `tc_13` | 2 | single_tool | ❌ | — | 3 | 0 | 2 | 0 |
| `tc_14` | 2 | single_tool | ❌ | — | 3 | 2 | 0 | 1 |
| `tc_15` | 2 | single_tool | ❌ | — | 3 | 0 | 2 | 0 |
| `tc_16` | 2 | single_tool | ❌ | — | 3 | 2 | 0 | 2 |
| `tc_17` | 2 | single_tool | ✅ | — | 1 | 0 | 0 | 0 |
| `tc_18` | 2 | single_tool | ❌ | — | 3 | 0 | 2 | 2 |
| `tc_19` | 2 | single_tool | ❌ | — | 3 | 0 | 2 | 0 |
| `tc_20` | 2 | single_tool | ❌ | — | 3 | 0 | 2 | 1 |
| `tc_21` | 2 | single_tool | ❌ | — | 3 | 0 | 2 | 2 |
| `tc_22` | 2 | single_tool | ❌ | — | 3 | 2 | 0 | 2 |
| `tc_23` | 2 | single_tool | ❌ | — | 3 | 0 | 2 | 1 |
| `tc_24` | 2 | single_tool | ❌ | — | 3 | 0 | 2 | 1 |
| `tc_25` | 2 | single_tool | ❌ | — | 3 | 0 | 2 | 2 |
| `tc_26` | 2 | multi_step | ✅ | — | 2 | 0 | 1 | 0 |
| `tc_27` | 2 | multi_step | ❌ | — | 4 | 1 | 2 | 1 |
| `tc_28` | 2 | multi_step | ❌ | — | 3 | 0 | 2 | 0 |
| `tc_29` | 2 | multi_step | ✅ | — | 1 | 0 | 0 | 0 |
| `tc_30` | 2 | multi_step | ❌ | — | 3 | 0 | 2 | 1 |
| `tc_31` | 2 | multi_step | ❌ | — | 3 | 2 | 0 | 1 |
| `tc_32` | 2 | multi_step | ❌ | — | 3 | 0 | 2 | 2 |
| `tc_33` | 2 | multi_step | ❌ | — | 3 | 2 | 0 | 1 |
| `tc_34` | 2 | multi_step | ❌ | — | 3 | 0 | 2 | 2 |
| `tc_35` | 2 | multi_step | ❌ | — | 3 | 0 | 2 | 2 |
| `tc_36` | 2 | edge_case | ❌ | — | 3 | 0 | 2 | 2 |
| `tc_37` | 2 | edge_case | ❌ | — | 3 | 2 | 0 | 1 |
| `tc_38` | 2 | edge_case | ❌ | — | 3 | 2 | 0 | 0 |
| `tc_39` | 2 | edge_case | ❌ | — | 3 | 0 | 2 | 0 |
| `tc_40` | 2 | edge_case | ❌ | — | 3 | 0 | 2 | 0 |

**Semantic not evaluated** (40): tc_01, tc_02, tc_03, tc_04, tc_05, tc_06, tc_07, tc_08, tc_09, tc_10, tc_11, tc_12, tc_13, tc_14, tc_15, tc_16, tc_17, tc_18, tc_19, tc_20, tc_21, tc_22, tc_23, tc_24, tc_25, tc_26, tc_27, tc_28, tc_29, tc_30, tc_31, tc_32, tc_33, tc_34, tc_35, tc_36, tc_37, tc_38, tc_39, tc_40

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
| Non-evaluated cases excluded from semantic rate | ✅ yes |
| Report regenerated without model/GRASS | ✅ yes (persisted results only) |

- `permanent_hash_before`: `7ee9b49d11264d9497dd28358260dd5a7dccf719f2dbbc9a6c4d2b7fcd56630e`
- `permanent_hash_after`: `7ee9b49d11264d9497dd28358260dd5a7dccf719f2dbbc9a6c4d2b7fcd56630e`
- `pilot_suite_hash`: `8cbcac67a45be0952900c8d614f76c007e5cd1b13bc92fc54ea6ae8d09182e37`
- `pilot_expectations_hash`: `550a956c298ab9c76a36ce62dfd439ace0fef8feab6a0a4ad449b9f5f76403c4`


## Feature 004 — Matched latency and token evidence (3B substitute)

**Date**: 2026-11-19
**Host**: local Linux, GRASS 8.5.0, dataset `nc_basic_spm_grass7`
**Matched configuration**: `qwen2.5-coder:3b`, cases `pilot_tc_01`, `pilot_tc_05`, one seed, same dataset and suite
**Why 3B**: `qwen2.5-coder:14b`/`32b` are not provisioned on this host and no network pull is permitted.

| Mode | Cases | Pass@Executed | Per-case wall-clock (s) | P95 case wall-clock | Attempt P95 | Manual-card tokens | Actual prompt tokens |
|---|---:|---:|---|---:|---:|---:|---:|
| legacy | 2 | 0/2 | 85.1, 152.4 | 152.4 | 56.1 | 0 | 0 / 2179 / 2694 (attempts) |
| manual-kb | 2 | 1/2 | 74.0, 152.6 | 152.6 | 152.6 | 2442, 2767 | 3160 |

- **Case-level P95 ratio**: 152.6 / 152.4 = **1.00×** (assertion ≤ 2× holds).
- Attempt-level P95 is 152.6 / 56.1 = 2.72× because the successful manual-kb case did all
  inference and execution in one attempt while the legacy case spent three bounded attempts.
  Per-case wall-clock, which is what the SLO bounds, is unchanged.
- Context-overflow events: **0** in both runs.
- Plan repairs / fallbacks / replans / shortlist shortfalls: **0** (manual-kb does not plan).
- Tool swaps: **0**.
- Accepted duplicate executions: **0**; `PERMANENT` unchanged; 0 leaked scratch mapsets.

These figures are a 3B substitute and do not satisfy the 32B SC-004 comparison (T053/T054).
