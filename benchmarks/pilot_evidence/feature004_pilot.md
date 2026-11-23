# Feature 004 Pilot Evidence

**Date**: 2026-11-23
**Branch**: `004-manual-grounded-planning` @ `c575e3a`
**Host**: Tesla V100-PCIE-32GB, `lincalc-04.fsv.cvut.cz`
**Runtime**: `grass-agent-tests:latest` (GRASS 8.5.0), isolated Ollama on `:11435`
**Context**: 8192 (`OLLAMA_CONTEXT_LENGTH=8192`, `--num-ctx 8192`)
**Dataset**: `/grassdata/nc_basic_spm_grass7` (content verified 10/10 against
the frozen reference scripts)

Full ablation, integrity and per-case evidence:
[`../feature004_pilot_report.md`](../feature004_pilot_report.md). Raw tables:
[`../feature004_ablation_14b.md`](../feature004_ablation_14b.md) and
[`../feature004_ablation_32b.md`](../feature004_ablation_32b.md).

## GPU results (one 10-case pilot run per mode/model)

| Model | Mode | Pass@Executed | Pass@Semantic | P95 | Plan repairs | Fallbacks |
|---|---|---|---:|---:|---:|---:|---:|
| 14B | legacy | 8/10 | 7/10 | 60.4s | — | — |
| 14B | manual-kb | 8/10 | 8/10 | 68.8s | — | — |
| 14B | planned | 9/10 | 8/10 | 66.3s | 6 | 5 |
| 32B | legacy | 8/10 | 7/10 | 75.6s | — | — |
| 32B | manual-kb | 9/10 | 8/10 | 82.4s | — | — |
| 32B | planned | 8/10 | 8/10 | 128.1s | 5 | 5 |

- `pilot_tc_08` passes semantically in both new modes at both sizes.
- `pilot_tc_14` always executes with the acceptable `v.clean` tool; it passes
  semantically in 14B manual-kb and 32B planned.
- `pilot_tc_32` remains unresolved: the synthesized script passes inline rule
  text to `r.reclass`, and GRASS rejects it with `Cannot open rules file`.
  Planned mode falls back cleanly, but the fallback repeats the mistake.
- SC-004 is not met: both 32B new modes scored 8/10 semantic, above the 7/10
  floor but below the required 9/10.
- Integrity: `PERMANENT` unchanged in every run, 0 leaked scratch dirs,
  0 accepted duplicate executions, 0 context overflows, 0 manual-budget
  failures.

## GPU safety log

`nvidia-smi` and `nvidia-smi --query-compute-apps` were run before every model
load and between every run. All checks: `0–2%` utilization, `1 MiB` used,
`32495 MiB` free, no non-Ollama compute processes. Models were unloaded between
runs; no run started while another user's job was active.

## Host dataset identity

The frozen expectations path/hash (`/home/rhea/…`, `7ee9…`) does not exist on
this host. All 10 reference scripts passed semantically on the container dataset
(`/grassdata/…`, `d6bb…`), so only the environment identity was overridden.
The GPU identity file is committed at
`benchmarks/pilot_expectations_gpu.json`; the local frozen file is unchanged.

## Historical 3B substitute (2026-11-19, local host)

Before the GPU was available, a 3B substitute smoke was recorded:

- manual-kb, 3 cases: Pass@Executed 0/3, Pass@Semantic 0/3 (3B emitted invalid
  Python, then repeated it).
- planned, 2 cases: shortlist/plan/cards worked; final 3B code was statically
  invalid.
- Matched 3B latency evidence (case-level P95 1.00×) is in
  `benchmarks/gate3_report.md`.

These 3B numbers are not part of SC-003/SC-004 and are retained only as a
historical local smoke.
