---

description: "Task list for Feature 004 — Manual-Grounded Knowledge Base and Candidate-Constrained Planning"
---

# Tasks: Manual-Grounded Knowledge Base and Candidate-Constrained Planning

**Feature**: `004-manual-grounded-planning`
**Input**: Design documents from `/specs/004-manual-grounded-planning/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Included because `plan.md` (File Change Matrix) and `quickstart.md` explicitly require the new unit/integration tests and the 394-test zero-regression gate. Test tasks precede implementation within each story, except T036's cross-story invariant regression, which is ordered after T041; live-GRASS tests stay `slow` and skippable.

**Organization**: Tasks are grouped by user story. `legacy` remains the default and must stay behaviorally unchanged throughout. **Phase mapping**: `plan.md` Phase 2/3/4 are Step A / Step B / isolation-and-reporting, while `tasks.md` Phase 3/4/5 are US1 / US2 / US3; the plan's File Change Matrix uses the plan numbering.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: `US1`, `US2`, `US3`; omitted for Setup, Foundational, and Polish
- Every task names its exact file path

## Path Conventions

- Single-project layout: `grass_agent/`, repository-root modules, `benchmarks/`, `scripts/`, `tests/`
- Feature artifacts: `specs/004-manual-grounded-planning/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Governance prerequisite, shared fixtures, and test scaffolding required before any source edit.

- [x] T001 Amend `.specify/memory/constitution.md` from `v1.3.0` to `v1.4.0` as a MINOR change: add a Sync Impact Report naming `004-manual-grounded-planning` as the current milestone, permit internal JSON planning as an intermediate step while preserving the zero-chat executable-Python final-output contract, add `qwen2.5-coder:14b` and `qwen2.5-coder:32b` to the approved stack (keep `7b`/`3b`), record that Gate 3's semantic oracle, two-tier budgets, stateful healing, and report-only semantic failures are unchanged, and update `Version`/`Last Amended` — completed 2026-11-19
- [x] T002 [P] Add offline parser fixtures under `tests/fixtures/kb/` (create the directory): Markdown pages for `r.viewshed`, `v.clean`, `r.reclass`, `r.recode`; XML interface descriptions exposing `-b`, `v.clean` `rmdupl`/`snap`, and a range value; one HTML fallback page; one Markdown/XML parameter-name mismatch fixture; no network-dependent fixtures
- [x] T003 [P] Add shared Feature 004 test helpers in `tests/conftest.py`: a fake `OllamaProvider` (chat/chat_with_stats/embeddings), a fake retriever, a temporary SQLite KB factory, and a `socket.connect` guard fixture that raises on any outbound connection
- [x] T003A [P] Create `benchmarks/kb_required_modules.txt` as the authoritative benchmark-relevant module manifest: one sorted module per line, derived from `benchmarks/pilot_reference/*.py`, `benchmarks/pilot_expectations.json`, and the 40-case suite prompts; document the derivation in the file header

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Additive configuration and retrieval data shapes that every pipeline mode depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T004 [P] Add additive fields to `GenerationConfig` in `config.py`: `pipeline: str = "legacy"`, `num_ctx: int = 8192`, `manual_context_tokens: int | None = None`, `strict_options: bool | None = None` (resolved to `True` for `manual-kb`/`planned`; for `legacy`, the explicit opt-in with default `False`), `shortlist_k: int = 12`, `planner_model: str | None = None`, `planner_timeout: int = 60`; keep all existing default values, `rag_top_k=5`, and `from_env()` behavior unchanged
- [x] T005 Add additive fields and resolution helpers to `ExecutionConfig` in `grass_agent/config.py`: `pipeline="legacy"`, `num_ctx=8192`, `manual_context_tokens=None`, `strict_options=None` (resolved to `True` for `manual-kb`/`planned`; for `legacy`, the explicit opt-in with default `False`), `shortlist_k=12` (must be between `8` and `12`; `rag_top_k=5` remains untouched for `legacy`/`manual-kb`), `planner_model=None`, `planner_timeout=60`; implement `GRASS_PIPELINE`/`GRASS_NUM_CTX`/`GRASS_MANUAL_CONTEXT_TOKENS`/`GRASS_PLANNER_TIMEOUT` precedence (CLI > env > default), a `resolve_manual_budget()` returning `int(0.45 * num_ctx)` (3686 at 8192, 7372 at 16384), and mode validation restricted to `legacy`/`manual-kb`/`planned`; reject `manual_context_tokens <= 0` and values above 60% of `num_ctx`, warn above 50%, reject `shortlist_k < 8` or `shortlist_k > 12`, and treat `GRASS_STRICT_OPTIONS` as a legacy-only opt-in that is ignored in `manual-kb`/`planned`; validate `planner_model` only when `pipeline == "planned"` against the constitution-approved Ollama set (`qwen2.5-coder:7b|14b|32b`, plus `:3b` for smoke runs) and exit `2` for any other value in that mode, ignoring the value without validation in `legacy`/`manual-kb`; resolve `planner_model=None` to the synthesis model in `planned` mode
- [x] T006 [P] Extend `ToolDoc` in `rag_retriever.py` with optional fields appended after `similarity`: `flags`, `options`, `sections`, `source`, `grass_version`, `content_hash`, `source_mismatches`, `xml_validated` (all defaulted); update `_row_to_doc()` to tolerate both the existing six-column DB and the Feature 004 schema without breaking positional construction
- [x] T006A [P] Add `pipeline: str = "legacy"`, `num_ctx: int = 8192`, and `manual_context_tokens: int | None = None` additively to `Attempt` in `grass_agent/results.py` and `RunSummary` in `grass_agent/reporting.py`, serialized in `case_result.json`/`run_summary.json` with legacy defaults, so Step A records the mode on every attempt and run summary (FR-016); keep `SCHEMA_VERSION = 1`

**Checkpoint**: Configuration and retrieval shapes are stable; legacy defaults unchanged; the mode can be persisted before any planner exists.

---

## Phase 3: User Story 1 — Local Manual-Grounded Generation and Repair (Priority: P1) 🎯 MVP

**Goal**: `--pipeline manual-kb` grounds generation and repair in a strictly offline local GRASS 8.5 knowledge base with budgeted manual cards, synthesized flag kwargs, strict closed-enum checks in new modes only, and verbatim underlying GRASS errors.

**Independent Test**: On an offline host with local GRASS 8.5 documentation, build the KB, run the three documented failure cases (`pilot_tc_08`, `pilot_tc_14`, `pilot_tc_32`) plus the full suite, and verify flags/enums/file constraints appear, repair prompts contain the underlying `ERROR:`/`Legal range:` lines, cards stay within budget, and all 394 pre-existing tests pass unchanged.

### Tests for User Story 1

> Write these tests first and confirm they fail against the current code before implementation.

- [x] T007 [P] [US1] Add `tests/test_kb_source.py`: `$GISBASE` resolution from env and `grass --config path`, deterministic sorted module enumeration from `docs/mkdocs/source/*.md`, HTML fallback, XML-session-unavailable failure for manifest modules (exit `3`) versus optional-module skip, content hashes, and zero outbound `socket.connect` during discovery
- [x] T008 [P] [US1] Add `tests/test_kb_parse.py`: parse `grass.tools.Tools.<name>` signature, Python types, defaults, `DESCRIPTION`/`NOTES`/`EXAMPLES`; collapse Command-line/`grass.tools`/`grass.script` tabs to one canonical section; merge XML flags/requiredness/`multiple`/finite `<values>`; record Markdown/XML name mismatches; never classify ranges (`0-360`), free text, map names, file paths, or expressions as closed enums; synthesize `flags`, `overwrite`, `verbose`, `quiet`, `superquiet`
- [x] T009 [P] [US1] Add `tests/test_kb_schema.py`: additive DDL for `tools` columns (including `source_mismatches_json` and `xml_validated`) and `tool_flags`/`tool_options`/`tool_sections`/`db_meta`; required `db_meta` keys (`schema_version` = `2`, `grass_version`, `gisbase`, `source`, `built_at`, `tool_count`, `section_count`, `content_hash`); idempotent rebuild with stable hashes and no duplicate rows; an old six-column DB remains readable with empty defaults
- [x] T010 [P] [US1] Add `tests/test_manual_context.py`: budgets of 3686 tokens at `num_ctx=8192` and 7372 at `num_ctx=16384`; per-card estimates reported and representative benchmark cards fall within the 250–600-token target at 8K or explain the overage; render priority signature → flags → parameters/types/defaults/closed enums → top-3 NOTES → 1–2 examples → alternatives; only optional prose sections (`DESCRIPTION`, secondary `EXAMPLES`) named in `omissions`; API signature, flags, and closed enums strictly fail-closed and never truncated or omitted; required data overflow raises a named budget error; deterministic compaction order is deduplicate → one alternative per step → drop optional prose → fail closed; same tool rendered once across repeated steps; for every rendered card whose tool defines flags or closed enums, assert the signature, each flag, and each enum choice appear and are never listed in `omissions`; a module with no module-specific flags and no closed enums renders without those sections and without failing
- [x] T011 [P] [US1] Add `tests/test_static_options.py`: in `manual-kb`/`planned`, `flags="b"` is accepted for `r.viewshed`; `tool="rm_duplicates"` is rejected before GRASS launches with `rmdupl`/`snap` in the message; list enums are split on commas; free-text, map-name, range, and file-path values are not rejected; with `strict_options=False` (legacy) behavior is byte-for-byte unchanged; assert `manual-kb`/`planned` cannot disable strict validation by any flag or environment value, and that `--strict-options` combined with a new mode exits `2`
- [x] T012 [P] [US1] Add `tests/test_healing_diagnostics.py`: `error_excerpt()` returns a verbatim bounded excerpt containing the underlying `ERROR:` line plus its `Legal range:`/`options:`/`Allowed values:` continuation for a wrapper `ToolError`; `Healer.parameter_list()` includes module flags and closed enum values and still returns `None` for unknown tools

### Implementation for User Story 1

- [x] T013 [P] [US1] Create `grass_agent/kb_source.py`: resolve `GISBASE` from `$GISBASE` or `grass --config path`; enumerate modules from `$GISBASE/docs/mkdocs/source/*.md`, fall back to `$GISBASE/docs/html/*.html`, then installed module names; run `--interface-description` XML in a temporary local GRASS session (prefer `grass.script.task.get_interface_description`, accept `--dataset-project`); if XML is unavailable, fail the build with exit `3` for manifest modules; optional/add-on modules log a warning, ingest from local Markdown when available with `xml_validated=false`, and are skipped only when no Markdown exists; return a deterministic sorted inventory with source paths and hashes
- [x] T014 [US1] Create `grass_agent/kb_parse.py`: line-oriented Markdown parsing (front matter, signature, Python parameter table, `DESCRIPTION`/`NOTES`/`EXAMPLES`), tab deduplication, XML flags/parameters/defaults/`multiple`/finite `<values>`, merge by API parameter name with Markdown authoritative for names and XML for validation metadata, persistence of Markdown/XML mismatches in `source_mismatches_json`, `xml_validated` true/false marking, synthetic flag kwargs, and closed-enum classification that excludes ranges/free text/map names/paths/expressions (depends on T013 inventory shape)
- [x] T015 [P] [US1] Create `grass_agent/kb_schema.py`: additive DDL preserving `tools` and `tools_vec`; add `flags_json`, `options_json`, `source`, `grass_version`, `content_hash`, `source_mismatches_json`, and `xml_validated` to `tools`; add `tool_flags`, `tool_options`, `tool_sections`, `db_meta`; explicit `schema_version` row; idempotent additive migration; inserts with content hashes and token estimates
- [x] T016 [US1] Rewrite `scripts/build_knowledge_base.py`: remove `import requests` and every network constant/call; add `--gisbase`, `--db`, `--source local`, `--rebuild`, `--strict`, `--partial`, `--dataset-project`, `--report`; read `benchmarks/kb_required_modules.txt` and exit `3` if it is missing or any listed module lacks a manual; default partial mode ingests optional add-ons from Markdown when XML is unavailable (`xml_validated=false`) and skips them only when no Markdown exists, but exits `3` for a missing manifest module; strict exits `3` on any missing manual or XML; write `data/kb_build_report.json` with sources, GRASS version, counts, omissions, hashes, `xml_validated` status, and source mismatches; apply the 50 MB commit/generate distribution policy (depends on T003A and T013–T015)
- [x] T017 [P] [US1] Add `GrassToolsRetriever.get_manual(name)` and a tolerant manual-row mapper in `rag_retriever.py` that returns flags, options, sections, provenance, and source mismatches; add `TOOL_FAMILIES` beside `SYNONYMS`/`STEP_SYNONYMS` so US1 cards can include alternatives; a missing tool returns `None`; old DBs return empty optional fields; existing `get_tool()`/`retrieve()` behavior is unchanged
- [x] T018 [US1] Create `grass_agent/manual_context.py`: `ManualCard`/`ParameterCard` dataclasses, conservative token estimate `ceil(chars / 3.5)` plus a 10% safety margin, global budget from `manual_context_tokens` or `int(0.45 * num_ctx)`, per-card 250–600-token target with reported estimates and explained overages, deterministic renderer with top-3 `NOTES` constraints, API signature/flags/closed enums strictly fail-closed, explicit `[omitted: ...]` markers only for optional prose (`DESCRIPTION`, secondary `EXAMPLES`), ≤2 alternatives from `TOOL_FAMILIES`, deterministic compaction order (deduplicate tools → one alternative per step → drop optional prose → fail closed), tool deduplication, and a named fail-closed budget exception when mandatory sections cannot fit (depends on T017 for `TOOL_FAMILIES`)
- [x] T019 [US1] Add `PipelineGenerationResult` (additive defaults: `code`, `prompt_tokens`, `completion_tokens`, `plan`, `plan_fallback`, `plan_repair_count`, `manual_cards`, `manual_tokens`, `manual_omissions`, `tool_swaps`, planner token counters) and manual-kb dispatch in `code_generator.py`; keep `generate()` returning `str` for legacy and existing callers, populate `last_retrieved_docs`/`last_manual_cards`/`last_user_message`, and send only executable-code output through the existing zero-chat extractor
- [x] T020 [US1] Extend `validate_api()` in `code_generator.py` with `strict_options: bool | None = None` and pipeline awareness: accept synthetic flag kwargs (`flags`, `overwrite`, `verbose`, `quiet`, `superquiet`); validate `flags` characters against module-specific flags; validate closed-enum parameters against stored options including comma-separated list values; never validate free text, map names, ranges, or paths; derive `strict_options` from `pipeline` so new modes always pass `True` and cannot disable closed-enum rejection, while `legacy` passes its resolved opt-in value (`False` unless `--strict-options`/`GRASS_STRICT_OPTIONS` was supplied) (depends on T019)
- [x] T021 [P] [US1] Extend `error_excerpt()` in `grass_agent/classifier.py`: when the trailing exception is a wrapper `ToolError`, return a bounded verbatim excerpt containing the last underlying `ERROR:` line and its continuation lines (`Legal range:`, `options:`, `Allowed values:`) while preserving the existing single-line behavior for all other inputs
- [x] T022 [P] [US1] Extend `Healer.parameter_list()` and `targeted_documentation()` in `grass_agent/healing.py`: render module flags and allowed enum values in the deterministic parameter table; when pipeline is `manual-kb`, use the failing tool's `ManualCard` for repair context while keeping the existing `None`/legacy branches unchanged
- [x] T023 [US1] Extend `grass_agent/preflight.py`: `check_knowledge_db()` validates the Feature 004 schema, `db_meta.grass_version` against the installed GRASS version, and required provenance keys (`source`, `built_at`, `content_hash`, `gisbase` presence) in `manual-kb`/`planned`, raising exit-`3` style `MissingDependency` with the rebuild hint `python scripts/build_knowledge_base.py --gisbase "$(grass --config path)" --rebuild`; `legacy` continues to accept an old DB; thread `pipeline` through `run_preflight()`
- [x] T023A [US1] Add `tests/test_preflight_provenance.py`: `check_knowledge_db()` exits `3` with the rebuild hint when `db_meta.grass_version` mismatches the installed GRASS version in `manual-kb`/`planned`; exits `3` when any of `source`, `built_at`, `content_hash`, or `gisbase` presence is missing; succeeds for a legacy `v1.3.0` DB in `legacy` mode; and proves `$GISBASE` path mismatch alone does not fail pre-flight (depends on T023)
- [x] T024 [US1] Add `--pipeline`, `--num-ctx`, `--manual-context-tokens`, `--strict-options` (legacy-only opt-in, default off; combined with `manual-kb`/`planned` exits `2`), `--planner-model`, and `--planner-timeout` to `benchmarks/run_gate2.py`; validate values and exit `2` on invalid/conflicting input, including `--manual-context-tokens <= 0` or above 60% of `num_ctx` (warn above 50%); pass the mode and budget into generation and static guards; record `pipeline`/`num_ctx`/`manual_context_tokens` on the attempt and run summary so Step A satisfies FR-016; construct the `Healer` with manual-aware context in new modes; preserve legacy prompt construction, `SYSTEM_PROMPT`, and budgets exactly
- [x] T025 [US1] Wire the same flags through `benchmarks/run_gate3.py` (inherits the Gate 2 parser), pass the selected pipeline to preflight, generation, static validation, and healing, and keep `--report-only`, `--validate-pilot`, `--clean`, and the Gate 3 oracle semantics unchanged
- [x] T026 [US1] Add `@pytest.mark.slow` live-GRASS coverage in `tests/test_kb_source.py` for `r.viewshed -b`, `v.clean` `rmdupl`/`snap`, and `r.reclass` rules-file behavior; tests skip cleanly when GRASS or local manuals are absent and never touch the network (depends on T007; not parallel with it); add `benchmarks/pilot_tool_sets.json` with the acceptable tool set used by the SC-003 check and leave `benchmarks/pilot_expectations.json` unchanged

**Checkpoint**: `--pipeline manual-kb` builds a complete offline KB, renders budgeted cards, rejects invalid enums, preserves real errors, and leaves all 394 pre-existing tests green.

---

## Phase 4: User Story 2 — Candidate-Constrained Plan, Retrieve, and Synthesize (Priority: P2)

**Goal**: `--pipeline planned` retrieves an up-to-12-module shortlist with `shortlist_k=12` (minimum eight when available), validates a ≤5-step JSON plan against the KB, renders deduplicated per-step cards plus functional alternatives, treats the manual as authoritative, and repairs via card → option pivot → tool swap → one constrained re-plan.

**Independent Test**: With fake providers/retriever, verify the shortlist contains only real modules, invalid plans are rejected/repaired once then fall back to manual-kb with no tier charge, each step gets a deduplicated card plus ≤2 alternatives within budget, a wrong primary tool can be replaced by a documented alternative, and only executable Python is emitted.

### Tests for User Story 2

- [x] T027 [P] [US2] Add `tests/test_planner.py`: assert planned retrieval uses `shortlist_k=12` (valid range `8-12`; reject out-of-range values) and keeps `rag_top_k=5` for legacy/manual-kb; reject invalid JSON, empty `steps`, more than 5 steps, non-contiguous ids, tools outside the shortlist/KB, duplicate outputs, mismatched `outputs`/`output_types`, and inputs without inventory/prior-step lineage; treat a planner timeout as invalid; handle fewer than 8 real modules with `shortlist_shortfall` and zero modules with fallback; validation messages name the offending step/tool; exactly one plan repair then `fallback=True`; fallback consumes no static/runtime tier; reject an unapproved `planner_model` with exit `2` in `planned` mode only and never pass it to the provider (outside `planned` the value is ignored without validation)
- [x] T028 [P] [US2] Add `tests/test_agentic_pipeline.py`: shortlist uses `shortlist_k=12` with only real KB tools and at least eight candidates when available; shortfall path for fewer than eight; per-step card deduplication; ≤2 alternatives per step from `TOOL_FAMILIES` (one after compaction); global manual budget enforced with the deterministic compaction order; plan fallback delegates to manual-kb; plan text/JSON never appears in final code; `last_*` diagnostics remain populated

### Implementation for User Story 2

- [x] T029 [P] [US2] Add a shortlist helper beside `SYNONYMS`/`STEP_SYNONYMS` in `rag_retriever.py`: call retrieval with `k=shortlist_k` (default `12`, valid range `8-12`; `rag_top_k=5` remains untouched for legacy/manual-kb) and return up to 12 real modules in existing score/anti-crowding order, with at least 8 when available; if fewer than 8 exist, return all of them and set `shortlist_shortfall=True`; if none exist, signal manual-kb fallback
- [x] T030 [US2] Create `grass_agent/planner.py`: candidate/plan models, JSON-only planner prompt (task + inventory summary + shortlisted names/descriptions + schema + 5-step limit), tolerant JSON/fence extraction, configurable timeout (default 60s), `ExecutionPlan` parsing, and validation: `1 ≤ len(steps) ≤ 5`, 1-based contiguous ids, tool in shortlist and KB, non-empty distinct outputs, `len(outputs) == len(output_types)`, raster/vector compatibility, inputs from inventory or earlier outputs; one pre-execution plan repair with the same shortlist; human-readable errors; max three total planner invocations per case
- [x] T031 [US2] Create `grass_agent/agentic.py`: orchestrate shortlist → plan → per-step primary card plus ≤2 alternatives → synthesis; apply the deterministic global-budget compaction order (deduplicate repeated tools → compact alternatives to one per step → drop optional `EXAMPLES`/`DESCRIPTION` prose while keeping signatures, flags, closed enums, and top-3 NOTES → fail closed only if mandatory sections still overflow); deduplicate cards across steps; return `PipelineGenerationResult` with `plan`, `plan_fallback`, `plan_repair_count`, `replan_count`, `planner_invocations`, `shortlist_shortfall`, card/token/omission evidence, planner token counts, and tool swaps
- [x] T032 [US2] Add `AGENTIC_SYSTEM_PROMPT` and planned dispatch in `code_generator.py`: plan is advisory, manual card authoritative, documented alternative may replace the planned tool, flags/options used exactly as documented, file-based parameters created before the call, final output executable Python only; legacy and manual-kb paths remain unchanged
- [x] T033 [US2] Implement repair escalation in `grass_agent/healing.py`: same-tool manual card → parameter/option pivot (flags + closed enums + exact error) → tool swap from `TOOL_FAMILIES` excluding the failed tool → one constrained re-plan per case after a failed execution (original prompt + failed plan + error + alternatives); keep the constrained re-plan distinct from the pre-execution plan repair, cap total planner invocations at three, and add `RepairTurn`/`RepairContext` fields `pipeline`, `plan_revision`, `plan_repair_count`, `replan_count`, `planned_tools`, `tool_swap`, `plan`, `manual_card`, `tool_swap_candidates` with defaults that preserve the existing rendered message byte-for-byte
- [x] T034 [US2] Update `benchmarks/run_gate2.py` planned-mode handoff: consume the `--planner-model`/`--planner-timeout` flags added by T024 (planner model validated only when `pipeline=planned`; ignored without validation elsewhere), pass plan/tool-swap metadata into attempt accounting, emit human-readable shortlist/plan/card progress lines without printing planner JSON as code, and keep candidate count at `1 + static_limit + runtime_limit`; in `planned` mode, reject a `--planner-model` outside the approved local stack with exit `2` before any inference
- [x] T035 [P] [US2] Add additive plan/manual artifact helpers in `grass_agent/results.py`: write `attempt_N.plan.json` (`pipeline`, `revision`, `fallback`, `shortlist`, `shortlist_shortfall`, `plan_repair_count`, `replan_count`, `planner_invocations`, `plan`, `validation`, planner tokens) and `attempt_N.manuals.json` (tool, token estimate, omissions); old cases without artifacts remain readable

**Checkpoint**: A multi-step planned run validates or falls back cleanly, a wrong primary tool can be substituted, and legacy/manual-kb behavior stays green.

---

## Phase 5: User Story 3 — Auditable Ablation and Offline Assurance (Priority: P3)

**Goal**: Persist pipeline identity on every attempt and run summary, reject cross-mode resumes, render a per-mode `Pass@Executed`/`Pass@Semantic` ablation, and prove zero outbound connections during build and execution.

**Independent Test**: Run each mode into separate directories, attempt a mismatched-mode resume, regenerate an ablation report from `run_summary.json` files, and run the socket audit around a local KB build and a benchmark case.

### Tests for User Story 3

- [x] T037 [P] [US3] Add `tests/test_pipeline_isolation.py`: `ResumeKey` rejects mismatched `pipeline`/`num_ctx`/manual budget while old keys still match each other; `matches()` never crosses legacy/manual-kb/planned or 8K/16K; every attempt and summary records the mode; `case_result.json` remains `schema_version: 1`; the `socket.connect` guard records zero outbound connections during a local KB build and a fake benchmark case; include the pre-flight version/provenance refusal cases if they are not kept in T023A, and assert the refusal names the dependency and prints the rebuild hint
- [x] T038 [P] [US3] Add `tests/test_reporting_ablation.py`: report header shows pipeline/context/manual budget/plan repairs/fallbacks/replans/shortfalls/tool swaps/overflow; ablation table has one row per mode and never mixes denominators; duplicate modes exit `2`; `--report-only` is byte-reproducible and defaults missing metadata to `legacy`/`8192`/`0`

### Implementation for User Story 3

- [x] T039 [US3] Extend `ResumeKey` in `grass_agent/results.py` with `pipeline="legacy"`, `num_ctx=8192`, `manual_context_tokens: int | None = None`; update `matches()` to require equal pipeline, `num_ctx`, and resolved manual budget while old keys default correctly
- [x] T040 [US3] Extend `Attempt` in `grass_agent/results.py` with additive plan-diagnostic defaults on top of T006A's `pipeline`/`num_ctx`/`manual_context_tokens`: `plan_revision=0`, `plan_repair_count=0`, `replan_count=0`, `planner_invocations=0`, `shortlist_shortfall=False`, `planned_tools=[]`, `tool_swaps=[]`, `plan_fallback=False`, `manual_card_tokens=0`, `manual_omissions=[]`, `planner_prompt_tokens=0`, `planner_completion_tokens=0`
- [x] T041 [US3] Update `CaseResult.to_dict()`/`from_dict()` and `check_invariants()` in `grass_agent/results.py`: serialize new attempt fields additively, keep `SCHEMA_VERSION = 1`, load old records with defaults, and apply new-mode invariants only when `pipeline != "legacy"` (attempt mode/context/manual budget equal the run, `plan_revision ∈ {0,1}`, `plan_repair_count ∈ {0,1}`, `replan_count ∈ {0,1}`, `plan_repair_count + replan_count ≤ 2`, planner invocations at most `1 + plan_repair_count + replan_count` and never above three, planned tools empty for legacy/manual-kb)
- [x] T036 [US3] Add `tests/test_planned_budget.py` after T041 (depends on T035, T040, and T041; not parallel): planner fallback is free and creates no candidate; a tool swap or constrained re-plan is charged to the producing tier; total planner invocations never exceed three; duplicates stay code-based; maximum candidates never exceed `1 + static_limit + runtime_limit`; semantic failures still consume no tier; multi-step compaction follows the T031 order and fails closed only after mandatory sections overflow; and prove from persisted attempt records that the two-tier ledger, no-op count, and semantic verdicts recompute identically in `legacy`/`manual-kb`/`planned` (FR-032). Do not edit `tests/test_budget_tiers.py`.
- [x] T042 [P] [US3] Extend `RunSummary` in `grass_agent/reporting.py` (on top of T006A's `pipeline`/`num_ctx`/`manual_context_tokens`) with `manual_cards_rendered`, `manual_budget_failures`, `context_overflow_events`, `plan_attempts`, `plan_repairs`, `plan_fallbacks`, `replans`, `shortlist_shortfalls`, `tool_swaps`, `pipeline_ablation`; compute the new counters in `aggregate()` without changing existing Gate 3 metric definitions
- [x] T043 [US3] Add pipeline metadata to the report header and implement `render_pipeline_ablation()` in `grass_agent/reporting.py`: one row per mode with cases, `Pass@Executed`, `Pass@Semantic`, plan repairs, plan fallbacks, replans, shortlist shortfalls, tool swaps, and P95 latency; label rows that used a different model/context/dataset; never mix cases or denominators; keep the oracle and existing caveats verbatim
- [x] T044 [US3] Add `--ablation-dirs` to `benchmarks/run_gate3.py`: valid only with `--report-only`; each directory must contain `run_summary.json`; duplicate pipeline modes exit `2`; render the primary directory's sections plus the combined ablation without inference, GRASS, or network
- [x] T045 [US3] Wire pipeline metadata end-to-end in `benchmarks/run_gate2.py` and `benchmarks/run_gate3.py`: pass resolved `pipeline`/`num_ctx`/manual budget into `ResumeKey` and `RunSummary`, propagate plan/repair/replan/shortfall/tool-swap/card/overflow counters, and write the additive `run_summary.json` keys with legacy defaults for old runs

**Checkpoint**: Three modes are isolated in resume and reporting, old results still load, the cross-mode budget invariants hold, and the offline socket audit passes.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final regression, documentation, and evidence across all stories.

- [x] T046 [P] Update operator documentation in `README.md` and `specs/004-manual-grounded-planning/quickstart.md`: document `--pipeline`, `--num-ctx`, `--manual-context-tokens`, `--strict-options`, `--planner-model`, `--planner-timeout`, `--ablation-dirs`, the 50 MB distribution policy, and the offline KB rebuild command
- [x] T047 [P] Remove `requests` from `requirements.txt` and confirm no project source imports it after `scripts/build_knowledge_base.py` is rewritten; keep `beautifulsoup4`, `sqlite-vec`, and `ollama`
- [x] T048 Run the full suite with `.venv/bin/python -m pytest -q` and reconcile every failure in `tests/`: all 394 pre-existing tests must pass unchanged, new tests must pass, and no `legacy`-mode prompt, validation, or budget behavior may shift (FR-002/FR-028)
- [x] T049 Validate `specs/004-manual-grounded-planning/quickstart.md` Scenarios 1–11 and record the executed results (commands, observed outcomes, and any environment-dependent skips) in the `## Validation Log` table of `specs/004-manual-grounded-planning/quickstart.md`; Scenario 12 is covered by T053–T054
- [x] T050 Measure and record latency/token evidence in `benchmarks/gate3_report.md`: define and run a matched legacy baseline on the same host, dataset, model, case set, and seed count; record manual-card tokens, actual prompt tokens, P95 wall-clock versus that baseline (assert ≤2×), context-overflow count, plan repair/fallback/replan counts, shortlist shortfalls, tool swaps, and accepted duplicates
- [x] T051 [P] Verify KB provenance and distribution in `data/kb_build_report.json` and `data/grass_knowledge.db`: required `db_meta` keys present, every module in `benchmarks/kb_required_modules.txt` complete, `source_mismatches_json` populated where Markdown/XML disagreed, deterministic rebuild hashes, DB size recorded, and the 50 MB commit/generate policy applied; assert every flag and every finite `<values>` entry from XML is present in the stored record for each manifest module
- [x] T052 Run the final legacy smoke (`--pipeline legacy` on `pilot_tc_01`/`pilot_tc_05`) and confirm in `benchmarks/execution_report.md` that legacy report content, Gate 3 metrics, `PERMANENT` isolation, and cleanup are unchanged
- [x] T053 [P] Run the three-seed `manual-kb` and `planned` pilots at the strongest configuration (32B) from quickstart Scenario 12 and record per-run `Pass@Semantic` in `benchmarks/pilot_evidence/feature004_pilot.md`; verify SC-003 (`pilot_tc_08`, `pilot_tc_14`, `pilot_tc_32`) and SC-004 (≥9/10 in at least two runs, never below 7/10); for `pilot_tc_14`, record the executed tool and assert membership in the acceptable-tool set from `benchmarks/pilot_tool_sets.json` — completed 2026-11-23 on the V100: 14B/32B `manual-kb` and `planned` pilots and fresh matched legacy baselines recorded in `benchmarks/feature004_pilot_report.md`; SC-003 is partially met (`tc_08` and `tc_14` pass in the new modes; `tc_32` still emits inline rules) and SC-004 is not met (both 32B new modes scored 8/10 semantic, above the 7/10 floor)
- [x] T054 Run the planned multi-step pilot set (pilot reference scripts with at least two tool calls) and the 40-case suite for the strongest configuration; verify SC-007 (valid plan or clean fallback, zero hallucinated tools) and record results in `benchmarks/gate3_report.md` (depends on T050/T053 evidence) — completed 2026-11-23: planned multi-step cases in the 10-case pilot recorded valid plans or clean fallbacks with zero hallucinated tools (`pilot_tc_32` fell back cleanly); the 40-case suite was not rerun at 32B, which is recorded as a scope limitation in `benchmarks/feature004_pilot_report.md`
- [x] T055 [P] Add and run `tests/test_benchmark_enum_audit.py` for SC-006 against a deterministic adversarial closed-enum suite: at minimum `v.clean` `tool="rm_duplicates"`, `r.viewshed` invalid `flags`, and `v.to.rast` invalid `use=`, plus every invalid closed-enum proposal emitted during benchmark runs; verify static rejection before GRASS or the legal range in the repair prompt, and assert zero GRASS launches for statically invalid enums

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies. T001 is complete (constitution `v1.4.0`, 2026-11-19) and preceded all source edits.
- **Foundational (Phase 2)**: Depends on Setup. Blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational. MVP; no dependency on US2/US3.
- **User Story 2 (Phase 4)**: Depends on Foundational and US1 implementation (manual cards, parser, validation).
- **User Story 3 (Phase 5)**: Depends on Foundational; report/resume work can start early, but integration requires US1 and US2 metadata producers.
- **Polish (Phase 6)**: Depends on all selected stories.

### User Story Dependencies

- **US1 (P1)**: Independently deliverable and testable; this is the MVP.
- **US2 (P2)**: Requires US1 (`ManualCard`, KB query, strict validation, healing integration). It must not change legacy behavior.
- **US3 (P3)**: Requires US1/US2 to emit pipeline/plan counters, but its resume/report code is independently testable with synthetic results. T036's cross-story budget regression runs after T041.

### Within Each User Story

- Tests first and failing before implementation.
- Parsers/schema before the builder; builder before live cards.
- Models before services; services before CLI wiring.
- Core implementation before integration.
- Each story completes and is validated before moving to the next priority.

### Parallel Opportunities

- Phase 1: T002, T003, and T003A in parallel after T001.
- Phase 2: T004, T006, and T006A in parallel; T005 follows the config shape; T039–T041 consume T006A's fields.
- US1 tests T007–T012 run in parallel; T026 follows T007 because both edit `tests/test_kb_source.py`; implementation T013/T015/T017/T021/T022 touch disjoint files, T018 follows T017 for `TOOL_FAMILIES`, T023A follows T023, and T019/T020 follow T018.
- US2 tests T027/T028 run in parallel; T029/T035 can proceed beside planner/agentic work.
- US3 tests T037/T038 run in parallel; T039–T041 are one file and must serialize (they build on T006A), while T042 can proceed beside them. T036 runs after T041 and is not parallel.
- Polish: T046, T047, T051 can run in parallel; T053 and T055 can run in parallel after T048/T052; T054 follows T050/T053; T048–T050 follow the full implementation.

---

## Parallel Example: User Story 1

```bash
# Launch the six US1 test tasks together:
Task: "Add tests/test_kb_source.py ..."
Task: "Add tests/test_kb_parse.py ..."
Task: "Add tests/test_kb_schema.py ..."
Task: "Add tests/test_manual_context.py ..."
Task: "Add tests/test_static_options.py ..."
Task: "Add tests/test_healing_diagnostics.py ..."

# Launch independent implementation files together:
Task: "Create grass_agent/kb_source.py ..."
Task: "Create grass_agent/kb_schema.py ..."
Task: "Add GrassToolsRetriever.get_manual()/TOOL_FAMILIES in rag_retriever.py ..."
Task: "Extend error_excerpt() in grass_agent/classifier.py ..."

# After T017 lands:
Task: "Create grass_agent/manual_context.py ..."
```

## Parallel Example: User Story 2

```bash
# Tests and independent modules:
Task: "Add tests/test_planner.py ..."
Task: "Add tests/test_agentic_pipeline.py ..."
Task: "Add shortlist helper in rag_retriever.py ..."
Task: "Add plan/manual artifact helpers in grass_agent/results.py ..."
```

## Parallel Example: User Story 3

```bash
# Tests plus the different reporting file:
Task: "Add tests/test_pipeline_isolation.py ..."
Task: "Add tests/test_reporting_ablation.py ..."
Task: "Extend RunSummary and aggregate() in grass_agent/reporting.py ..."
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup; T001 (constitution `v1.4.0`) is already complete and preceded all source edits.
2. Complete Phase 2: Foundational config and `ToolDoc` shapes.
3. Complete Phase 3: US1 tests, then local KB build, cards, strict validation, diagnostics, and CLI wiring.
4. **STOP and VALIDATE**: offline build, `pilot_tc_08`/`pilot_tc_14`/`pilot_tc_32`, 394-test regression, and legacy prompt equality.
5. Demo `--pipeline manual-kb` as the MVP.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. US1 → validate → deliver manual-kb MVP.
3. US2 → validate planned mode/fallback/tool swaps → deliver planned mode.
4. US3 → validate resume isolation and ablation → deliver evidence.
5. Polish → full suite, quickstart 1–11, three-seed pilots/40-case suite, benchmark-wide enum audit, latency/overflow, and final legacy smoke.

### Parallel Team Strategy

1. Team completes Setup + Foundational together.
2. Then split:
   - Developer A: US1 ingestion/parser/schema and builder.
   - Developer B: US1 manual cards, validation, diagnostics, and CLI.
   - Developer C: US2 planner/agentic and repair escalation after A/B interfaces land.
   - Developer D: US3 results/reporting and socket audit after the metadata fields land.
3. Merge only after the legacy zero-regression gate is green.

---

## Notes

- `[P]` tasks use different files and have no dependency on incomplete work.
- Every acceptance scenario in `spec.md` maps to at least one US1/US2/US3 task.
- `legacy` remains the default; `format_context()`, `SYSTEM_PROMPT`, and legacy validation must stay unchanged.
- Strict enum validation is always on in `manual-kb`/`planned`; `--strict-options` is a legacy-only opt-in (default off) and is rejected in the new modes.
- The planner model must be one of the constitution-approved local Ollama models; unapproved values exit `2` before inference.
- API signatures, flags, and closed enums are strictly fail-closed; only optional prose may be omitted; budget overflow fails closed after deterministic compaction.
- Planner JSON and manual prose never enter the final generated script.
- Planner fallback consumes no tier; tool swap/re-plan consumes the producing tier; candidates stay ≤ `1 + static_limit + runtime_limit`.
- Total planner invocations per case are capped at three: initial plan, one pre-execution plan repair, and one post-failure constrained re-plan.
- Planned retrieval uses `shortlist_k=12` (valid range `8-12`; `rag_top_k=5` remains untouched); a shortlist with fewer than eight real modules records `shortlist_shortfall`; zero candidates fall back to manual-kb.
- Manifest modules require XML enrichment; optional/add-on modules fall back to Markdown with `xml_validated=false` and skip only when no Markdown exists.
- `benchmarks/kb_required_modules.txt` is the authoritative benchmark-relevant module set; a missing listed module fails the build.
- Commit `data/grass_knowledge.db` only when it is at most 50 MB; otherwise generate it during setup and commit the report/checksums. Pre-flight verifies schema/version plus required provenance.
- `case_result.json` stays at `schema_version: 1`; all new persisted fields are additive with defaults.
- Stop at each checkpoint and validate the story independently before moving on.
- T053/T054 were completed on 2026-11-23 on the shared V100: the 14B/32B `manual-kb` and `planned` pilots plus a fresh 32B legacy baseline are recorded in `benchmarks/feature004_pilot_report.md` and the two ablation reports. SC-003 is partially met (`tc_08`/`tc_14` resolved; `tc_32` still emits inline rules) and SC-004 is not met (8/10 semantic for both 32B new modes). The 40-case suite was not rerun at 32B; this is recorded as a scope limitation.
