# Implementation Plan: Gate 2 — Headless Runtime Execution & Autonomous Self-Healing Harness

**Branch**: `002-runtime-self-healing-harness` | **Date**: 2026-10-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-runtime-self-healing-harness/spec.md`, plus ratified architectural decisions 1–5 from the user.

## Summary

Gate 2 adds a live-execution and bounded self-healing layer on top of the existing Gate 1 generation pipeline. Every LLM-generated script is statically validated against `data/grass_knowledge.db` (unchanged Gate 1 barrier), then executed in a throwaway GRASS mapset inside a real headless GRASS session, launched as a subprocess so a C-level crash cannot kill the harness. Failures — static rejections *and* runtime tracebacks — are classified into one of four modes by a fixed precedence chain and fed back to the local model together with the verbatim error, the prior code, the original task, and re-retrieved documentation for the tool named in the failure. Results are persisted atomically per case so interrupted 40-case runs resume at case granularity, and a single markdown report compares Gate 1 static validity against Gate 2 live runtime success.

The technical approach is dictated by three VERIFIED environment findings that materially shape the design and are recorded in [research.md](./research.md):

1. `--tmp-mapset` creates a **writable default mapset, not a sandbox** — a script can `g.mapset PERMANENT` and mutate it. PERMANENT immutability therefore requires an explicit filesystem-level guard, not merely the temp mapset.
2. The `grass --exec` wrapper **destroys signal information** (SIGSEGV surfaces as exit 245, indistinguishable from `sys.exit(245)`), so crash detection needs a forked status-reporting inner wrapper rather than exit-code heuristics.
3. SIGTERM/SIGKILL leave **leaked `tmp_<uuid>` mapsets and `.gislock` files** that GRASS cannot clean up (cleanup is `atexit`-based). A post-run sweep is mandatory to satisfy FR-006/SC-004.

## Technical Context

**Language/Version**: Python 3.13 (project venv at `.venv/`, interpreter `/usr/bin/python3` for GRASS child sessions)

**Primary Dependencies**: `ollama` 0.6.2 (local inference; `qwen2.5-coder:7b` evaluation, `qwen2.5-coder:3b` smoke), `sqlite-vec` 0.1.9 (retrieval over `data/grass_knowledge.db`, 543 tools), GRASS GIS 8.5.0 at `/usr/lib64/grass85`, stdlib `ast`/`subprocess`/`re`

**Storage**: Filesystem only. GRASS database (`GISDBASE` + project dir, one `PERMANENT` per dataset), fixture directory `benchmarks/fixtures/`, per-case artifact tree `benchmarks/output_execution/<tc_id>/`. Existing `data/grass_knowledge.db` is read-only.

**Testing**: `pytest` 9.1.1 (available in `.venv/`). No test suite exists yet; Gate 2 introduces the first one. Unit tests target classification, precedence, atomicity, and resumption; integration tests target one real GRASS execution.

**Target Platform**: Linux server, GRASS 8.5.x, offline host with a local Ollama service. Verified host: GRASS 8.5.0 at `/usr/lib64/grass85`, `/usr/bin/grass`, `~/.ollama/models` contains both `qwen2.5-coder:3b` and `:7b` plus `nomic-embed-text`.

**Project Type**: CLI (benchmark evaluation harness)

**Performance Goals**: Per-attempt execution wall-clock bound of 120 s (default `--timeout`, configurable). Raised from an initial 60 s after measurement showed a single `r.slope.aspect` over the full NC elevation DEM takes 62–81 s, so 60 s killed correct heavy raster work and misclassified it as a timeout. Suite of 40 cases × up to 3 attempts. Total runtime dominated by local 7b inference — the prior Gate 1 run's own `ollama.log` shows ~42 s for a 589-token generation, so budget minutes per attempt, not seconds.

**Constraints**: 100% offline (no network egress at any point in the evaluation or healing path). Zero mutation of the persistent `PERMANENT` mapset. Generated and repaired code must use `grass.tools` exclusively — `grass.script.run_command`, `gs.run_command`, and shell calls are rejected. Strict Zero-Chat output contract. Scratch cleanup guaranteed on success, error, and SIGINT. No parallel case execution (spec Out of Scope).

**Scale/Scope**: 40 benchmark cases (10 tier 1 + 30 tier 2). Artifacts: per-case script, every intermediate failed attempt, execution logs, machine-readable case result. One report file.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement | Gate Evaluation |
|---|---|---|
| I. Core Mission & Scope | Fully offline local AI agent; NL → executable GRASS Python; refer to the software as GRASS, never "GRASS GIS" | **PASS** — no network path is added; all wording uses "GRASS" |
| II. Technology Stack & API Standards | `grass.tools` only; no `run_command`/CLI; offline Ollama; `qwen2.5-coder:7b` primary, `:3b` smoke; `nomic-embed-text` for retrieval | **PASS** — FR-015 rejects legacy interfaces as a failed attempt; FR-016 forbids external services; reuses the existing provider and retriever unchanged |
| III. Zero-Chat & Pure Script Contract | Model output is executable Python only; no fences, prose, or explanations | **PASS** — FR-014 applies the contract to repair output too; repair output goes through the same `extract_python_code` path |
| IV. Phased Development Gates | Gate 2 = pre-flight guard, headless runtime execution, traceback interception/classification, autonomous bounded self-healing | **PASS** — FR-001/FR-001b, FR-003–FR-006, FR-007/FR-008/FR-008a, FR-009–FR-013 respectively. Sub-gate 2 mechanism ratified by constitution **v1.2.0** (see amendment note below); the four sub-gates and their ordering are unchanged |
| V. Code Quality & Pre-flight Execution Safety | Self-contained scripts with explicit imports; strongly typed keyword args; no positional or hallucinated params; **never execute against persistent production mapsets**; isolated ephemeral test mapsets only | **PASS, with a designed-in guard** — the temp mapset alone does not satisfy this (a script can `g.mapset PERMANENT`). Design adds a filesystem permission guard plus a content-hash assertion. See Complexity Tracking. |

**Gate result: PASS.** One Principle V hazard is real and is addressed by explicit design rather than waived — recorded below.

### Amendment: constitution v1.1.0 → v1.2.0 (Principle IV.2)

`/speckit.analyze` raised a CRITICAL finding: the plan's primary execution mechanism (the GRASS CLI `--tmp-mapset` sandbox) contradicted Principle IV.2's then-wording, which named `grass.script.setup.init()` exclusively — while scoring Principle IV as PASS without disclosure.

The engineering decision was correct and is now ratified in the constitution rather than reinterpreted. Verified rationale, recorded in the constitution's Sync Impact Report:

- `grass.script.setup.init()` has **no temp-mapset support** (research R4). It only validates and writes a gisrc.
- Hand-rolling a temp mapset through `init()` requires manually deleting the `.gislock` that `g.mapset -c` leaves behind, or the next `init(lock=True)` raises `MapsetLockingException`.
- The CLI sandbox provides cleaner process-group isolation and automatic cleanup on normal exit and SIGINT.
- `grass.script.setup.init()` is **retained as a fallback worker** (research D1/R4, task T009) for hosts where the CLI sandbox is unsupported.

Version bumped MINOR per the constitution's own governance rule (material expansion of an existing principle, not a backward-incompatible change). Affected component: spec 002 plan/tasks mechanism references. Migration: none — Gate 2 is unreleased, so no prior implementation depends on the superseded wording. The four Gate 2 sub-gates, their ordering, and Principle V's isolation mandate are unchanged.

### Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| An inner fork-based status-reporting wrapper is executed between `grass --exec` and the generated script | The `grass --exec` wrapper converts a child SIGSEGV into exit 245, which is byte-identical to `sys.exit(245)`. Without a surviving parent to `waitpid()` the child, a hard crash cannot be distinguished from an ordinary failure, so FR-008's general-exception category and SC-003 cannot be honoured. | Reading the exit code alone: VERIFIED ambiguous — `245` means either SIGSEGV or a legitimate `exit(245)`. The wrapper writes a status file from a parent that outlives the crash, making the signal unambiguous. |
| Post-run sweep deletes stray `tmp_<uuid>` mapsets and `TMPDIR` trees | GRASS registers temp-mapset cleanup via `atexit`, which does not run on SIGTERM or SIGKILL. VERIFIED leftovers containing `.gislock` survive, violating FR-006 and SC-004. | Trusting GRASS cleanup: VERIFIED false under signal termination. The harness owns a per-run `TMPDIR` and a pre/post snapshot of the project directory, so the sweep is precise rather than a blanket delete. |
| `chmod` write-bit removal on the `PERMANENT` directory as a runtime guard | `--tmp-mapset` gives a writable *default mapset*, not a sandbox. VERIFIED: a script calling `g.mapset PERMANENT` creates rasters that persist. Principle V and SC-002 require zero mutation, so a defense is needed beyond the temp mapset. | Relying on the temp mapset alone: VERIFIED insufficient. Removing the write bit was verified to still allow the full workload while causing `g.mapset PERMANENT` to fail; the project directory itself must stay writable because `--tmp-mapset` creates its mapset inside it. |
| Benchmark suite JSON files gain an optional `auxiliary_inputs` field per case | FR-001b requires declared per-case auxiliary inputs; FR-022 of the clarification session requires the harness to stage them and never synthesise undeclared ones. | Generating placeholder data on demand was explicitly rejected in clarification Q2 — it would mask genuine agent errors by making every referenced file exist. |

## Project Structure

### Documentation (this feature)

```text
specs/002-runtime-self-healing-harness/
├── spec.md              # Ratified specification (from /speckit.specify + /speckit.clarify)
├── plan.md              # This file (/speckit.plan output)
├── research.md          # Phase 0 output — VERIFIED environment findings and decisions
├── data-model.md        # Phase 1 output — entities, artifacts, state machine
├── quickstart.md        # Phase 1 output — runnable end-to-end validation guide
├── contracts/
│   ├── cli.md           # run_execution.py command-line contract
│   └── case-result.md   # case_result.json schema + atomicity/resumption contract
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit.specify)
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
benchmarks/
├── run_execution.py          # NEW — Gate 2 CLI entry point; orchestration
├── fixtures/                 # NEW — auxiliary input registry (FR-001b)
│   ├── points.geojson
│   ├── boundary.geojson      # + .prj equivalent via CRS note, or .shp/.shx/.dbf set
│   └── README.md             # provenance, CRS, which cases use which fixture
├── benchmark_prompts_tier1.json   # MODIFIED — add "auxiliary_inputs": [] per case
├── benchmark_prompts_tier2.json   # MODIFIED — add "auxiliary_inputs" where needed
└── output_execution/         # NEW — per-case artifact tree (FR-019); layout in data-model.md §9

grass_agent/                 # NEW — harness internals (importable, unit-testable)
├── __init__.py
├── config.py               # ExecutionConfig, from_env(), dataset auto-detection
├── preflight.py            # FR-023 dependency checks; exit-code contract
├── executor.py             # GRASS subprocess launch, timeout, process-group kill, sweep
├── inner_wrapper.py        # fork+waitpid status reporter (copied into the GRASS child)
├── fallback_worker.py      # grass.script.setup.init() worker for CLI-unsupported hosts
├── classifier.py           # ordered failure-mode signatures + precedence resolution
├── fixtures.py             # fixture discovery, CRS-aware staging into scratch
├── results.py              # atomic case_result.json read/write, resume keying
├── healing.py              # unified retry loop + targeted RAG re-query + repair prompt
└── reporting.py            # Gate 1 vs Gate 2 markdown report generation

benchmarks/execution_report.md   # NEW — Phase 1 output artifact (FR-020)

tests/                      # NEW — first test suite in the project
├── conftest.py             # dataset resolution, GRASS availability, `slow` marker
├── test_classifier.py      # ordered signature matching, precedence, real GRASS strings
├── test_results.py         # atomic write, torn-file recovery, resume keying
├── test_executor.py        # timeout, crash detection, cleanup sweep, offline + legacy-interface assertions
├── test_fixtures.py        # staging, undeclared-file refusal
├── test_cli_contract.py    # every flag, default, and interaction from contracts/cli.md
├── test_healing.py         # unified budget accounting, repair-prompt assembly
├── test_reporting.py       # report aggregation and rendering
├── test_integration_smoke.py  # one real GRASS execution, marked slow
└── test_integration_heal.py   # healing loop with a stubbed model
```

> **The per-case artifact directory layout is specified in exactly one place: [data-model.md](./data-model.md) §9.** It is deliberately not duplicated here — a second copy drifted once already, omitting the mandatory `attempt_<n>.stdout` / `attempt_<n>.stderr` files that the resume contract requires.

**Structure Decision**: The existing project is flat (`config.py`, `llm_provider.py`, `rag_retriever.py`, `code_generator.py` at root, `benchmarks/` holding the Gate 1 runner). Gate 2 adds a `grass_agent/` package of ten cohesive, independently testable modules that do not belong at root and would otherwise be un-importable from `benchmarks/run_execution.py` without path hacks. The package splits along the dependency order the harness actually runs in: `config` → `preflight` → `executor`/`inner_wrapper`/`fallback_worker` (the execution boundary) → `classifier`/`fixtures` (per-attempt concerns) → `results` (persistence) → `healing` (the retry loop) → `reporting` (aggregation). `grass_agent/config.py` is distinct from the root `config.py`: the latter remains Gate 1's `GenerationConfig` and is imported unchanged, while the former carries execution settings and its own `from_env()`. `benchmarks/run_execution.py` stays at the path named in the user's architectural decisions and in the spec, and becomes a thin CLI over `grass_agent/`. Existing root modules are **imported and reused unchanged** — no edits to `code_generator.py`, `rag_retriever.py`, or the root `config.py` are planned.

The `tests/` tree above is the full set; `tasks.md` is authoritative if the two ever diverge, since it carries the task-level detail.

One planned change to an existing module: `llm_provider.py` gains an **additive** `chat_with_stats()` returning `(text, stats)`, because FR-018/SC-008 require per-attempt token accounting that `OllamaProvider.chat` currently discards (`llm_provider.py:15` returns only `response.message.content`). The existing `chat()` is left untouched so the Gate 1 caller at `code_generator.py:118` keeps working — research decision D11.

Two clarifications to the directory tree above, resolved during Phase 1:

- **`inner_wrapper.py` ships in `grass_agent/`** and is *copied* into each case's scratch directory at execution time. It must exist as a real file inside the GRASS session, not as an importable module, because it runs under GRASS's injected `PYTHONPATH` (D3, research R2/R5).
- **Captured streams get their own files.** `attempt_<n>.stdout` and `attempt_<n>.stderr` are retained verbatim alongside a combined human-readable `attempt_<n>.log`, so FR-007's "capture stdout and stderr" is materially inspectable and the classifier operates on the same bytes the report cites (contract `case-result.md`, invariant I8).

## Phase 0: Research

Full findings in [research.md](./research.md). Summary of decisions:

| # | Decision | Rationale | Alternatives rejected |
|---|---|---|---|
| D1 | Launch via `grass --tmp-mapset <project>/ --exec python3 <inner_wrapper> <status.json> <script>` | VERIFIED working. Temp mapset inherits a copy of PERMANENT's `DEFAULT_WIND` and sees PERMANENT maps read-only through the normal search path, so NC data is reachable while writes land in the temp mapset. | `--tmp-project EPSG:3358`: creates a fresh empty project with a different `GISDBASE`, so NC data is invisible and would need re-import per run. Hand-rolled `init()` + `g.mapset -c`: VERIFIED requires manually deleting the `.gislock` that `g.mapset -c` leaves behind, else the next `init(lock=True)` raises `MapsetLockingException`. Retained only as the CLI-unsupported fallback. |
| D2 | Read `grass --config path`/`python_path` at runtime; invoke plain `python3` | VERIFIED: `--exec` uses `Popen(..., shell=False, env=os.environ)`, so plain `python3` runs and GRASS injects `PYTHONPATH=/usr/lib64/grass85/etc/python`, which is *why* `import grass.tools` works. `GRASS_PYTHON` does not affect `--exec`. | Passing a GRASS-specific interpreter: `GRASS_PYTHON` is only consulted for `wxgui.py`. There is no bare `python` on this host — VERIFIED `--exec python` fails with ENOENT. |
| D3 | Fork-based inner wrapper writes a status JSON; classify crash from it | VERIFIED: `grass --exec` maps SIGSEGV→245, SIGABRT→250, SIGKILL→247, all indistinguishable from real exit codes of the same value. A parent that `waitpid()`s the child survives the crash and records `WIFSIGNALED`/`WTERMSIG`. | `returncode < 0`: VERIFIED unreachable through `grass --exec`. `256 - rc` heuristic: VERIFIED ambiguous. `faulthandler.register(11, ...)`: VERIFIED raises `RuntimeError: signal 11 cannot be registered`. |
| D4 | `start_new_session=True` + `os.killpg` on timeout, SIGTERM then SIGKILL after grace | VERIFIED: timing out or killing only the `grass` process orphans the Python child and its grandchildren, and `communicate()` blocks for the child's full duration (measured 60.1 s against a 3 s budget). `killpg` returned in 3.0 s with no orphans. | `Popen.kill()` / `subprocess.run(timeout=)`: VERIFIED kills only the wrapper. `grass --timeout N`: VERIFIED this is a *mapset lock acquisition* timeout — an 8 s job under `--timeout 2` completed normally. The `--timeout` budget is enforced by the harness, not by GRASS. |
| D5 | PERMANENT immutability = drop the write bit on the `PERMANENT` dir + assert a content hash before/after every run | VERIFIED: with the write bit removed, the full workload ran with PERMANENT unchanged and `g.mapset PERMANENT` failed non-zero. A tree content hash was byte-identical across read and write workloads. | Temp mapset alone: VERIFIED insufficient — a created raster persisted. Read-only *project* dir: VERIFIED fails with `PermissionError` because `--tmp-mapset` mkdirs inside the project. |
| D6 | Post-run sweep: diff project-dir `tmp_*` entries against a pre-run snapshot (filtered by run start time) and delete; delete the per-run `TMPDIR` | VERIFIED: SIGTERM/SIGKILL leak `tmp_<uuid>/` with `.gislock` plus `/tmp/grass8-<user>-<pid>`. `TMPDIR` is honored by GRASS, so it can be owned per run. The leaked lock is always inside the temp mapset, never PERMANENT, so it cannot block future sessions. | Blanket `rmtree` of all `tmp_*`: unsafe under concurrent runs. Trusting `atexit`: VERIFIED does not fire on SIGTERM/SIGKILL. |
| D7 | Classification anchors on the bare message body, never on a literal `ERROR: ` prefix | VERIFIED: `grass.tools` raises `ToolError`, and for single-line stderr its message has the `ERROR: ` prefix **stripped**. Multi-line stderr keeps it. A pattern anchored on `ERROR:` would miss every single-line case. | Anchoring on `ERROR:` for category 1 and 2 — would silently under-count. |
| D8 | Test `AttributeError`/missing-method signatures **before** the map/parameter signatures | VERIFIED: `Tools.__getattr__` raises a plain `AttributeError` with `Tool <name> (<dotted>) not found (but found ...)` or `Tool or attribute <name> (<dotted>) not found (...)`. The wording never contains an `ERROR:` line and never collides with `ToolError` text, so testing it early is collision-free. | Applying the spec's literal precedence to match order — would misfile every `AttributeError` into the general catch-all. Precedence is preserved over the *content* categories; the missing-method signatures are matched first because they are categorically disjoint. Recorded as a deliberate, testable ordering decision in `classifier.py`. |
| D9 | Force `LANG`/`LC_ALL` to a fixed English locale for all child runs; normalise continuation-line indentation before matching | VERIFIED: `LANG=de_DE.UTF-8` localises `ERROR: Raster map <nope> not found` into German and `LANGUAGE=en` does **not** override it. GRASS hard-wraps at ~72 chars with a 7-space continuation indent, splitting messages mid-sentence. | Relying on host locale: VERIFIED breaks classification under a non-English host. Matching raw multi-line text: VERIFIED fails on wrapped messages. |
| D10 | Dataset bootstrap is a separate, explicitly-flagged prerequisite | VERIFIED absent: no `nc_basic_spm*` anywhere, `~/grassdata` empty, `grass-sample-data` not installed, no bundled geofile, and `r.in.nc` is absent so no NetCDF construction path exists. `nc_basic_spm_grass8.zip` returns **404**; `nc_basic_spm_grass7.zip` (50 MB) is the live URL and loads in 8.5. | Assuming the dataset is present: it is not, and FR-023 requires a clear non-zero exit naming the missing dependency. `grass -c EPSG:3358` reproduces the exact NC CRS but yields an empty project with no data. |
| D11 | Extend `OllamaProvider` with a non-breaking `chat_with_stats` rather than changing `chat` | Token accounting is required by FR-018/SC-008, but `OllamaProvider.chat` returns only `response.message.content`. The Ollama response object also carries `prompt_eval_count` and `eval_count`. | Mutating `chat`'s return type: would break the existing Gate 1 caller in `code_generator.py:118`. |

## Phase 1: Design & Contracts

- **[data-model.md](./data-model.md)** — entities (`BenchmarkCase`, `Attempt`, `AttemptOutcome`, `FailureMode`, `CaseResult`, `RunSummary`), the artifact directory layout, the attempt state machine, the resume-key composition, and the atomic write protocol.
- **[contracts/cli.md](./contracts/cli.md)** — the `run_execution.py` command-line contract: every flag (`--resume`, `--clean`, `--reuse-artifacts`, `--max-retries`, `--timeout`, plus inherited `--model`/`--suite`), defaults, precedence between `--clean` and `--resume`, exit codes, and the pre-flight dependency checks behind FR-023.
- **[contracts/case-result.md](./contracts/case-result.md)** — the `case_result.json` schema, field-by-field semantics, the atomic write/torn-file recovery protocol behind FR-006a, and the resume-matching rules behind SC-019.
- **[quickstart.md](./quickstart.md)** — prerequisites (Ollama running, NC dataset present), a single-case smoke run, the zero-shot baseline run, the healed run, and how to verify each success criterion end to end.

### Constitution Re-check (post-design)

| Principle | Post-design status |
|---|---|
| II (stack) | **PASS** — D11 extends the provider additively; `code_generator.py` is untouched. `--reuse-artifacts` loads Gate 1 `.py` files as attempt 1 and records zero tokens (FR-001a, SC-015). |
| III (Zero-Chat) | **PASS** — repair output reuses `extract_python_code`; a repair response that yields no parseable script is a failed attempt, not a harness error. |
| IV (gates) | **PASS** — all four Gate 2 sub-gates map to explicit FRs. |
| V (execution safety) | **PASS** — D5 (permission guard + content-hash assertion) and D6 (post-run sweep) together satisfy the "never execute against persistent production mapsets" mandate and SC-002/SC-004, closing the gap D1 alone would leave. |

**Post-design gate result: PASS.** No complexity violations remain unjustified.