# Contract: 10-Case Semantic Pilot Suite

**Date**: 2026-11-10 | **Plan**: [../plan.md](../plan.md) | **Data model**: [../data-model.md](../data-model.md) | **Probe**: [semantic-result.md](./semantic-result.md)

Normative contract for `benchmarks/benchmark_prompts_pilot10.json` and its companion `benchmarks/pilot_expectations.json`. The pilot is the only suite that declares geospatial assertions; non-pilot cases are reported as semantic-not-evaluated.

## Suite file

```jsonc
{
  "version": "1.0.0",
  "name": "gate3-semantic-pilot",
  "tier": "pilot",
  "description": "Deterministic, output-producing tasks with independent geospatial assertions.",
  "target_dataset": "nc_basic_spm_grass7",
  "test_cases": [
    {
      "id": "pilot_tc_05",
      "source_id": "tc_05",
      "source_suite": "tier1",
      "tier": 1,
      "category": "multi_step",
      "prompt": "Compute the slope of the elevation raster and generate 10-meter contour lines from the elevation raster. Write the slope to the raster map pilot_slope and the contours to the vector map pilot_contours. Do not change the computational region.",
      "expected_tools": ["r.slope.aspect", "r.contour"],
      "auxiliary_inputs": [],
      "outputs": [
        {"name": "pilot_slope", "type": "raster"},
        {"name": "pilot_contours", "type": "vector", "geometry": "line"}
      ],
      "assertions": [
        {"output": "pilot_slope", "check": "non_null_count", "min": 1},
        {"output": "pilot_slope", "check": "value_range", "min_value": 0, "max": 90},
        {"output": "pilot_slope", "check": "mean", "tolerance": 0.01, "expected_source": "reference"},
        {"output": "pilot_contours", "check": "feature_count", "min": 1},
        {"output": "pilot_contours", "check": "geometry_type", "expected": "line"},
        {"output": "pilot_contours", "check": "required_columns", "columns": ["cat", "level"]}
      ]
    }
  ]
}
```

### Case fields

| Field | Required | Rule |
|---|---|---|
| `id` | yes | `pilot_<source_id>`; unique |
| `source_id` | yes | Existing benchmark case id |
| `source_suite` | yes | `tier1` or `tier2` |
| `tier` | yes | Must agree with `source_suite` |
| `category` | yes | Must agree with the source case |
| `prompt` | yes | Names every output and its type; ends with "Do not change the computational region." |
| `expected_tools` | yes | Informational; never used for a verdict |
| `auxiliary_inputs` | yes | `[]` for every pilot case |
| `outputs` | yes | Non-empty, unique names, each with `type` |
| `assertions` | yes | Non-empty; each references a declared output |

## Composition requirements

- Exactly 10 cases.
- At least 4 from Tier 1 and at least 4 from Tier 2. The selected set is 5/5.
- At least one raster output and one vector output.
- At least 2 multi-step or mixed raster/vector cases. The selected set has 4.
- Every output name begins with `pilot_` and appears verbatim in the prompt.
- Every case is deterministic and produces at least one persistent map. Display-only, statistics-only, and export-only cases are excluded.

## Selected cases

Planning verification measured the actual dataset. Values shown are evidence of feasibility, not frozen expectations; `derive_pilot_expectations.py` re-measures them from the golden scripts.

| ID | Source | Tier | Outputs | Assertions | Verified note |
|---|---|---|---|---|---|
| `pilot_tc_01` | `tc_01` | 1 | `pilot_streams_buffer` (vector) | feature count ≥ 1; geometry `area` | 200 m `v.buffer` on `streams`; buffer output has no attribute table, so no column check |
| `pilot_tc_05` | `tc_05` | 1 | `pilot_slope` (raster), `pilot_contours` (vector) | slope non-null ≥ 1, range 0–90, mean ±1%; contours count ≥ 1, geometry `line`, columns `cat`,`level` | `r.slope.aspect` ~57 s; `r.contour` produces `cat` and `level` |
| `pilot_tc_06` | `tc_06` | 1 | `pilot_streams_buffer_100m` (vector), `pilot_streams_buffer_raster` (raster) | vector count ≥ 1, geometry `area`; raster non-null ≥ 1 | 100 m buffer ~53 s; `v.to.rast` output all non-null 1s |
| `pilot_tc_08` | `tc_08` | 1 | `pilot_viewshed` (raster) | non-null ≥ 1, range 0–1, mean ±5% | prompt requires binary visibility; golden uses `r.viewshed -b`; verified n=810, 22 visible; a one-cell change is ~4.5% of the mean, so this case declares 5% rather than the 1% default |
| `pilot_tc_09` | `tc_09` | 1 | `pilot_elevation_double` (raster) | non-null ≥ 1, range from reference (≈115–305), mean ±1% | `r.mapcalc` output at default region; verified mean ≈ 220.976, exactly 2× the default-region elevation mean |
| `pilot_tc_12` | `tc_12` | 2 | `pilot_relief` (raster) | non-null ≥ 1, range 0–255, mean ±1% | `r.relief`; verified n=700, min 175, max 184 |
| `pilot_tc_14` | `tc_14` | 2 | `pilot_roads_clean` (vector) | count ≥ 1, geometry `line`, columns `cat`,`ROAD_NAME` | `v.clean` preserves the road table; verified 361 lines |
| `pilot_tc_18` | `tc_18` | 2 | `pilot_geology_dissolved` (vector) | count ≥ 1, geometry `area`, columns `cat`,`GEO_NAME` | prompt adapted from parcels/zoning to the available geology/GEO_NAME layer; verified 1830 areas |
| `pilot_tc_32` | `tc_32` | 2 | `pilot_steep_slope` (raster), `pilot_steep` (vector) | slope non-null ≥ 1, mean ±1%; steep count ≥ 1, geometry `area`, column `cat` | slope → reclass >15° → `r.to.vect type=area`; mixed raster/vector |
| `pilot_tc_33` | `tc_33` | 2 | `pilot_hospitals_raster` (raster), `pilot_distance` (raster) | both non-null ≥ 1; distance range min 0; mean ±1% | `v.to.rast` + `r.grow.distance`; verified distance mean ≈ 40470, min 0 |

### Prompt rules

1. Name every output and its type: `... write the slope to the raster map pilot_slope ...`.
2. State the required semantics that the assertions depend on, e.g. "binary visibility (1 visible, 0 not visible)" or "reclassify slopes greater than 15 degrees".
3. End with `Do not change the computational region.` so the reference and candidate share the default region.
4. Do not reveal expected numeric values; assertions are not part of the prompt.
5. Do not mention the oracle or its tolerances.

### Verified pilot hazards

- `v.buffer` creates a vector map with **no attribute table**. `v.info -c` exits 1. Do not assert `cat` on a buffer output.
- `r.viewshed` without `-b` writes elevation-difference values, not 0/1. The prompt must ask for binary visibility and the golden script must use `-b`.
- `r.contour` reports `map3d=1`; geometry is still `line` and must be classified from the line counter, not from `map3d`.
- A slope run over the full elevation raster takes ~57 s. The 120 s per-attempt bound leaves limited headroom; the report records latency so a run that kills correct slope work is visible.
- `r.univar -r` on a slope map produced at the 10 m region can take ~7 s. Query timeout is 30 s.

## Expectations file

```jsonc
{
  "version": "1.0.0",
  "generated_at": "2026-11-10T12:00:00Z",
  "generator": "benchmarks/derive_pilot_expectations.py",
  "grass_version": "8.5.0",
  "dataset": {
    "project": "/home/user/grassdata/nc_basic_spm_grass7",
    "permanent_hash": "f5290457…"
  },
  "cases": {
    "pilot_tc_05": {
      "reference_script": "benchmarks/pilot_reference/pilot_tc_05.py",
      "reference_script_sha256": "…",
      "outputs": {
        "pilot_slope": {"type": "raster", "n": 2019304, "min": 0.0, "max": 38.689, "mean": 3.8645},
        "pilot_contours": {"type": "vector", "geometry": "line", "feature_count": 122, "columns": ["cat", "level"]}
      }
    }
  }
}
```

### Authority and review rules

- The generator runs only scripts under `benchmarks/pilot_reference/`.
- It MUST refuse to read `benchmark_prompts_pilot10.json` candidates, `attempt_*.py`, or `final.py` as value sources.
- A human reviews the generated file before the first pilot benchmark run. The reviewed SHA-256 is recorded in `run_summary.json`.
- A reference mismatch on re-derivation is a suite defect: exit `3` before inference.
- The file records GRASS version, dataset path, and `PERMANENT` hash so drift is attributable.

### Tolerances

| Check | Default | Override |
|---|---|---|
| `non_null_count` | min 1 | per assertion |
| `value_range` | reference min/max | per assertion |
| `mean` | relative 0.01 | per assertion |
| `feature_count` | min 1 | per assertion |
| `geometry_type` | exact | not overridable |
| `required_columns` | exact, case-sensitive | not overridable |

## Validation

`--validate-pilot` MUST fail with exit `3` when any of the following holds:

1. The suite is not exactly 10 cases.
2. Fewer than 4 cases come from either benchmark tier.
3. Fewer than 2 cases are multi-step or mixed raster/vector.
4. A case declares no output or no assertion.
5. An assertion names an undeclared output.
6. An output name is absent from the prompt or does not start with `pilot_`.
7. An assertion has an unknown `check` or an invalid value for its check.
8. The expectations file is missing, unparseable, or lacks a declared output.
9. The recorded reference script hash does not match the file.
10. The dataset identity or GRASS version differs from the recorded reference environment.

A passing validation prints: case count, tier split, multi-step count, raster/vector counts, expectation hash, and GRASS/dataset identity.

## Verdict effect

- `Pass@Executed` is evaluated for all 10 pilot cases.
- `Pass@Semantic` is evaluated for the 10 pilot cases only.
- A semantic failure is terminal and report-only: no repair, no budget charge, no script mutation.
- A missing output, a wrong output type, a failed query, or a query timeout is a semantic failure, never a skip.
