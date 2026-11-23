# Gate 3 pilot evidence (2026-11-11, remote GPU re-run)

This directory preserves the per-case artifacts of the 10-case semantic pilot
(`benchmarks/benchmark_prompts_pilot10.json`). The original 2026-11-10 evidence
lived under `/tmp/opencode/pilot_evidence/` and was lost when the temporary
directory was cleaned; this re-run replaces it in a durable, in-repo location.

## Provenance

| Item | Value |
|---|---|
| Host | `lincalc-04.fsv.cvut.cz` (`radchenko`), Debian 13, 36 cores, 188 GiB RAM |
| GPU | Tesla V100-PCIE-32GB (32 GiB) |
| Runtime | Docker image `grass-agent-tests:1.0` (GRASS 8.5.0, Python 3.14) |
| Model | `qwen2.5-coder:7b` served by `ollama/ollama` in Docker with `--gpus all` |
| Embeddings | `nomic-embed-text` (knowledge-base RAG) |
| Dataset | `nc_basic_spm_grass7`, mounted at `/home/rhea/grassdata/nc_basic_spm_grass7` |
| Date | 2026-11-11 |
| Wall clock | 4.3 min |

Command run inside the container:

```bash
python -m benchmarks.run_gate3 --clean \
  --model qwen2.5-coder:7b \
  --dataset /home/rhea/grassdata/nc_basic_spm_grass7
```

Before the run, `--validate-pilot` passed: 10 cases, GRASS 8.5.0, expectations
sha256 `550a956c298ab9c76a36ce62dfd439ace0fef8feab6a0a4ad449b9f5f76403c4`.
The image's dataset copy was missing six empty `sqlite.db` placeholder files;
recreating them made the `PERMANENT` content hash match the frozen expectation
exactly (`7ee9b49d11264d9497dd28358260dd5a7dccf719f2dbbc9a6c4d2b7fcd56630e`),
and it was unchanged after the run.

## Results

| Metric | Value |
|---|---|
| Cases completed | 10/10 |
| Pass@Executed | 7/10 = 70.0% |
| Pass@Semantic | 6/10 = 60.0% |
| Execution→semantic gap | 10.0 pp |
| Static tier | 2 used of 20 |
| Runtime tier | 6 used of 14 remaining |
| Accepted duplicate repairs | 0 |
| `PERMANENT` changed | no |
| Leaked scratch mapsets | none |

The only semantic failure is `pilot_tc_08` (non-binary viewshed: observed
89.79–180.0 instead of 0–1, mean 94.81 vs 0.027). Execution failures:
`pilot_tc_14` (schema misuse), `pilot_tc_32` and `pilot_tc_33` (general
exception), each exhausting repair attempts.

Model sampling is not seeded, so the executed count differs slightly from the
2026-11-10 local run (8/10 executed, 6/10 semantic, same `pilot_tc_08` semantic
failure). The semantic result is stable across both runs.

## Contents

- `gate3_report.md` — report written by the harness.
- `output_execution/` — `run_summary.json` plus one directory per case with
  `case_result.json`, final script, per-attempt scripts, stdout/stderr and logs.
- `run.log` — full console transcript.

Integrity: `gate3_report.md` sha256
`6b2a3b132720459a907473a80d5496b3faa6ad1569e40684022ca4814d5ab3d7`.
Regenerating it locally with `--report-only` produced a byte-identical file.
