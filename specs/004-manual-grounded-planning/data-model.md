# Phase 1 Data Model: Manual-Grounded Knowledge Base and Candidate-Constrained Planning

**Date**: 2026-11-19 | **Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

This document defines the persisted and in-memory entities added or changed by Feature 004, the knowledge-base schema, artifact layout, pipeline state machines, and invariants. It is the authoritative shape reference for `grass_agent/kb_*.py`, `grass_agent/manual_context.py`, `grass_agent/planner.py`, `grass_agent/agentic.py`, `grass_agent/results.py`, and [contracts/](./contracts/).

Existing Gate 2/Gate 3 entities (`Attempt`, `CaseResult`, `ResumeKey`, `RunSummary`) are extended additively. No field is renamed or removed, and `case_result.json` stays at `schema_version: 1`.

## 1. Entity: KnowledgeBaseMetadata

One row per key in `db_meta`; describes the knowledge base as a whole.

| Key | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | string | yes | Additive schema version; `2` for Feature 004 |
| `grass_version` | string | yes | Installed GRASS version used to build, e.g. `8.5.0` |
| `gisbase` | string | yes | Resolved `$GISBASE` |
| `source` | string | yes | `mkdocs-markdown` \| `html` \| `mixed` |
| `built_at` | string | yes | ISO-8601 UTC |
| `tool_count` | int | yes | Number of module records |
| `section_count` | int | yes | Number of stored manual sections |
| `content_hash` | string | yes | Hash over canonical record content |

**Rules**

- A `manual-kb` or `planned` run requires `schema_version` compatible with the code, `grass_version` equal to the installed version, and the required provenance keys (`source`, `built_at`, `content_hash`, `gisbase`) present.
- `gisbase` presence is required, but the path need not match the current host; portability is allowed.
- `legacy` may read a DB without these rows.
- A version mismatch or missing required provenance is a pre-flight failure (exit `3`) with a rebuild hint.

## 2. Entity: ManualRecord (`ToolDoc` extension)

One local GRASS module's complete manual equivalent. In memory this extends the existing `ToolDoc` with optional fields appended after the current positional fields.

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | Module name, e.g. `r.viewshed` |
| `category` | string | yes | `r`, `v`, `d`, etc. |
| `description` | string | yes | Short manual description |
| `signature` | string | yes | `grass.tools.Tools.<method>(...)` signature |
| `example` | string | yes | Canonical shortest example (legacy field) |
| `params` | dict | yes | API parameter map: type, required, default, `options` |
| `similarity` | float | yes | Retrieval score; `0.0` for exact lookup |
| **`flags`** | list of ModuleFlag | no | Module-specific and generic flags |
| **`options`** | dict[str, list[ClosedEnumOption]] | no | Closed enum values by API parameter |
| **`sections`** | dict[str, list[ManualSection]] | no | Full manual sections at rest |
| **`source`** | string | no | Source kind and path/provenance |
| **`grass_version`** | string | no | Version used to build this record |
| **`content_hash`** | string | no | Hash of canonical record content |
| **`source_mismatches`** | list of dict | no | Markdown/XML disagreements, persisted as `source_mismatches_json` |
| **`xml_validated`** | bool | no | `true` when XML enrichment was applied; `false` for Markdown-only optional/add-on records |

**Rules**

- `name` is unique.
- A Markdown/XML parameter-name or enum disagreement is persisted in `source_mismatches_json` with the parameter, Markdown value, XML value, and mismatch kind; it is also summarized in the build report.
- `signature` comes from local Markdown when available; otherwise it is synthesized from XML and marked as synthesized.
- Manifest modules MUST have XML enrichment; optional/add-on modules without it are ingested from Markdown with `xml_validated=false`.
- `params` MUST include synthetic API flag kwargs: `flags`, `overwrite`, `verbose`, `quiet`, `superquiet`.
- `options[param]` is non-empty only for genuinely closed enums.
- Full sections may be large; they are stored at rest and never passed unbounded to a model.

## 3. Entity: ModuleFlag

| Field | Type | Required | Notes |
|---|---|---|---|
| `flag` | string | yes | Single character, e.g. `b`, or a generic name like `overwrite` |
| `description` | string | yes | Localized English description |
| `generic` | bool | yes | True for `overwrite`, `verbose`, `quiet`, `superquiet`, `help` |
| `gui_section` | string | no | Optional grouping from XML |

**Rules**

- A module-specific flag is addressable through `flags="..."`.
- A generic flag is an API keyword (`overwrite=True`), not a `flags` character.
- Static validation checks `flags` characters against module-specific flags only.

## 4. Entity: ClosedEnumOption

| Field | Type | Required | Notes |
|---|---|---|---|
| `parameter` | string | yes | API parameter name |
| `value` | string | yes | Allowed value, e.g. `rmdupl` |
| `description` | string | no | One-line meaning from XML/Markdown |
| `ordinal` | int | yes | Stable source order |

**Rules**

- Only finite `<values>` sets become options.
- Ranges (`0-360`), free text, map names, file paths, and expressions are not options.
- Multi-valued parameters are validated per comma-separated value.

## 5. Entity: ManualSection

| Field | Type | Required | Notes |
|---|---|---|---|
| `section` | string | yes | `SYNOPSIS`, `DESCRIPTION`, `NOTES`, `EXAMPLES`, etc. |
| `ordinal` | int | yes | Stable order within a section |
| `text` | string | yes | Canonical plain text; tabs deduplicated |
| `token_estimate` | int | yes | Conservative estimate at build time |
| `content_hash` | string | yes | Hash for provenance/deduplication |

**Rules**

- The same section is stored once per module; CLI/Python/`grass.script` duplicates are collapsed.
- `DESCRIPTION` is stored in full but is the first section dropped by the renderer.
- `NOTES` and `EXAMPLES` are retained for constraint and file-based-parameter guidance.

## 6. Entity: ManualCard

The compact inference view of a `ManualRecord`.

| Field | Type | Required | Notes |
|---|---|---|---|
| `tool` | string | yes | Module name |
| `signature` | string | yes | API signature |
| `flags` | list of string | yes | Module-specific flags with descriptions |
| `parameters` | list of ParameterCard | yes | Type, required, default, options |
| `constraints` | list of string | no | Selected NOTES bullets |
| `examples` | list of string | no | 1–2 worked examples |
| `alternatives` | list of string | no | 1–2 functional alternatives |
| `omissions` | list of string | yes | Optional prose sections dropped by budget (`DESCRIPTION`, secondary `EXAMPLES`), explicitly named; mandatory sections are never omitted |
| `token_estimate` | int | yes | Estimated tokens |
| `source` | string | no | Provenance |

**ParameterCard** fields: `name`, `type`, `required`, `default`, `options` (closed values), `description`.

**Rendering rules**

- Deterministic order: signature → flags → parameters/types/defaults/enums → top-3 NOTES constraints → examples → alternatives.
- Closed enums are rendered as Python-literal choices.
- The per-card target is 250–600 tokens at 8K; every estimate is reported, and an out-of-range card is allowed only when required flags, enums, or constraints explain it.
- The API signature, module flags, and closed enums are mandatory and strictly fail-closed; they are never truncated or omitted. Only optional prose (`DESCRIPTION`, secondary `EXAMPLES`) may be listed in `omissions`.
- Compaction order: deduplicate tools, compact alternatives to one per step, drop optional prose, then fail closed with a named error if mandatory sections still do not fit.
- `ManualCard` for the same tool is deduplicated across plan steps.

## 7. Entity: CandidateShortlist

| Field | Type | Required | Notes |
|---|---|---|---|
| `query` | string | yes | Original user prompt |
| `candidates` | list of Candidate | yes | Up to `shortlist_k=12` real modules from hybrid retrieval; at least eight when available |
| `shortlist_shortfall` | bool | yes | True when fewer than eight real modules were available |
| `shortlist_k` | int | yes | Retrieval count for planned mode; default `12`, valid range `8-12` (`rag_top_k=5` unchanged for legacy/manual-kb) |
| `retrieval_mode` | string | yes | Existing `hybrid` path |
| `embedding_model` | string | yes | `nomic-embed-text` |

**Candidate**: `name`, `category`, `description`, `similarity`, `source`.

**Rules**

- Planned-mode retrieval uses `shortlist_k` (default `12`, valid range `8-12`); `rag_top_k=5` is untouched for legacy/manual-kb.
- Candidates must exist in the knowledge base.
- The planner may select only from this list.
- Fewer than eight candidates is allowed only when `shortlist_shortfall` is true; zero candidates force manual-kb fallback.
- The list is deterministic for a given query/embedding/model/DB.

## 8. Entity: ExecutionPlan

| Field | Type | Required | Notes |
|---|---|---|---|
| `steps` | list of PlanStep | yes | 1–5 ordered steps |
| `assumptions` | list of string | no | Planner assumptions |
| `revision` | int | yes | `0` initial; `1` after a plan repair or constrained re-plan |
| `plan_repair_count` | int | yes | `0` or `1`; pre-execution plan repair |
| `replan_count` | int | yes | `0` or `1`; post-failure constrained re-plan |
| `planner_invocations` | int | yes | Initial plan plus repairs; must be `≤ 3` |
| `raw_response_hash` | string | no | Hash of the raw planner response for diagnostics |
| `fallback` | bool | yes | True when the run fell back to manual-kb |

**PlanStep**

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | int | yes | 1-based, contiguous |
| `intent` | string | yes | Atomic GIS action |
| `tool` | string | yes | From the candidate shortlist |
| `inputs` | list of string | yes | Inventory maps or prior-step outputs |
| `outputs` | list of string | yes | Distinct within the plan |
| `output_types` | list of `raster`/`vector` | yes | Type compatibility |
| `constraints` | list of string | no | Planner-declared constraints |

**Validation rules**

- `1 ≤ len(steps) ≤ 5`.
- Every `tool` is in the shortlist and exists in the KB.
- Every input is an inventory map or an output of an earlier step.
- Every output is non-empty and distinct.
- Raster/vector type compatibility is checked against the tool family/category.
- A plan that fails validation or times out is repaired at most once; then fallback to manual-kb.
- A pre-execution plan repair and a post-failure constrained re-plan are distinct; both may occur, but `planner_invocations ≤ 3`.
- A plan repair does not consume a static/runtime tier.

## 9. Entity: ToolFamily

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | `reclassify`, `clean`, `buffer`, `import`, ... |
| `members` | list of string | yes | Real module names |
| `default_alternative` | string | no | Preferred replacement |
| `notes` | string | no | One-line functional distinction |

**Initial families**

| Family | Members |
|---|---|
| `reclassify` | `r.reclass`, `r.recode`, `r.mapcalc` |
| `clean` | `v.clean`, `v.edit`, `v.generalize` |
| `buffer` | `v.buffer`, `r.buffer` |
| `import` | `v.import`, `r.import`, `v.in.ogr`, `r.in.gdal` |
| `rasterize` | `v.to.rast`, `r.mapcalc` |

**Rules**

- Alternatives are real KB tools with a manual card.
- At most two alternatives are rendered per step.
- The family is used for tool swaps during repair, not for free-form planner expansion.

## 10. Entity: PipelineMode

| Value | Meaning |
|---|---|
| `legacy` | Existing retrieval + `format_context()` + synthesis; default |
| `manual-kb` | Retrieval + `ManualCard`s + synthesis; no planner |
| `planned` | Shortlist + validated JSON plan + per-step cards + synthesis |

**Rules**

- One mode per run; not per case.
- The mode is recorded in `ResumeKey`, `Attempt`, and `RunSummary`.
- A resumed result is reusable only when the mode matches.
- `legacy` keeps existing validation behavior; strict closed-enum checks are gated to the new modes.

## 11. Entity: PipelineGenerationResult

The return value of the generation layer; `run_case` consumes it without changing the candidate budget.

| Field | Type | Required | Notes |
|---|---|---|---|
| `code` | string | yes | Extracted executable code |
| `prompt_tokens` | int | yes | Existing provider counter |
| `completion_tokens` | int | yes | Existing provider counter |
| `plan` | ExecutionPlan \| null | no | Planned mode only |
| `plan_fallback` | bool | yes | True when planner failed and manual-kb was used |
| `plan_repair_count` | int | yes | `0` or `1` |
| `replan_count` | int | yes | `0` or `1` |
| `planner_invocations` | int | yes | Initial plan plus repairs; `≤ 3` |
| `shortlist_shortfall` | bool | yes | Fewer than eight real candidates |
| `manual_cards` | list of ManualCard | no | Evidence for diagnostics |
| `manual_tokens` | int | yes | Estimated/actual card tokens |
| `manual_omissions` | list of string | yes | Explicit optional-prose omissions; mandatory sections never appear here |
| `tool_swaps` | list of string | no | Tools replaced during synthesis/repair |
| `planner_prompt_tokens` | int | no | Planner call cost |
| `planner_completion_tokens` | int | no | Planner call cost |

**Rules**

- `plan_fallback=true` means no tier was charged for the planner failure.
- A tool swap/re-plan during repair is part of a repair candidate and charges the producing tier.
- The final code is still extracted and validated by the existing zero-chat/static path.
- Naming: `manual_context_tokens` is the documentation budget; `manual_tokens` and `manual_card_tokens` are rendered-card token counts; `manual_omissions` is the attempt-level copy of `ManualCard.omissions`.

## 12. Entity: Attempt (extended)

Existing fields are unchanged. New fields are appended with defaults so positional construction and old records keep working.

| Field | Type | Default | Notes |
|---|---|---|---|
| **`pipeline`** | string | `"legacy"` | `legacy` \| `manual-kb` \| `planned` |
| **`num_ctx`** | int | `8192` | Resolved context used for this attempt |
| **`manual_context_tokens`** | int \| null | `null` | Resolved documentation budget |
| **`plan_revision`** | int | `0` | `0` initial; `1` after a plan repair or replan |
| **`plan_repair_count`** | int | `0` | `0` or `1`; pre-execution repairs |
| **`replan_count`** | int | `0` | `0` or `1`; post-failure constrained replans |
| **`planner_invocations`** | int | `0` | Initial plan plus repairs; `≤ 3` |
| **`shortlist_shortfall`** | bool | `false` | Fewer than eight real candidates |
| **`planned_tools`** | list of string | `[]` | Tools in the plan for this attempt |
| **`tool_swaps`** | list of string | `[]` | e.g. `["r.reclass -> r.recode"]` |
| **`plan_fallback`** | bool | `false` | Planner failed and manual-kb was used |
| **`manual_card_tokens`** | int | `0` | Rendered card tokens |
| **`manual_omissions`** | list of string | `[]` | Explicit optional-prose drops; mandatory sections never appear here |
| **`planner_prompt_tokens`** | int | `0` | Planner call cost |
| **`planner_completion_tokens`** | int | `0` | Planner call cost |

**Rules**

- `pipeline`, `num_ctx`, and `manual_context_tokens` match the run.
- `plan_revision` is `0` or `1`.
- `plan_repair_count` and `replan_count` are each `0` or `1`, and their sum is at most `2` (`planner_invocations ≤ 3`).
- `planner_invocations` never exceeds three and is never less than `1 + plan_repair_count + replan_count` when a plan exists.
- `planned_tools` is empty for legacy/manual-kb attempts.
- `tool_swaps` records documented substitutions, not arbitrary changes.
- `plan_fallback=true` implies `planned_tools` may be empty and no planner tier was charged.

## 13. Entity: ResumeKey (extended)

| Field | Type | Default | Notes |
|---|---|---|---|
| `model` | string | — | Existing |
| `max_retries` | int | — | Existing |
| `timeout` | int | — | Existing |
| `attempt1_source` | string | — | Existing |
| `max_static_retries` | int \| null | `null` | Existing |
| `max_runtime_retries` | int \| null | `null` | Existing |
| `harness` | string | `"gate2"` | Existing |
| **`pipeline`** | string | `"legacy"` | New; must match for reuse |
| **`num_ctx`** | int | `8192` | New; context budget is part of reproducibility |
| **`manual_context_tokens`** | int \| null | `null` | New; resolved docs budget |

**Rules**

- `matches()` requires equal `pipeline`, `num_ctx`, and effective manual budget.
- Old keys default to `legacy`/`8192`/`None` and still match each other.
- A `legacy` result never matches a `manual-kb` or `planned` key.
- A 16K result never matches an 8K key.

## 14. Entity: RunSummary (extended)

Additive fields:

| Field | Type | Notes |
|---|---|---|
| `pipeline` | string | Mode for the run |
| `num_ctx` | int | Context used |
| `manual_context_tokens` | int | Resolved documentation budget |
| `manual_cards_rendered` | int | Count |
| `manual_budget_failures` | int | Fail-closed events |
| `context_overflow_events` | int | Must be `0` for success |
| `plan_attempts` | int | Planned-mode cases with a planner call |
| `plan_repairs` | int | Pre-execution plan repair count |
| `plan_fallbacks` | int | Planner fallback count |
| `replans` | int | Post-failure constrained re-plan count |
| `shortlist_shortfalls` | int | Cases with fewer than eight real candidates |
| `tool_swaps` | int | Documented substitutions |
| `pipeline_ablation` | list of dict | Optional per-mode comparison rows when multiple summaries are supplied |

Derived properties remain unchanged. `pass_at_executed` and `pass_at_semantic` retain their Gate 3 definitions.

## 15. Entity: RepairTurn / RepairContext (extended)

`RepairTurn` gains optional diagnostics:

| Field | Type | Default | Notes |
|---|---|---|---|
| `pipeline` | string | `"legacy"` | Mode |
| `plan_revision` | int | `0` | Plan revision |
| `plan_repair_count` | int | `0` | Pre-execution plan repairs |
| `replan_count` | int | `0` | Post-failure constrained replans |
| `planned_tools` | list of string | `[]` | Plan tools |
| `tool_swap` | string \| null | `null` | e.g. `r.reclass -> r.recode` |

`RepairContext` gains optional:

| Field | Type | Default | Notes |
|---|---|---|---|
| `pipeline` | string | `"legacy"` | Mode |
| `plan_revision` | int | `0` | Plan revision |
| `plan_repair_count` | int | `0` | Pre-execution plan repairs |
| `replan_count` | int | `0` | Post-failure constrained replans |
| `planned_tools` | list of string | `[]` | Plan tools |
| `plan` | ExecutionPlan \| null | `null` | Current plan |
| `manual_card` | string | `""` | Rendered failing-tool card |
| `tool_swap_candidates` | list of string | `[]` | Alternatives for the failing step |

**Rules**

- When no new fields are supplied, the rendered message is byte-for-byte the existing Gate 2/Gate 3 prompt.
- Manual cards and plan evidence are inserted before the previous-attempt history; the exact error remains adjacent to the failing code.
- The parameter pivot table includes module flags and closed enum options.

## 16. Artifact layout

```text
benchmarks/output_execution/<case_id>/
├── case_result.json
├── attempt_1.py
├── attempt_1.log
├── attempt_1.stdout
├── attempt_1.stderr
├── attempt_1.maps.json          # when executed
├── attempt_1.semantic.json      # when probed
├── attempt_1.plan.json          # planned mode; plan used for this attempt
├── attempt_1.manuals.json       # card metadata, token counts, omissions
├── status.json
└── final.py
```

`data/kb_build_report.json` is optional build evidence: source paths, GRASS version, per-module status, omissions, hashes, source mismatches, and the distribution decision (committed or generated).

## 17. State machines

### 17.1 Generation mode selection

```text
pipeline = legacy
  └─ existing retrieve -> format_context -> synthesize

pipeline = manual-kb
  └─ retrieve top-k -> ManualCards -> synthesize

pipeline = planned
  └─ shortlist(shortlist_k=12, minimum 8 when available, or all available with shortfall; zero -> fallback)
       └─ planner JSON (timeout default 60s)
            ├─ valid -> per-step cards + alternatives -> synthesize
            ├─ invalid/timeout -> one pre-execution plan repair
            │              ├─ valid -> per-step cards -> synthesize
            │              └─ invalid -> fallback manual-kb (no tier charge)
            └─ parser/provider failure -> fallback manual-kb (no tier charge)
```

### 17.2 Repair escalation (all non-legacy modes)

```text
failure
  │
  ├─ same-tool ManualCard repair
  │     └─ still fails?
  ├─ parameter/option pivot (flags + closed enums)
  │     └─ still fails?
  ├─ tool swap from TOOL_FAMILIES
  │     └─ still fails?
  └─ one constrained re-plan (post-failure; distinct from pre-execution plan repair)
        └─ still fails? -> existing tier exhaustion / terminal failure
```

Every repair candidate is charged to the producing tier. Planner fallback before a candidate is free. Semantic failures never enter this ladder. Total planner invocations, including the initial plan and any pre-execution repair, never exceed three.

### 17.3 No-op and semantic interaction

```text
candidate generated
  -> byte/AST duplicate? -> reject before execution, charge producing tier
  -> static guard (strict enums only in manual-kb/planned)
  -> execute
  -> semantic probe (if declared)
       -> pass/fail verdict, report-only
```

## 18. Invariants

| # | Invariant | Spec ref |
|---|---|---|
| I1 | `legacy` behavior, `format_context()`, `SYSTEM_PROMPT`, and all 394 existing tests are unchanged | FR-028 |
| I2 | A `manual-kb`/`planned` result is reusable only when `pipeline`, `num_ctx`, and manual budget match | FR-029 |
| I3 | Plan steps are 1–5, tools are from the shortlist, outputs are distinct, and inputs have lineage | FR-018, FR-019 |
| I4 | Planner fallback consumes no tier; tool swap/re-plan consumes the producing tier; candidates ≤ `1 + static + runtime` | FR-025 |
| I4a | A shortlist uses `shortlist_k=12` (minimum `8`) and has at least eight candidates when available; fewer than eight records `shortlist_shortfall`; zero forces manual-kb fallback | FR-017 |
| I4b | Total planner invocations are at most three (initial plan, one plan repair, one constrained re-plan) | FR-020, FR-024 |
| I5 | Rendered cards stay within budget; signatures, flags, and closed enums are mandatory and never truncated/omitted; only optional prose may be omitted; mandatory overflow fails closed after deterministic compaction | FR-010, FR-011 |
| I6 | Strict closed-enum rejection runs only in `manual-kb`/`planned` | FR-013, FR-028 |
| I7 | `error_excerpt` remains a verbatim substring and preserves the underlying `ERROR:`/legal-range lines when present | FR-014 |
| I8 | Semantic failures generate no repair and consume no tier | FR-026 |
| I9 | Byte/AST duplicate detection is unchanged and code-based | FR-026, FR-027 |
| I10 | `manual-kb`/`planned` require a matching DB version and required provenance; `legacy` may read an old DB | FR-009 |
| I11 | A tool card is rendered once per context; alternatives are ≤2 per step | FR-012 |
| I12 | Attempt plan/tool-swap metadata is consistent with the generated code and the plan artifact | FR-027 |
| I13 | `RunSummary.pipeline` equals the mode of every attempt in the run | FR-029 |
| I14 | Zero outbound network calls occur during build or execution | FR-031 |
| I15 | The two-tier ledger, no-op count, `Pass@Executed`, and `Pass@Semantic` recompute identically from persisted attempts | FR-032 |

**Enforcement**: `check_invariants()` raises on I1/I4a/I4b/I5/I6/I7/I9/I10/I15 violations; `is_reusable()` rejects I2/I13 mismatches; pipeline tests cover I3/I4/I8/I11/I12/I14.
