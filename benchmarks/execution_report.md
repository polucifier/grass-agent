# Gate 2 Execution Report — Headless Runtime Execution & Self-Healing

- **Model**: `qwen2.5-coder:7b`
- **Suites**: benchmark_prompts_tier1.json, benchmark_prompts_tier2.json
- **Cases**: 40 completed of 40
- **Attempt-1 source**: `fresh`
- **Retry budget**: `2` (unified across static and runtime stages)
- **Per-attempt timeout**: `120`s
- **Resume**: yes — reused completed cases

## Headline metrics

| Metric | Value |
|---|---|
| Gate 1 static validity (baseline, constitution IV) | 90.0% |
| Gate 2 **Pass@1** (zero-shot, no healing) | 11/40 = **27.5%** |
| Gate 2 **Pass@Healed** (after retry 1 and 2) | 13/40 = **32.5%** |
| Healing gain (absolute) | **+5.0 pp** |
| Healing gain (relative) | +18.2% |

> Gate 1 and Gate 2 are measured by **different harnesses**: Gate 1 asks whether a script parses and matches a schema; Gate 2 asks whether it actually runs in GRASS. The two rates are not on one continuous scale, and the drop from the first to the second is the real finding of this milestone.

## Interpretation caveats

**Exit status is not correctness.** A script that runs cleanly may still produce the wrong map. Pass@Healed measures *executability* -- whether the generated script completes inside a live GRASS session -- and must not be read as an accuracy figure. Gate 2 does not validate geospatial output.

**Generation is stochastic.** Pass@1 comes from one sampling run of a local model, so it varies between runs by a case or two. A healed gain of one or two cases is within that noise and should not be reported as a reliable improvement. Re-run with `--clean` to resample.

- `missing_input` is **under-reported**: when a script both invents an option name and references a missing map, GRASS's option parser aborts first and emits only `Sorry, <x> is not a valid parameter`. The schema error masks the missing map.
- `schema_misuse` is **under-reported**: GRASS accepts unambiguous option prefixes (`m=`, `in=`, `out=`), so a slightly-wrong parameter name often works and never reaches this category.
- A wrong *type* for a map parameter is reported by GRASS as a missing map (`Raster map <a,b> not found`), so some genuine type errors are counted under `missing_input`. Unavoidable at the string level.

## Failure modes

| Failure mode | Failed attempts |
|---|---|
| `general_exception` | 35 |
| `missing_input` | 31 |
| `schema_misuse` | 17 |
| **Total** | **83** |

Mode totals equal the number of failed attempts exactly (invariant I5), so no failure is unclassified.

### Failure-mode transitions

How a mode became the next mode on a later attempt.

| Transition | Count |
|---|---|
| `general_exception -> general_exception` | 21 |
| `missing_input -> missing_input` | 20 |
| `schema_misuse -> schema_misuse` | 8 |
| `schema_misuse -> general_exception` | 3 |
| `general_exception -> success` | 1 |
| `general_exception -> missing_input` | 1 |
| `general_exception -> schema_misuse` | 1 |
| `schema_misuse -> success` | 1 |

## Per-case results

| Case | Tier | Category | Pass@1 | Pass@Healed | Attempts | Modes |
|---|---|---|---|---|---|---|
| `tc_01` | 1 | single_tool | ❌ | ❌ | 3 | general_exception → general_exception → general_exception |
| `tc_02` | 1 | single_tool | ❌ | ❌ | 3 | general_exception → general_exception → general_exception |
| `tc_03` | 1 | single_tool | ✅ | ✅ | 1 | ✓ |
| `tc_04` | 1 | single_tool | ❌ | ❌ | 3 | general_exception → general_exception → general_exception |
| `tc_05` | 1 | multi_step | ✅ | ✅ | 1 | ✓ |
| `tc_06` | 1 | multi_step | ❌ | ✅ | 2 | general_exception → ✓ |
| `tc_07` | 1 | multi_step | ❌ | ❌ | 3 | general_exception → general_exception → general_exception |
| `tc_08` | 1 | edge_case | ✅ | ✅ | 1 | ✓ |
| `tc_09` | 1 | edge_case | ✅ | ✅ | 1 | ✓ |
| `tc_10` | 1 | edge_case | ❌ | ❌ | 3 | general_exception → general_exception → missing_input |
| `tc_11` | 2 | multi_step | ✅ | ✅ | 1 | ✓ |
| `tc_12` | 2 | single_tool | ✅ | ✅ | 1 | ✓ |
| `tc_13` | 2 | single_tool | ✅ | ✅ | 1 | ✓ |
| `tc_14` | 2 | single_tool | ❌ | ❌ | 3 | schema_misuse → schema_misuse → schema_misuse |
| `tc_15` | 2 | single_tool | ❌ | ❌ | 3 | missing_input → missing_input → missing_input |
| `tc_16` | 2 | single_tool | ❌ | ❌ | 3 | general_exception → general_exception → general_exception |
| `tc_17` | 2 | single_tool | ✅ | ✅ | 1 | ✓ |
| `tc_18` | 2 | single_tool | ❌ | ❌ | 3 | missing_input → missing_input → missing_input |
| `tc_19` | 2 | single_tool | ❌ | ❌ | 3 | missing_input → missing_input → missing_input |
| `tc_20` | 2 | single_tool | ❌ | ❌ | 3 | missing_input → missing_input → missing_input |
| `tc_21` | 2 | single_tool | ❌ | ❌ | 3 | missing_input → missing_input → missing_input |
| `tc_22` | 2 | single_tool | ✅ | ✅ | 1 | ✓ |
| `tc_23` | 2 | single_tool | ✅ | ✅ | 1 | ✓ |
| `tc_24` | 2 | single_tool | ✅ | ✅ | 1 | ✓ |
| `tc_25` | 2 | single_tool | ❌ | ❌ | 3 | schema_misuse → general_exception → schema_misuse |
| `tc_26` | 2 | multi_step | ❌ | ❌ | 3 | general_exception → general_exception → general_exception |
| `tc_27` | 2 | multi_step | ❌ | ✅ | 2 | schema_misuse → ✓ |
| `tc_28` | 2 | multi_step | ❌ | ❌ | 3 | general_exception → general_exception → general_exception |
| `tc_29` | 2 | multi_step | ❌ | ❌ | 3 | schema_misuse → schema_misuse → schema_misuse |
| `tc_30` | 2 | multi_step | ❌ | ❌ | 3 | missing_input → missing_input → missing_input |
| `tc_31` | 2 | multi_step | ❌ | ❌ | 3 | missing_input → missing_input → missing_input |
| `tc_32` | 2 | multi_step | ❌ | ❌ | 3 | general_exception → general_exception → general_exception |
| `tc_33` | 2 | multi_step | ❌ | ❌ | 3 | missing_input → missing_input → missing_input |
| `tc_34` | 2 | multi_step | ❌ | ❌ | 3 | schema_misuse → general_exception → general_exception |
| `tc_35` | 2 | multi_step | ❌ | ❌ | 3 | general_exception → general_exception → general_exception |
| `tc_36` | 2 | edge_case | ❌ | ❌ | 3 | schema_misuse → general_exception → general_exception |
| `tc_37` | 2 | edge_case | ❌ | ❌ | 3 | schema_misuse → schema_misuse → schema_misuse |
| `tc_38` | 2 | edge_case | ❌ | ❌ | 3 | schema_misuse → schema_misuse → schema_misuse |
| `tc_39` | 2 | edge_case | ❌ | ❌ | 3 | missing_input → missing_input → missing_input |
| `tc_40` | 2 | edge_case | ❌ | ❌ | 3 | missing_input → missing_input → missing_input |

## Cost per attempt ordinal

| Ordinal | Mean latency (s) | Mean prompt tok | Mean completion tok |
|---|---|---|---|
| 1 (initial) | 206.3 | 1246 | 87 |
| 2 (retry 1) | 114.5 | 1088 | 102 |
| 3 (retry 2) | 48.9 | 1055 | 96 |

Total tokens: **109880 prompt + 9009 completion** across 96 attempts.
Cost per successful case: **9145 tokens**.

## Integrity evidence

| Check | Result |
|---|---|
| Persistent mapset unchanged | ✅ yes |
| Leaked scratch directories | 0  |

- `permanent_hash_before`: `d6bbd2d2ac0c841c70b432a2b841467b685d4b8637966249eeb31b9bc83473b3`
- `permanent_hash_after`: `d6bbd2d2ac0c841c70b432a2b841467b685d4b8637966249eeb31b9bc83473b3`

