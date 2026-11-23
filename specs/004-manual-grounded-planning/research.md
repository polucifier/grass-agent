# Phase 0 Research: Manual-Grounded Knowledge Base and Candidate-Constrained Planning

**Date**: 2026-11-19 | **Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md)

Every finding below was established by inspecting the installed GRASS 8.5.0 tree, the current repository code, the committed knowledge base, or the persisted Gate 3 pilot artifacts. Findings are tagged **VERIFIED** (executed/observed) or **INFERRED** (read from source or documentation). No unresolved `NEEDS CLARIFICATION` remains.

## Environment baseline (VERIFIED)

| Fact | Value |
|---|---|
| GRASS | 8.5.0, launcher `/usr/bin/grass`, prefix `/usr/lib64/grass85` |
| Local Markdown manuals | 738 files under `$GISBASE/docs/mkdocs/source/` |
| Local HTML manuals | 728 files under `$GISBASE/docs/html/` |
| Current knowledge base | `data/grass_knowledge.db`, 543 tools, ~3.8 MB |
| Current DB coverage gap | Only `i.svm.predict` and `i.svm.train` are absent from the local 8.5 docs |
| Test baseline | 394 tests collected (`.venv/bin/python -m pytest --collect-only -q`) |
| Model stack in evidence | `qwen2.5-coder:7b`, `14b`, `32b`; `nomic-embed-text` embeddings |
| 32B pilot context | `OLLAMA_CONTEXT_LENGTH=8192`, ~20.5 GiB VRAM; 32K would need ~28 GiB |
| 32B prefill speed | ~190.6 tokens/s for short prompts |
| Current pilot baseline | 7B: 70% executed / 60% semantic; 14B and 32B: 80% / 70% |
| Current test count in stale docs | 255; actual current count is 394 |

### Verified documentation facts

| Fact | Evidence |
|---|---|
| Local Markdown contains the `grass.tools.Tools.<name>` signature, Python types, defaults, and allowed values | `r.reclass.md`, `v.clean.md`, `r.viewshed.md` |
| Local HTML does **not** contain the `grass.tools` signature | `grep -l "grass.tools" $GISBASE/docs/html/*.html` returned zero files |
| Local XML exposes flags and closed `<values>` with descriptions | `r.viewshed --interface-description` shows `-b`; `v.clean` shows `rmdupl`, `snap`, etc. |
| XML parameter names match the current API names | `r.viewshed`, `v.clean`, `r.reclass`, `r.recode`, `v.distance`, `v.overlay`, `r.mapcalc`, `r.slope.aspect` |
| `r.reclass` requires integer input and uses a rules file/stream | Local `r.reclass.md` notes and parameter table |
| `v.clean` exposes `rmdupl` and `snap` as closed values | Local `v.clean.md` and XML |
| `r.viewshed -b` is the binary-output flag | Local `r.viewshed.md` and XML |

### Verified token-size evidence

Approximate core manual size (SYNOPSIS + DESCRIPTION + NOTES + EXAMPLES), excluding navigation, references, authors, and source-code links. Range uses chars/4 to chars/3.5.

| Module | Approx. tokens |
|---|---:|
| `r.recode` | 0.9–1.1k |
| `r.buffer` | 1.3–1.5k |
| `v.buffer` | 1.9–2.2k |
| `r.to.vect` | 2.0–2.2k |
| `v.to.rast` | 2.4–2.7k |
| `v.clean` | 4.0–4.5k |
| `r.slope.aspect` | 4.4–5.0k |
| `r.viewshed` | 4.6–5.2k |
| `v.overlay` | 4.6–5.2k |
| `r.reclass` | 4.8–5.4k |
| `r.univar` | 4.9–5.7k |
| `r.mapcalc` | 11.2–12.8k |

`pilot_tc_32` (`r.slope.aspect` + `r.reclass` + `r.to.vect`) is ~11.2–12.6k tokens before system/task/output/history. This confirms that raw full manuals cannot be passed at 8K.

---

## R1. Local source precedence

**Decision**: Use `$GISBASE/docs/mkdocs/source/*.md` as the primary source; use `--interface-description` XML as the authoritative enrichment/validation source for flags and closed enums; use `$GISBASE/docs/html/*.html` as fallback.

**Rationale**:

- Markdown contains the exact `grass.tools` signature, Python types, defaults, allowed values, and all manual sections. It is the only local source that gives the API shape without reconstructing it.
- XML is the executable truth for flags, requiredness, defaults, multiple values, and closed `<values>`; it is authoritative even when prose drifts.
- HTML is a universal fallback but lacks the Python signature on this installation, so it cannot be the primary source.
- Local docs also remove the current 8.6-online vs 8.5-runtime drift.

**Alternatives considered**:

- *HTML + XML only*: would require synthesizing API signatures and risk drift from `grass.tools`. Rejected as primary, retained as fallback.
- *Online 8.6 manuals*: violates offline mandate and version pinning. Rejected.
- *Runtime introspection*: `inspect.signature(tools.r_reclass)` returns `(**kwargs)` on this install, so it cannot recover the documented signature. Rejected.

## R2. Offline XML extraction mechanics

**Decision**: Resolve `GISBASE` from `$GISBASE` or `grass --config path`. Run XML extraction inside a local GRASS session via `grass.script.task.get_interface_description` or an equivalent `--interface-description` invocation. Accept an optional `--dataset-project`; when absent, use a minimal local project. If XML still cannot be obtained, manifest modules fail the build (exit `3`) while optional modules may fall back to Markdown/HTML-derived flags with a recorded exclusion.

**Evidence**:

- Direct `$GISBASE/bin/<module> --interface-description` exits without useful XML unless a GRASS session (`GISRC`) is active.
- `grass --tmp-mapset <project> --exec <module> --interface-description` works and returns the full XML.
- Markdown carries flags and allowed values, but only XML is authoritative for finite enum sets; manifest modules therefore require XML, while optional modules may degrade.

**Rationale**: The builder stays offline and deterministic, and XML remains authoritative. Manifest modules are never accepted without it, so SC-002 remains achievable; the record carries a `source`/`xml_validated` marker so downstream users know which authority was used.

**Alternative rejected**: Requiring the North Carolina dataset for every KB build. It couples documentation generation to the benchmark fixture and makes fresh installs brittle.

## R3. Additive SQLite schema and migration

**Decision**: Keep `tools` and `tools_vec`; add `flags_json`, `options_json`, `source`, `grass_version`, and `content_hash` to `tools`; add `tool_flags`, `tool_options`, `tool_sections`, and `db_meta`. Use a `db_meta.schema_version` row and idempotent additive migration.

**Evidence**:

- `check_knowledge_db()` only requires a readable non-empty `tools` table, so additive columns are safe.
- `GrassToolsRetriever._row_to_doc()` currently selects six fixed columns; it must tolerate old and new DBs.
- Current tests use fake retrievers, so schema changes do not break the 394-test suite; real-DB integration tests are the risk surface.

**Rationale**: Full manual sections and normalized options cannot fit cleanly in the existing single JSON column without making validation and section retrieval awkward. Additive tables preserve legacy reads and make the new data queryable.

**Alternatives considered**:

- *One large `manual_json` column*: simpler migration, but section retrieval, token accounting, and option validation become opaque. Rejected.
- *New database file*: duplicates connection/preflight logic and breaks the committed artifact. Rejected.

## R4. Markdown/HTML/XML parsing and deduplication

**Decision**: Parse Markdown line-oriented, not with a new heavyweight parser. Extract the Python `grass.tools` tab, parameter tables, and `DESCRIPTION`/`NOTES`/`EXAMPLES` sections. Deduplicate the CLI/Python/`grass.script` tabs. Parse XML into flags, parameters, defaults, multiple, and closed values. Merge by API parameter name; the Markdown signature wins on API naming, XML wins on validation metadata. Record disagreements.

**Rationale**: The Markdown layout is stable and uses tab markers (`=== "Command line"`, `=== "Python (grass.tools)"`, `=== "Python (grass.script)"`). A line parser avoids a new runtime dependency and is deterministic. Deduplication is essential: raw pages repeat parameter tables three times.

**Edge handling**:

- No Markdown: parse HTML sections and synthesize API records from XML.
- No XML: use Markdown flags/values and mark `xml_validated=false`.
- Parameter name mismatch: keep the signature name, attach options under the matching XML parameter where possible, and persist the mismatch in `source_mismatches_json` and the build report.
- Free-text/range/file parameters: never mark as closed enums.

## R5. Token budget and ManualCard rendering

**Decision**: Store complete sections at rest. At inference, target 250–600 tokens per card at 8K within a 45% global documentation budget; report every per-card estimate, and allow an out-of-range card only when required flags, enums, or constraints explain it. Default `num_ctx=8192` (~3,686 tokens); `num_ctx=16384` is an explicit opt-in. Estimate tokens conservatively (`ceil(chars/3.5)` plus safety), and record actual `prompt_eval_count`.

**Priority**:

1. API signature.
2. Module-specific flags with descriptions.
3. Parameters with Python types, defaults, and closed enum `Literal[...]` choices.
4. Key `NOTES` constraints.
5. 1–2 worked examples.
6. Functional alternatives.

**Fail-closed rule**: Drop optional sections first. If required flags or closed enums still cannot fit, raise a named budget error rather than silently omitting them. The prompt must never contain a truncated enum list without an explicit marker.

**Evidence**: Current pilot prompts are 1,164–1,690 tokens. `pilot_tc_32` full manuals are ~11.2–12.6k tokens, which does not fit 8K. A compact card for `r.reclass` can fit in ~400–600 tokens while preserving the integer constraint, rules-file semantics, and the `r.recode` alternative.

**Alternatives considered**:

- *Raw full manuals*: does not fit; risks Ollama truncation and lost-in-the-middle. Rejected.
- *Single fixed token count per tool*: ignores manual size and context; rejected in favor of a global budget with deterministic priority.
- *Drop flags/enums first*: directly contradicts the feature's purpose. Rejected.

## R6. Static flag synthesis and closed-enum validation

**Decision**: Add synthetic API parameters `flags`, `overwrite`, `verbose`, `quiet`, `superquiet` to every record's parameter map. Add `validate_api(..., strict_options=False)`; strict closed-enum checks run only for `manual-kb` and `planned`.

**Rules**:

- `flags="b"` is valid when `b` is a known module flag; invalid characters are reported with valid flags.
- Closed enums (`v.clean.tool`, `r.viewshed.flags`, `v.overlay.operator`) are validated per comma-separated value.
- Free text, map names, numeric ranges, expressions, and file paths are never validated as enums.
- Legacy passes `strict_options=False` by default, preserving current behavior and all 394 tests; an explicit legacy-only `--strict-options` opt-in may enable the same checks for verification.

**Evidence**: The current DB includes `flags` in `params_json` for 356 tools, but `clean_signature()` strips the flags line and `format_context()` never renders options. `validate_api()` only checks parameter names, so `tool="rm_duplicates"` passes statically and fails at runtime. The XML/Markdown now provide the missing options.

**Alternative rejected**: Apply strict validation in legacy. It would change legacy behavior and risk the zero-regression contract; the spec clarification explicitly chooses new-modes-only.

## R7. Repair diagnostic preservation

**Decision**: When the trailing exception is a wrapper `ToolError`, prefer the last underlying `ERROR:` line and its continuation lines. Include `Legal range:`, `options:`, or `Allowed values:` when present. Keep the excerpt a verbatim substring of captured stderr. `parameter_list()` includes module flags and closed enum values.

**Evidence**:

- `tc_14` excerpt currently ends at `ERROR: Value <rm_duplicates> out of range for parameter <tool>` and omits the next `Legal range: break,snap,...` line.
- `tc_32` excerpt currently shows the `ToolError` summary and omits `ERROR: Cannot open rules file <...>`.
- The model repeated `rm_dups` and inline rules because the actionable line was absent.

**Rationale**: GRASS already reports the legal values. Preserving them is cheaper and more reliable than relying on the model to infer them from prose.

**Alternative rejected**: Increase the generic excerpt length blindly. It adds traceback noise; a targeted `ERROR:` + continuation policy is deterministic and useful.

## R8. Retrieval-informed shortlist and functional families

**Decision**: Run the existing hybrid retriever before planning. Give the planner 8–12 real candidates when available; if fewer than eight exist, use all of them and record `shortlist_shortfall`, and if none exist, fall back to manual-kb. Add `TOOL_FAMILIES` during Foundational/US1 so manual-kb cards can include alternatives, before the planner work begins.

**Evidence**:

- Current retrieval recall is 39/40, so the retriever is strong.
- The current synonym map sends “reclassify” only to `r.reclass`; it has no `r.recode`/`r.mapcalc` alternative.
- A free-form planner over 543 modules is likely to invent names like `rm_duplicates` or `r.reclassify`.

**Rationale**: Retrieval supplies the vocabulary; the planner supplies ordering and step decomposition. This is more robust than either alone.

**Alternatives considered**:

- *Planner-first over all modules*: hallucination and no candidate provenance. Rejected.
- *Retrieval-only*: leaves multi-step ordering and tool substitution unresolved. Rejected.

## R9. Planner JSON, validation, and fallback

**Decision**: The planner emits strict JSON with `steps[]` and `assumptions[]`. Each step has `id`, `intent`, `tool`, `inputs`, `outputs`, `output_types`, `constraints`. Maximum 5 steps. Tools must come from the shortlist. Validate tool existence, type compatibility, distinct outputs, and inventory/prior-step lineage. Allow one pre-execution plan repair; then fall back to manual-kb single-shot. A planner timeout (default 60s) is treated as invalid and uses the same repair path.

**Budget rule**: Planner fallback occurs before a candidate is generated and consumes no static/runtime tier. A constrained re-plan during repair is part of the repair candidate and consumes the producing tier. The pre-execution plan repair and the post-failure constrained re-plan are distinct; total planner invocations are capped at three. The maximum candidate count stays `1 + static_limit + runtime_limit`.

**Evidence**: Current `run_case` charges candidates at generation and bounds them; the planner is a pre-generation step. The existing no-op detector remains the final guard.

**Alternative rejected**: Let planner failure become a static rejection. That would consume a tier for a non-code failure and distort the budget.

## R10. Manual-authoritative synthesis and repair escalation

**Decision**: The synthesizer treats the plan as advisory and the `ManualCard` as authoritative. If the primary tool cannot satisfy the step, it may use a documented alternative. Repair escalation is:

1. Same-tool manual card.
2. Parameter/option pivot.
3. Tool swap using functional alternatives.
4. One post-failure constrained re-plan, distinct from the pre-execution plan repair; total planner invocations ≤3.

**Rationale**: `r.reclass` on floating-point slope is the canonical case: the manual says integer input and points to scaling or `r.recode`; the synthesizer should be allowed to follow the manual over the plan. The repair loop must be able to swap tools, not just parameters.

**No-op/budget**: Code digest remains the duplicate authority; plan changes do not bypass it. Tool swaps/re-plans consume the producing tier and do not create extra candidates. A case may use one plan repair and one constrained re-plan, but total planner invocations never exceed three.

## R11. Pipeline isolation and ablation reporting

**Decision**: Add `pipeline`, `num_ctx`, and `manual_context_tokens` to `ResumeKey`, `Attempt`, and `RunSummary`; default `legacy`/`8192`/`None`; include all three in reuse matching. Add the mode to the report header and a per-mode ablation table when multiple mode summaries are supplied. Keep `case_result.json` at `schema_version: 1` with additive fields.

**Evidence**: Current `ResumeKey.matches()` compares model, budgets, timeout, attempt1 source, and harness. Without a pipeline field, a `manual-kb` result could be reused by a `planned` run or by `legacy`, invalidating the ablation.

**Rationale**: Mode isolation is required for credible comparison. Additive fields preserve old records; old keys default to `legacy`.

**Alternative rejected**: Infer mode from attempt content. It is ambiguous and would not protect resume safety.

## R12. Offline audit and provenance

**Decision**: Remove `requests` from the builder; add a socket audit test that raises on outbound `socket.connect` during a local build and a benchmark case. Store `grass_version`, `source`, `build time`, `schema_version`, and content hashes in `db_meta`; preflight compares the installed version.

**Evidence**: Current builder imports `requests` and fetches `https://grass.osgeo.org/grass-stable/manuals`. The cache makes rebuilds offline only on this host; a fresh clone is not offline. The DB is 8.6 while the runtime is 8.5.0.

**Rationale**: The constitution requires offline operation and the spec requires provenance. A socket audit makes the guarantee testable.

## R13. Build strictness and distribution

**Decision**: Default build is partial: optional/add-on modules without local manuals are reported and skipped; any module listed in `benchmarks/kb_required_modules.txt` missing a manual fails the build. `--strict` fails on any missing manual. Commit the rebuilt DB only when it is at most 50 MB; otherwise generate it during setup and commit the build report and checksums.

**Rationale**: Fresh installs may not include every add-on. Benchmark modules are the correctness surface and must be complete. Full manuals grow the DB; the current committed DB is 3.8 MB, while full sections may grow it materially.

## R14. Testing and zero-regression strategy

**Decision**: Keep `legacy` as the default; preserve `format_context()`, `SYSTEM_PROMPT`, and `validate_api()` defaults; add new behavior behind explicit mode/flag paths. Use checked-in Markdown/XML/HTML fixtures for unit tests; keep live GRASS tests `slow`.

**Test layers**:

- Parser/schema tests with small checked-in fixtures (no network, no GRASS).
- ManualCard budget/priority/fail-closed tests.
- Static flag/enum tests and repair-excerpt tests.
- Planner JSON/validation/fallback tests with fake providers.
- Agentic orchestration tests with fake retriever/provider.
- Resume/report isolation tests.
- Slow live tests for `r.viewshed -b`, `v.clean` enum, and `r.reclass` rules file.
- Full `pytest -q` gate: 394 existing plus new.

**Evidence**: Existing tests construct `ToolDoc`, `ResumeKey`, and `Attempt` positionally, so new fields must be appended with defaults. `test_integration_smoke.py` asserts `schema_version == 1`, so the result schema must stay additive.

## Resolved decisions summary

| Question | Resolution |
|---|---|
| Primary local source | Markdown; XML enrichment; HTML fallback |
| DB evolution | Additive columns/tables; legacy readable |
| Context budget | 8K default, 45%; 16K opt-in; fail closed |
| Static enum scope | `manual-kb`/`planned` only |
| Planner input | 8-12 retrieved candidates when available; all available with shortfall; zero falls back |
| Plan failure | One pre-execution repair (timeout included), then manual-kb fallback, no tier charge |
| Tool swap | Allowed via functional families; manual authoritative |
| Repair re-plan | One post-failure constrained re-plan per case; distinct from plan repair; total planner invocations ≤3; charges producing tier |
| Mode isolation | `pipeline`, `num_ctx`, and manual budget in resume key, attempt, run summary |
| Offline proof | Socket audit; local-only builder |
| Regression baseline | 394 tests; legacy default unchanged |
| Distribution | Commit DB if ≤50 MB; otherwise generate during setup and commit report/checksums |
