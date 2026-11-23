# Gate 3 pilot evidence — qwen2.5-coder:14b (2026-11-11, remote GPU)

Per-case artifacts of the 10-case semantic pilot
(`benchmarks/benchmark_prompts_pilot10.json`) with `qwen2.5-coder:14b`.
Companion to `benchmarks/pilot_evidence/`, which holds the `7b` run.

## Provenance

| Item | Value |
|---|---|
| Host | `lincalc-04.fsv.cvut.cz` (`radchenko`), Debian 13, 36 cores, 188 GiB RAM |
| GPU | Tesla V100-PCIE-32GB (32 GiB) |
| Runtime | Docker image `grass-agent-tests:1.0` (GRASS 8.5.0, Python 3.14) |
| Model | `qwen2.5-coder:14b` served by `ollama/ollama` in Docker with `--gpus all` |
| Embeddings | `nomic-embed-text` (knowledge-base RAG) |
| Dataset | `nc_basic_spm_grass7`, mounted at `/home/rhea/grassdata/nc_basic_spm_grass7` |
| Date | 2026-11-11 |
| Wall clock | 4.3 min |

Command run inside the container:

```bash
GRASS_OUTPUT_EXEC_DIR=benchmarks/output_execution_14b \
python -m benchmarks.run_gate3 --clean \
  --model qwen2.5-coder:14b \
  --dataset /home/rhea/grassdata/nc_basic_spm_grass7 \
  --report-path benchmarks/pilot_14b_report.md
```

`--validate-pilot` passed before the run (10 cases, GRASS 8.5.0, expectations
sha256 `550a956c298ab9c76a36ce62dfd439ace0fef8feab6a0a4ad449b9f5f76403c4`).
`PERMANENT` was `7ee9b49d11264d9497dd28358260dd5a7dccf719f2dbbc9a6c4d2b7fcd56630e`
before and after the run.

## Results

| Metric | Value |
|---|---|
| Cases completed | 10/10 |
| Pass@Executed | 8/10 = 80.0% |
| Pass@Semantic | 7/10 = 70.0% |
| Execution→semantic gap | 10.0 pp |
| Pass@1 | 6/10 = 60.0% |
| Pass@Healed | 8/10 = 80.0% |
| Static tier | 1 used of 20 |
| Runtime tier | 5 used; 2 cases exhausted |
| Duplicate candidates / accepted | 2 / 0 |
| `PERMANENT` changed | no |
| Leaked scratch mapsets | none |

Only `pilot_tc_08` fails semantically (non-binary viewshed: observed
89.79–180.0 instead of 0–1, mean 94.81 vs 0.027) — the same defect seen with
both smaller models. `pilot_tc_33` was healed at runtime (general exception →
semantic pass on attempt 2). `pilot_tc_14` and `pilot_tc_32` remained unhealed
after exhausting the runtime tier.

## Comparison with `qwen2.5-coder:7b` (same host, same day)

| Model | Pass@Executed | Pass@Semantic | Semantic failures |
|---|---|---|---|
| `qwen2.5-coder:7b` | 7/10 (70.0%) | 6/10 (60.0%) | `pilot_tc_08` |
| `qwen2.5-coder:14b` | 8/10 (80.0%) | 7/10 (70.0%) | `pilot_tc_08` |

Sampling is unseeded, so individual outcomes vary; the `pilot_tc_08` semantic
failure is stable across all three pilot runs (including the 2026-11-10 local
run with `7b`, 8/10 executed).

## Contents

- `gate3_report.md` — report written by the harness.
- `output_execution/` — `run_summary.json` plus one directory per case with
  `case_result.json`, final script, per-attempt scripts, stdout/stderr and logs.
- `run.log` — full console transcript.

Integrity: `gate3_report.md` sha256
`dddcf17240e45a2906c94732c4b7997e572f8ce40db397b0680a5923fcb9e61f`.
Regenerating it locally with `--report-only` produced a byte-identical file.
