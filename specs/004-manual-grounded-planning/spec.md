# Feature Specification: Manual-Grounded Knowledge Base and Candidate-Constrained Planning

**Feature Branch**: `004-manual-grounded-planning`

**Created**: 2026-11-19

**Status**: Draft

**Input**: User description: "Feature 004 delivers Step A and Step B as sequential milestones. Step A (MVP) builds a strictly offline local GRASS 8.5 manual knowledge base, renders budgeted manual cards, and fixes static-validation and repair-diagnostic gaps. Step B adds a candidate-constrained Plan -> Retrieve -> Synthesize workflow. Step C, an autonomous ReAct tool-calling loop, is out of scope and reserved for Feature 005. A MINOR constitution amendment is a governance prerequisite."

## Clarifications

### Session 2026-11-19

- Q: Should strict rejection of invalid closed-enum values apply only in the new `manual-kb` and `planned` modes, or also in the existing `legacy` mode? → A: New modes only; `legacy` retains its current validation behavior so the 394-test baseline remains unchanged.
- Q: Which model-context default should govern the manual-card budget when `num_ctx` is not explicitly provided? → A: Default to 8,192 tokens with a 45% documentation budget; allow an explicit opt-in to 16,384 tokens.
- Q: How should planner timeout interact with plan repair and the repair budget? → A: Treat a timeout as an invalid plan, allow one pre-execution plan repair, then fall back to manual-kb without charging a tier. A post-failure constrained re-plan is distinct; total planner invocations never exceed three.
- Q: What happens when hybrid retrieval returns fewer than eight real modules? → A: Use all available modules, record `shortlist_shortfall`, and fall back only when none are found.
- Q: Which provenance fields must pre-flight verify? → A: Schema version, GRASS version, and presence of `source`, `built_at`, `content_hash`, and `$GISBASE`; the `$GISBASE` path need not match the current host.
- Q: How is the rebuilt knowledge base distributed? → A: Commit it when it is at most 50 MB; otherwise generate it during setup and commit the build report and checksums.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Local Manual-Grounded Generation and Repair (Priority: P1)

A GIS analyst runs the agent with `--pipeline manual-kb`. The agent grounds generation in the locally installed GRASS 8.5 manuals, so it sees module flags, closed enum choices, parameter types and defaults, key `NOTES` constraints, and worked examples. When a script fails, the repair prompt shows the real GRASS error and the legal values rather than only a wrapper summary. The analyst gets correct calls for binary viewshed output, vector cleaning tools, and file-based reclass rules without any network access.

**Why this priority**: This is the MVP. It directly addresses all three documented pilot failures with the smallest architectural risk, requires no planner, and keeps the existing generation and healing contracts intact.

**Independent Test**: On an offline host with a local GRASS 8.5 installation, build the knowledge base, run the three documented failure cases and the existing regression suite, and verify that flags, closed enums, and file-based constraints are present; repair prompts contain the underlying error and legal range; manual cards stay within budget; and all existing tests pass unchanged.

**Acceptance Scenarios**:

1. **Given** a clean offline host with local GRASS 8.5 documentation, **When** the knowledge base is built, **Then** zero outbound network calls occur and every module in `benchmarks/kb_required_modules.txt` has a manual record with provenance.
2. **Given** a binary viewshed task, **When** the agent generates an `r.viewshed` call, **Then** the module flag for binary output (`-b`) is present in the manual card and `flags="b"` is accepted by static validation.
3. **Given** a duplicate-removal and snapping task, **When** the model proposes `tool="rm_duplicates"`, **Then** static validation rejects the value before GRASS launches and lists the valid closed-enum choices, including `rmdupl` and `snap`.
4. **Given** a floating-point slope raster that must be reclassified, **When** the agent considers `r.reclass`, **Then** the manual card exposes that `rules` is a file or stream, that `r.reclass` expects integer input, and that `r.recode` or `r.mapcalc` is a documented alternative.
5. **Given** a runtime failure wrapped in a `ToolError`, **When** the repair prompt is built, **Then** it preserves the underlying `ERROR:` line and any `Legal range:` or `options:` line.
6. **Given** an 8,192-token or 16,384-token model context, **When** manual cards are rendered, **Then** they stay within the configured documentation budget and never silently drop module flags or closed enum choices.
7. **Given** legacy mode, **When** the agent runs, **Then** existing prompt construction, generation behavior, and all 394 existing tests remain unchanged.
8. **Given** a knowledge base built from a different GRASS version, **When** manual-kb or planned mode starts, **Then** pre-flight refuses the run with a named dependency and a rebuild hint; legacy mode may still read the old knowledge base.

---

### User Story 2 - Candidate-Constrained Plan, Retrieve, and Synthesize (Priority: P2)

A maintainer runs the agent with `--pipeline planned`. The agent first retrieves a shortlist of real candidate modules, then decomposes the request into an ordered plan of at most five atomic steps using only those candidates. For each step it retrieves a manual card plus one or two functional alternatives. The synthesizer treats the plan as advisory and the manual as authoritative, so it can substitute a better-documented tool when the plan's first choice cannot satisfy the request. If a repair is needed, the agent can pivot parameters, swap tools, or perform one constrained re-plan without exceeding the existing repair budget.

**Why this priority**: This builds on Step A and improves multi-step ordering and tool selection. It carries more risk than Step A, so it must remain opt-in and be validated against the manual-kb baseline.

**Independent Test**: Run a multi-step prompt through planned mode; confirm the shortlist contains only real modules, the plan validates against the knowledge base, each step receives a deduplicated manual card and alternatives within budget, an invalid plan falls back to manual-kb after one repair, and a wrong primary tool can be replaced by a documented alternative.

**Acceptance Scenarios**:

1. **Given** any planned-mode request, **When** planning begins, **Then** the planner receives an up-to-12-module shortlist from `shortlist_k=12` retrieval, with at least eight real modules when available (all available with a recorded shortfall otherwise), and may select only from that shortlist.
2. **Given** a planner response, **When** the plan is validated, **Then** it contains at most five steps, each with a real tool, declared inputs and outputs, raster/vector type compatibility, and lineage from the dataset inventory or a prior step.
3. **Given** an invalid plan, **When** the first plan repair also fails, **Then** the run falls back to manual-kb single-shot retrieval without consuming a static or runtime repair tier.
4. **Given** a valid plan, **When** per-step manuals are retrieved, **Then** each step receives a deduplicated manual card plus one or two functional alternatives within the documentation budget.
5. **Given** a plan that selects `r.reclass` for floating-point input, **When** the synthesizer reads the manual card, **Then** it may substitute `r.recode` or `r.mapcalc` because the manual is authoritative over the plan.
6. **Given** a repeated failure, **When** repair escalates, **Then** the order is same-tool manual card, parameter/option pivot, tool swap, and one constrained re-plan; the producing tier is charged and the maximum candidate count remains `1 + static_limit + runtime_limit`.
7. **Given** invalid planner JSON or a planner timeout, **When** the fallback occurs, **Then** no repair tier is consumed and no extra candidate is created.
8. **Given** any planned-mode output, **Then** only executable Python using `grass.tools` is emitted; planner prose, JSON, and explanations never appear in the final script.
9. **Given** a semantic failure, **Then** it remains report-only and generates no repair, exactly as in Gate 3.

---

### User Story 3 - Auditable Ablation and Offline Assurance (Priority: P3)

A maintainer compares legacy, manual-kb, and planned modes without mixing results. Every persisted case identifies its pipeline mode, resumed runs never cross modes, and the Gate 3 report presents a clean ablation of execution and semantic outcomes. An independent audit confirms the knowledge-base build and benchmark execution make zero outbound network calls.

**Why this priority**: The improvement claim is only credible if the three modes can be compared with isolated results and a verifiable offline guarantee. This story protects the evidence, not the feature scope.

**Independent Test**: Run each pipeline mode into separate output directories, attempt a resume with a mismatched mode, regenerate the report, and run a socket audit alongside the knowledge-base build and a benchmark case.

**Acceptance Scenarios**:

1. **Given** a persisted result, **When** it is inspected, **Then** the pipeline mode is recorded on the case attempt and run summary.
2. **Given** a resume request for a different pipeline mode, **When** the harness checks reusability, **Then** it rejects the result rather than mixing modes.
3. **Given** results from multiple modes, **When** the Gate 3 report is generated, **Then** `Pass@Executed` and `Pass@Semantic` are shown per mode in a comparison table.
4. **Given** a clean offline environment, **When** the knowledge base is built and a benchmark case runs, **Then** the socket audit records zero outbound connections.
5. **Given** any pipeline mode, **When** the Gate 3 semantic oracle runs, **Then** its assertions, expectations, and report-only semantics are unchanged.

---

### Edge Cases

- Local Markdown manuals are absent but HTML manuals exist: the build falls back to HTML and synthesizes API records from interface descriptions.
- XML enrichment cannot be obtained (for example, because no local GRASS session or project can be established): the build MUST fail (exit `3`) when a manifest module lacks XML enrichment, and Markdown/HTML-only records are never accepted as manifest-module records. Optional/add-on modules log a warning, are ingested from local Markdown when available, and record `xml_validated=false`; when no Markdown exists they are reported and skipped. A module that legitimately defines zero flags or zero closed enums is not an XML failure and is handled by the no-section rule below.
- Local Markdown and XML disagree on a parameter name or enum set: the manual signature remains authoritative for the API name, the mismatch is persisted in `source_mismatches_json` and summarized in the build report, and no data is silently discarded.
- A module has no module-specific flags or no closed enum choices: the manual card omits those sections without failing.
- A parameter accepts free text, a map name, a range, or a file path: static validation must not mistake it for a closed enum.
- A module is installed but has no manual page, or an add-on referenced by the old knowledge base is absent: strict builds fail with a named module; partial builds report the omission.
- The documentation budget is too small to fit the API signature, required flags, or closed enums: optional prose sections are dropped first in the deterministic compaction order, and if mandatory sections still cannot fit, rendering fails closed rather than silently truncating them.
- The same tool appears in multiple plan steps: its manual card is rendered once and referenced by each step.
- The planner returns invalid JSON, an empty plan, more than five steps, a tool outside the shortlist, duplicate outputs, or an input with no lineage: the plan is rejected and repaired once, then falls back.
- Retrieval returns fewer than eight real modules, or zero: the shortfall and fallback rules in FR-017 apply.
- The planner times out: the timeout is treated as an invalid plan, uses the one plan repair, then falls back without consuming a static or runtime tier.
- The rebuilt knowledge base exceeds the 50 MB distribution threshold: it is generated during setup and not committed; the build report and checksums are committed instead.
- A case has both a pre-execution plan repair and a post-failure constrained re-plan: both are allowed, but total planner invocations must not exceed three.
- The planner selects a tool that cannot accept the input type, such as `r.reclass` on floating-point data: the synthesizer may substitute a documented alternative.
- A repair produces code that is byte- or AST-identical to a prior attempt: the existing no-op detector rejects it before execution.
- The static or runtime tier is exhausted during a tool swap or re-plan: the case terminates under the existing budget rules.
- A semantic assertion fails: the case remains report-only and consumes no repair budget.
- A legacy knowledge base is used in manual-kb or planned mode: pre-flight refuses it; in legacy mode it remains readable.
- The model emits planner-style prose or Markdown fences: the zero-chat extractor still yields only executable code, and planner text never leaks into the final script.

## Requirements *(mandatory)*

### Governance Prerequisite

- **FR-001**: The constitution MUST be amended from `v1.3.0` to `v1.4.0` as a MINOR change, naming `004-manual-grounded-planning` as the current milestone, permitting internal JSON planning as an intermediate workflow step, preserving the zero-chat executable-Python final-output contract, and adding `qwen2.5-coder:14b` and `qwen2.5-coder:32b` to the approved benchmark model stack while retaining `qwen2.5-coder:7b` as the baseline and `qwen2.5-coder:3b` as smoke-only.
- **FR-002**: The feature MUST preserve Principles I-V, including the offline-only mandate, the modern `grass.tools` interface, the zero-chat contract, the phased gates, and the pre-flight execution-safety guarantees. No isolation, budget, or oracle requirement may be weakened.
- **FR-003**: Step C, an autonomous ReAct tool-calling loop, and any semantic-repair tier are explicitly out of scope and reserved for Feature 005.

### Step A - Local Manual Knowledge Base

- **FR-004**: The knowledge-base build MUST be fully offline. All network dependencies MUST be removed from the build path, and an audit MUST confirm zero outbound connections during build and benchmark execution.
- **FR-005**: Module discovery MUST use the locally installed GRASS environment. Local Markdown manuals MUST be the primary source, interface-description XML MUST be the authoritative enrichment and validation source for flags and closed enum values, and local HTML manuals MUST be the fallback. XML enrichment MUST be available for every module in `benchmarks/kb_required_modules.txt`; when it cannot be obtained the build MUST fail (exit `3`) instead of emitting an unvalidated record. Optional/add-on modules that cannot obtain XML MUST log a warning, be ingested from local Markdown when available, and record `xml_validated=false`; they are skipped only when no Markdown exists.
- **FR-006**: Each module record MUST contain the full manual equivalent: the `grass.tools` signature, Python parameter types, defaults, module flags with descriptions, closed enum choices, parameter descriptions, `DESCRIPTION`, `NOTES`, and `EXAMPLES`. Duplicated command-line and Python tabs MUST be deduplicated.
- **FR-007**: Each record MUST carry provenance: local GRASS version, source kind, content hash, and build metadata. Rebuilding the knowledge base MUST be deterministic and idempotent.
- **FR-008**: The knowledge-base schema MUST be additive. Existing tool and vector records MUST remain readable by legacy mode, while normalized flag, option, manual-section, and metadata records MUST be available to the new modes.
- **FR-009**: Pre-flight MUST validate the knowledge-base schema version (`2` for Feature 004), GRASS version, and required provenance (source, build time, content hash, and `$GISBASE` presence). Manual-kb and planned modes MUST refuse a mismatched version or missing required provenance with a named dependency and a rebuild hint; legacy mode MUST continue to accept the old knowledge base.
- **FR-010**: Inference MUST render compact manual cards with a per-tool target of 250-600 tokens at the default 8,192-token context, within a configurable global documentation budget. The per-tool target is advisory: a card outside it is acceptable only when required flags, closed enum choices, or constraints explain the size, and the renderer MUST report the per-card token estimate in diagnostics. The default context is 8,192 tokens with a 45% documentation budget, and 16,384 tokens MUST be available as an explicit opt-in with the same budget policy.
- **FR-011**: Manual-card rendering MUST follow a deterministic priority order: API signature, module flags, parameters with Python types, defaults and closed enum choices presented as Python-literal choices, key `NOTES` constraints, one or two worked examples, and functional alternatives. `NOTES` constraints MUST be selected deterministically by a documented keyword rule (integer input, file or stream parameters, topology, units, extent), in manual order and capped at three, so the same record always yields the same card. The API signature, module flags, and closed enum choices are mandatory and strictly fail-closed: they MUST never be truncated or omitted. Only optional prose sections (`DESCRIPTION` and secondary `EXAMPLES`) may be listed in `omissions` when compacting for budget; if mandatory sections still cannot fit, rendering fails closed with a named budget error.
- **FR-012**: Manual cards MUST include one or two functional alternatives from the curated `TOOL_FAMILIES` map without exceeding the global documentation budget. In planned mode, cards MUST be deduplicated when the same tool appears in multiple steps.
- **FR-013**: In `manual-kb` and `planned` modes, static validation MUST accept API flag keyword arguments such as `flags`, `overwrite`, `verbose`, `quiet`, and `superquiet`, and MUST reject invalid closed-enum values before GRASS launches. Strict enum validation is automatic and MUST NOT be disableable in these modes. It MUST NOT reject free-text, map-name, range, or file-path values. `legacy` mode MUST retain its current validation behavior by default, and the only supported opt-out path is selecting `--pipeline legacy`. An explicit `--strict-options` opt-in MAY enable the same checks in `legacy` for verification; it defaults off, changes nothing unless supplied, and MUST be rejected with exit `2` when combined with `manual-kb` or `planned`, where strict validation is always on.
- **FR-014**: Repair diagnostics MUST preserve the underlying GRASS `ERROR:` line and any `Legal range:` or `options:` line when the failure is wrapped in a tool exception. Repair prompts MUST expose allowed enum options and flags for the failing tool.
- **FR-015**: The manual-kb pipeline MUST use manual cards for initial generation and for repair, reusing the existing configured top-k retrieval unchanged (this feature does not change `rag_top_k`; planned mode uses the separate `shortlist_k` setting from FR-017). Legacy mode MUST remain unchanged.
- **FR-016**: The pipeline mode MUST be selectable per run, with legacy as the default, and the selected mode MUST be recorded on every attempt and run summary from Step A onward.

### Step B - Candidate-Constrained Planning

- **FR-017**: Planned mode MUST first run hybrid retrieval with the explicit `shortlist_k` setting (default `12`, bounded `8-12`; the existing `rag_top_k=5` remains untouched for legacy and manual-kb) to produce up to 12 real candidate modules, and MUST provide at least eight when at least eight real modules exist. If fewer than eight real modules are retrieved, the planner MUST use all available modules (minimum one) and record a `shortlist_shortfall` diagnostic; if none are available, the run MUST fall back to manual-kb.
- **FR-018**: The planner MUST emit an ordered JSON plan of at most five atomic GIS steps, selecting tools only from the candidate shortlist and declaring each step's inputs, outputs, and raster/vector types.
- **FR-019**: The plan MUST be validated against the knowledge base for tool existence, raster/vector compatibility, distinct output names, lineage from the dataset inventory or a prior step, and the five-step limit.
- **FR-020**: An invalid plan or planner timeout MUST be repaired at most once (the pre-execution "plan repair"). If the repair also fails, the run MUST fall back cleanly to manual-kb single-shot retrieval without consuming a static or runtime repair tier. The planner timeout defaults to 60 seconds and MUST be configurable.
- **FR-021**: Each planned step MUST receive a deduplicated manual card plus one or two functional alternatives per FR-012, bounded by the manual documentation budget and the deterministic compaction order in the pipeline contract (deduplicate tools → one alternative per step → drop optional prose → fail closed only if mandatory sections still overflow).
- **FR-022**: The synthesizer MUST be instructed that the plan is advisory and the manual card is authoritative, allowing a documented alternative to replace the planned tool. The final output MUST remain strictly executable Python using `grass.tools`.
- **FR-023**: Planner output MUST remain internal. Planner JSON, prose, and explanations MUST never appear in the final generated script.
- **FR-024**: Repair escalation MUST support same-tool manual cards, parameter and option pivots, tool swaps, and at most one constrained re-plan per case after a failed execution. A constrained re-plan is distinct from the pre-execution plan repair; a case MAY use both, but total planner invocations MUST NOT exceed three (initial plan, one plan repair, one constrained re-plan).
- **FR-025**: A tool swap or constrained re-plan during repair MUST consume the tier that produced the repair candidate. Planner fallback MUST NOT consume a tier, and the maximum candidate count MUST remain `1 + static_limit + runtime_limit`.
- **FR-026**: SHA-256 byte/AST no-op duplicate detection, ordered attempt history, the two-tier retry budget, and the report-only semantic oracle MUST remain intact in all modes.
- **FR-027**: Plan revisions, selected tools, and tool swaps MUST be recorded for diagnostics. Duplicate rejection MUST continue to be based on generated code, not on the plan.

### Compatibility and Isolation

- **FR-028**: `--pipeline legacy` MUST remain the default. `format_context()`, `SYSTEM_PROMPT`, the existing validation behavior (unless the explicit legacy-only `--strict-options` opt-in from FR-013 is supplied), and all 394 existing tests MUST remain unchanged and passing.
- **FR-029**: The pipeline mode, resolved model context, and resolved manual documentation budget MUST be part of the resume key, attempt record, and run summary so resumed runs never mix modes or contexts.
- **FR-030**: Gate 3 reporting MUST support per-mode ablation of `Pass@Executed` and `Pass@Semantic` without changing the oracle, expectations, reference scripts, or metric definitions. Additive, non-authoritative advisory metadata (for example acceptable-tool sets) MUST live outside `benchmarks/pilot_expectations.json`.
- **FR-031**: The offline audit in FR-004 MUST be automated: a test MUST intercept `socket.connect` during knowledge-base build and benchmark execution and MUST fail on any external connection.
- **FR-032**: A regression test MUST prove that the two-tier repair ledger, no-op duplicate detection, stateful healing history, and semantic report-only behavior recompute identically from persisted attempts in every mode.
- **FR-033**: The planner model MUST be an approved offline Ollama model from the v1.4.0 stack (`qwen2.5-coder:7b`, `:14b`, and `:32b`; `:3b` is permitted for smoke runs only). In `planned` mode, a `--planner-model` value outside that set MUST exit `2` with a named invalid-model error before any inference. In `legacy` and `manual-kb` modes the value MUST be ignored without validation or exit `2`, so it can never change synthesis behavior.

### Out of Scope

- Step C autonomous ReAct tool-calling loop (Feature 005).
- Semantic-failure repair or a new semantic-repair tier.
- Cloud model backends or any non-local inference.
- Changes to Gate 3 expectations, reference scripts, semantic probe, or metric definitions.
- New benchmark cases beyond those needed to regression-test this feature.
- Replacing or rewriting the existing healing, budget, or execution architecture.

### Key Entities

- **Manual Record**: One local GRASS module's complete manual equivalent, including identity, description, API signature, parameter types and defaults, flags, closed enums, manual sections, and provenance.
- **Manual Section**: A named portion of a manual page such as `DESCRIPTION`, `NOTES`, or `EXAMPLES`, with stable order and a token estimate.
- **Module Flag**: A module-specific or generic flag with its description, used to render flags and to validate flag kwargs.
- **Closed Enum Option**: An allowed value for a parameter, with its description, used to validate values and to render choices.
- **Manual Card**: The compact, budgeted inference view of a manual record, with deterministic priority and explicit omissions.
- **Knowledge Base Metadata**: Provenance for the whole knowledge base, including GRASS version, source, schema version, build time, and content hashes.
- **Candidate Shortlist**: The up to 12 real modules retrieved before planning with `shortlist_k` (at least eight when available); fewer than eight is allowed only with a recorded shortfall.
- **Execution Plan**: An ordered, validated list of at most five steps, including assumptions, revision history, plan-repair count, and constrained re-plan count.
- **Plan Step**: One atomic GIS operation with intent, selected tool, inputs, outputs, raster/vector types, and constraints.
- **Tool Family**: A functional grouping such as reclassify, clean, or buffer, with one or two documented alternatives.
- **Pipeline Mode**: One of legacy, manual-kb, or planned, fixed for a run and recorded in results.
- **Repair Attempt**: An existing attempt record extended with plan revision and tool-swap diagnostics.
- **Benchmark Result**: The existing per-case record carrying `Pass@Executed` and `Pass@Semantic` verdicts.

### Data and Interface Contracts

These names are retained because they are compatibility contracts from the current repository and the feature request, not new design choices; the benchmark manifest and distribution-policy bullets are new Feature 004 enforcement points.

- **Knowledge-base storage**: preserve the existing `tools` and `tools_vec` tables. Add `flags_json`, `options_json`, `source`, `grass_version`, `content_hash`, `source_mismatches_json`, and `xml_validated` to `tools`, plus normalized `tool_flags`, `tool_options`, `tool_sections`, and `db_meta` tables.
- **Local source precedence**: `$GISBASE/docs/mkdocs/source/*.md` first, `--interface-description` XML for flag and closed-enum validation/enrichment, and `$GISBASE/docs/html/*.html` as fallback, with `$GISBASE` resolved from `grass --config path` or the environment.
- **Benchmark-relevant module set**: the checked-in manifest `benchmarks/kb_required_modules.txt`, derived from the pilot reference scripts, benchmark expectations, and the 40-case suite. The builder MUST fail if the manifest is missing or any listed module lacks a manual.
- **Distribution policy**: commit `data/grass_knowledge.db` when the rebuilt file is at most 50 MB; if it is larger, generate it during setup and commit only `data/kb_build_report.json` plus checksums. Legacy mode continues to read a `v1.3.0` database.
- **Pipeline selectors**: `--pipeline legacy`, `--pipeline manual-kb`, and `--pipeline planned`; legacy is the default. The model context defaults to 8,192 tokens, with 16,384 tokens available through an explicit setting, and the manual-card budget is 45% of the selected context. Planned-mode shortlist retrieval uses `shortlist_k` (default `12`, minimum `8` before `shortlist_shortfall`), while `rag_top_k=5` remains unchanged for legacy and manual-kb. The planner timeout defaults to 60 seconds and is configurable.
- **Rendering component**: `ManualCard` rendering in `grass_agent/manual_context.py`, with `TOOL_FAMILIES` supplying functional alternatives.
- **Validation and healing integration**: `validate_api()` must accept synthesized flag kwargs and apply strict closed-enum checks only in `manual-kb` and `planned`; `error_excerpt()` in `grass_agent/classifier.py` and `parameter_list()` in `grass_agent/healing.py` must expose underlying errors and allowed options.
- **Planning integration**: planner logic in `grass_agent/planner.py`, consuming the existing hybrid retriever before planning.
- **Compatibility fields**: add `pipeline`, `num_ctx`, and `manual_context_tokens` to `ResumeKey`, `Attempt`, and `RunSummary`; preserve `format_context()` and `SYSTEM_PROMPT` unchanged in legacy mode.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A clean offline knowledge-base build and a benchmark execution produce zero outbound network connections in the socket audit.
- **SC-002**: 100% of modules listed in `benchmarks/kb_required_modules.txt` have a complete manual record, including every flag and every finite closed-enum value present in the authoritative XML. Additionally, 100% of rendered manual cards for modules that define flags or closed enum values include the API signature, every such flag, and every closed-enum choice. These mandatory sections are strictly fail-closed: a card MUST NOT be rendered with a missing or truncated mandatory section, and `omissions` may list only optional prose sections (`DESCRIPTION`, secondary `EXAMPLES`).
- **SC-003**: The three documented pilot failure modes are resolved across repeated runs at the strongest configuration (32B), in at least two of three runs each: `pilot_tc_08` passes `Pass@Semantic`; `pilot_tc_14` exits zero and uses only tools listed as acceptable for that case in the advisory `benchmarks/pilot_tool_sets.json`; `pilot_tc_32` writes `rules` as a file or stream, or uses `r.recode`/`r.mapcalc`.
- **SC-004**: Across three pilot runs per new mode at the strongest configuration (32B), `Pass@Semantic` is at least 9/10 in at least two runs and never falls below the 7/10 baseline.
- **SC-005**: 100% of rendered manual cards stay within the configured token budget, with zero silent truncation of flags or closed enum choices.
- **SC-006**: In `manual-kb` and `planned` modes, 100% of invalid closed-enum proposals are either rejected statically before GRASS launches or accompanied by the legal range in the repair prompt, with zero GRASS launches for statically invalid enums. The measurement uses a deterministic adversarial closed-enum suite covering at minimum `v.clean` `tool="rm_duplicates"`, `r.viewshed` invalid `flags`, and `v.to.rast` invalid `use=`, plus any invalid closed-enum proposal emitted during benchmark runs. `legacy` behavior is unchanged.
- **SC-007**: Planned mode produces a valid plan or falls back cleanly for 100% of the multi-step pilot cases (pilot reference scripts in `benchmarks/pilot_reference/` with at least two tool calls), and zero hallucinated tools are executed.
- **SC-008**: All 394 existing tests pass unchanged, and no existing public behavior changes in legacy mode.
- **SC-009**: 100% of resumed runs reject a mismatched pipeline mode, model context, or manual budget, and the Gate 3 report shows separate ablation rows for legacy, manual-kb, and planned.
- **SC-010**: Pilot wall-clock latency at the 95th percentile stays within twice the legacy baseline measured on the same host, dataset, model, case set, and seed count, and zero context-overflow or silent-truncation events are observed.
- **SC-011**: Zero duplicate candidates are accepted for execution, and the two-tier budget invariants continue to hold in all modes.
- **SC-012**: 100% of knowledge-base records carry version and provenance, and pre-flight refuses mismatched versions or missing required provenance in manual-kb and planned modes.

## Assumptions

- The target environment is a local GRASS 8.5.0 installation that includes Markdown or HTML documentation and module executables; HTML is the fallback when Markdown is absent.
- Local manual content is trusted, static documentation. It is not adversarial input.
- The approved benchmark models are `qwen2.5-coder:7b`, `qwen2.5-coder:14b`, and `qwen2.5-coder:32b`; `qwen2.5-coder:3b` remains available for rapid smoke testing but is not part of the benchmark comparison. Embeddings remain `nomic-embed-text`.
- The default model context is 8,192 tokens with a 45% manual-card budget; 16,384 tokens is an explicit opt-in with the same budget policy, leaving room for the task, inventory, history, and output.
- Legacy remains the default pipeline. Manual-kb and planned are opt-in modes.
- The current regression baseline is 394 collected tests, not the stale 255 figure in earlier milestone documents.
- Gate 3 expectations, reference scripts, and semantic assertions remain the independent authority; semantic failures remain report-only.
- The planner uses at most one pre-execution plan repair and at most one post-failure constrained re-plan per case, with total planner invocations capped at three. The planner timeout defaults to 60 seconds. Plans have at most five steps and an up-to-12-module shortlist (`shortlist_k=12`, minimum eight when available), with a recorded shortfall otherwise; each step gets one or two alternatives.
- The pipeline mode is chosen per run, not per case, so an ablation run has one mode throughout.
- `manual-kb` reuses the existing top-k retrieval and renders manual cards for the selected tools; `planned` renders per-step cards plus alternatives.
- The planner uses the same selected model as synthesis. In `planned` mode, if `--planner-model` is provided it MUST be one of the constitution-approved local Ollama models (`qwen2.5-coder:7b`, `:14b`, `:32b`, or `:3b` for smoke only); any other value MUST be rejected during configuration resolution with exit `2` before any inference occurs. In `legacy` and `manual-kb` modes the value is ignored without validation.
- The default knowledge-base build is partial: optional or add-on modules without local manuals are reported and skipped, but every module listed in `benchmarks/kb_required_modules.txt` must have a manual or the build fails. A strict mode fails on any missing manual.
- Add-on modules absent from the local installation may be absent from the rebuilt knowledge base; all modules listed in `benchmarks/kb_required_modules.txt` are expected to be installed.
- The knowledge base may grow substantially because full manual sections are stored at rest; this is acceptable for local SQLite storage.
- The rebuilt knowledge base is committed when it is at most 50 MB; if it is larger, it is generated during setup and only the build report and checksums are committed. `v1.3.0` databases remain readable in legacy mode.
- No cloud API, external embedding service, or network fetch is permitted in any mode.
- Step C, semantic repair, and new benchmark suites are outside this feature and reserved for later work.
