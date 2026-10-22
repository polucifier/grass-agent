# Contract: `benchmarks/run_gate2.py` CLI

**Date**: 2026-10-06 | **Plan**: [../plan.md](../plan.md) | **Data model**: [../data-model.md](../data-model.md)

Normative specification of the Gate 2 execution harness command line. The harness is an offline CLI; it exposes no network interface and no library API beyond the importable `grass_agent/` package.

## Invocation

```sh
python benchmarks/run_gate2.py [OPTIONS]
```

Run from the repository root. The interpreter must be the project virtual environment (`.venv/bin/python`), which provides `ollama`, `sqlite-vec`, and `pytest`.

## Options

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `--model` | string | `qwen2.5-coder:3b` | Local Ollama model. `qwen2.5-coder:7b` for evaluation (FR-017); `:3b` for smoke tests |
| `-s`, `--suite` | path | *both tiers* | Benchmark JSON file. Omit to cover tier 1 **and** tier 2 (all 40 cases). A path covers just that file |
| `-k`, `--case` | string | *all cases* | Comma-separated case-id filter, e.g. `-k tc_01` or `-k tc_01,tc_11`. Combined with `--suite`, filters within the selected suite(s). A filter matching no case id is an argument error, exit `2` |
| `--dataset` | path | *auto-detect* | Path to the GRASS project directory holding the `PERMANENT` mapset to run against. Omit to auto-detect the first standard North Carolina dataset found under `$GRASSDATA`, `~/grassdata`, or `$GISDBASE` |
| `--max-retries` | int | `2` | Unified retry budget per case. `0` disables healing and yields the pure Pass@1 zero-shot baseline (FR-009) |
| `--timeout` | int | `120` | Per-attempt wall-clock bound in seconds for a single GRASS execution (FR-022). Enforced by the harness, **never** forwarded to `grass --timeout` (R6). Default is 120s so that legitimate long-running raster work is not killed: a measured `r.slope.aspect` over the full NC elevation DEM takes 62–81s depending on host load, which the previous 60s default cut off and recorded as a timeout |
| `--resume` | flag | **on** | Skip cases already `complete` with a matching resume key (FR-006a) |
| `--no-resume` | flag | off | Disable resume; rerun every case, reusing nothing |
| `--clean` | flag | off | Wipe `benchmarks/output_execution/` and run the suite from scratch (FR-006a) |
| `--reuse-artifacts` | flag | off | Load existing Gate 1 scripts from `benchmarks/output/` as attempt 1 (FR-001a, clarification Q1) |
| `--report-only` | flag | off | Re-render `benchmarks/execution_report.md` from persisted `case_result.json` files. Invokes neither the model nor GRASS |


## Option interactions

| Combination | Behaviour |
|---|---|
| `--clean --resume` | `--clean` wins. The output directory is wiped, so nothing exists to resume. Logged as a warning, not an error |
| `--clean --reuse-artifacts` | Valid. Attempt 1 still comes from `benchmarks/output/`; only execution artifacts are wiped |
| `--reuse-artifacts` + missing `benchmarks/output/` | Pre-flight failure, exit `3` (§Exit codes) |
| `--reuse-artifacts` + missing script for a case | That case's attempt 1 falls back to fresh generation, logged per case. Not a harness failure |
| `--max-retries 0` + `--report-only` | Allowed. Renders a baseline-only report |
| `--max-retries` < 0 | Argument error, exit `2` |
| `--timeout` ≤ 0 | Argument error, exit `2` |
| `-k` / `--case` matching no case id | Argument error, exit `2`, naming the unmatched ids |
| `--dataset` pointing at a non-project | Pre-flight dependency failure, exit `3`, naming the path checked |

**Configuration precedence.** Every flag may be supplied by environment variable instead, matching the Gate 1 `GenerationConfig.from_env()` convention (`config.py:15-23`). CLI arguments take precedence over environment variables; environment variables take precedence over built-in defaults. Recognised variables:

| Variable | Backing field | Default |
|---|---|---|
| `GRASS_OLLAMA_MODEL` | `model` | `qwen2.5-coder:3b` |
| `GRASS_OLLAMA_BASE_URL` | `ollama_base_url` | `http://localhost:11434` |
| `GRASS_RAG_DB` | `knowledge_db` | `data/grass_knowledge.db` |
| `GRASS_DATASET_PROJECT` | `dataset_project` | auto-detect |
| `GRASS_EXEC_TIMEOUT` | `timeout_s` | `120` |
| `GRASS_MAX_RETRIES` | `max_retries` | `2` |
| `GRASS_FIXTURES_DIR` | `fixtures_dir` | `benchmarks/fixtures` |
| `GRASS_OUTPUT_EXEC_DIR` | `output_dir` | `benchmarks/output_execution` |

**Dataset auto-detection.** With `--dataset` and `GRASS_DATASET_PROJECT` both unset, the harness searches in order: `$GISDBASE`, `$GRASSDATA`, `~/grassdata`, then `./grassdata`. Within each root it accepts the first directory containing a `PERMANENT/` with `DEFAULT_WIND` and `PROJ_INFO`, matching either standard name: `nc_basic_spm_grass8` or `nc_spm_08_grass7`. If none is found, pre-flight exits `3` naming every root searched (FR-023).

**Resume key** (data-model §7): a persisted case is reused only when `model`, `max_retries`, `timeout`, and `attempt1_source` all match the current invocation. Any mismatch reruns that case from attempt 1 (SC-019). This is independent of the `--resume` flag, which only controls whether resume is attempted at all.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Suite completed. Note: a low pass rate is **not** a non-zero exit — the report carries the result |
| `1` | Harness fault: unhandled exception, artifact write failure, unexpected internal error |
| `2` | Argument error: unknown flag, non-integer value, out-of-range value |
| `3` | Missing pre-flight dependency (FR-023). The message names **which** dependency is absent |

FR-023 requires a non-zero exit with a named dependency when the runtime environment is unavailable. Checked once per run, before any case executes:

| Dependency | Check | On failure |
|---|---|---|
| GRASS installation | `grass --version` exits 0 | `exit 3` — "GRASS not found on PATH" |
| `--tmp-mapset` support | `grass --help` lists `--tmp-mapset` | Falls back to the `grass.script.setup.init()` worker (R4). If that also fails, `exit 3` |
| Target dataset | Project directory exists and contains a valid `PERMANENT` with `DEFAULT_WIND` and `PROJ_INFO` | `exit 3` — names the project path checked and the dataset expected |
| Local model service | Ollama reachable at `GRASS_OLLAMA_BASE_URL` | `exit 3` — "local model service unreachable; start `ollama serve`" |
| Knowledge base | `data/grass_knowledge.db` readable, `tools` table non-empty | `exit 3` |
| Fixtures (only if a case declares any) | Each declared fixture resolves and is readable under `benchmarks/fixtures/` | `exit 3`, naming the missing fixture and the case that needs it |
| Reuse artifacts (only with `--reuse-artifacts`) | `benchmarks/output/` exists | `exit 3` |

**Dataset provisioning is a prerequisite, not a harness action.** The dataset is absent on a fresh host and the harness performs no network access (FR-016). The pre-flight check reports its absence clearly rather than fabricating a substitute; see [../quickstart.md](../quickstart.md).

## Determinism and environment

- **Locale**: all child processes run with a fixed English locale (`LANG`/`LC_ALL`). VERIFIED: a German host locale localises GRASS error text into German and `LANGUAGE=en` does not override it, which would break classification (R9/D9).
- **`TMPDIR`**: each attempt gets its own temporary directory, removed by the post-run sweep (D6). GRASS honors `TMPDIR`.
- **`PYTHONPATH`**: not set by the harness. GRASS injects its own for the child (R2).
- **Interpreter**: plain `python3` resolved from `PATH`. Bare `python` does not exist on this host (R2).
- **Process group**: each execution is launched with `start_new_session=True` so the timeout path can `killpg` the whole group including grandchildren (D4).

## Output

**stdout** — human-readable progress, one block per case:

```
--- [tc_01] single_tool: "Create a 200-meter buffer around the stream network lines."
    attempt 1  static: PASS                              12.4s
    attempt 1  execute: FAIL  missing_input              31.8s  1842+96 tok
    attempt 2  static: PASS                              11.9s
    attempt 2  execute: OK                               28.1s  1765+88 tok
    => PASS@HEALED  (missing_input → recovered on retry 1)
```

**stderr** — pre-flight failures, sweep results, and PERMANENT integrity assertions.

**Files** — per-case artifacts under `benchmarks/output_execution/<tc_id>/` (data-model §9) and the report at `benchmarks/execution_report.md`.

## Non-requirements

- The harness exposes no watch, serve, or interactive mode.
- It does not accept `--parallel`; cases run sequentially (spec Out of Scope).
- It does not write outside `benchmarks/output_execution/`, `benchmarks/fixtures/`, and the GRASS temp areas it creates and sweeps.
- It exposes **no flag that suppresses cleanup or shortens the suite**. `--keep-scratch` and `--fail-fast` were considered and removed: retaining scratch directories would weaken SC-004's zero-leftover guarantee, and stopping early would leave a partial report with no metric to publish. Debugging reuses `--keep`-free means — inspect the retained `attempt_<n>.stdout`/`attempt_<n>.stderr`/`status.json` files, or run a single case with `-k` and a raised `--timeout`. The full suite always runs to completion and always produces a report.