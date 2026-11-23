# Contract: Gate 3 CLI (`benchmarks/run_gate3.py`, `benchmarks/run_gate2.py`)

**Date**: 2026-11-10 | **Plan**: [../plan.md](../plan.md) | **Data model**: [../data-model.md](../data-model.md) | **Report contract**: [report.md](./report.md)

Normative command-line contract for the Gate 3 harness. Gate 3 is an offline CLI plus the importable `grass_agent/` package; it exposes no network service. `benchmarks/run_gate2.py` remains the Gate 2 entry point and keeps its existing contract unless one of the new optional flags is supplied.

## Invocation

```sh
# Gate 3, semantic pilot (default)
.venv/bin/python -m benchmarks.run_gate3 [OPTIONS]

# Gate 3, full 40-case benchmark
.venv/bin/python -m benchmarks.run_gate3 --all [OPTIONS]

# Gate 2, unchanged
.venv/bin/python benchmarks/run_gate2.py [OPTIONS]
```

Run from the repository root with the project virtual environment.

## Shared options

These options exist on both entry points with the same meaning.

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `--model` | string | `qwen2.5-coder:3b` (`:7b` for evaluation) | Local Ollama model |
| `-s`, `--suite` | path | *entry-point dependent* | Benchmark JSON file. Gate 2: one file, or both tiers when omitted. Gate 3: repeatable; one or more files |
| `-k`, `--case` | string | *all cases* | Comma-separated case-id filter. An unmatched id is an argument error, exit `2` |
| `--dataset` | path | *auto-detect* | GRASS project directory containing `PERMANENT` |
| `--max-retries` | int | `2` | **Shorthand** that sets both tier budgets. `0` disables both tiers. Retained for compatibility |
| `--max-static-retries` | int | *unset* | Static tier repair budget. Overrides `--max-retries` for the static tier only |
| `--max-runtime-retries` | int | *unset* | Runtime tier repair budget. Overrides `--max-retries` for the runtime tier only |
| `--timeout` | int | `120` | Wall-clock bound in seconds for one generated-script execution. Never forwarded to `grass --timeout` |
| `--resume` | flag | on | Skip completed cases with a matching resume key |
| `--no-resume` | flag | off | Disable resume |
| `--clean` | flag | off | Wipe `benchmarks/output_execution/` before running |
| `--reuse-artifacts` | flag | off | Load Gate 1 scripts from `benchmarks/output/` as the initial candidate |
| `--report-only` | flag | off | Re-render the report from persisted results; no model, no GRASS |
| `--verbose` | flag | off | Explain every resume rejection |

## Gate 3-only options

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `--all` | flag | off | Run both benchmark tiers (40 cases) instead of the 10-case pilot |
| `--semantic` / `--no-semantic` | flag | on | Enable/disable semantic probing. `--no-semantic` runs the pilot as an execution-only suite |
| `--pilot-suite` | path | `benchmarks/benchmark_prompts_pilot10.json` | Pilot definition |
| `--expectations` | path | `benchmarks/pilot_expectations.json` | Frozen reference values |
| `--validate-pilot` | flag | off | Validate the pilot definition and expectations, print a summary, and exit without inference or GRASS |
| `--report-path` | path | `benchmarks/gate3_report.md` | Report destination |

## Budget resolution

For each tier independently, the first supplied source wins:

```text
tier CLI flag
  > --max-retries
  > tier-specific environment variable
  > GRASS_MAX_RETRIES
  > default 2
```

| Tier | CLI flag | Environment variable |
|---|---|---|
| static | `--max-static-retries` | `GRASS_MAX_STATIC_RETRIES` |
| runtime | `--max-runtime-retries` | `GRASS_MAX_RUNTIME_RETRIES` |

Examples:

| Invocation | Static | Runtime |
|---|---|---|
| (no flag) | 2 | 2 |
| `--max-retries 0` | 0 | 0 |
| `--max-retries 3 --max-static-retries 1` | 1 | 3 |
| `--max-static-retries 0 --max-runtime-retries 4` | 0 | 4 |
| `GRASS_MAX_RETRIES=1 --max-runtime-retries 3` | 1 | 3 |

Validation:

- Any budget `< 0` is an argument error, exit `2`, naming the flag.
- A non-integer value is an argument error, exit `2`.
- `--max-retries` remains present in `args` even when overridden, so existing tests and callers can inspect it. The effective values live in `ExecutionConfig.max_static_retries` / `max_runtime_retries`.
- Gate 2 without any new flags resolves both tiers to `--max-retries` / `GRASS_MAX_RETRIES`, so an existing invocation still requests the same `N` repairs per tier. Under the two-tier architecture the maximum candidates per case is therefore `1 + 2N` (5 at the default `N=2`), which is the documented FR-002b bound. Gate 2's parser, report, and public functions are otherwise unchanged.

## Option interactions

| Combination | Behaviour |
|---|---|
| `--clean --resume` | `--clean` wins; the output directory is wiped, so nothing can be resumed. Logged as a warning |
| `--clean --reuse-artifacts` | Valid; attempt 1 still loads from `benchmarks/output/` |
| `--report-only --clean` | Argument error, exit `2`. Cleaning destroys the only report source |
| `--report-only` + new flags | Allowed; flags that affect execution are ignored and echoed as such in the report metadata |
| `--validate-pilot` + any execution flag | `--validate-pilot` wins and exits `0` after validation |
| `--all --pilot-suite` | Argument error, exit `2`: the two suite selections conflict |
| `-k` with `--all` | Allowed; filters within the 40 benchmark cases |
| `-k` with the default pilot | Allowed; filters within the 10 pilot cases |
| `--max-static-retries 0` | Static failures terminate immediately; a valid initial candidate still executes with the full runtime budget |
| `--max-runtime-retries 0` | A runtime failure terminates the case; static repairs still run |
| Both tier budgets `0` | Pure zero-shot mode: exactly one candidate per case |
| `--no-semantic` | No probe is launched; `semantic_evaluated=false` for every case and the semantic denominator is empty |
| `--semantic` with a non-pilot suite | Non-pilot cases have no assertions; they are reported as semantic-not-evaluated |

## Resume key

A persisted case is reusable only when all of these match the current invocation:

| Field | Source |
|---|---|
| `model` | `--model` / environment |
| `max_static_retries` | resolved static budget |
| `max_runtime_retries` | resolved runtime budget |
| `timeout` | `--timeout` |
| `attempt1_source` | `fresh` \| `reuse_artifacts` |
| `harness` | `"gate3"` for `run_gate3`; `"gate2"` for legacy records |

Any mismatch reruns that case from the initial candidate. A Gate 2 `case_result.json` never matches a Gate 3 key, even when model, timeout, and legacy budget coincide.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Run completed (a low pass rate is not a non-zero exit) |
| `1` | Harness fault: unhandled exception, artifact write failure, internal error |
| `2` | Argument error: unknown flag, non-integer, negative budget, conflicting options, unmatched `-k` |
| `3` | Missing or invalid pre-flight dependency, or a reference-expectation mismatch |

## Pre-flight checks

Checked once per run, before any case executes.

| Dependency | Check | On failure |
|---|---|---|
| GRASS installation | `grass --version` exits 0 | exit `3`, naming GRASS |
| `--tmp-mapset` support | `grass --help` lists it | fall back to the established `init()` worker; if that fails, exit `3` |
| Target dataset | Project with `PERMANENT/DEFAULT_WIND` and `PERMANENT/PROJ_INFO` | exit `3`, naming the path |
| Local model service | Ollama reachable at `GRASS_OLLAMA_BASE_URL` | exit `3` (skipped for `--report-only` and `--validate-pilot`) |
| Knowledge base | `data/grass_knowledge.db` readable with a non-empty `tools` table | exit `3` |
| Fixtures | Every declared fixture resolves under `benchmarks/fixtures/` | exit `3`, naming the fixture and case |
| Pilot definition | 10 cases, ≥4 per benchmark tier, ≥2 multi-step/mixed, outputs named, assertions valid | exit `3`, naming the violation |
| Expectations file | Present, parseable, covers every pilot output, records GRASS version and dataset hash | exit `3`, naming the missing case/output |
| Reference script hash | `reference_script_sha256` matches the file under `benchmarks/pilot_reference/` | exit `3`, naming the drifted script |

## Progress output

stdout is human-readable, one block per case:

```text
--- [pilot_tc_05] multi_step: "Compute slope ... write pilot_slope (raster) ..."
    candidate 1  tier=initial  static: PASS                      11.8s
    candidate 1  execute: OK  new_maps=2                          71.4s  1842+96 tok
    candidate 1  semantic: PASS (3 assertions)                     2.1s
    => PASS@EXECUTED  PASS@SEMANTIC

--- [pilot_tc_33] multi_step: "Convert hospitals ... pilot_distance (raster) ..."
    candidate 1  tier=initial  static: FAIL  unknown tool         10.2s
    candidate 2  tier=static   static: PASS                       10.9s
    candidate 2  execute: FAIL  missing_input                     31.8s  1765+88 tok
    candidate 3  tier=runtime  static: PASS                       11.1s
    candidate 3  execute: OK  new_maps=2                          44.0s  1790+91 tok
    candidate 3  semantic: FAIL  mean (expected 120.4, observed 98.7, tol 1%)
    => PASS@EXECUTED  FAIL@SEMANTIC  (no repair: semantic is report-only)
```

stderr carries pre-flight failures, sweep results, duplicate rejections, and `PERMANENT` integrity assertions.

## Outputs

- `benchmarks/output_execution/<case_id>/case_result.json` — source of truth.
- Per-attempt `.py`, `.log`, `.stdout`, `.stderr`, and when applicable `.maps.json`, `.semantic.json`.
- `benchmarks/gate3_report.md` — Gate 3 report.
- `benchmarks/output_execution/run_summary.json` — run metadata: model, GRASS version, dataset, tier budgets, suite identity, expectation hash.

## Non-goals

- No parallel execution; cases run sequentially.
- No flag that suppresses cleanup or truncates the suite. Debugging uses retained artifacts and `-k`.
- No hidden network access. `--report-only` and `--validate-pilot` perform no inference and no execution.
