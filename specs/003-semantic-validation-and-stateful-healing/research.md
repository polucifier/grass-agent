# Phase 0 Research: Semantic Validation, Stateful Healing, and Two-Tier Retry Budget

**Date**: 2026-11-10 | **Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md)

Every finding below was established on this host by running the shown command, by reading the installed code, or by inspecting the actual dataset. Findings are tagged **VERIFIED** (executed and observed) or **INFERRED** (read from source/docs). No finding is assumed.

## Environment baseline (VERIFIED)

| Fact | Value |
|---|---|
| GRASS | 8.5.0, launcher `/usr/bin/grass`, prefix `/usr/lib64/grass85` |
| Target project | `~/grassdata/nc_basic_spm_grass7` |
| Project mapsets | `PERMANENT`, `user1` |
| Rasters in `PERMANENT` | `basins`, `elevation`, `elevation_shade`, `geology`, `lakes`, `landuse`, `soils` |
| Vectors in `PERMANENT` | `boundary_region`, `boundary_state`, `census`, `elev_points`, `firestations`, `geology`, `geonames`, `hospitals`, `points_of_interest`, `railroads`, `roadsmajor`, `schools`, `streams`, `streets`, `zipcodes` |
| Attribute storage | One project-level SQLite database `PERMANENT/sqlite/sqlite.db`; `vector/<name>/dbln` points to it |
| Python | `.venv/bin/python` 3.13; `pytest` 9.1.1; 255 tests collected before this feature |
| Model | `qwen2.5-coder:7b` local Ollama; `nomic-embed-text` embeddings |
| Gate 2 baseline | 40 cases, `Pass@1` 27.5%, `Pass@Healed` 32.5%, 69% of repairs were no-ops |

### Verified dataset facts used by the pilot

| Layer | Type | Geometry / columns | Observed size |
|---|---|---|---|
| `elevation` | raster | FCELL, 10 m | 2025 × 1500 cells; non-null over its own extent |
| `elevation_shade` | raster | FCELL | derived from `elevation` |
| `landuse` | raster | CELL, 28.5 m | 474 × 526 cells, 7 categories |
| `streams` | vector | lines | 8554 features; `cat`, `LENGTH`, `FTYPE`, `NAME`, … |
| `roadsmajor` | vector | lines | 355 lines, 266 nodes; `cat`, `ROAD_NAME`, `MULTILANE`, `PROPYEAR`, … |
| `geology` | vector | areas | 1832 areas/centroids, 3649 boundaries; `cat`, `GEO_NAME`, `GEOL250_ID`, … |
| `hospitals` | vector | points | 160 points; `cat`, `NAME`, `ADDRESS`, `CITY`, … |
| `elev_points` | vector | points | 6000 points; `cat`, `value` |

The NC sample gives the pilot enough deterministic inputs for raster, line, polygon, and point outputs without importing external data.

## R1. Two-tier budget accounting

**Decision**: Keep an initial candidate free, then maintain two independent counters: `static_used/static_limit` and `runtime_used/runtime_limit`. A **repair candidate** is charged to the tier that produced it when it is generated; the failure that motivated the repair consumes nothing. This is what "two static repairs and two runtime repairs" means in FR-002b.

Rules:

1. The initial candidate is generated and statically validated. It is always free. Its outcome determines which repair tier is requested next.
2. A static repair candidate is charged to `static_used` when generated. If it fails static validation, it requests another static repair; if it passes, it is executed.
3. A runtime repair candidate is charged to `runtime_used` when generated. It is statically validated before execution. If it fails static validation it is **not** executed and requests another runtime repair; if it passes, it is executed.
4. Any execution failure — non-zero exit, crash, timeout, or a zero exit with no new map — requests a runtime repair. The failure itself is free; the generated runtime repair consumes the unit.
5. A failed semantic assertion terminates the case immediately; it consumes no budget and generates no candidate.
6. A duplicate candidate is charged to its producing tier because it is a generated repair candidate, is not executed, and requests a parameter-pivot repair if budget remains.
7. Terminal states: success, semantic verdict, static exhaustion (`static_used == static_limit` when another static repair is needed), runtime exhaustion (`runtime_used == runtime_limit` when another runtime repair is needed), or a rejected duplicate with no budget remaining.
8. The maximum number of generated candidates is `1 + static_limit + runtime_limit`.

**Rationale**: Charging repair candidates at generation (rather than charging failures) is the only attribution that keeps the total bounded at `1 + S + R` and prevents a static-invalid runtime repair from bouncing between tiers forever. It also satisfies FR-002a literally.

**Alternatives considered**:

- *Charge failures by stage*: a static repair that executes and fails at runtime would consume both tiers for one candidate, and a runtime-tier repair that misses a schema check would consume the static budget and could re-open static work after it was exhausted. Rejected.
- *One global budget with two counters as views*: cannot express independent overrides or prove non-interference. Rejected.

**Precedence** (highest first): `--max-static-retries` / `--max-runtime-retries`, then `--max-retries`, then `GRASS_MAX_STATIC_RETRIES` / `GRASS_MAX_RUNTIME_RETRIES`, then `GRASS_MAX_RETRIES`, then defaults of 2/2. A tier-specific CLI value wins over both the shorthand and environment variables for that tier only.

## R2. Backward-compatible persisted schema

**Decision**: Keep `schema_version: 1`, add only optional fields with defaults, infer a legacy attempt's tier from `ordinal` and `stage`, and add a `harness` discriminator to `ResumeKey`.

**Evidence**: `tests/test_integration_smoke.py:159` asserts `payload["schema_version"] == 1`. Bumping the version would fail an existing test, violating FR-010. Existing tests also construct `ResumeKey("stub-model", 2, 60, "fresh")` positionally and `Attempt(...)` with the old field set.

**Compatibility mechanics**:

- New `Attempt` fields are appended with defaults, so positional construction is unaffected.
- Loaded attempts without `budget_tier` infer: `ordinal == 1` → `initial`; `stage == "static"` → `static`; otherwise `runtime`.
- `check_invariants(result, max_retries)` keeps its signature. When no tier limits are supplied, it applies the legacy ceiling `len(attempts) ≤ max_retries + 1` and also infers tiers. New callers pass explicit static/runtime limits.
- `ResumeKey` gains `max_static_retries`, `max_runtime_retries`, and `harness` with `None`/`"gate2"` defaults. `matches()` normalises `None` to the legacy `max_retries` value, so old keys still compare correctly among themselves.
- Gate 3 writes `harness: "gate3"`; a Gate 2 result therefore never matches a Gate 3 resume key even when the model, budget, and timeout coincide.

**Rationale**: Additive evolution preserves every existing test and every old artifact while preventing silently mixed Gate 2/Gate 3 metrics.

**Alternative rejected**: A new `case_result_v2.json` would duplicate the whole persistence layer, resume rules, and artifact checks. The compatibility cost is larger than the schema's additive cost.

## R3. In-session semantic probe placement

**Decision**: Run the probe in the `inner_wrapper.py` parent after the forked child exits zero and before the wrapper returns. Write `maps.json` and `semantic.json` next to `status.json`.

**Evidence**: `Executor.execute()` creates a fresh `--tmp-mapset` session per attempt and removes it after the process exits. A second GRASS session cannot see the scratch maps, and preserving the mapset would weaken the zero-leftover guarantee (SC-008). The wrapper parent already outlives the child and holds GRASS's injected `PYTHONPATH`/`GISRC`/`GISBASE`, so `g.list`, `r.univar`, and `v.info` work there without a new session.

**Sequence**:

```text
wrapper start
  snapshot current-mapset rasters + vectors       (g.list mapset=.)
  fork child -> exec candidate
  parent waitpid
  if child exited 0:
      snapshot again
      new_maps = after - before
      run probe with bounded per-query/total timeouts
      write maps.json, semantic.json
  else:
      write maps.json with empty new_maps; no probe
  write status.json (unchanged crash semantics)
  re-raise child signal if any (unchanged)
```

**Rationale**: The probe must see the exact scratch mapset the candidate wrote. It is read-only, has its own timeout, and cannot change the child's status.

**Alternative rejected**: A separate `grass --exec` session after the attempt. The temp mapset is gone by then, and `PERMANENT` contains none of the candidate outputs.

## R4. Semantic query semantics (VERIFIED)

### Raster statistics

**Critical hazard found by execution**: `r.univar` computes over the *current computational region*, not over the raster's own extent. The project default region is 500 m (`rows=620, cols=1630`), while `elevation` is 10 m (`rows=1350, cols=1500`). The same command produced two different answers:

```text
r.univar -g map=elevation
  n=810  null_cells=1009790  cells=1010600  mean=110.4878

r.univar -g -r map=elevation
  n=2025000  null_cells=0  cells=2025000  min=55.5788  max=156.3299  mean=110.3754
```

A candidate that sets `g.region` (a normal and often necessary thing) would therefore change the measured mean of a correct output and produce a spurious semantic failure.

**Decision**: The probe always runs `r.univar -g -r map=<name>`. The `-r` flag computes statistics over the raster's own region, so the expected values are a property of the produced map, not of whatever region the script happened to leave behind.

**Parsing**: key=value lines. `n` is the non-null cell count. `min`, `max`, and `mean` are parsed as floats. A missing `n` or `mean`, a non-zero exit, or a non-finite value is a semantic failure with a named reason (`query_failed`, `no_values`, `non_finite`).

### Vector topology and columns

**VERIFIED output formats**:

```text
v.info -t map=roadsmajor
nodes=266
points=0
lines=355
boundaries=0
centroids=0
areas=0
islands=0
primitives=355
map3d=0

v.info -c map=roadsmajor
INTEGER|cat
DOUBLE PRECISION|MAJORRDS_
CHARACTER|ROAD_NAME
...
```

**Decision**:

- Geometry type is derived deterministically: `areas > 0` → `area`; else `lines > 0` → `line`; else `points > 0` → `point`; else `boundaries > 0` → `boundary`; else `empty`.
- Feature count is the count for the declared geometry: `areas` for area, `lines` for line, `points` for point, `centroids`/`areas` for polygon centroids as appropriate. `primitives` is recorded for diagnosis but is not the feature count.
- Required columns are the last `|`-separated field of each `v.info -c` line, compared case-sensitively.
- Feature count and column presence are separate assertions and reported separately (FR-008a).

**Alternative rejected**: `v.info -g` for counts. It reports the bounding box, not topology, and would not distinguish an empty vector from a populated one.

### New-map detection

**VERIFIED**: inside the scratch mapset, `g.list type=raster mapset=.` and `g.list type=vector mapset=.` return only maps in the current mapset; `mapset=PERMANENT` returns the reference layers. Explicit `mapset=.` is therefore the correct snapshot scope — it cannot credit a `PERMANENT` layer as a candidate output.

**Decision**: Snapshot before the child and after a zero-exit child; `new_maps = after − before`, split by type. A map created and then deleted before exit is absent from `after` and does not count. A stale map cannot be credited because every attempt gets a fresh temp mapset.

### Probe timeouts

**Decision**: Each query gets `semantic_query_timeout_s = 30` (a verified full-extent `r.univar -r` on a slope map took 7.4 s, so 10 s was too tight). The whole probe gets `semantic_probe_timeout_s = 60`. The executor extends its outer communicate deadline by `semantic_probe_grace_s = 5` only when a semantic spec is present, so a long successful script plus a bounded probe is not mislabelled as a timeout. A probe timeout is a semantic failure, never a harness crash and never a repair trigger.

**Rationale**: A hung `r.univar` must not hold the run open; the probe is bounded independently of the generated script.

## R5. Expected-value authority and tolerances

**Decision**: Expected values live in `benchmarks/pilot_expectations.json`, generated by `benchmarks/derive_pilot_expectations.py` from human-reviewed golden scripts and reviewed before use. The pilot suite declares *checks and tolerances*; the expectations file declares *values*.

- Mean: relative tolerance, default `0.01` (1%). A case may override.
- Range: expected `min`/`max` from the reference run, with a declared absolute margin (default `0.0`; cases such as slope may use a small margin).
- Non-null count: minimum `1`; a case may require more.
- Vector features: minimum `1`; a case may require more.
- Geometry and required columns: exact declared values.

**Evidence integrity**: The expectations file records GRASS version, project path, `PERMANENT` hash, the reference script hash, and the command used. `derive_pilot_expectations.py` refuses to read a candidate `attempt_*.py` or `final.py`; it runs only scripts from `benchmarks/pilot_reference/`.

**Rationale**: A semantic oracle tuned on candidate output measures nothing. The reference execution must be independent and frozen before the benchmark run.

**Mismatch policy**: A reference mismatch (the golden script does not reproduce its own frozen expectations) is a suite defect: the run aborts with exit `3` before any model inference, and the report is not generated.

## R6. Deterministic no-op detection

**Decision**: Compute two digests per candidate before execution.

1. **Byte digest**: `sha256(code.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))`. Identical bytes after line-ending normalisation are a duplicate.
2. **AST digest**: parse with `ast.parse`, recursively strip module/class/function docstrings, then `ast.dump(tree, annotate_fields=False, include_attributes=False)` and SHA-256. Comments and whitespace never enter the AST; formatting-only differences collapse to the same digest.

A candidate is a duplicate when either digest matches any previously recorded attempt for the same case, including the initial candidate and attempts from both tiers. If the candidate does not parse, only the byte digest participates; the static guard rejects it anyway.

**Charge**: A duplicate consumes one attempt from the tier that produced it and is recorded with `duplicate: true`, `exit_code: null`, and zero-byte stdout/stderr artifacts. It is never executed. The next prompt pivots.

**Pivot**: `Healer.parameter_list(tool)` returns the knowledge-base signature, required/optional parameters, and accepted options. The pivot prompt replaces the generic "fix it" instruction with an explicit parameter table and the constraint "change the approach; do not resubmit a previous program". If the pivot is also a duplicate, or no budget remains, the case ends as `no_op_exhausted`.

**Determinism**: The detector is a pure function of the ordered candidate bytes and ASTs. No filesystem order, set iteration, or model state affects the verdict (FR-006d).

**Alternative rejected**: Fuzzy similarity (edit distance, embedding cosine). It would reject genuinely different programs and cannot be reproduced exactly. Byte + AST equality is conservative and deterministic.

## R7. History rendering under a context budget

**Decision**: `RepairContext` gains `attempt_history: list[RepairTurn]`. Rendering rules:

1. Always include every attempt's ordinal, producing tier, failure mode (or `success`), static/runtime status, duplicate flag, and full error excerpt.
2. Always include the most recent failed attempt's full code.
3. For older attempts, include a SHA-256 prefix, line count, and a bounded excerpt (first 12 lines or 600 characters, whichever is smaller).
4. Emit the verbatim instruction: `DO NOT repeat previous scripts or failed parameter combinations.`
5. Keep the task, tool documentation, and inventory blocks ahead of history so the model sees the objective first.

**Budget**: History code and excerpts are capped at 6000 characters total. Metadata is never truncated. The cap is a module constant, so the same history always renders the same prompt.

**Backward compatibility**: `attempt_history` defaults to `[]`; when empty, `to_user_message()` produces exactly the current four-element repair prompt. Existing `RepairContext` tests therefore pass unchanged. The four FR-012 elements remain present in both modes.

**Rationale**: Dropping old attempts loses the evidence the feature exists to provide; dropping the current error or the task loses the immediate fix target. Truncating only old code preserves all failure evidence within a predictable budget.

## R8. Dual-metric reporting and Gate 2 continuity

**Decision**: Add a separate Gate 3 renderer instead of changing the Gate 2 renderer's text.

- `render_markdown()` remains the Gate 2 renderer, byte-compatible with existing tests and `benchmarks/execution_report.md` semantics.
- `render_gate3_markdown()` emits the Gate 3 report and calls out the Gate 2 historical baseline in its own section.
- `aggregate()` gains additive summary fields; existing fields and properties remain.

**Metric definitions**:

| Metric | Numerator | Denominator |
|---|---|---|
| `Pass@Executed` | completed cases whose successful attempt exited 0 and created ≥1 new map | all completed cases |
| `Pass@Executed` (semantic subset) | same, restricted to cases with `semantic_evaluated = true` | completed semantic cases |
| `Pass@Semantic` | cases with `pass_at_semantic = true` | completed semantic cases only |
| `Pass@1` | `attempts[0].pass_at_executed` | all completed cases |
| `Pass@Healed` | any attempt `pass_at_executed` | all completed cases |

**Why separate renderers**: Existing reporting tests assert Gate 2 phrases, the Gate 1 baseline, "different harnesses", and the integrity section. Rewriting the single renderer risks silent regressions and mixes historical and current metrics. Two renderers make the separation explicit and testable.

**Report invariants**:

- `Pass@Semantic ≤ Pass@Executed` over the semantic subset.
- Non-evaluated cases are listed and excluded from the semantic denominator.
- The gap is computed only over the semantic subset.
- Every semantic failure names the output, check, expected value, observed value, tolerance, and verdict.
- Duplicate and tier counters are rendered even when zero, so a clean run proves the invariant rather than hiding it.

## R9. Pilot composition

**Decision**: Ten cases: five from Tier 1 (`pilot_tc_01`, `_05`, `_06`, `_08`, `_09`) and five from Tier 2 (`pilot_tc_12`, `_14`, `_18`, `_32`, `_33`). Four are multi-step or mixed raster/vector (`_05`, `_06`, `_32`, `_33`).

**Pilot feasibility was checked by execution, not assumed.** Findings that changed the selection:

- `v.buffer` produces a vector map with **no attribute table** (`v.info -c` exits 1: "Database connection ... is not defined"). Buffer outputs therefore assert feature count and area geometry only; a `cat` column assertion would be a guaranteed false failure.
- `v.dissolve` preserves `cat` and the dissolve column (`GEO_NAME`), so a column assertion is valid.
- `v.clean` preserves the full roadsmajor table (`cat`, `ROAD_NAME`, …), so column assertions are valid.
- `r.contour` produces lines with `cat` and `level`; its output reports `map3d=1`, which must not be mistaken for a 3D geometry failure.
- `r.viewshed` without `-b` writes an elevation-difference value, not a visibility flag. The pilot prompt requires a binary visibility raster and the golden script uses `-b`.
- `r.slope.aspect` over the full NC elevation takes ~57 s on this host, so the pilot's two slope cases fit the 120 s bound but leave little headroom for a slow candidate.
- `r.grow.distance` after `v.to.rast` completes in under 1 s and produces a non-null raster over the default region.

| Pilot | Source | Tier | Workflow | Why it is in the pilot |
|---|---|---|---|---|
| `pilot_tc_01` | tc_01 | 1 | single | Vector line → polygon buffer; simple, fast, validates area geometry |
| `pilot_tc_05` | tc_05 | 1 | multi, mixed | Raster slope + vector contours; two output types, known slope range |
| `pilot_tc_06` | tc_06 | 1 | multi, mixed | Vector buffer → raster; exercises both output types from one chain |
| `pilot_tc_08` | tc_08 | 1 | single (edge) | Binary viewshed; 0/1 range is unambiguous |
| `pilot_tc_09` | tc_09 | 1 | single (edge) | `elevation * 2`; mean and range are exactly 2× a known reference |
| `pilot_tc_12` | tc_12 | 2 | single | Shaded relief; deterministic 0–255 raster |
| `pilot_tc_14` | tc_14 | 2 | single | Road cleaning; line geometry and `ROAD_NAME` column |
| `pilot_tc_18` | tc_18 | 2 | single | Geology dissolve; polygon geometry and `GEO_NAME` column |
| `pilot_tc_32` | tc_32 | 2 | multi, mixed | Slope → reclassified steep raster → vector polygons; two output types, threshold semantics |
| `pilot_tc_33` | tc_33 | 2 | multi, mixed | Hospitals → raster → distance; distance minimum and non-null count |


**Dataset adaptation**: `tc_18`'s original wording says "parcels … zoning code"; the NC sample has no parcels layer. The pilot prompt is rewritten to dissolve `geology` polygons by `GEO_NAME` while keeping the same task class (polygon dissolve by attribute). This is an explicit, documented adaptation, not a hidden substitution; `source_id` preserves provenance. Every pilot prompt names its `pilot_*` output maps and their types, as FR-007b requires.

**Region convention**: every pilot prompt states *"Do not change the computational region."* A fresh `--tmp-mapset` session starts from `PERMANENT/DEFAULT_WIND` (500 m on this host), so the reference execution and every candidate see the same region. Without this constraint a correct candidate that calls `g.region` could change a raster's mean and fail a statistical assertion for a reason unrelated to correctness. The expected values are measured with `r.univar -r` on the output map and the prompts hold the region fixed.

**Excluded source cases**: display-only (`tc_04`), statistics-only (`tc_13`), export-only (`tc_24`, `tc_25`, `tc_30`), interpolated-surface (`tc_35`: a verified `v.surf.rst` run produced a near-constant surface, making a mean assertion weak and misleading), and cases requiring layers absent from the NC dataset (e.g. `bathymetry`, `parcels`, rainfall series, temperature) are excluded because they either create no persistent map or cannot be reproduced on the target dataset.

## R10. CLI and entry-point split

**Decision**:

- `benchmarks/run_gate2.py` keeps its public functions, parser shape, and Gate 2 report. It gains optional `--max-static-retries`, `--max-runtime-retries`, and `--semantic` (default off), and shares the tier-aware loop. `--max-retries N` therefore sets both tiers to `N`, and the maximum candidates per case becomes `1 + 2N` (5 at the default). Existing CLI contract tests still pass because the parser surface and resolved `max_retries` value are preserved; the only behavioural change is the documented two-tier bound.
- `benchmarks/run_gate3.py` is the Gate 3 entry point: defaults to `benchmarks/benchmark_prompts_pilot10.json`, enables semantic evaluation, uses tier budgets, and writes `benchmarks/gate3_report.md`.
- Both call the same `run_case` and `Executor`. There is no duplicated execution logic.

**Rationale**: Existing CLI contract tests import `run_gate2` and assert its parser and defaults. A new entry point gives Gate 3 a clean surface without breaking that contract. `--max-retries` remains a both-tier shorthand in both entry points.

## R11. Determinism and verification strategy

**Decision**:

- All new collections that reach a persisted artifact are sorted before serialisation; verdicts never depend on `set` iteration.
- Duplicate detection, tier charging, assertion ordering (declared output order, then declared check order), and metric aggregation are pure functions.
- Unit tests use fake `r.univar`/`v.info` output; live-GRASS tests are marked `slow` and skip when GRASS or the dataset is absent.
- Regression evidence is the unchanged 255-test suite plus the new tests; the existing tests are not edited.

**Verification commands**:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m benchmarks.run_gate3 --validate-pilot
.venv/bin/python -m benchmarks.run_gate3 --clean
.venv/bin/python -m benchmarks.run_gate3 --report-only
.venv/bin/python -m benchmarks.run_gate3 --suite benchmarks/benchmark_prompts_tier1.json \
    --suite benchmarks/benchmark_prompts_tier2.json
```

## Open questions

None. Every `NEEDS CLARIFICATION` from the plan's Technical Context has a decision above. Exact expected numeric values and the golden reference scripts are implementation artifacts produced and reviewed in Phase 3, not planning unknowns.
