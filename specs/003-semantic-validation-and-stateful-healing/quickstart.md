# Quickstart: Gate 3 Semantic Validation and Stateful Healing

**Date**: 2026-11-10 | **Plan**: [plan.md](./plan.md) | **CLI**: [contracts/cli.md](./contracts/cli.md)

Runnable validation scenarios that prove Gate 3 works end to end. These are validation steps, not implementation instructions.

## Prerequisites

| Requirement | Check |
|---|---|
| Python virtual environment | `.venv/bin/python --version` |
| pytest | `.venv/bin/python -m pytest --version` |
| GRASS 8.x | `grass --version` |
| North Carolina dataset | `ls ~/grassdata/nc_basic_spm_grass7/PERMANENT` |
| Local model | `ollama list` shows `qwen2.5-coder:7b` and `nomic-embed-text` |
| Ollama running | `curl -s http://localhost:11434/api/tags` |
| Knowledge base | `data/grass_knowledge.db` exists and is non-empty |
| Pilot reference scripts | `benchmarks/pilot_reference/pilot_tc_*.py` (implementation artifact) |

The dataset must be readable and its `PERMANENT` mapset write-protected:

```sh
ls -ld ~/grassdata/nc_basic_spm_grass7/PERMANENT
# expect no write permission for group/other; the harness applies the guard at startup
```

## Scenario 1 — Zero-regression baseline

```sh
.venv/bin/python -m pytest -q
```

**Expected**: the 255 pre-existing tests pass, plus the new Gate 3 tests. No existing test is edited. A failure in an existing test blocks the feature.

## Scenario 2 — Validate the pilot definition

```sh
.venv/bin/python -m benchmarks.run_gate3 --validate-pilot
```

**Expected**:

```text
Pilot: benchmark_prompts_pilot10.json
Cases: 10 (tier1=5, tier2=5)
Multi-step/mixed: 4
Outputs: raster=8, vector=6
Expectations: benchmarks/pilot_expectations.json sha256:…
Dataset: nc_basic_spm_grass7  GRASS: 8.5.0
Pilot validation: OK
```

Exit `3` with a named violation if composition, output naming, assertion validity, expectations coverage, or the reference script hash is wrong.

## Scenario 3 — Derive frozen expectations

Only needed when creating or changing the pilot. The golden scripts are human-reviewed and live under `benchmarks/pilot_reference/`.

```sh
.venv/bin/python -m benchmarks.derive_pilot_expectations \
    --suite benchmarks/benchmark_prompts_pilot10.json \
    --out benchmarks/pilot_expectations.json
```

**Expected**: a file with GRASS version, dataset path, `PERMANENT` hash, reference script hashes, and per-output raster/vector values. The generator reads only the golden scripts.

**Human review gate**: inspect every expected value, confirm it matches the task semantics, then mark the file reviewed in the repository. A mismatch on re-derivation is a suite defect, not a model failure.

## Scenario 4 — Run the 10-case pilot

```sh
.venv/bin/python -m benchmarks.run_gate3 --clean
```

**Expected**: a run over `benchmark_prompts_pilot10.json` that writes `benchmarks/gate3_report.md`.

Checks after the run:

1. The main table contains exactly `Pass@Executed` and `Pass@Semantic` with cases and percentages.
2. `Pass@Semantic ≤ Pass@Executed`.
3. Semantic cases = 10; non-pilot cases, if any, are listed as semantic-not-evaluated.
4. `Accepted duplicates executed` is `0`.
5. Every semantic failure names the output, check, expected, observed, tolerance, and verdict.
6. The Gate 2 historical section shows `Pass@Healed` and the 90.0% Gate 1 baseline, separated from the Gate 3 table.
7. `PERMANENT` hash is unchanged; leaked scratch directories = 0.

## Scenario 5 — Report-only reproducibility

```sh
cp benchmarks/gate3_report.md /tmp/gate3_report.live.md
.venv/bin/python -m benchmarks.run_gate3 --report-only
diff -u /tmp/gate3_report.live.md benchmarks/gate3_report.md
```

**Expected**: no diff. The report regenerates from persisted results without model inference or GRASS.

## Scenario 6 — Prove a semantic failure is report-only

Use a single case and a stub/fixture candidate that exits 0 but writes a raster with an out-of-tolerance mean. The test suite covers this automatically; to inspect a live case:

```sh
.venv/bin/python -m benchmarks.run_gate3 -k pilot_tc_09 --no-resume
```

Then inspect `benchmarks/output_execution/pilot_tc_09/case_result.json`.

**Expected**:

- `pass_at_executed = true`
- `pass_at_semantic = false`
- the failing assertion has `expected`, `observed`, `tolerance`, and `passed=false`
- no new attempt is generated after the semantic verdict
- `budget_ledger` is unchanged after verification

## Scenario 7 — Prove tier independence

```sh
.venv/bin/python -m benchmarks.run_gate3 -k pilot_tc_33 \
    --max-static-retries 2 --max-runtime-retries 2 --no-resume
```

Force two static slips (for example by injecting a stub model in the test suite), then confirm:

- only the static ledger increases for the first two candidates;
- GRASS is launched only when a candidate passes static validation;
- the runtime ledger still has its full allowance when execution begins;
- a runtime-tier candidate that fails static validation increases the runtime ledger and does not launch GRASS.

The automated proof is `tests/test_budget_tiers.py`.

## Scenario 8 — Prove duplicate repairs are rejected

```sh
.venv/bin/python -m pytest tests/test_noop_detection.py -q
```

**Expected**: byte-identical, formatting-only, and docstring-only duplicates are rejected before execution; a changed parameter is not; a pivot prompt contains the failing tool's parameter list; a stub 40-case run records zero accepted duplicate executions.

For a live inspection, look for `"outcome": "no_op_duplicate"` and `"duplicate": true` in a `case_result.json`, with `exit_code: null` and zero-byte stdout/stderr artifacts.

## Scenario 9 — Full 40-case benchmark

```sh
.venv/bin/python -m benchmarks.run_gate3 --all --clean
```

**Expected**:

- 40 completed cases;
- `Pass@Executed` over all 40;
- `Pass@Semantic` over the 10 semantic cases only, with the denominator printed;
- zero accepted duplicate executions;
- a separate Gate 2 historical section with `Pass@1` and `Pass@Healed`;
- no crash, every case terminal, `PERMANENT` unchanged, no leaked scratch directories.

This is the longest scenario (40 cases, local model, live GRASS). Run it only after the pilot and unit tests pass.

## Scenario 10 — Gate 2 compatibility

```sh
.venv/bin/python benchmarks/run_gate2.py --report-only
.venv/bin/python -m pytest tests/test_cli_contract.py tests/test_reporting.py -q
```

**Expected**: the Gate 2 report still renders with its original wording, and the CLI contract tests pass unchanged. `run_gate2` without the new flags behaves exactly as before.

## Interpreting results

| Observation | Meaning |
|---|---|
| `Pass@Executed` high, `Pass@Semantic` low | Scripts run but produce wrong or incomplete geospatial results; the oracle is doing its job |
| `Pass@Semantic` = `Pass@Executed` | No semantic failures in the evaluated subset |
| `Accepted duplicates executed > 0` | Feature defect; block the release |
| Static used > 0 but runtime used = 0 | Candidates failed pre-execution; GRASS was never launched for those attempts |
| Runtime used > 0 with static used = 0 | Normal runtime healing path |
| Semantic not evaluated = 30 in a 40-case run | Expected: only the 10 pilot cases declare assertions |
| A reference mismatch before inference | Suite defect: fix the golden script or expectations, do not blame the model |

## Troubleshooting

| Symptom | Check |
|---|---|
| `exit 3` naming GRASS | `grass --version`; `grass --help` includes `--tmp-mapset` |
| `exit 3` naming the dataset | `--dataset` or `GRASS_DATASET_PROJECT`; `PERMANENT/DEFAULT_WIND` and `PROJ_INFO` exist |
| `exit 3` naming Ollama | `ollama serve`; model names match `--model` |
| `exit 3` naming expectations | Run Scenario 3; confirm every pilot output is covered |
| Semantic query timeout | Inspect `attempt_N.semantic.json`; raise `semantic_query_timeout_s` only with evidence |
| Slope case times out | The NC elevation slope takes ~57 s on this host; confirm `--timeout` is at least 120 and the host is not loaded |
| `v.info -c` fails on a buffer output | Expected: `v.buffer` creates no attribute table. Remove the column assertion |
| `r.viewshed` range is not 0–1 | The prompt/golden script omitted the binary visibility flag `-b` |
| Duplicate never detected | Confirm both digests are recorded and the initial candidate is seeded into the index |
| Report shows `Pass@Semantic` over all cases | Denominator bug; it must use `semantic_evaluated` only |
| `PERMANENT` changed | Stop and investigate; the read-only guard or a probe performed a write |
