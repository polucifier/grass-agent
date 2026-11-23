# Feature 004 — GPU Pilot Ablation (14B and 32B)

**Date**: 2026-11-23
**Branch**: `004-manual-grounded-planning` @ `c575e3a`
**Host**: `lincalc-04.fsv.cvut.cz` (`radchenko`), Tesla V100-PCIE-32GB (32 GiB)
**Runtime**: Docker image `grass-agent-tests:latest` (GRASS 8.5.0), host network
**Serving**: isolated `ollama-feature004` container on `127.0.0.1:11435`,
`OLLAMA_CONTEXT_LENGTH=8192`, models `qwen2.5-coder:14b` (9.0 GB) and
`qwen2.5-coder:32b` (19 GB)
**Pilot**: `benchmarks/benchmark_prompts_pilot10.json` (10 cases), one run per mode/model
**Harness**: `--num-ctx 8192`, `--dataset /grassdata/nc_basic_spm_grass7`

## GPU safety

The shared V100 was checked with `nvidia-smi` and
`nvidia-smi --query-compute-apps` **before every inference run** and again
before each model switch. Every check showed:

```text
0 %, 32768 MiB total, 1 MiB used, 32495 MiB free
(no compute processes)
```

No non-Ollama processes were present. Models were explicitly unloaded between
runs (`ollama stop`), and no run started while the GPU was busy.

## Dataset identity note

The frozen expectations recorded `/home/rhea/grassdata/nc_basic_spm_grass7`
and `PERMANENT` hash `7ee9…`. That path/copy does not exist on this host. The
container dataset is `/grassdata/nc_basic_spm_grass7`, hash `d6bb…`.

Before any model run, all ten reference scripts were executed against the
container dataset and **all 10/10 passed their semantic assertions**, proving
the data content matches the frozen expectations. The remote expectations
identity was therefore updated to the container path/hash; the assertion
values were not changed. A copy is committed at
`benchmarks/pilot_expectations_gpu.json` (sha256
`c6206ae806aab01d47b27318637a49397dcf54d4cd7edfc74a76d51584843810`).
The local frozen expectations remain unchanged.

## Unified ablation

### 14B

Source: [`feature004_ablation_14b.md`](feature004_ablation_14b.md)

| Pipeline | Cases | Pass@Executed | Pass@Semantic | Plan repairs | Plan fallbacks | Replans | Shortfalls | Tool swaps | P95 latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `legacy` | 10 | 8/10 = 80.0% | 7/10 = 70.0% | — | — | — | — | 0 | 60.4s |
| `manual-kb` | 10 | 8/10 = 80.0% | 8/10 = 80.0% | — | — | — | 0 | 0 | 68.8s |
| `planned` | 10 | 9/10 = 90.0% | 8/10 = 80.0% | 6 | 5 | 0 | 0 | 0 | 66.3s |

### 32B

Source: [`feature004_ablation_32b.md`](feature004_ablation_32b.md)

| Pipeline | Cases | Pass@Executed | Pass@Semantic | Plan repairs | Plan fallbacks | Replans | Shortfalls | Tool swaps | P95 latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `legacy` | 10 | 8/10 = 80.0% | 7/10 = 70.0% | — | — | — | — | 0 | 75.6s |
| `manual-kb` | 10 | 9/10 = 90.0% | 8/10 = 80.0% | — | — | — | 0 | 0 | 82.4s |
| `planned` | 10 | 8/10 = 80.0% | 8/10 = 80.0% | 5 | 5 | 0 | 0 | 0 | 128.1s |

Rows are not pooled: each mode keeps its own case set and semantic denominator.

## The three documented failure cases

| Case | 14B legacy | 14B manual-kb | 14B planned | 32B legacy | 32B manual-kb | 32B planned |
|---|---|---|---|---|---|---|
| `pilot_tc_08` | exec ✅ / sem ❌ | exec ✅ / sem ✅ | exec ✅ / sem ✅ | exec ✅ / sem ❌ | exec ✅ / sem ✅ | exec ✅ / sem ✅ |
| `pilot_tc_14` | unhealed ❌ | exec ✅ / sem ✅ (`v.clean`) | exec ✅ / sem ❌ (`v.clean`) | unhealed ❌ | exec ✅ / sem ❌ (`v.clean`) | exec ✅ / sem ✅ (`v.clean`) |
| `pilot_tc_32` | unhealed ❌ | unhealed ❌ (`r.reclass` with inline rules) | clean fallback; unhealed ❌ | unhealed ❌ | unhealed ❌ (`r.reclass` with inline rules) | clean fallback; unhealed ❌ |

- **`pilot_tc_08`**: resolved semantically by both new modes at both model
  sizes (binary viewshed flags), versus a stable legacy semantic failure.
- **`pilot_tc_14`**: always executed with the acceptable tool `v.clean`
  (`benchmarks/pilot_tool_sets.json`). 14B manual-kb and 32B planned also pass
  semantically; the other new-mode combinations execute but fail the declared
  assertions.
- **`pilot_tc_32`**: still unresolved. The synthesizer emits `r.reclass` with
  inline rule text (`rules="- ..."`), which GRASS rejects with
  `Cannot open rules file`. Planned mode detects the invalid plan/fallback
  cleanly, but the fallback candidate repeats the same inline-rules mistake.

## Success-criterion verdicts

| Criterion | Result |
|---|---|
| SC-003 (`tc_08` semantic; `tc_14` exit 0 + acceptable tool; `tc_32` rules file/stream or `r.recode`/`r.mapcalc`) | **Partially met**: `tc_08` and `tc_14` pass in the new modes; `tc_32` does not (inline rules rejected) |
| SC-004 (≥9/10 semantic in at least two 32B runs per mode, never below 7/10) | **Not met**: both 32B new modes scored 8/10, above the 7/10 floor but below 9/10 |
| SC-005 (cards within budget, no truncation) | Met: 0 manual-budget failures, 0 overflows |
| SC-007 (valid plan or clean fallback; no hallucinated tools) | Met: 32B planned had 5 plan repairs / 5 clean fallbacks; 14B planned had 6 / 5; no tool outside shortlist/KB executed |
| SC-010 (P95 ≤ 2× matched legacy; no overflow) | Met: 32B manual 1.09×, planned 1.69×; 14B manual 1.14×, planned 1.10×; 0 overflows |
| Integrity | `PERMANENT` unchanged in every run; 0 leaked scratch dirs; 0 accepted duplicates |

## Evidence directories

- `benchmarks/pilot_evidence_14b_manual_kb/`
- `benchmarks/pilot_evidence_14b_planned/`
- `benchmarks/pilot_evidence_32b_legacy/` (fresh matched baseline; complete 10 cases)
- `benchmarks/pilot_evidence_32b_manual_kb/`
- `benchmarks/pilot_evidence_32b_planned/`

Each contains `run_summary.json`, one directory per case with
`case_result.json`, final/per-attempt scripts and captures, plus the harness
`gate3_report.md`.
