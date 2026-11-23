# Contract: Pipeline Modes, Budgets, and Repair

**Date**: 2026-11-19 | **Plan**: [../plan.md](../plan.md) | **Data model**: [../data-model.md](../data-model.md)

Normative behavior for `legacy`, `manual-kb`, and `planned`, including budget accounting, duplicate handling, and semantic report-only interaction.

## 1. Mode definitions

| Mode | Generation |
|---|---|
| `legacy` | Existing: retrieve top-k → `format_context()` → synthesize. Default. |
| `manual-kb` | Retrieve top-k → `ManualCard`s → synthesize. |
| `planned` | Shortlist → validated JSON plan → per-step cards + alternatives → synthesize. |

All modes share the existing static guard, executor, semantic probe, healing loop, and result persistence.

## 2. Generation result

`run_case` consumes a `PipelineGenerationResult`:

| Field | Used by |
|---|---|
| `code` | Static guard and execution |
| `prompt_tokens` / `completion_tokens` | Attempt accounting |
| `plan` / `plan_revision` / `plan_repair_count` / `replan_count` / `planner_invocations` / `plan_fallback` / `shortlist_shortfall` | Attempt metadata and artifacts |
| `manual_cards` / `manual_tokens` / `manual_omissions` | Diagnostics and report |
| `tool_swaps` | Diagnostics |
| `planner_prompt_tokens` / `planner_completion_tokens` | Cost accounting |

The existing zero-chat extractor and `validate_syntax()` still run on `code`.

## 3. Plan flow

```text
if mode == legacy:
    retrieve -> format_context -> synthesize

if mode == manual-kb:
    retrieve -> cards -> synthesize

if mode == planned:
    retrieve shortlist (shortlist_k=12, at least 8 when available; shortfall, or fallback)
    -> planner (timeout default 60s)
    -> valid? -> cards -> synthesize
    -> invalid/timeout? -> one pre-execution plan repair -> valid? -> cards -> synthesize
                                                        -> invalid? -> fallback manual-kb
```

Planner failure before a candidate is generated is free: no static/runtime tier is charged, no attempt ordinal is consumed beyond the normal initial candidate. Total planner invocations are capped at three: initial plan, one plan repair, one post-failure constrained re-plan.

## 4. Repair escalation

Applies to `manual-kb` and `planned`; `legacy` keeps its existing repair behavior.

| Step | Context | Charge |
|---|---|---|
| 1. Same-tool card | Manual card for the failing tool | Producing tier |
| 2. Parameter/option pivot | Flags + closed enum table + exact error | Producing tier |
| 3. Tool swap | Alternatives from `TOOL_FAMILIES` | Producing tier |
| 4. Constrained re-plan | Original prompt + failed plan + error + alternatives; max one per case, distinct from the pre-execution plan repair | Producing tier |

The ladder is a policy for choosing the next prompt, not an extra budget. Each rung produces at most one candidate and consumes one unit of the producing tier. If the tier is exhausted, the case terminates under existing rules. A case may use one plan repair before execution and one constrained re-plan after a failure, but total planner invocations never exceed three.

## 5. Budget accounting

Unchanged rules:

- Initial candidate is free.
- Static repairs count against `static_limit`.
- Runtime repairs count against `runtime_limit`.
- A runtime-tier candidate that fails static validation stays charged to runtime and never executes.
- A duplicate is charged to its producing tier and never executes.
- Maximum candidates: `1 + static_limit + runtime_limit`.
- Semantic failures consume no budget and generate no repair.

Feature 004 additions:

- Planner fallback is free.
- A plan repair before the initial candidate is free.
- A tool swap or re-plan during repair is part of the repair candidate and consumes the producing tier.
- Planner token counts are recorded separately and do not affect candidate counts.
- Before failing closed on the global manual budget, apply this deterministic order: (1) deduplicate repeated tool cards across steps, (2) compact functional alternatives to one per step, (3) drop optional `EXAMPLES`/`DESCRIPTION` prose while keeping signatures, flags, closed enums, and the top-3 `NOTES` constraints, then (4) fail closed only if mandatory sections still exceed the budget.

## 6. No-op detection

Unchanged:

- Byte digest = SHA-256 of line-ending-normalized code.
- AST digest = SHA-256 of docstring-stripped normalized AST.
- A candidate is a duplicate if either matches any prior attempt.
- A duplicate is rejected before execution and charged to its producing tier.
- Plan changes do not bypass code duplicate detection.

## 7. Semantic interaction

- Semantic probing is unchanged.
- A semantic failure terminates the case at the semantic verdict, is report-only, and consumes no tier.
- No semantic-repair ladder exists in Feature 004.

## 8. Mode isolation

- `pipeline` is recorded on `ResumeKey`, `Attempt`, and `RunSummary`.
- `ResumeKey.matches()` requires equal mode, `num_ctx`, and manual budget.
- A resumed run never mixes modes or context sizes.
- The report header names the mode; an ablation table compares modes when multiple summaries are supplied.

## 9. Failure modes and responses

| Failure | Response |
|---|---|
| Planner invalid JSON | One plan repair; then manual-kb fallback |
| Planner timeout | Treat as invalid: one plan repair, then manual-kb fallback; no tier charge |
| Planner hallucinated tool | Validation rejection; repair; fallback |
| Manual budget overflow | Apply deterministic compaction order; fail closed with named error only if mandatory sections still exceed the budget; do not execute a truncated card |
| Static enum invalid | Reject before GRASS in new modes; repair with legal range |
| Tool cannot satisfy step | Synthesizer may swap to a documented alternative |
| Repeated same tool failure | Escalate to tool swap, then one re-plan |
| Repair duplicate | Existing no-op detector; pivot/tier rules |
| Semantic failure | Report-only; no repair |

## 10. Invariants

| # | Invariant |
|---|---|
| P1 | `legacy` behavior is unchanged |
| P2 | Planner fallback consumes no tier |
| P3 | Tool swap/re-plan consumes the producing tier |
| P4 | Candidates ≤ `1 + static_limit + runtime_limit` |
| P5 | Duplicate detection remains byte/AST-based |
| P6 | Semantic failures never repair |
| P7 | Pipeline mode is fixed for a run and recorded |
| P8 | Final output is executable `grass.tools` Python only |
| P9 | Plan JSON and manual prose never leak into final code |
| P10 | Manual is authoritative over the plan during synthesis |
| P11 | Total planner invocations ≤ 3: initial plan, one plan repair, one constrained re-plan |
| P12 | A shortlist with fewer than 8 candidates records `shortlist_shortfall`; zero candidates force fallback |
