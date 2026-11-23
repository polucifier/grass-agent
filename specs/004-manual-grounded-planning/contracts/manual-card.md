# Contract: ManualCard Rendering

**Date**: 2026-11-19 | **Plan**: [../plan.md](../plan.md) | **Data model**: [../data-model.md](../data-model.md)

Normative contract for converting a stored `ManualRecord` into the compact, budgeted inference context used by `manual-kb` and `planned`.

## 1. Purpose

The knowledge base stores complete manual sections at rest. The model sees a `ManualCard`: small enough for an 8K context, but complete enough to expose flags, closed enums, constraints, and examples.

## 2. Budget

```text
num_ctx                = 8192 (default) or 16384 (explicit opt-in)
manual_context_tokens  = int(0.45 * num_ctx) unless explicitly overridden
```

Default budgets:

| Context | Default docs budget |
|---|---:|
| 8192 | 3686 |
| 16384 | 7372 |

The budget is global for one generation attempt. It covers the primary card for each tool plus alternatives. Planner output, system prompt, task, inventory, history, and generated code are outside this budget.

The per-card target is 250–600 tokens at 8K. This target is advisory, not a hard cap: every card estimate is reported, and a card outside the range is allowed only when required flags, closed enums, or constraints explain the size. The global budget remains the hard constraint.

## 3. Token estimation

- Estimate at build time and at render time with `ceil(len(text) / 3.5)` plus a 10% safety margin.
- Prefer the model tokenizer when available; otherwise use the conservative estimate.
- Record actual `prompt_eval_count` after each model call and compare with the estimate.
- If actual exceeds the budget, record a context-overflow event; do not claim success.

## 4. Card fields

| Field | Required | Notes |
|---|---|---|
| `tool` | yes | Module name |
| `signature` | yes | `grass.tools.Tools.<method>(...)` |
| `flags` | yes | Module-specific flags with one-line descriptions |
| `parameters` | yes | Name, type, required, default, closed options |
| `constraints` | no | Deterministically selected `NOTES` bullets (documented keyword rule, manual order, capped at three) |
| `examples` | no | 1–2 worked examples |
| `alternatives` | no | 1–2 functional alternatives |
| `omissions` | yes | Explicitly named optional-prose sections dropped by budget; mandatory sections never appear here |
| `token_estimate` | yes | Estimated tokens |
| `source` | no | Provenance |

## 5. Priority

Render in this order:

1. API signature.
2. Module-specific flags with descriptions.
3. Parameters with Python types, defaults, and closed enum `Literal[...]` choices.
4. Top three `NOTES` constraints selected by the documented keyword rule (integer input, file-based parameters, topology, units, extent), in manual order.
5. One or two worked examples.
6. Functional alternatives.

`DESCRIPTION` prose is the lowest priority and is omitted by default unless the tool is ambiguous or the planner flags it.

## 6. Never-silent-truncate rule

- The API signature, module flags, and closed enum choices are mandatory and strictly fail-closed: never truncated, compacted, or omitted.
- Compaction order: deduplicate repeated tools across steps, compact alternatives to one per step, drop optional `EXAMPLES`/`DESCRIPTION`, and keep signatures, flags, closed enums, and the top-3 NOTES constraints.
- If mandatory sections still cannot fit, **fail closed** with a named budget error.
- Only optional prose sections (`DESCRIPTION`, secondary `EXAMPLES`) may be listed in `omissions`; render an explicit marker such as `[omitted: DESCRIPTION]`.
- Never render a truncated mandatory section or a truncated enum list.

## 7. Deduplication and alternatives

- Render each tool once per attempt, even if multiple plan steps use it.
- Include at most two alternatives per step, and only from `TOOL_FAMILIES`.
- When the global budget is tight, compact alternatives to one per step before dropping any mandatory section; never drop signatures, flags, or closed enums.
- `TOOL_FAMILIES` is available in Foundational/US1, so `manual-kb` cards can include alternatives without waiting for the planner.
- Alternatives are compact: tool name, one-line purpose, and one differentiating constraint.

## 8. Example shapes

### `r.viewshed`

```text
### r.viewshed
API: tools.r_viewshed(input, output, coordinates, ..., flags=None)
Flags:
  -b  Output format is invisible = 0, visible = 1
  -c  Consider the curvature of the earth
  -r  Consider atmospheric refraction
  -e  Output format is invisible = NULL, else current elev - viewpoint_elev
Parameters:
  input: raster, required
  output: raster, required
  coordinates: east,north, required
  observer_elevation: float = 1.75
  ...
Constraints:
  - Use -b for binary visibility; without it the output is elevation differences.
Example:
  tools.r_viewshed(input="elevation", output="pilot_viewshed",
                   coordinates="635000,216500", flags="b")
```

### `v.clean`

```text
### v.clean
API: tools.v_clean(input, output, tool, threshold=None, ..., flags=None)
Flags:
  -b  Do not build topology for the output vector
  -c  Combine tools with recommended follow-up tools
Parameters:
  tool: str | list[str], required
    Literal["break", "snap", "rmdangle", "chdangle", "rmbridge",
            "chbridge", "rmdupl", "rmdac", "bpol", "prune",
            "rmarea", "rmline", "rmsa"]
Constraints:
  - rmdupl removes duplicate geometry features.
  - The rmdupl tool should be used after breaking lines.
Example:
  tools.v_clean(input="roadsmajor", output="pilot_roads_clean",
                tool="break,snap", threshold=1)
```

### `r.reclass`

```text
### r.reclass
API: tools.r_reclass(input, output, rules, title=None, ...)
Parameters:
  input: raster, required
  output: raster, required
  rules: str | io.StringIO, required
    File containing reclass rules; "-" for standard input
Constraints:
  - Only works on integer input; floating-point input must be scaled or use r.recode.
  - Rules are a file or stream, not inline text passed as a plain string.
Example:
  with open("rules.txt", "w") as f:
      f.write("0 thru 15 = NULL\n* = 1\n")
  tools.r_reclass(input="slope", output="steep", rules="rules.txt")
Alternatives:
  r.recode — recodes categorical rasters, supports file rules
  r.mapcalc — expression-based classification
```

## 9. Mode behavior

| Mode | Card use |
|---|---|
| `legacy` | Never; `format_context()` remains unchanged |
| `manual-kb` | Cards for the top-k retrieved tools, initial and repair |
| `planned` | Cards for each planned step plus alternatives; deduplicated |

## 10. Invariants

| # | Invariant |
|---|---|
| MC1 | Total card tokens ≤ `manual_context_tokens` |
| MC2 | API signatures, module flags, and closed enums are present or the render fails closed |
| MC3 | Optional omissions are named in `omissions` |
| MC4 | Same tool is rendered once per attempt |
| MC5 | Alternatives are ≤2 per step and are real KB tools |
| MC6 | Rendering is deterministic for the same record, budget, and step set |
| MC7 | Actual prompt tokens are recorded; overflow is observable |
