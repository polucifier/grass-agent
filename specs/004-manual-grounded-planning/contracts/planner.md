# Contract: Candidate-Constrained Planner

**Date**: 2026-11-19 | **Plan**: [../plan.md](../plan.md) | **Data model**: [../data-model.md](../data-model.md)

Normative contract for `--pipeline planned`: shortlist, JSON plan, validation, repair, fallback, and artifacts.

## 1. Pipeline

```text
prompt + inventory
  -> hybrid retrieval shortlist (shortlist_k=12; at least 8 real modules when available)
       -> fewer than 8: all available + shortlist_shortfall
       -> zero: fallback to manual-kb
  -> local planner JSON (timeout default 60s)
  -> KB validation
       -> valid: per-step ManualCards + alternatives -> synthesis
       -> invalid/timeout: one pre-execution plan repair -> validate
            -> valid: synthesis
            -> invalid: fallback to manual-kb single-shot
```

The planner is an internal workflow step. Its JSON is never emitted as final output.

## 2. Candidate shortlist

| Field | Rule |
|---|---|
| Size | Up to `shortlist_k=12` real modules; at least 8 when available; fewer than 8 only with `shortlist_shortfall=true`; zero forces fallback |
| Retrieval count | `shortlist_k` (default `12`, valid range `8-12`); `rag_top_k=5` remains unchanged for legacy/manual-kb |
| Source | Existing hybrid retriever (`rag_retriever.retrieve`) with `k=shortlist_k` |
| Names | Must exist in `tools` |
| Ordering | Existing score order after anti-crowding |
| Determinism | Same query/embedding/model/DB yields the same list |

The shortlist may include functional alternatives already, but the planner must not invent names. A shortfall is recorded on the plan artifact and run summary.

## 3. Planner output schema

The model MUST return JSON only:

```jsonc
{
  "steps": [
    {
      "id": 1,
      "intent": "Compute slope from elevation",
      "tool": "r.slope.aspect",
      "inputs": ["elevation"],
      "outputs": ["pilot_steep_slope"],
      "output_types": ["raster"],
      "constraints": []
    }
  ],
  "assumptions": []
}
```

### Field rules

| Field | Type | Rule |
|---|---|---|
| `steps` | array | 1–5 items |
| `id` | int | 1-based, contiguous |
| `intent` | string | Non-empty, atomic |
| `tool` | string | Must be in the shortlist |
| `inputs` | array of string | Inventory map or earlier output |
| `outputs` | array of string | Non-empty, distinct across the plan |
| `output_types` | array of `raster`/`vector` | Length matches `outputs` |
| `constraints` | array of string | Optional planner notes |
| `assumptions` | array of string | Optional |

## 4. Validation

Reject the plan when any of these hold:

- Invalid JSON, a planner timeout, empty `steps`, more than 5 steps, or non-contiguous ids.
- A tool is not in the shortlist or not in the KB.
- A step has no inputs, no outputs, or mismatched `outputs`/`output_types`.
- An output name is duplicated.
- An input is neither an inventory map nor an output of an earlier step.
- A raster/vector type is incompatible with the tool family/category.
- The plan asks for an unsupported operation that the manual family cannot satisfy.

Validation errors are human-readable and include the offending step id and tool.

## 5. Plan repair

- At most one pre-execution plan repair.
- The repair prompt includes the original prompt, the invalid plan, the validation error, and the same shortlist.
- A timeout is treated as invalid and uses the same repair path; the timeout defaults to 60 seconds and is configurable.
- A repaired plan is re-validated.
- If the repair is also invalid, fall back to manual-kb single-shot.
- Planner repair and fallback consume no static/runtime tier and create no candidate.

## 5.1 Constrained re-plan

- A constrained re-plan is a post-failure repair escalation step, distinct from the pre-execution plan repair.
- At most one constrained re-plan per case.
- A case may use both one plan repair and one constrained re-plan.
- Total planner invocations are capped at three: initial plan, one plan repair, one constrained re-plan.
- The constrained re-plan consumes the producing repair tier.

## 6. Fallback

Fallback is clean and observable:

- `plan_fallback = true`.
- The attempt records `pipeline = planned` but `planned_tools = []`.
- Generation proceeds as `manual-kb`: retrieve top-k, render cards, synthesize.
- The report counts the fallback; it is not a failure.

## 7. Artifact

`attempt_N.plan.json`:

```jsonc
{
  "pipeline": "planned",
  "revision": 0,
  "plan_repair_count": 0,
  "replan_count": 0,
  "planner_invocations": 1,
  "fallback": false,
  "shortlist": ["r.slope.aspect", "r.reclass", "r.recode", "r.to.vect"],
  "shortlist_shortfall": false,
  "plan": { "steps": [], "assumptions": [] },
  "validation": {"ok": true, "errors": []},
  "planner_prompt_tokens": 412,
  "planner_completion_tokens": 96
}
```

A plan repair writes `revision: 1`, increments `plan_repair_count`, and includes the prior validation errors. A constrained re-plan increments `replan_count` and also writes `revision: 1`. `planner_invocations` never exceeds three. The final plan used for synthesis is the one persisted.

## 8. Prompt contract

The planner prompt includes:

- The original task and inventory summary.
- The candidate shortlist with one-line descriptions.
- The JSON schema and the 5-step limit.
- The instruction to use only shortlisted tools and real inventory maps.
- The instruction to return JSON only, with no Markdown fences or prose.

The synthesizer prompt includes:

- The original task.
- The validated plan as advisory context.
- The per-step manual cards as authoritative context.
- The instruction that a documented alternative may replace the plan's tool.
- The existing zero-chat rules and `grass.tools` contract.

## 9. Error handling

| Failure | Behaviour |
|---|---|
| Planner returns prose or fences | Parse/extract JSON; if impossible, one repair; then fallback |
| Planner timeout/provider error | Treat as invalid: one plan repair, then fallback; no tier charge |
| Planner hallucinates a tool | Validation rejects; one repair; fallback |
| Planner picks a tool that cannot accept the input | Synthesizer may substitute a documented alternative |
| Manual card budget cannot fit required data | Fail closed with a named error; do not silently truncate |
| Constrained re-plan during repair | At most one per case, distinct from plan repair; consumes the producing tier |

## 10. Invariants

| # | Invariant |
|---|---|
| PL1 | Every planned tool is in the shortlist and the KB |
| PL2 | `1 ≤ steps ≤ 5` |
| PL3 | Outputs are distinct; inputs have lineage |
| PL4 | At most one pre-execution plan repair; then fallback |
| PL5 | At most one constrained re-plan per case; total planner invocations ≤ 3 |
| PL6 | A shortlist uses `shortlist_k=12` (minimum `8`); fewer than 8 candidates records `shortlist_shortfall`; zero candidates force fallback |
| PL7 | Fallback consumes no tier |
| PL8 | Planner JSON never appears in final code |
| PL9 | Manual is authoritative over the plan |
| PL10 | Plan artifacts are persisted for each planned attempt |
