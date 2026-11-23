# Gate 3 pilot evidence — qwen2.5-coder:32b (2026-11-11, remote GPU)

Per-case artifacts of the 10-case semantic pilot
(`benchmarks/benchmark_prompts_pilot10.json`) with `qwen2.5-coder:32b`.
Companions: `benchmarks/pilot_evidence/` (7b) and
`benchmarks/pilot_evidence_14b/` (14b).

## Provenance

| Item | Value |
|---|---|
| Host | `lincalc-04.fsv.cvut.cz` (`radchenko`), Debian 13, 36 cores, 188 GiB RAM |
| GPU | Tesla V100-PCIE-32GB (32 GiB) |
| Runtime | Docker image `grass-agent-tests:1.0` (GRASS 8.5.0, Python 3.14) |
| Model | `qwen2.5-coder:32b` (Q4_K_M, 19 GB) served by `ollama/ollama` with `--gpus all` |
| Context | `OLLAMA_CONTEXT_LENGTH=8192` (20.5 GiB VRAM; the default 32K would need ~28 GiB) |
| Embeddings | `nomic-embed-text` (knowledge-base RAG) |
| Dataset | `nc_basic_spm_grass7`, mounted at `/home/rhea/grassdata/nc_basic_spm_grass7` |
| Measured speed | 31.0 tok/s generation, 190.6 tok/s prompt eval (short prompt) |
| Date | 2026-11-11 |
| Wall clock | 4.9 min (model pre-warmed; load took 11.3 s from page cache) |

Command run inside the container:

```bash
GRASS_OUTPUT_EXEC_DIR=benchmarks/output_execution_32b \
python -m benchmarks.run_gate3 --clean \
  --model qwen2.5-coder:32b \
  --dataset /home/rhea/grassdata/nc_basic_spm_grass7 \
  --report-path benchmarks/pilot_32b_report.md
```

`--validate-pilot` passed before the 7b/14b runs (10 cases, GRASS 8.5.0,
expectations sha256 `550a956c298ab9c76a36ce62dfd439ace0fef8feab6a0a4ad449b9f5f76403c4`).
`PERMANENT` was `7ee9b49d11264d9497dd28358260dd5a7dccf719f2dbbc9a6c4d2b7fcd56630e`
before and after the run.

## Results

| Metric | Value |
|---|---|
| Cases completed | 10/10 |
| Pass@Executed | 8/10 = 80.0% |
| Pass@Semantic | 7/10 = 70.0% |
| Execution→semantic gap | 10.0 pp |
| Pass@1 | 7/10 = 70.0% |
| Pass@Healed | 8/10 = 80.0% |
| Static tier | 1 used of 20 |
| Runtime tier | 4 used; 2 cases exhausted |
| Duplicate candidates / accepted | 1 / 0 |
| `PERMANENT` changed | no |
| Leaked scratch mapsets | none |

`pilot_tc_08` is again the only semantic failure (non-binary viewshed: observed
89.79–180.0 instead of 0–1, mean 94.81 vs 0.027). `pilot_tc_14` (schema misuse)
and `pilot_tc_32` (general exception) remained unhealed; `pilot_tc_06` needed one
runtime repair.

## Comparison across models (same host and dataset, 2026-11-11)

| Model | Wall | Pass@Executed | Pass@Semantic | Pass@1 | Semantic failures |
|---|---|---|---|---|---|
| `qwen2.5-coder:7b` | 4.3 min | 7/10 (70.0%) | 6/10 (60.0%) | 5/10 | `pilot_tc_08` |
| `qwen2.5-coder:14b` | 4.3 min | 8/10 (80.0%) | 7/10 (70.0%) | 6/10 | `pilot_tc_08` |
| `qwen2.5-coder:32b` | 4.9 min | 8/10 (80.0%) | 7/10 (70.0%) | 7/10 | `pilot_tc_08` |

The 32b model matched 14b on executed/semantic pass rates and needed one fewer
repair, at a cost of ~0.6 min. Sampling is unseeded, so single-run differences
of one case are not significant. The `pilot_tc_08` semantic defect is stable
across all runs (including the 2026-11-10 local 7b run).

## Contents

- `gate3_report.md` — report written by the harness.
- `output_execution/` — `run_summary.json` plus one directory per case with
  `case_result.json`, final script, per-attempt scripts, stdout/stderr and logs.
- `run.log` — full console transcript.

Integrity: `gate3_report.md` sha256
`a6c43f31a633068ccdd2ad6a363b871343648b69247dbc37507b0c7f27ae227c`.
Regenerating it locally with `--report-only` produced a byte-identical file.
