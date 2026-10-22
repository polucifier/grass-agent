# Autonomous Code Generation Agent for GRASS GIS 8.6 (`grass.tools`)

## Project Description

This project implements a fully offline autonomous agent that translates unconstrained natural-language GIS queries into executable, syntactically verified Python scripts built on the modern object-oriented `grass.tools` API (GRASS GIS 8.5+).

**Motivation and core problem.** A GIS analyst can describe an analysis in plain English long before they can recall the exact module name, parameter spelling, and argument types that the `grass.tools` object API demands. The obstacle is not the language model's general coding ability — it is *specificity*. Public model pretraining is dominated by the legacy GRASS command-line interface, so general-purpose LLMs reliably fail in three characteristic ways when asked for `grass.tools` code:

1. **Legacy-interface drift.** They emit `grass.script.run_command("r.slope.aspect", ...)` shell invocations instead of the object API.
2. **Signature hallucination.** They invent plausible but non-existent method signatures and parameter names that never existed in any GRASS release.
3. **Interface-convention confusion.** They conflate the CLI calling convention — where `output=` is always written explicitly — with the Python wrapper convention, where many tools *return* their result and therefore have no `output` parameter at all. This is the single most persistent error class observed during development.

**Objective.** Close that gap with a deterministic, fully offline pipeline that grounds generation in the official GRASS 8.6 manual, optimises the context supplied to the model, and then *verifies* the result statically against the same source of truth. No inference-time network access, no cloud API, no human in the loop. The guarantee is narrow and deliberately so: the system produces scripts that are syntactically valid, schema-conformant, and free of hallucinated modules — it does not claim their numerical results are correct.

**Current state:** Gate 1 complete. 36/40 (90.0%) zero-shot static verification across a two-tier benchmark suite on `qwen2.5-coder:7b`. Tier 1 alone scores 10/10 on discrete GPU hardware and 9–10/10 on integrated graphics across repeated runs; see [Hardware & Latency](#hardware--latency).

Gate 2 is implemented as a headless execution and bounded self-healing harness. On the same 40-case suite it reaches **27.5% Pass@1** and **32.5% Pass@Healed**; those figures measure executability, not correctness. The diagnosis and enhancement plan are in [Gate 2 — Runtime Execution & Self-Healing](#gate-2--runtime-execution--self-healing).

---

## Table of Contents

1. [Project Description](#project-description)
2. [System Architecture & Pipeline](#system-architecture--pipeline)
3. [Benchmark Methodology & Evaluation Results](#benchmark-methodology--evaluation-results)
4. [Diagnostic Failure Analysis (The 4 Residual Cases)](#diagnostic-failure-analysis-the-4-residual-cases)
5. [Gate 2 — Runtime Execution & Self-Healing](#gate-2--runtime-execution--self-healing)
6. [Quickstart & CLI Usage](#quickstart--cli-usage)
7. [Repository Layout](#repository-layout)
8. [Configuration](#configuration)
9. [Provenance, Reproducibility & Known Limitations](#provenance-reproducibility--known-limitations)
10. [License](#license)

---

## System Architecture & Pipeline

The agent executes four sequential stages. Each is deterministic, and stages 1, 2 and 4 are entirely independent of the language model.

```text
                      ┌─────────────────────────────────────────────┐
  "Buffer the streams │  STAGE 1  Knowledge Extraction (offline)    │
   by 200 metres"     │  scripts/build_knowledge_base.py           │
                      │  GRASS 8.6 manual  →  SQLite + sqlite-vec │
                      │  543 tools · signatures · schemas · 768-d  │
                      └──────────────────┬──────────────────────────┘
                                         │  data/grass_knowledge.db
                                         v
                      ┌─────────────────────────────────────────────┐
                      │  STAGE 2  Hybrid RAG Retrieval              │
                      │  rag_retriever.py                           │
                      │  ① dense cosine (sqlite-vec)               │
                      │  ② lexical  (SQL LIKE, SYNONYMS-expanded)  │
                      │  ③ re-rank  (category · wrapper · step)    │
                      │  → 5 de-duplicated tools                    │
                      └──────────────────┬──────────────────────────┘
                                         │  RAG context
                                         v
                      ┌─────────────────────────────────────────────┐
                      │  STAGE 3  Context Optimisation + Synthesis  │
                      │  code_generator.py                         │
                      │  strip generic kwargs · canonical examples │
                      │  → Ollama · qwen2.5-coder:7b (local)       │
                      └──────────────────┬──────────────────────────┘
                                         │  raw completion
                                         v
                      ┌─────────────────────────────────────────────┐
                      │  STAGE 4  Static Verification  (no model)   │
                      │  extract → normalise → ast.parse           │
                      │  → AST walk vs. knowledge base             │
                      │  PASS = emitted · FAIL = raises            │
                      └─────────────────────────────────────────────┘
```

### Stage 1 — Knowledge Extraction & Offline Database

`scripts/build_knowledge_base.py` ingests the official GRASS 8.6 manual and produces `data/grass_knowledge.db`. For each of **543 tools** it stores the name, category, description, the exact `grass.tools` method signature, parsed parameter schema (type, required flag, default), a usage example, and a **768-dimensional** `float32` embedding generated locally by `nomic-embed-text` and indexed in a `sqlite-vec` virtual table.

The database is **committed to the repository** (3.8 MB), so a fresh clone runs without a network round-trip. Scraped HTML is cached in `data/cache/` (gitignored), which makes a rebuild network-free.

### Stage 2 — Hybrid RAG Retrieval Engine

Pure dense retrieval fails on short GIS prompts: general terrain modules outrank the specific tool the user actually asked for. `rag_retriever.py` therefore blends three independent signals.

**(a) Dense similarity.** Cosine distance over the `sqlite-vec` index, normalised to a score.

**(b) Lexical matching.** A SQL `LIKE` sweep over `name` and `description`, using tokens expanded through a **`SYNONYMS`** map that bridges GIS vernacular to GRASS naming — `statistics`→`stats`, `zonal`→`v.rast.stats`, `rasterize`→`to.rast`, `reclassify`→`r.reclass`, `euclidean`→`r.grow.distance`, and ~60 further terms. Underscore API names (`v_rast_stats`) are normalised back to dotted form so both conventions match the database.

**(c) Structural re-ranking.**

| Heuristic | Rationale |
|---|---|
| **GIS category weighting** (`CATEGORY_BOOST`) | Bias toward raster modules for DEM/terrain vocabulary, vector modules for road/parcel vocabulary, display modules for presentation intent. |
| **Modern wrapper preference** | `v.import` / `r.import` are scored **+0.6** over the raw drivers `v.in.ogr` / `r.in.gdal` (**−0.4**), unless the prompt explicitly names `ogr`/`gdal`/`ascii`. Ties break toward the wrapper. |
| **Cross-type penalty** | `r.buffer` is demoted on a clearly vector-scoped prompt, and vice versa. |
| **Anti-crowding** (`MAX_PER_STEP = 1`) | Tools are mapped to *functional steps*; entire module families collapse into one step (`d.*` → `display`, `r.li.*`/`v.lidar.*` → `lidar_analysis`, `i.*` → `imagery_index`). Without this, five slots filled with `r.li.*` variants and the correct tool never appeared. |
| **Display de-noising** | `d.*` modules are penalised on prompts with no presentation intent. |

Measured retrieval recall: **39/40** across both suites — the one miss is documented under Diagnostic Analysis.

### Stage 3 — Context Optimisation & LLM Synthesis

**Generic-kwarg stripping.** The parameters `flags`, `overwrite`, `verbose`, `quiet` and `superquiet` are removed from every rendered signature and from the required-parameter summary. This eliminates the dominant source of *parameter bleed*: the model otherwise reproduces these in its output, where `grass.tools` frequently does not accept them. Measured effect: **36.3%** reduction in signature text, and **17–19%** reduction in the fully rendered top-k context actually sent to the model.

**Canonical example overrides.** A deliberately small `CANONICAL_EXAMPLES` map supplies a correct call for tools whose scraped example is unusable. It exists for two reasons:

- *Outliers* — `r.mapcalc` documents no usable call pattern, so `CANONICAL_EXAMPLES` supplies `tools.r_mapcalc(expression="elevation_double = elevation * 2")`.
- *Corrupt source data* — four scraped examples **cannot execute**: `v.distance`, `r.smooth.edgepreserve` and `r3.gwflow` document a parameter named after a Python keyword (`from`, `lambda`, `yield`), which is a syntax error as a keyword argument; and `m.nviz.image` lost the quoting around its size pair. The model was faithfully reproducing the broken `v.distance` example. All four are now overridden.

**Generation.** A ten-rule system prompt fixes the contract — exact `Tools()` instantiation, flat underscore naming, keyword arguments, coordinate-pair string serialisation, and the `**{...}` unpacking form for keyword-named parameters. Synthesis is zero-shot against a local Ollama instance of `qwen2.5-coder:7b`.

### Stage 4 — Deterministic Verification

Two-tier static analysis, performed with **no model involvement**, so it is reproducible to the bit.

1. **Syntax.** `ast.parse()` over the extracted code. A `SyntaxError` fails the generation outright.
2. **Schema.** A recursive AST walk inspects every `tools.*(...)` call and checks it against the knowledge base: module existence, required-parameter presence, unknown-parameter rejection, positional-argument rejection, and `**{...}` unpacking via `_dict_literal_keys` (needed because `node.keywords` has `arg=None` for `**`).
3. **Rule 3 enforcement.** Dotted chains (`tools.v.buffer`) are both flagged *and* repaired — `normalize_dotted_calls()` rewrites them to `tools.v_buffer` post-extraction, so a correct answer is not discarded over a formatting slip.

Every saved artifact is prefixed with a commented record of the system prompt, the user message (which embeds the RAG context verbatim), and the model's raw response — allowing any bad output to be attributed to the prompt, the response, or the extraction step.

---

## Benchmark Methodology & Evaluation Results

### Evaluation Framework

Two suites, selected with `-s/--suite`. Each case must pass **all four** assertions, or it fails:

1. `ast.parse()` syntax validity
2. Zero-chat compliance — begins with the `Tools` import, no markdown fences, no prose
3. Zero `validate_api()` issues
4. Expected tools actually called — an alias group such as `["v.in.ogr", "v.import"]` passes if **any** member is used

| Suite | File | Cases | Coverage |
|---|---|---|---|
| **Tier 1** — smoke / sanity | `benchmarks/benchmark_prompts_tier1.json` | 10 | Core raster & vector workflows, multi-step chaining, edge cases, API compliance |
| **Tier 2** — advanced | `benchmarks/benchmark_prompts_tier2.json` | 30 | Hydrology & subwatersheds, remote sensing / NDVI, raster algebra, vector topology, network routing, multi-ring concentric buffering, surface interpolation, attribute-table management |

### Current Results

Measured on a Colab Tesla T4 (15 GB) with `qwen2.5-coder:7b`.

| Suite | Passed | Score | Suite wall time |
|---|---|---|---|
| Tier 1 | 10 / 10 | **100%** | 181–198 s |
| Tier 2 | 26 / 30 | **86.7%** | 142 s |
| **Combined** | **36 / 40** | **90.0%** | — |

*90.0% zero-shot static verification rate.*

Tier 2 progressed 18 → 21 → 22 → 26 across four iterations; the last was a correction to suite strictness rather than a change to the engine.

### Hardware & Latency

| Model | Hardware | Result | Suite (cold) | Suite (warm) | Warm latency / prompt |
|---|---|---|---|---|---|
| `qwen2.5-coder:7b` | Colab T4 15 GB | **10 / 10** | 181–198 s | 26–49 s | **0.9–1.8 s** |
| `qwen2.5-coder:3b` | Colab T4 15 GB | 9–10 / 10 | 167 s | 13 s | 0.8–1.1 s |
| `qwen2.5-coder:7b` | Local laptop, iGPU Vulkan | 9–10 / 10 | 424–465 s | 352 s | 10–11 s |
| `qwen2.5-coder:3b` | Local laptop, iGPU Vulkan | 8–10 / 10 | 173–258 s | 223 s | 15–16 s |

"Cold" means the model was unloaded before the run and is loaded on first prompt; "warm" re-runs immediately with the model resident. Tier 1 only. `Result` is the observed range across every Tier 1 run performed on that configuration, not a single run.

**The 7B model does not hold a clean 10/10 on this suite.** On local hardware it first scored 10/10, then 9/10 on two subsequent runs (`tc_07`, the multi-step import → buffer → zonal-statistics chain, failing on a hallucinated or mistyped call). Every 7B run on the T4 has scored 10/10, but the honest reading is that 7B is *reliable on discrete hardware and near-reliable on integrated graphics*, not uniformly perfect. The 3B model is weaker and less stable: it has ranged from 8/10 to 10/10 on local hardware and fails `tc_10` (parcel/zoning intersection overlay) on every warm run observed, local and remote alike.

**Local hardware:** HP Laptop 15s-eq2xxx; AMD Ryzen 5 5500U (6C/12T @ 4.0 GHz, mobile-class); 15.67 GB RAM; integrated AMD Radeon (Lucienne, Vega 8); openSUSE Tumbleweed.

> **Measurement note.** Inference on the local machine runs on the **integrated GPU via Vulkan**, not the CPU. `ollama ps` reports `100% GPU` and this is correct: `/sys/class/drm/card1/device/gpu_busy_percent` reads ~0% idle and holds ~99% for the duration of a generation. Ollama's startup log *does* print `dropping integrated GPU ... compute=0.0` and registers only a `cpu` compute device, which is misleading — the runner still maps `libggml-vulkan.so` and holds `/dev/dri/renderD128` open. When diagnosing this, trust `gpu_busy_percent`, not the log line. The iGPU shares system memory rather than having dedicated VRAM, which is why it remains an order of magnitude slower than the T4 despite being genuine GPU compute.

**Latency composition.** The gap is dominated by model load, not compute: a cold first prompt costs 18 s on the T4 and ~45 s locally, and a cold embedding call adds up to 40 s if `nomic-embed-text` is not resident. Everything after that is token generation. The specification's target of **< 5 s per prompt is met on a discrete GPU and missed on integrated graphics.**

**Counter-intuitive finding.** The smaller model is *slower* per prompt on integrated graphics. 3B decodes at 4.8 tok/s against 7B's 3.4 tok/s, but emits roughly twice the tokens for the same prompt (97 vs 44 on `tc_01`) because it pads with commentary. Latency follows output length, not decode speed. On the T4 the gap inverts and 3B is marginally quicker.

---

## Diagnostic Failure Analysis (The 4 Residual Cases)

The four remaining Tier 2 failures are reported individually rather than as a percentage, because they have four different causes and only one of them is a retrieval defect.

### 1. `tc_28` — wrong operator for the task (suite strictness)

> *Populate the parcel vector polygons with their calculated area in square meters.*

The model reached for `v.report(column_prefix=...)` rather than `v.to.db`. `v.report` prints a table; it does not write geometry-derived values into the attribute table. This is a genuine mis-selection, not an alternative pipeline — but it is a *model* error, not a retrieval error: `v.to.db` was present in the context.

### 2. `tc_33` — intermediate conversion retrieval gap (the one real defect)

> *Calculate the minimum Euclidean distance from each cell to the nearest hospital vector points.*

`v.to.rast` never reaches the top-5, so the model passed the vector layer directly to `r.grow.distance`. The prompt never states a conversion — inferring it requires noticing that "each cell" is raster-scoped while "vector points" is vector-scoped. A cross-type conversion boost was implemented and then **removed**: A/B measurement showed it changed the total by zero (39/40 either way), so it was deleted rather than retained as unjustified complexity. This remains the single unresolved recall gap in the system.

### 3. `tc_34` — narrow kwarg omission

> *Calculate the average temperature per county by computing zonal statistics of temperature raster over county vector polygons.*

The model selected a valid pipeline — `v.to.rast(type="cat")` followed by `r.stats.zonal(method="average")` — but passed `type=` where `v.to.rast` requires `use=`. `validate_api()` caught it precisely: `missing required parameter(s): use`. The approach was right; one argument was wrong. This is the validation layer doing exactly its job.

### 4. `tc_38` — hallucinated helper appended to a correct answer

> *Find the nearest fire station vector point for each building vector point and record the distance in the attribute table.*

The model produced a **correct** `v_distance(**{"from": "buildings", "to": "fire_stations", "upload": "cat"})` and a correct `v_db_addcolumn`, then appended a third step calling `tools.v_update_column` — a module that does not exist. This is the most frequent failure shape across both suites and both models: **a right answer followed by invented scaffolding**. `validate_api()` rejects it, which is the desired conservative behaviour, but it means the pass criterion is strict by design.

### Why iteration stopped at 90%

Two reasons, and both are methodological rather than budgetary.

**Overfitting.** Each of the four iterations moved the Tier 2 score by moving *either* the engine or the assertion. Iterating the system prompt against a 30-case suite with non-deterministic sampling is fitting to noise: the model re-derives a different script on every run, so a prompt edit that fixes two cases can silently break two others. The stopping criterion is whole-suite movement, not a single recovered case.

**The wrong kind of fix.** Three Tier 2 cases were failing with *correct answers reached by a different route* — the model was producing valid GRASS pipelines that the suite rejected for using a different single tool. The correct response was to widen the assertion (accepting `r.drain`/`r.path`, `r.watershed`/`r.fill.dir`, `v.rast.stats`/`r.stats.zonal`), **not** to bend the engine to match a narrow assertion. Widening a disjunction can also mask a wrong answer, so it warrants review rather than being routine; the mitigating evidence is that the model, left to choose, picked the *alternative* branch in two of the three cases and those scripts are valid.

**These are Gate 2 work.** All four residual failures are **runtime-detectable exceptions** — a missing layer, a type error, a wrong column name — that a headless execution harness surfaces immediately and unambiguously. Continuing to chase them through prompt wording, against a validator that can only reason statically, is the wrong instrument. They are deferred to the Gate 2 self-healing loop by design.

> **A caveat on the headline number.** 36/40 is a snapshot, not a pass rate with error bars. Re-running produces different scripts: 8 of 10 Tier 1 artifacts were byte-different between two runs of the identical model, and across repeated Tier 1 runs 3B has scored anywhere from 8/10 to 10/10 while 7B has scored 9/10 to 10/10 on integrated graphics. 40 cases is a small sample; the figure should be read as "the pipeline reliably produces verifiable code," not as a stable metric.

---

## Gate 2 — Runtime Execution & Self-Healing

Gate 1 asks whether a script is well-formed. Gate 2 asks whether it actually runs in a live GRASS session — and, when it does not, whether a bounded repair loop can recover it.

### Mechanism

1. **Pre-flight static guard.** Every generated and repaired script is re-validated against the knowledge base before execution. A static rejection costs one unit of the unified retry budget and skips execution.
2. **Isolated execution.** Scripts run in disposable `tmp_<uuid>` mapsets via `grass --tmp-mapset <project> --exec python3`. The persistent `PERMANENT` mapset is write-protected and its content hash is verified before and after the run.
3. **Failure classification.** Each failed attempt is classified deterministically as `missing_input`, `schema_misuse`, `unknown_method`, or `general_exception`, with the failing GRASS tool and a diagnostic excerpt recorded.
4. **Repair loop.** The next attempt receives the original task, the previous script, the previous error, targeted tool documentation, and the dataset map inventory. The loop is bounded by `--max-retries` (default 2).
5. **Reporting.** Per-case artifacts and `case_result.json` are written under `benchmarks/output_execution/`; `benchmarks/execution_report.md` is regenerated from them.

### Results

Measured with `qwen2.5-coder:7b`, both suites, 2 retries, 120 s per attempt:

| Metric | Value |
|---|---|
| Cases | 40 |
| Pass@1 (zero-shot, no healing) | 11/40 = **27.5%** |
| Pass@Healed (after retries) | 13/40 = **32.5%** |
| Healing gain | **+5.0 pp** |
| Failed attempts | 83 (`general_exception` 35, `missing_input` 31, `schema_misuse` 17) |

> **Executability is not correctness.** A script can finish with exit code 0 and still produce the wrong map. Gate 2 does not yet validate geospatial output, so these numbers must not be read as accuracy. At least 5 of the 13 "passes" in this run are semantically wrong — for example, `tc_17` computes "NDVI" from `elevation` and `elevation_shade`, and `tc_24` calls `r.external_out` without exporting `elevation.tif`.

### What the first run found

The full breakdown is in [`benchmarks/execution_report.md`](benchmarks/execution_report.md) and [`benchmarks/leakage_report.md`](benchmarks/leakage_report.md).

- **18 of 27 unhealed cases were not repairable by code editing.** The prompts reference maps or columns that do not exist in the North Carolina dataset or the declared fixtures (`parcels`, `bathymetry`, `landcover`, `canopy_density`, `rain_01`…`rain_12`, `northern_dem`, etc.). The model cannot invent data.
- **The repair loop was mostly a no-op.** 37 of 54 repair turns (69%) produced byte-identical code, and 14 of 27 failed cases never changed code at all. If attempt 2 repeats attempt 1, attempt 3 receives the same prompt and repeats it again.
- **Some errors hid their own cause.** For nested `r.drain` failures, the repair prompt received the outer `CalledModuleError` wrapper instead of the inner `ERROR: No start point(s) specified` line.
- **Repair is anchored to the failing tool, not the intended tool.** When the model picked the wrong tool, the loop kept retrieving documentation for that wrong tool and never escaped the local minimum (`tc_28` never reached `v.to.db`; `tc_35` never reached `v.surf.rst`).
- **Harness conditions consumed budget.** `v.buffer` over the full NC streams layer takes ~188 s and `r.slope.aspect` ~101 s, so the 120 s timeout is too low. `d.rast` has no monitor in headless mode. `tc_24`, `tc_25`, and `tc_30` declare their expected *outputs* as auxiliary inputs, which causes an "already exists" collision during staging.

The prioritised fixes are: provision or alias the missing dataset inputs; remove outputs from `auxiliary_inputs`; raise the per-attempt timeout; add output-level assertions; detect no-op repairs and force a different strategy; pass attempt history to the repair prompt; extract the innermost GRASS error; add a semantic linter for the recurring API mistakes; and retrieve documentation for both the failing tool and the task's intended tool.

### Reproducing

Gate 2 requires GRASS 8.4+ and the North Carolina sample dataset, provisioned once per [`benchmarks/fixtures/README.md`](benchmarks/fixtures/README.md). Then:

```bash
.venv/bin/python benchmarks/run_execution.py \
  --model qwen2.5-coder:7b \
  --max-retries 2 \
  --timeout 120
```

Use `--clean` to resample from scratch, `-k tc_01,tc_02` to run selected cases, and `--report-only` to regenerate the report from persisted results.

---

## Quickstart & CLI Usage

### Environment setup

```bash
git clone git@github.com:polucifier/grass-agent.git
cd grass-agent

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Local models (synthesis + embeddings)
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
```

`data/grass_knowledge.db` ships with the repository — no build step is required. To rebuild it from the GRASS 8.6 manual, run `.venv/bin/python scripts/build_knowledge_base.py`.

For GPU execution, `benchmarks/run_remote.sh` provisions a Colab instance end to end: Ollama and the models, GRASS GIS (`grass-core` from the UbuntuGIS PPA — 8.4+, since the harness needs `--tmp-mapset`), the North Carolina sample dataset with its `PERMANENT` write guard, and the Python dependencies. It then runs the test suite (or, with `bash benchmarks/run_remote.sh eval`, the Gate 1 evaluation). It installs `zstd` first, because the Ollama installer refuses to extract without it and stock Colab images do not ship it.

### Single-query generation

```bash
.venv/bin/python generate.py "create a 200-meter buffer around the stream network lines"
# → generated/create_a_200_meter_buffer_around_the_stream_network_lines.py
```

```bash
.venv/bin/python generate.py --print "compute slope from the elevation raster and generate 10m contour lines"
```

```python
from grass.tools import Tools
tools = Tools()

slope_output = "slope_output"
tools.r_slope_aspect(elevation="elevation", slope=slope_output)

contour_output = "contour_output"
tools.r_contour(input="elevation", output=contour_output, step="10")
```

### Running the benchmarks

```bash
# Tier 1 (default suite)
.venv/bin/python benchmarks/run_eval.py --model qwen2.5-coder:7b

# Tier 2
.venv/bin/python benchmarks/run_eval.py --suite benchmarks/benchmark_prompts_tier2.json --model qwen2.5-coder:7b
```

Artifacts are written to `benchmarks/output/` for every case, pass or fail, each prefixed with the commented prompt and raw response.

Gate 2 executes those scripts against a real GRASS dataset and retries failures:

```bash
# Requires GRASS 8.4+ and the NC sample dataset; see benchmarks/fixtures/README.md
.venv/bin/python benchmarks/run_execution.py --model qwen2.5-coder:7b

# Selected cases, from scratch, with a longer execution timeout
.venv/bin/python benchmarks/run_execution.py -k tc_01,tc_02 --clean --timeout 300

# Regenerate benchmarks/execution_report.md without re-running anything
.venv/bin/python benchmarks/run_execution.py --report-only
```

Per-case artifacts are written to `benchmarks/output_execution/` (gitignored); the aggregate report is tracked at `benchmarks/execution_report.md`.

### CLI reference

```text
usage: generate.py [-h] [-o OUTPUT] [--model MODEL] [--print] request

positional arguments:
  request               Natural language description of the GRASS task

options:
  -o, --output OUTPUT   Output file path (default: generated/<slug>.py)
  --model MODEL         Override the Ollama model
  --print               Print code to stdout instead of writing a file

usage: run_eval.py [-h] [--model MODEL] [-s SUITE]

options:
  --model MODEL         Ollama model (qwen2.5-coder:3b | qwen2.5-coder:7b)
  -s, --suite SUITE     Path to the benchmark JSON test suite
                        (default: benchmarks/benchmark_prompts_tier1.json)

usage: run_execution.py [-h] [--model MODEL] [-s SUITE] [-k CASE]
                        [--dataset DATASET] [--max-retries N] [--timeout N]
                        [--clean] [--resume | --no-resume] [--report-only]

options:
  -s, --suite SUITE     Benchmark suite (default: both tiers)
  -k, --case CASE       Comma-separated case ids, e.g. tc_01,tc_11
  --dataset DATASET     GRASS project directory (default: auto-detect)
  --max-retries N       Repair budget per case (default: 2)
  --timeout N           Per-attempt wall-clock bound in seconds (default: 120)
  --clean               Wipe output_execution/ and run from scratch
  --report-only         Re-render the report from persisted results
```

---

## Repository Layout

```text
grass-agent/
├── generate.py                       CLI entry point
├── code_generator.py                 Stages 3 + 4: prompt, synthesis, verification
├── rag_retriever.py                  Stage 2: hybrid retrieval
├── llm_provider.py                   Ollama chat + embeddings
├── config.py                         Environment-driven settings
├── data/grass_knowledge.db           543 tools + 768-d embeddings (committed)
├── grass_agent/                      Gate 2: executor, classifier, healing, fixtures, reporting
├── benchmarks/
│   ├── run_eval.py                   Gate 1 static evaluation runner
│   ├── run_execution.py              Gate 2 execution + self-healing harness
│   ├── execution_report.md           Gate 2 aggregate report (tracked)
│   ├── leakage_report.md             Benchmark contamination audit
│   ├── benchmark_prompts_tier1.json  10-case smoke suite
│   ├── benchmark_prompts_tier2.json  30-case advanced suite
│   ├── fixtures/                     Auxiliary inputs + NC dataset provisioning guide
│   ├── run_remote.sh                 Colab provisioning
│   ├── output/                       Gate 1 artifacts (gitignored)
│   └── output_execution/             Gate 2 per-case artifacts (gitignored)
├── scripts/                          Knowledge-base build, leakage audit, figures
├── tests/                            Unit + integration tests (pytest)
├── specs/001-pure-script-generation/ Gate 1 specification and research
├── specs/002-runtime-self-healing-harness/  Gate 2 specification and tasks
└── thesis/                           Thesis sources
```

---

## Configuration

All settings are environment variables, resolved by `GenerationConfig.from_env()` (Gate 1) and `ExecutionConfig.from_env()` (Gate 2).

| Variable | Default | Description |
|---|---|---|
| `GRASS_OLLAMA_MODEL` | `qwen2.5-coder:7b` | Ollama chat model for synthesis |
| `GRASS_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `GRASS_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `GRASS_RAG_DB` | `data/grass_knowledge.db` | Knowledge base path |
| `GRASS_RAG_TOP_K` / `RAG_TOP_K` | `5` | Tool documents supplied to the model |
| `GRASS_OUTPUT_DIR` | `generated` | Output directory for generated scripts |
| `GRASS_MAX_RETRIES` | `2` | Gate 2 unified repair budget per case |
| `GRASS_EXEC_TIMEOUT` | `120` | Gate 2 per-attempt execution timeout (seconds) |
| `GRASS_DATASET_PROJECT` | auto-detect | GRASS project used for Gate 2 execution |
| `GRASS_FIXTURES_DIR` | `benchmarks/fixtures` | Auxiliary input directory |
| `GRASS_OUTPUT_EXEC_DIR` | `benchmarks/output_execution` | Gate 2 per-case artifact directory |

Retrieval tuning constants live at the top of `rag_retriever.py`: `CATEGORY_BOOST = 0.2`, `LEXICAL_BOOST = 0.4`, `WRAPPER_BONUS = 0.6`, `MAX_PER_STEP = 1`.

---

## Provenance, Reproducibility & Known Limitations

**Benchmark immutability.** The prompt suites are treated as immutable: they represent realistic user input, and behavioural changes belong in `code_generator.py`, `SYSTEM_PROMPT`, or the retrieval configuration. The three widened disjunctions in Tier 2 (`tc_23`, `tc_27`, `tc_34`) are the deliberate and documented exception — in each the engine produced a correct answer and the assertion was too narrow.

**What is verified, and what is not.**

| Checked | Not checked |
|---|---|
| Python syntax; zero-chat compliance (Gate 1) | Whether the script produces correct *results* |
| Module and parameter names exist in the knowledge base (Gate 1) | Whether the chosen tool is semantically right for the request |
| Required parameters present (Gate 1) | Whether argument *values* are sensible (e.g. `distance=200`) |
| Script executes to completion in a live GRASS session (Gate 2) | Whether units, CRS, and geospatial output are correct |
| Failure mode and failing tool classified (Gate 2) | Whether the output map/table contains the expected values |
| Persistent `PERMANENT` mapset unchanged (Gate 2) | — |

A script that executes cleanly can still be semantically wrong. Gate 2 moves the boundary from "well-formed" to "runs", but it is not yet a correctness oracle.

**Other limitations.**

- **No output validation.** Gate 2 checks exit status and runtime failure modes, not whether the resulting map, table, or geometry is correct. At least 5 of the 13 Gate 2 passes in the recorded run are semantically wrong.
- **Dataset coverage.** Several benchmark prompts reference maps or columns that are absent from the North Carolina dataset or fixtures. Those cases are unhealable by code editing and should be provisioned or rewritten before quoting the Pass@Healed figure.
- **Bounded, one-step repair memory.** Each retry receives only the immediately previous script and error. There is no cumulative attempt history and no no-op detection, so identical repairs are common.
- **Placeholders.** Gate 1 examples still use placeholder map names and assume an already-initialised GRASS session; Gate 2 supplies the session and inventory.
- **Determinism.** LLM output is not reproducible between runs. See the caveat under Diagnostic Failure Analysis.
- **Suite size.** 40 cases is a small sample; individual case outcomes move between runs.
- **Model dependence.** 3B (8–10/10 observed) is not a drop-in substitute for 7B (9–10/10 observed) on Tier 1, and it fails `tc_10` on every warm run measured.

---

## License

[MIT](LICENSE) — Copyright (c) 2026 Mykhailo Radchenko
