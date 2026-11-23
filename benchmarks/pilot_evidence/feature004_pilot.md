# Feature 004 Pilot Evidence

**Date**: 2026-11-19
**Host**: local Linux, GRASS 8.5.0, dataset `nc_basic_spm_grass7`
**Knowledge base**: `data/grass_knowledge.db`, schema `2`, 541 module records, built offline

## Environment limitation (blocks the strongest-configuration run)

The approved benchmark stack names `qwen2.5-coder:14b` and `qwen2.5-coder:32b`, but
this host only has the following local Ollama models:

```text
qwen2.5-coder:7b
qwen2.5-coder:3b
nomic-embed-text:latest
```

No network pull was attempted (Feature 004 is offline). Consequently tasks
T050, T053, and T054 cannot be executed at 32B on this host. The runs below are
**3B substitute smoke evidence** and must not be read as the SC-004 comparison.

## Manual-kb substitute smoke (3B)

Command:

```sh
.venv/bin/python -m benchmarks.run_gate3 --clean --pipeline manual-kb \
  --model qwen2.5-coder:3b --num-ctx 8192 \
  -k pilot_tc_08,pilot_tc_14,pilot_tc_32 \
  --report-path benchmarks/pilot_manual_kb_report.md
```

Observed (8.6 min):

| Case | Verdict | Notes |
|---|---|---|
| `pilot_tc_08` | ❌ unhealed | 3B emitted invalid Python (`tools.g_region(raster=..., -p)`), then repeated it |
| `pilot_tc_14` | ❌ unhealed | Static syntax failure, then 3B repeated the same candidate (no-op detector rejected it) |
| `pilot_tc_32` | ❌ unhealed | Executed but failed; cards rendered `r.slope.aspect` (1204 tok), `r.reclass` (275), `v.to.db` (561), `r.to.vect` (515), `r.import` (1015) |

Pass@Executed 0/3, Pass@Semantic 0/3. Manual-card diagnostics and no-op
detection worked; model quality at 3B was the limiting factor.

## Planned substitute smoke (3B)

Command:

```sh
.venv/bin/python -m benchmarks.run_gate3 --clean --pipeline planned \
  --model qwen2.5-coder:3b --num-ctx 8192 \
  -k pilot_tc_32,pilot_tc_33 \
  --report-path benchmarks/pilot_planned_report.md
```

Observed (5.4 min):

- `pilot_tc_32`: planner produced a plan; cards were rendered; final code was
  statically invalid and repeated on repair.
- `pilot_tc_33`: shortlist had 12 modules (`v.distance`, `v.surf.rst`,
  `r.grow.distance`, `r.import`, `v.to.rast`, ...); a valid 2-step plan was
  produced; cards `v.to.rast` (591 tok) and `r.grow.distance` (460 tok); the
  synthesized code failed static validation on all three candidates.

Pass@Executed 0/2, Pass@Semantic 0/2. Shortlist, plan, per-step cards, and
repair-budget behavior are evidenced; final synthesis quality at 3B is not.

## What remains unverified at the required configuration

- SC-003 per-case semantic outcomes at 32B.
- SC-004 ≥9/10 in at least two of three pilot runs, never below 7/10.
- P95 wall-clock within 2× a matched 32B legacy baseline.
- Three-seed manual-kb and planned pilots.
- Planned multi-step pilot set and 40-case suite at 32B.

These require provisioning `qwen2.5-coder:14b` and `qwen2.5-coder:32b` locally.
