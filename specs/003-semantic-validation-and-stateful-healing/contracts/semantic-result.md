# Contract: In-Session Semantic Probe

**Date**: 2026-11-10 | **Plan**: [../plan.md](../plan.md) | **Data model**: [../data-model.md](../data-model.md) | **Pilot suite**: [pilot-suite.md](./pilot-suite.md)

Normative contract for the read-only probe that runs inside the disposable GRASS session after a candidate exits successfully. It produces `maps.json` and `semantic.json` next to `status.json`.

## Placement and lifecycle

```text
Executor.execute(script, workdir, semantic_spec=None)
  ├─ create workdir + copy inner_wrapper.py and semantic_probe.py
  ├─ if spec: write semantic_spec.json and set:
  │     GRASS_AGENT_SEMANTIC_SPEC=<workdir>/semantic_spec.json
  │     GRASS_AGENT_MAPS_OUT=<workdir>/maps.json
  │     GRASS_AGENT_SEMANTIC_OUT=<workdir>/semantic.json
  ├─ launch: grass --tmp-mapset <project>/ --exec python3 inner_wrapper.py
  │             <status.json> <script.py>
  └─ read status.json, maps.json, semantic.json
```

Environment variables are used instead of extra argv so the candidate's own script arguments are never polluted. The wrapper reads `Path(__file__).with_name("semantic_probe.py")` and imports/executes it; the Executor copies both files into the workdir.

Inside the wrapper:

```text
1. g.list type=raster mapset=.   -> before_rasters
2. g.list type=vector mapset=.   -> before_vectors
3. fork/exec the candidate
4. waitpid
5. if the child exited 0 and a spec was supplied:
       g.list again                  -> after_*
       new_maps = after - before
       run read-only assertions
       write maps.json, semantic.json
   else:
       write maps.json with empty new_maps
       write no semantic.json, or one with evaluated=false
6. write status.json exactly as today
7. re-raise the child signal, if any, exactly as today
```

The probe never creates, deletes, renames, or writes a GRASS map. It runs before `grass` exits, so it observes the exact scratch mapset the candidate wrote.

**Fresh session per attempt**: `Executor.execute()` creates a new temp mapset for every candidate, so no map from an earlier attempt can satisfy a later attempt's assertions (FR-008d). No reset step is required.

## Input: `semantic_spec.json`

Written by `Executor` from the pilot case plus resolved expectations.

```jsonc
{
  "schema_version": 1,
  "case_id": "pilot_tc_05",
  "query_timeout_s": 30,
  "probe_timeout_s": 60,
  "outputs": [
    {"name": "pilot_slope", "type": "raster"},
    {"name": "pilot_contours", "type": "vector", "geometry": "line"}
  ],
  "assertions": [
    {"output": "pilot_slope", "check": "non_null_count", "min": 1},
    {"output": "pilot_slope", "check": "value_range", "min_value": 0, "max": 90},
    {"output": "pilot_slope", "check": "mean", "expected": 3.8645, "tolerance": 0.01},
    {"output": "pilot_contours", "check": "feature_count", "min": 1},
    {"output": "pilot_contours", "check": "geometry_type", "expected": "line"},
    {"output": "pilot_contours", "check": "required_columns", "columns": ["cat", "level"]}
  ]
}
```

Expected values are copied from the reviewed `pilot_expectations.json`. The probe never derives an expected value from the candidate output.

## Output: `maps.json`

```jsonc
{
  "schema_version": 1,
  "case_id": "pilot_tc_05",
  "before": {"raster": ["elevation"], "vector": ["streams"]},
  "after":  {"raster": ["elevation", "pilot_slope"], "vector": ["streams", "pilot_contours"]},
  "new_maps": {"raster": ["pilot_slope"], "vector": ["pilot_contours"]},
  "error": null
}
```

- All arrays are sorted. `mapset=.` restricts the snapshot to the scratch mapset, so `PERMANENT` layers never appear as candidate outputs.
- A map created and deleted before exit is absent from `after` and does not count.
- `new_maps` is empty when the child did not exit 0.
- `g.list` failure sets `error` and leaves `new_maps` empty; it does not crash the wrapper.

## Output: `semantic.json`

```jsonc
{
  "schema_version": 1,
  "case_id": "pilot_tc_05",
  "evaluated": true,
  "passed": false,
  "new_maps": {"raster": ["pilot_slope"], "vector": ["pilot_contours"]},
  "outputs": [
    {
      "name": "pilot_slope",
      "type": "raster",
      "exists": true,
      "observed": {"n": 2019304, "min": 0.0, "max": 38.689, "mean": 3.87},
      "assertions": [
        {"output": "pilot_slope", "check": "mean",
         "expected": 3.8645, "observed": 3.87, "tolerance": 0.01,
         "passed": true, "detail": "within 1% relative tolerance",
         "query": "r.univar -g -r map=pilot_slope"}
      ]
    }
  ],
  "error": null,
  "elapsed_s": 2.3
}
```

### Field rules

| Field | Rule |
|---|---|
| `schema_version` | `1` |
| `case_id` | Matches the spec |
| `evaluated` | False when no spec was supplied or the child did not execute successfully |
| `passed` | True only when `evaluated` and every assertion passed |
| `new_maps` | Copy of `maps.json.new_maps` |
| `outputs` | One entry per declared output, in declaration order |
| `outputs[].exists` | Result of the output-existence check |
| `outputs[].observed` | Parsed measurements; `{}` when the output is missing or the query failed |
| `outputs[].assertions` | One entry per declared assertion, in declaration order |
| `error` | `null` or one of the probe error codes |
| `elapsed_s` | Probe wall-clock, `≥ 0` |

### Probe error codes

| Code | Meaning |
|---|---|
| `probe_timeout` | Total probe budget exceeded |
| `query_timeout` | One query exceeded `query_timeout_s` |
| `query_failed` | Non-zero exit from a query module |
| `missing_output` | A declared output does not exist in the scratch mapset |
| `wrong_type` | A declared raster exists as a vector or vice versa |
| `no_values` | `r.univar` returned `n=0` or no `mean` |
| `non_finite` | `min`, `max`, or `mean` is NaN or infinite |
| `parse_error` | Module output did not match the contracted format |

An error is a **semantic failure**, not a harness fault. It is recorded in `semantic.json` and persisted through `assertion_results`; it never consumes a repair attempt.

## Query commands

### Raster

```sh
r.univar -g -r map=<name>
```

**Why `-r`**: without it, statistics follow the current computational region. Verified on this host: `elevation` gave `n=810, mean=110.4878` under the default 500 m region and `n=2025000, mean=110.3754` with `-r` over its own 10 m region. A candidate that calls `g.region` would otherwise change the measured mean of a correct output.

**Parsing**: split stdout on newlines, then on the first `=`. Required keys: `n`, `min`, `max`, `mean`. A missing key or a non-finite value is a failure.

### Vector topology

```sh
v.info -t map=<name>
```

**Parsing**: split on newlines, then on `=`; values are integers. Geometry classification:

```text
areas     > 0 -> "area"
lines     > 0 -> "line"
points    > 0 -> "point"
boundaries> 0 -> "boundary"
otherwise      -> "empty"
```

Feature count uses the counter for the declared geometry: `areas` for area, `lines` for line, `points` for point, `centroids` for boundary/centroid. `primitives` is retained for diagnosis but is not the feature count. `map3d=1` does not change the geometry classification.

### Vector columns

```sh
v.info -c map=<name>
```

**Parsing**: each non-empty line is `<SQL type>|<column name>`; the column is the substring after the last `|`. Comparison is case-sensitive. A vector with no attribute table exits non-zero; the probe records `columns = []` and fails only if the case declared required columns.

### Map snapshot

```sh
g.list type=raster mapset=.
g.list type=vector mapset=.
```

**Parsing**: non-empty lines are map names. `mapset=.` is explicit and verified to list only the current scratch mapset.

## Execution rules

1. Probe only after a child exit code of exactly `0` with no signal and no timeout.
2. Probe outputs in declaration order; assertions in declaration order.
3. Resolve every declared output's existence before evaluating any assertion.
4. If output `A` fails, continue to output `B`; one failure does not hide the rest.
5. Use the spec's expected values; never query the candidate's own output to derive an expectation.
6. Bound every query with `query_timeout_s`; bound the whole probe with `probe_timeout_s`.
7. On timeout, terminate the query process and continue with the remaining outputs if the total budget allows; otherwise set `probe_timeout`.
8. Write `semantic.json` atomically (`.part` + `os.replace`).
9. Never write a GRASS map, never mutate the dataset, never open `PERMANENT` for writing.

## Harness normalization

`Executor` reads the two JSON files into `ExecutionResult.new_maps` and `ExecutionResult.semantic`. `run_gate3` then:

- sets `attempt.new_maps`,
- sets `attempt.semantic_evaluated` / `semantic_passed`,
- copies `semantic.outputs[*].assertions` into `attempt.assertion_results`,
- sets `case.pass_at_executed` from `new_maps != empty`,
- sets `case.pass_at_semantic` from `semantic.passed`,
- terminates the case without a repair.

If `semantic.json` is missing or unparseable after a successful execution, the case is a semantic failure with `error="parse_error"`; it is not retried and does not crash the run.
