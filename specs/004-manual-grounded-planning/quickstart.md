# Quickstart: Manual-Grounded Knowledge Base and Candidate-Constrained Planning

**Date**: 2026-11-19 | **Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md)

Runnable validation scenarios for Feature 004. These are validation/run guides, not implementation code. Commands assume the repository root and `.venv/bin/python`.

## Prerequisites

- Linux host with local GRASS 8.5.0, including `$GISBASE/docs/mkdocs/source/` and/or `$GISBASE/docs/html/`.
- Provisioned North Carolina dataset (`nc_basic_spm_grass7`) with read-only `PERMANENT`.
- Local Ollama with `qwen2.5-coder:7b`, `14b`, `32b`, and `nomic-embed-text`; `qwen2.5-coder:3b` is optional for smoke tests.
- `.venv` with project dependencies; 394 baseline tests green.
- No network access required for any scenario.

```sh
cd /path/to/grass-agent-opencode
.venv/bin/python -m pytest --collect-only -q
# Expected: 394 tests collected before Feature 004 changes
```

## Scenario 1 — Governance amendment first

```sh
grep -n "Version" .specify/memory/constitution.md
grep -n "004-manual-grounded-planning\|14b\|32b\|internal JSON" .specify/memory/constitution.md
```

Expected:

- Version is `1.4.0`, dated on or after 2026-11-19.
- Feature 004 is named as the current milestone.
- Internal JSON planning is permitted; final output remains zero-chat executable Python.
- 14B and 32B are in the approved benchmark stack.

This scenario must pass before any source edit.

## Scenario 2 — Offline knowledge-base build

```sh
.venv/bin/python scripts/build_knowledge_base.py \
  --gisbase "$(grass --config path)" \
  --db data/grass_knowledge.db \
  --source local \
  --rebuild
```

Expected:

- No network access; the builder does not import `requests`.
- `data/kb_build_report.json` is written with source paths, GRASS version, counts, omissions, hashes, source mismatches, and the distribution decision.
- Every module in `benchmarks/kb_required_modules.txt` is complete; optional add-ons may be reported and skipped.
- `db_meta` contains `schema_version`, `grass_version`, `gisbase`, `source`, `built_at`, `tool_count`, `section_count`, `content_hash`.
- Distribution decision: commit `data/grass_knowledge.db` only when it is at most 50 MB; otherwise generate it during setup and commit `data/kb_build_report.json` plus checksums. The report records the decision.

Inspect representative records:

```sh
sqlite3 data/grass_knowledge.db \
  "select name, grass_version, source, length(flags_json), length(options_json)
   from tools where name in ('r.viewshed','v.clean','r.reclass','r.recode');"

sqlite3 data/grass_knowledge.db \
  "select tool_name, section, token_estimate
   from tool_sections
   where tool_name in ('r.viewshed','v.clean','r.reclass')
   order by tool_name, section;"
```

Expected:

- `r.viewshed` exposes flag `b`.
- `v.clean` exposes `tool` options including `rmdupl` and `snap`.
- `r.reclass` exposes `rules` as a file/stream and stores `NOTES`/`EXAMPLES`.
- `r.recode` exists as an alternative.

## Scenario 3 — ManualCard budget and priority

```sh
.venv/bin/python -m pytest tests/test_manual_context.py -q
```

Expected:

- Cards remain within `int(0.45 * num_ctx)` for `8192` and `16384`.
- Per-card estimates are reported; representative 8K cards fall within the 250–600-token target or explain the overage.
- Priority is signature → flags → parameters/types/defaults/enums → NOTES → examples → alternatives.
- Flags and closed enums are present or the renderer fails closed; no silent truncation.
- The same tool is rendered once across repeated steps.
- Omitted optional sections are named in `omissions`.

## Scenario 4 — Static enum validation and repair diagnostics

```sh
.venv/bin/python -m pytest \
  tests/test_static_options.py \
  tests/test_healing_diagnostics.py -q
```

Expected:

- In `manual-kb`/`planned`, `flags="b"` is accepted and `tool="rm_duplicates"` is rejected before GRASS launches.
- In `legacy`, validation behavior is unchanged.
- `error_excerpt()` preserves the underlying `ERROR:` line and any `Legal range:`/`options:` continuation.
- `parameter_list()` includes module flags and allowed enum values.
- For `pilot_tc_14`, the repair prompt contains `rmdupl`/`snap`; for `pilot_tc_32`, it contains `Cannot open rules file`.

## Scenario 5 — Step A MVP end-to-end

```sh
.venv/bin/python -m benchmarks.run_gate3 --clean \
  --pipeline manual-kb \
  --model qwen2.5-coder:32b \
  --num-ctx 8192 \
  -k pilot_tc_08,pilot_tc_14,pilot_tc_32 \
  --report-path benchmarks/pilot_manual_kb_report.md
```

Expected:

- `pilot_tc_08` uses `flags="b"` and passes semantically.
- `pilot_tc_14` uses a valid `v.clean` tool choice (`rmdupl`/`snap`/`break`) or is repaired with the legal range.
- `pilot_tc_32` uses a rules file/stream or a documented alternative (`r.recode`/`r.mapcalc`).
- No context-overflow events; manual-card tokens are recorded.
- No accepted duplicate executions.

## Scenario 6 — Legacy zero-regression

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m benchmarks.run_gate3 --clean \
  --pipeline legacy \
  --model qwen2.5-coder:7b \
  -k pilot_tc_01,pilot_tc_05
```

Expected:

- All 394 pre-existing tests pass unchanged.
- Legacy prompt construction, `format_context()`, `SYSTEM_PROMPT`, validation behavior, and budgets are unchanged.
- The legacy report does not include new pipeline-specific requirements.

## Scenario 7 — Planned mode and fallback

```sh
.venv/bin/python -m benchmarks.run_gate3 --clean \
  --pipeline planned \
  --model qwen2.5-coder:14b \
  --num-ctx 8192 \
  -k pilot_tc_32,pilot_tc_33 \
  --report-path benchmarks/pilot_planned_report.md
```

Expected:

- The run records an 8–12 candidate shortlist.
- `pilot_tc_32` produces a valid plan or falls back to manual-kb after one repair.
- If the plan picks `r.reclass` for floating-point slope, synthesis may substitute `r.recode` because the manual is authoritative.
- Planner fallback consumes no static/runtime tier.
- Tool swaps or re-plans during repair consume the producing tier and do not exceed `1 + static_limit + runtime_limit`.
- Final code contains no planner JSON or prose.

Artifacts to inspect:

```sh
ls benchmarks/output_execution/pilot_tc_32/
# attempt_N.plan.json, attempt_N.manuals.json, attempt_N.py, ...
```

## Scenario 8 — Invalid-plan fallback

```sh
.venv/bin/python -m pytest tests/test_planner.py -q
```

Expected:

- Invalid JSON, empty plans, >5 steps, tools outside the shortlist, duplicate outputs, and missing lineage are rejected.
- A planner timeout follows the same one-repair path.
- One plan repair is attempted.
- A second failure falls back to manual-kb with no tier charge.
- No hallucinated tool is executed.

## Scenario 9 — Resume and ablation isolation

```sh
# Run two modes into separate directories
GRASS_OUTPUT_EXEC_DIR=benchmarks/output_legacy \
  .venv/bin/python -m benchmarks.run_gate3 --pipeline legacy -k pilot_tc_01

GRASS_OUTPUT_EXEC_DIR=benchmarks/output_manual_kb \
  .venv/bin/python -m benchmarks.run_gate3 --pipeline manual-kb -k pilot_tc_01
```

Then attempt a mismatched resume:

```sh
GRASS_OUTPUT_EXEC_DIR=benchmarks/output_legacy \
  .venv/bin/python -m benchmarks.run_gate3 --pipeline planned -k pilot_tc_01
```

Expected:

- The mismatched run rejects reuse and reruns the case.
- `run_summary.json` records `pipeline`, `num_ctx`, and `manual_context_tokens`.

Generate the combined report:

```sh
.venv/bin/python -m benchmarks.run_gate3 --report-only \
  --ablation-dirs benchmarks/output_legacy,benchmarks/output_manual_kb \
  --report-path benchmarks/gate3_ablation.md
```

Expected:

- The combined report shows separate ablation rows and never mixes denominators.
- Duplicate modes in `--ablation-dirs` exit `2`.
- `--report-only` reproduces the report without model, GRASS, or network.

## Scenario 10 — Offline socket audit

```sh
.venv/bin/python -m pytest tests/test_kb_source.py tests/test_pipeline_isolation.py -q
```

Expected:

- The audit intercepts `socket.connect`.
- A local KB build and a benchmark case record zero outbound connections.
- No `requests` import exists in the KB build path.

## Scenario 11 — Version/provenance mismatch

```sh
# Point at a DB built for a different GRASS version, or edit db_meta in a copy
cp data/grass_knowledge.db /tmp/kb_mismatch.db
sqlite3 /tmp/kb_mismatch.db "update db_meta set value='8.6.0' where key='grass_version';"

GRASS_RAG_DB=/tmp/kb_mismatch.db \
  .venv/bin/python -m benchmarks.run_gate3 --pipeline manual-kb -k pilot_tc_01
```

Expected:

- `manual-kb` exits `3` with a named version/provenance mismatch and rebuild hint; removing a required provenance key produces the same exit.
- `--pipeline legacy` still reads the DB.

## Scenario 12 — Pilot and 40-case evaluation

```sh
# Matched legacy baseline first: same host, dataset, model, case set, and seeds
for seed in 1 2 3; do
  .venv/bin/python -m benchmarks.run_gate3 --clean \
    --pipeline legacy --model qwen2.5-coder:32b --num-ctx 8192
done

# Three seeds per new mode, 32B, default 8K context
for seed in 1 2 3; do
  .venv/bin/python -m benchmarks.run_gate3 --clean \
    --pipeline manual-kb --model qwen2.5-coder:32b --num-ctx 8192
  .venv/bin/python -m benchmarks.run_gate3 --clean \
    --pipeline planned --model qwen2.5-coder:32b --num-ctx 8192
done

# Strongest configuration on the full suite
.venv/bin/python -m benchmarks.run_gate3 --all --clean \
  --pipeline planned --model qwen2.5-coder:32b --num-ctx 8192
```

Expected:

- For each new mode, `Pass@Semantic` is at least 9/10 in at least two of three pilot runs and never below the 7/10 baseline.
- For each new mode, `pilot_tc_08` passes semantically; `pilot_tc_14` and `pilot_tc_32` execute with valid choices in at least two of three runs each.
- P95 pilot wall-clock is within 2× a legacy baseline measured on the same host, dataset, model, case set, and seed count.
- Zero context-overflow events, zero accepted duplicates, `PERMANENT` unchanged, zero leaked scratch mapsets.
- Gate 3 metrics and caveats are unchanged; the only additions are pipeline metadata and the ablation table.

## Troubleshooting

| Symptom | Check |
|---|---|
| Build reports missing modules | `--strict` vs `--partial`; local docs coverage; `data/kb_build_report.json` |
| Manual card fails closed | Increase `--manual-context-tokens` or `--num-ctx`; inspect `omissions` |
| Planner always falls back | Planner JSON invalid or shortlist too narrow; inspect `attempt_N.plan.json` |
| Legacy test fails | A new default leaked into legacy; confirm `--pipeline legacy` and `strict_options=False` |
| Resume reuses wrong mode | Check `ResumeKey.pipeline`, `num_ctx`, and `manual_context_tokens` |
| Outbound connection detected | A network client leaked into the build path; remove it |

## Validation Log

Record executed scenarios here (T049). Scenario 12 evidence is recorded in `benchmarks/pilot_evidence/feature004_pilot.md` and `benchmarks/gate3_report.md`.

| Date | Scenario | Command | Observed outcome | Environment-dependent skips |
|---|---|---|---|---|
| 2026-11-19 | 1 | `grep -n "Version\|004-manual-grounded-planning\|14b\|32b" .specify/memory/constitution.md` | Version `1.4.0`; Feature 004 milestone, internal JSON planning, and 14B/32B are present | none |
| 2026-11-19 | 2 | `.venv/bin/python scripts/build_knowledge_base.py --gisbase "$(grass --config path)" --db data/grass_knowledge.db --source local --rebuild` | Exit 0; 541 module records, 3769 sections; `db_meta` has all required keys; report written; DB 12,124,160 bytes ≤ 50 MB | 3 add-on modules ingested from Markdown with `xml_validated=false` |
| 2026-11-19 | 2b | `pytest tests/test_kb_schema.py tests/test_kb_parse.py tests/test_kb_source.py -q` | Provenance, additive schema, idempotent hashes, XML flags/values, and mismatches verified | live XML test ran (GRASS 8.5 available) |
| 2026-11-19 | 3 | `.venv/bin/python -m pytest tests/test_manual_context.py -q` | 13 passed: 3686/7372 budgets, priority order, fail-closed mandatory sections, dedupe, deterministic rendering | none |
| 2026-11-19 | 4 | `.venv/bin/python -m pytest tests/test_static_options.py tests/test_healing_diagnostics.py -q` | 19 passed: strict enums gated to new modes, flags validated, legal values preserved (`rmdupl`, `snap`, `Legal range:`) | none |
| 2026-11-19 | 6 | `.venv/bin/python -m pytest -q` | 515 passed (394 pre-existing unchanged + 121 Feature 004 tests) | none |
| 2026-11-19 | 8 | `.venv/bin/python -m pytest tests/test_planner.py -q` | 18 passed: invalid JSON/empty/>5/non-contiguous/outside-shortlist/duplicate outputs/lineage/timeout, one repair, then fallback | none |
| 2026-11-19 | 9 | `.venv/bin/python -m pytest tests/test_pipeline_isolation.py tests/test_reporting_ablation.py -q` | 15 passed: resume isolation, schema_version 1, ablation rows, duplicate modes exit 2, byte-reproducible report-only | none |
| 2026-11-19 | 10 | `.venv/bin/python -m pytest tests/test_kb_source.py tests/test_pipeline_isolation.py -q` | 21 passed: `socket.connect` guard records zero outbound connections; builder does not import `requests` | live XML test ran (GRASS 8.5 available) |
| 2026-11-19 | 5 | `.venv/bin/python -m benchmarks.run_gate3 --clean --pipeline manual-kb --model qwen2.5-coder:3b --num-ctx 8192 -k pilot_tc_08,pilot_tc_14,pilot_tc_32` | Pipeline/preflight/cards/no-op diagnostics exercised; Pass@Executed 0/3 and Pass@Semantic 0/3 because 3B emitted invalid Python | 32B unavailable; 3B substitute recorded in `benchmarks/pilot_evidence/feature004_pilot.md` |
| 2026-11-19 | 7 | `.venv/bin/python -m benchmarks.run_gate3 --clean --pipeline planned --model qwen2.5-coder:3b --num-ctx 8192 -k pilot_tc_32,pilot_tc_33` | 12-module shortlist, valid 2-step plan for `pilot_tc_33`, deduplicated per-step cards (591/460 tok), supervised repair; final 3B code statically invalid | 32B unavailable; 3B substitute recorded in `benchmarks/pilot_evidence/feature004_pilot.md` |
| 2026-11-19 | 11 | `.venv/bin/python -m pytest tests/test_preflight_provenance.py -q` | 5 passed: version/provenance mismatch exits 3 with rebuild hint; legacy DB accepted only in legacy mode; `$GISBASE` path mismatch alone passes | none |
| 2026-11-23 | 12 | 14B/32B `manual-kb` and `planned` pilot runs on the V100; fresh matched 32B legacy baseline; `--report-only --ablation-dirs` | Ablations generated in `benchmarks/feature004_ablation_14b.md` and `benchmarks/feature004_ablation_32b.md`; 32B manual-kb 9/10 executed, 8/10 semantic; 32B planned 8/10 executed, 8/10 semantic; `tc_08` resolved, `tc_14` executes with `v.clean`, `tc_32` still uses inline rules; SC-004 not met (8/10) | Dataset identity overridden to the container path/hash after 10/10 reference scripts passed; see `benchmarks/feature004_pilot_report.md` |
| 2026-11-19 | 6b | `.venv/bin/python -m benchmarks.run_gate2 --clean --pipeline legacy --model qwen2.5-coder:3b -s benchmarks/benchmark_prompts_pilot10.json -k pilot_tc_01,pilot_tc_05` | Exit 0; legacy metrics and report sections unchanged; `PERMANENT` hash identical before/after; 0 leaked scratch dirs; `run_summary.json` records `pipeline=legacy` | 3B smoke only (32B unavailable) |

