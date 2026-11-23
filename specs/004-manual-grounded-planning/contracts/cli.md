# Contract: Feature 004 CLI (`benchmarks/run_gate2.py`, `benchmarks/run_gate3.py`, `scripts/build_knowledge_base.py`)

**Date**: 2026-11-19 | **Plan**: [../plan.md](../plan.md) | **Data model**: [../data-model.md](../data-model.md)

Normative command-line contract for the offline knowledge-base builder and the three pipeline modes. Feature 004 remains a local CLI plus importable library; it exposes no network service.

## 1. Harness invocation

```sh
# Default: existing behavior
.venv/bin/python -m benchmarks.run_gate3 --pipeline legacy

# Step A MVP
.venv/bin/python -m benchmarks.run_gate3 --pipeline manual-kb

# Step B
.venv/bin/python -m benchmarks.run_gate3 --pipeline planned

# Gate 2 shares the same pipeline selector
.venv/bin/python benchmarks/run_gate2.py --pipeline manual-kb
```

## 2. New shared options

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `--pipeline` | enum | `legacy` | `legacy` \| `manual-kb` \| `planned` |
| `--num-ctx` | int | `8192` | Model context used for the manual-card budget |
| `--manual-context-tokens` | int | *derived* | Explicit documentation budget; default `int(0.45 * num_ctx)` |
| `--strict-options` | flag | off | Legacy-only test opt-in for strict closed-enum validation. Rejected (exit `2`) with `manual-kb`/`planned`, where strict validation is always on and cannot be disabled |
| `--planner-model` | string | *same as `--model`* | Optional planner model override; validated only in `planned` and ignored without validation elsewhere |
| `--planner-timeout` | int | `60` | Planner timeout in seconds; a timeout is treated as an invalid plan |
| `--ablation-dirs` | path list | *none* | Comma-separated output directories for a `--report-only` ablation; each must contain `run_summary.json` and represent a distinct mode |

### Validation

- `--pipeline` value is case-sensitive and restricted to the three modes; anything else exits `2`.
- `--num-ctx` must be `> 0`; supported benchmark values are `8192` and `16384`. Other positive values are accepted but warned.
- `--manual-context-tokens` must be `> 0` and must leave room for the task, inventory, history, and output. A value above 50% of `--num-ctx` is accepted with a warning; above 60% is an argument error.
- `--strict-options` is a `legacy`-only opt-in (default off, so default legacy validation is unchanged). With `manual-kb`/`planned` it exits `2` because strict validation is always on and cannot be disabled; there is no `--no-strict-options` flag.
- `--planner-model` is validated only in `planned` mode: an out-of-set value exits `2` before inference. In `legacy`/`manual-kb` the value is ignored without validation and never exits.
- `--planner-timeout` must be `> 0`; it is ignored outside planned mode.
- `--ablation-dirs` is valid only with `--report-only`; otherwise exit `2`. Each directory must contain `run_summary.json`, and the set must contain distinct pipeline modes; duplicates exit `2`.

### Environment variables

| Variable | Maps to |
|---|---|
| `GRASS_PIPELINE` | `--pipeline` |
| `GRASS_NUM_CTX` | `--num-ctx` |
| `GRASS_MANUAL_CONTEXT_TOKENS` | `--manual-context-tokens` |
| `GRASS_STRICT_OPTIONS` | `--strict-options` |
| `GRASS_PLANNER_TIMEOUT` | `--planner-timeout` |

Precedence: CLI flag > environment variable > built-in default. Existing `GRASS_*` variables keep their current meanings. `GRASS_STRICT_OPTIONS` affects only the legacy opt-in and is ignored in `manual-kb`/`planned`.

## 3. Budget resolution

```text
num_ctx              = --num-ctx / GRASS_NUM_CTX / 8192
manual_context_tokens = --manual-context-tokens
                        / GRASS_MANUAL_CONTEXT_TOKENS
                        / int(0.45 * num_ctx)
```

The manual budget is global for the attempt, not per tool. It covers primary cards plus alternatives. It is recorded in the resume key and run summary.

Examples:

| Invocation | Context | Docs budget |
|---|---:|---:|
| (defaults) | 8192 | 3686 |
| `--num-ctx 16384` | 16384 | 7372 |
| `--manual-context-tokens 3000` | 8192 | 3000 |
| `GRASS_NUM_CTX=16384 --manual-context-tokens 5000` | 16384 | 5000 |

## 4. Mode interactions

| Combination | Behaviour |
|---|---|
| `--pipeline legacy` + manual/context flags | Accepted; they do not change legacy generation, prompts, or budgets. `--strict-options` is the only flag that changes legacy validation, and only when explicitly supplied |
| `--pipeline manual-kb` + `--strict-options` | Argument error, exit `2`; strict enum checks are always on in this mode |
| `--pipeline planned` + `--strict-options` | Argument error, exit `2`; strict enum checks are always on in this mode |
| `--report-only` + `--pipeline` | Allowed; report metadata shows the requested mode, but no inference or GRASS runs |
| `--report-only` + `--ablation-dirs` | Valid; renders a combined per-mode ablation report without inference or GRASS |
| `--ablation-dirs` without `--report-only` | Argument error, exit `2` |
| `--clean` + `--resume` | Existing behavior: `--clean` wins |
| `--validate-pilot` + `--pipeline` | `--validate-pilot` wins; no inference or execution |
| `--all` + `--pilot-suite` | Existing conflict: exit `2` |

## 5. Knowledge-base build CLI

```sh
.venv/bin/python scripts/build_knowledge_base.py \
  --gisbase "$(grass --config path)" \
  --db data/grass_knowledge.db \
  --source local \
  --rebuild
```

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `--gisbase` | path | `$GISBASE` or `grass --config path` | Installed GRASS tree |
| `--db` | path | `data/grass_knowledge.db` | SQLite destination |
| `--source` | enum | `local` | `local` only; `online` is removed |
| `--rebuild` | flag | off | Rebuild all records; otherwise update missing/stale records |
| `--strict` | flag | off | Fail on any missing module manual or XML |
| `--partial` | flag | on | Ingest optional/add-on modules from Markdown when XML is unavailable (`xml_validated=false`); skip them only when no Markdown exists; fail if a module in `benchmarks/kb_required_modules.txt` is missing |
| `--dataset-project` | path | *optional* | GRASS project for XML extraction; if absent, use a minimal local project; if XML still cannot be obtained, manifest modules fail the build (exit `3`) |
| `--report` | path | `data/kb_build_report.json` | Build evidence |

Validation:

- No `requests` import and no outbound network call.
- `--strict` and `--partial` are mutually exclusive; `--strict` wins if both are supplied? **No**: exit `2`.
- A missing module listed in `benchmarks/kb_required_modules.txt` is always exit `3`, even in partial mode; a missing manifest is also exit `3`.
- A missing optional module is reported and skipped in partial mode; strict mode exits `3`.
- XML enrichment is mandatory for every module in `benchmarks/kb_required_modules.txt`; if it cannot be obtained, the build exits `3` rather than storing a Markdown/HTML-only record. Optional/add-on modules log a warning, are ingested from local Markdown when available with `xml_validated=false`, and are skipped only when no Markdown exists; strict mode exits `3` for any missing XML.
- Commit the rebuilt DB only when it is at most 50 MB; otherwise generate it during setup and commit the report and checksums.

## 6. Resume key

A persisted result is reusable only when all fields match:

| Field | Source |
|---|---|
| `model` | `--model` |
| `max_static_retries` | resolved static budget |
| `max_runtime_retries` | resolved runtime budget |
| `timeout` | `--timeout` |
| `attempt1_source` | `fresh` \| `reuse_artifacts` |
| `harness` | `gate2` \| `gate3` |
| `pipeline` | `legacy` \| `manual-kb` \| `planned` |
| `num_ctx` | resolved context |
| `manual_context_tokens` | resolved documentation budget |

A mismatch reruns the case from the initial candidate. A `legacy` result never matches `manual-kb` or `planned`; an 8K result never matches a 16K key.

## 7. Pre-flight

Checked once per run, before any case executes.

| Dependency | Check | On failure |
|---|---|---|
| GRASS installation | `grass --version` exits 0 | exit `3` |
| Dataset | Valid `PERMANENT` | exit `3` |
| Ollama | Reachable at the configured URL | exit `3` |
| Knowledge base | Readable `tools` table | exit `3` |
| DB schema/provenance | New modes require the Feature 004 schema, matching `grass_version`, and required provenance (`source`, `built_at`, `content_hash`, `gisbase` presence) | exit `3` with rebuild hint |
| Legacy DB | Old DB allowed only in `legacy` | New modes exit `3` |
| Fixtures | Declared fixtures resolve | exit `3` |
| Pilot metadata | Existing validation | exit `3` |

## 8. Exit codes

| Code | Meaning |
|---|---|
| `0` | Run completed (a low pass rate is not a failure) |
| `1` | Harness fault |
| `2` | Argument error |
| `3` | Missing/invalid dependency, DB mismatch, or reference mismatch |

## 9. Progress output

Existing per-case blocks remain. Extend them with mode and plan evidence:

```text
--- [pilot_tc_32] multi_step (pipeline=planned): "..."
    shortlist: r.slope.aspect, r.reclass, r.recode, r.to.vect, ...
    plan: 3 steps (revision 0)
    cards: r.slope.aspect (420 tok), r.reclass (510 tok), r.to.vect (390 tok)
    candidate 1  tier=initial  static: PASS
    candidate 1  execute: FAIL  general_exception  ...
    candidate 2  tier=runtime  plan: revision 1 (r.reclass -> r.recode)
    candidate 2  execute: OK  new_maps=2
```

Planner JSON and manual text are never printed to stdout as code; progress lines are human-readable summaries.

## 10. Non-goals

- No parallel execution.
- No network fallback for missing manuals.
- No semantic-repair flag.
- No changes to the existing `--max-retries`, `--max-static-retries`, or `--max-runtime-retries` semantics.
- No new output directory layout; plan/card evidence is additive.
