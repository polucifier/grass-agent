# Contract: Results, Resume, and Reporting

**Date**: 2026-11-19 | **Plan**: [../plan.md](../plan.md) | **Data model**: [../data-model.md](../data-model.md)

Normative contract for pipeline isolation in persisted results and Gate 3 ablation reporting. `case_result.json` remains at `schema_version: 1`; all changes are additive.

## 1. Attempt additions

| Field | Type | Default | Rule |
|---|---|---|---|
| `pipeline` | string | `"legacy"` | Must equal the run mode |
| `num_ctx` | int | `8192` | Resolved context used for the attempt |
| `manual_context_tokens` | int \| null | `null` | Resolved documentation budget |
| `plan_revision` | int | `0` | `0` or `1` |
| `plan_repair_count` | int | `0` | `0` or `1` |
| `replan_count` | int | `0` | `0` or `1`; `plan_repair_count + replan_count ≤ 2` |
| `shortlist_shortfall` | bool | `false` | Fewer than eight real candidates |
| `planned_tools` | list of string | `[]` | Empty for legacy/manual-kb |
| `tool_swaps` | list of string | `[]` | Documented substitutions |
| `plan_fallback` | bool | `false` | Planner fallback |
| `manual_card_tokens` | int | `0` | Rendered card tokens |
| `manual_omissions` | list of string | `[]` | Explicit omissions |
| `planner_prompt_tokens` | int | `0` | Planner call |
| `planner_completion_tokens` | int | `0` | Planner call |

Old records load with defaults. No existing field changes meaning.

## 2. ResumeKey additions

| Field | Type | Default | Rule |
|---|---|---|---|
| `pipeline` | string | `"legacy"` | Must match |
| `num_ctx` | int | `8192` | Must match |
| `manual_context_tokens` | int \| null | `null` | Must match after resolution |

`matches()` requires all three. Old keys default to legacy/8192/None and still match each other. A legacy result never matches a new-mode key; an 8K result never matches a 16K key.

## 3. RunSummary additions

| Field | Type | Notes |
|---|---|---|
| `pipeline` | string | Mode for the run |
| `num_ctx` | int | Context |
| `manual_context_tokens` | int | Resolved docs budget |
| `manual_cards_rendered` | int | Count |
| `manual_budget_failures` | int | Fail-closed events |
| `context_overflow_events` | int | Must be `0` for a clean run |
| `plan_attempts` | int | Planned-mode cases |
| `plan_repairs` | int | Pre-execution plan repairs |
| `plan_fallbacks` | int | Fallback count |
| `replans` | int | Post-failure constrained re-plans |
| `shortlist_shortfalls` | int | Cases with fewer than eight real candidates |
| `tool_swaps` | int | Substitutions |
| `pipeline_ablation` | list of dict | Optional comparison rows |

Existing Gate 3 metrics (`pass_at_executed`, `pass_at_semantic`, rates, gap, tier/no-op counters) are unchanged.

## 4. run_summary.json

Additive keys:

```jsonc
{
  "pipeline": "planned",
  "num_ctx": 8192,
  "manual_context_tokens": 3686,
  "manual_cards_rendered": 17,
  "manual_budget_failures": 0,
  "context_overflow_events": 0,
  "plan_attempts": 10,
  "plan_repairs": 1,
  "plan_fallbacks": 1,
  "replans": 1,
  "shortlist_shortfalls": 0,
  "tool_swaps": 2,
  "pipeline_ablation": []
}
```

Existing keys retain their meanings. `--report-only` reads these keys; absent values default to `legacy`/`8192`/`0` for old runs.

## 5. Report header

The Gate 3 report adds:

- `Pipeline`: `legacy` / `manual-kb` / `planned`
- `Context`: `num_ctx`
- `Manual budget`: tokens
- `Plan repairs`, `Plan fallbacks`, `Replans`, `Shortlist shortfalls`, and `Tool swaps`
- `Context overflow events`

The main metric table remains exactly `Pass@Executed` and `Pass@Semantic`; Gate 2 historical comparisons remain separate.

## 6. Ablation table

When multiple mode summaries are supplied, render:

| Pipeline | Cases | Pass@Executed | Pass@Semantic | Plan repairs | Plan fallbacks | Replans | Shortfalls | Tool swaps | P95 latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| legacy | 10 | 8/10 | 7/10 | — | — | — | — | 0 | baseline |
| manual-kb | 10 | ... | ... | — | — | — | ... | ... | ... |
| planned | 10 | ... | ... | ... | ... | ... | ... | ... | ... |

Rules:

- One row per mode; no mixing of cases or denominators.
- `Pass@Semantic` only over semantic cases.
- A mode with a different model/context/dataset is labelled, not silently compared.
- The table is informational; the single-run report remains the primary artifact.

## 6.1 Generating an ablation report

A combined ablation is produced without inference or GRASS:

```sh
.venv/bin/python -m benchmarks.run_gate3 --report-only \
  --ablation-dirs benchmarks/output_legacy,benchmarks/output_manual_kb,benchmarks/output_planned \
  --report-path benchmarks/gate3_ablation.md
```

Rules:

- Each directory must contain `run_summary.json` and completed case results.
- The set must contain distinct pipeline modes; duplicates exit `2`.
- The report includes the single-run sections for the primary directory (if supplied) plus the ablation table.
- If a mode used a different model, context, dataset, or suite, its row is labelled and not presented as a controlled comparison.
- `--report-only` remains byte-reproducible.

## 7. Report-only

`--report-only` remains a pure function of persisted results plus `run_summary.json`:

- No model call, no GRASS, no network.
- Missing new metadata defaults to legacy values.
- Regenerating a live report and a report-only report must be byte-identical.
- Existing Gate 3 caveats remain verbatim.

## 8. Compatibility

- `schema_version` stays `1`.
- Old case files load with pipeline `legacy`, plan fields empty, and no plan artifacts.
- Old run summaries load with pipeline `legacy`, context `8192`, docs budget `0`/unknown.
- A resume mismatch reruns the case from attempt 1.
- `check_invariants()` accepts old records; new-mode invariants apply only when `pipeline != "legacy"`.

## 9. Invariants

| # | Invariant |
|---|---|
| R1 | `schema_version` remains `1` |
| R2 | `pipeline` is present on every new attempt and run summary |
| R3 | Resume requires matching mode/context/budget |
| R4 | Report metrics and oracle definitions are unchanged |
| R5 | Ablation rows never mix modes |
| R6 | `--report-only` reproduces the report without model/GRASS/network |
| R7 | Old results remain readable and are never reused by new modes |
