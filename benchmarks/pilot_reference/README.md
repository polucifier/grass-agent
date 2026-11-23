# Pilot reference scripts

> **These are human-reviewed golden scripts, not model output.**

Each `pilot_tc_*.py` file is an independently authored, human-reviewed reference
implementation of one case in `benchmarks/benchmark_prompts_pilot10.json`. They
exist for exactly one purpose: to measure frozen expected values for the Gate 3
semantic oracle.

## The only consumer

`benchmarks/derive_pilot_expectations.py` is the **only** program allowed to
execute these scripts. It runs each one in a disposable
`grass --tmp-mapset` session, queries the produced maps read-only
(`r.univar -g -r`, `v.info -t`, `v.info -c`), and writes
`benchmarks/pilot_expectations.json`.

## Candidate artifacts are never a value source

The generator refuses to read `attempt_*.py`, `final.py`, or any other artifact
under `benchmarks/output_execution/`. A semantic oracle tuned on candidate output
measures nothing; expected values must come from an independent reference
execution (FR-007d).

## Authorship rules

- Use the modern `grass.tools` interface exclusively.
- Produce exactly the outputs declared by the pilot case, with the declared
  names and types.
- State required semantics explicitly: `pilot_tc_08` must use `r.viewshed -b`
  for binary visibility; `pilot_tc_32` must reclassify slopes strictly greater
  than 15 degrees.
- Do not change the computational region; pilot prompts require the default
  region.
- Do not assert attribute columns on `v.buffer` outputs — buffers have no
  attribute table.
- Raster expectations are measured with `r.univar -g -r`, over each map's own
  region, so a candidate's `g.region` call cannot move the reference target.
