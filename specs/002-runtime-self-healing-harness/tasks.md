---

description: "Task list for Gate 2 — Headless Runtime Execution & Autonomous Self-Healing Harness"
---

# Tasks: Gate 2 — Headless Runtime Execution & Autonomous Self-Healing Harness

**Input**: Design documents from `/specs/002-runtime-self-healing-harness/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md, contracts/case-result.md, quickstart.md

**Tests**: Test tasks ARE included. plan.md commits to a `tests/` package as this project's first test suite, and quickstart.md defines ten runnable validation scenarios. Write tests before the implementation they cover and confirm they fail first.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Single project, repository root. New: `grass_agent/` package, `tests/` package, `benchmarks/run_gate2.py`. Existing modules `config.py`, `code_generator.py`, `rag_retriever.py` are imported unchanged.

## Critical Constraints Carried From Design Documents

These are verified environment facts from research.md. Violating them produces silently wrong results.

- **`grass --exec` masks signals.** A child SIGSEGV surfaces as exit code `245`, byte-identical to `sys.exit(245)`. Never infer a crash from an exit code — read the inner wrapper's `status.json`.
- **`--tmp-mapset` is not a sandbox.** A generated script can call `g.mapset PERMANENT` and write there. The `chmod -w` guard on `PERMANENT` is what makes SC-002 hold.
- **GRASS temp-mapset cleanup is `atexit`-based.** SIGTERM and SIGKILL leave `tmp_<uuid>` mapsets with `.gislock` behind. A post-run sweep is mandatory, not defensive padding.
- **`grass --timeout` is a mapset LOCK timeout, not an execution timeout.** The `--timeout` budget is enforced by the harness via `communicate(timeout=)` plus `killpg`. Never forward it to `grass --timeout`.
- **`ToolError` strips the `ERROR: ` prefix** from single-line stderr. Classification patterns must anchor on the bare message body.
- **`'Tools' object has no attribute 'x'` never occurs on GRASS 8.5.** The real wording is `AttributeError: Tool <name> (<dotted>) not found`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Create `grass_agent/` package directory with empty `__init__.py`
- [x] T002 [P] Create `tests/` package directory with empty `__init__.py`
- [x] T002a [P] Create `tests/conftest.py` with shared fixtures: dataset-path resolution (delegating to `grass_agent.config.ExecutionConfig.dataset_project` auto-detection), a `grass_available` check that skips when `grass --version` fails, and a `require_dataset` fixture that skips when no standard NC dataset is found. Provide an `apply_slow_marker` autouse hook honouring the `slow` marker registered in T004
- [x] T003 [P] Create `benchmarks/fixtures/` directory for auxiliary input files
- [x] T004 [P] Create `pytest.ini` pinning `testpaths = tests` and registering a `slow` marker for tests that need a live GRASS session and dataset
- [x] T005 [P] Add `benchmarks/output_execution/` and `benchmarks/fixtures/*.tmp` to `.gitignore`
- [x] T006 [P] Create `benchmarks/fixtures/README.md` documenting, in one file: each fixture's provenance and CRS (EPSG:3358, matching `nc_basic_spm_grass8`); which benchmark cases declare it; **and** the one-time NC dataset prerequisite — `nc_basic_spm_grass8.zip` returns **404**, the live URL is `nc_basic_spm_grass7.zip` (50 MB, loads in GRASS 8.5 despite the name), provisioned manually by a human, with the harness never performing the fetch (FR-016)

**Checkpoint**: Directory skeleton exists, `pytest` collects zero tests cleanly, no project code touched yet

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. US1, US2, and US3 all depend on the classifier, the executor, and atomic result persistence.

### Environment discovery and pre-flight

- [x] T007 Implement `grass_agent/config.py` with a frozen `ExecutionConfig` dataclass: `model`, `max_retries` (default 2), `timeout_s` (default 120, raised from 60 after measurement showed `r.slope.aspect` over the full NC DEM takes 62–81 s), `attempt1_source` (`fresh` | `reuse_artifacts`), `resume`, `dataset_project`, `fixtures_dir`, `output_dir`, `knowledge_db`, `grass_bin`, `python_bin`, `ollama_base_url`. Resolve GRASS paths at runtime via `grass --config path` and `grass --config python_path` — never hard-code `/usr/lib64/grass85`
- [x] T007a Implement `ExecutionConfig.from_env()` in `grass_agent/config.py` reading `GRASS_OLLAMA_MODEL`, `GRASS_OLLAMA_BASE_URL`, `GRASS_RAG_DB`, `GRASS_DATASET_PROJECT`, `GRASS_EXEC_TIMEOUT`, `GRASS_MAX_RETRIES`, `GRASS_FIXTURES_DIR`, and `GRASS_OUTPUT_EXEC_DIR`, mirroring the Gate 1 `GenerationConfig.from_env()` convention at `config.py:15-23`. CLI arguments override environment variables; environment variables override built-in defaults
- [x] T007b Implement dataset auto-detection in `grass_agent/config.py` per contracts/cli.md: when `dataset_project` is unset, search `$GISDBASE`, `$GRASSDATA`, `~/grassdata`, `./grassdata` in order for the first directory containing a `PERMANENT/` with `DEFAULT_WIND` and `PROJ_INFO`, matching either `nc_basic_spm_grass8` or `nc_spm_08_grass7`. Return the list of roots searched when nothing is found, so pre-flight can name them in its exit-`3` message (FR-023)
- [x] T008 Implement `grass_agent/preflight.py` with one check per FR-023 dependency: GRASS installation, `--tmp-mapset` support, dataset project validity, local model service reachability, knowledge base readability, declared fixtures resolvable, reuse-artifacts directory when `--reuse-artifacts`. Each failure returns the missing dependency's name. Exit codes per contracts/cli.md: `2` argument error, `3` missing dependency, `1` harness fault
- [x] T009 Implement the `grass.script.setup.init()` fallback worker in `grass_agent/fallback_worker.py` for hosts where `--tmp-mapset` is unsupported: `init(gisdb, location=..., mapset="PERMANENT")` → `g.mapset -c mapset=tmp_<uuid>` → **manually remove the `.gislock` that `g.mapset -c` leaves behind** (research.md R4 — omitting this makes the next `init(lock=True)` raise `MapsetLockingException`) → `init(..., mapset=tmp_<uuid>, lock=True)` → work → `shutil.rmtree`

### Failure classification

- [x] T010 [P] Implement `grass_agent/classifier.py` with the four-value `FailureMode` enum: `missing_input`, `schema_misuse`, `unknown_method`, `general_exception` (FR-008). An unrecognised failure MUST assign `general_exception` rather than being dropped — 100% of failed attempts land in one of the four modes, with zero unclassified (SC-005)
- [x] T011 [P] Implement indentation normalisation in `grass_agent/classifier.py`: `re.sub(r"(?m)^[ \t]+", " ", combined)` applied before matching, because GRASS hard-wraps at ~72 chars with a 7-space continuation indent that splits messages mid-sentence
- [x] T012 Implement `classify()` in `grass_agent/classifier.py` with the **fixed precedence from contracts and research.md D8** (FR-008a): test `unknown_method` signatures first (they are collision-free with `ToolError` text), then `missing_input` → `schema_misuse` → `general_exception` catch-all. Must be deterministic and idempotent — identical captured output yields an identical mode every time (SC-005a)
- [x] T013 Implement the `missing_input` signature set in `grass_agent/classifier.py` covering every verbatim string in research.md R7 §1: `Raster map <x> not found`, `Vector map <x> not found`, `... not found in current mapset`, `Database connection not defined for layer <n>`, `Mapset <x> does not exist`, `Space time raster dataset <x> not found`, `Invalid map <x>`, `Unable to read input from <x>`, `Unable to open input file <x>`, `Unable to open datasource <x>`, and GDAL's bare `ERROR <n>: <path>: No such file or directory`. Must also match a missing table reported as `WARNING:` with rc=1, and must NOT require a literal `ERROR: ` prefix
- [x] T014 Implement the `schema_misuse` signature set in `grass_agent/classifier.py`: `Required parameter <x> not set` in both the colon and no-colon variants, `Sorry, <x> is not a valid parameter`, `Sorry <x> is not a valid option`, `Value <x> out of range for parameter <y>`, `option <x>: <y> exists. To overwrite`, mutually-exclusive-option errors, and `Parse error`. Evaluate the `Invalid map <x>` pattern before `Parse error` so `r.mapcalc` resolves correctly
- [x] T015 Implement the `unknown_method` signature set in `grass_agent/classifier.py` against the **actual** GRASS 8.5 wording: `AttributeError: Tool <name> (<dotted>) not found`, `AttributeError: Tool or attribute <name> (<dotted>) not found`, `OSError: Cannot find the executable <x>`, the resolver's positional-argument `TypeError`, and `module grass.tools has no attribute <x>`
- [x] T016 Implement `extract_failing_tool()` in `grass_agent/classifier.py` returning the tool name parsed from the error text to drive targeted RAG re-query (FR-011), and returning `None` when no tool is identifiable — callers must then fall back to querying with the error excerpt itself

### Subprocess execution

- [x] T017 Implement `grass_agent/inner_wrapper.py` as a standalone script (not an importable module — it runs under GRASS's injected `PYTHONPATH`): fork, `execv` the real script in the child, `waitpid` in the surviving parent, then atomically write `{"returncode", "status", "signal", "signal_name", "exit_code"}` to `status.json` via write-to-`.part`-then-`os.replace`. Re-raise the signal so the outer layer also observes it
- [x] T018 Implement `grass_agent/executor.py` building the launch command as `grass --tmp-mapset <project>/ --exec python3 <scratch>/inner_wrapper.py <scratch>/status.json <scratch>/attempt_<n>.py` (FR-003, FR-004). Invoke plain `python3` — bare `python` does not exist on this host, and `GRASS_PYTHON` does not affect `--exec`
- [x] T019 Implement child environment construction in `grass_agent/executor.py`: a **fixed English locale** (`LANG`/`LC_ALL`) because a German host locale translates GRASS error text into German and `LANGUAGE=en` does not override it (research.md D9); a fresh per-attempt `TMPDIR`, which GRASS honors, to contain session artifacts
- [x] T020 Implement timeout enforcement in `grass_agent/executor.py` using `subprocess.Popen(..., start_new_session=True)` plus `communicate(timeout=...)`, and on expiry `os.killpg(os.getpgid(pid), SIGTERM)` → 5 s grace → `killpg(SIGKILL)` (FR-022). Killing only the `grass` process orphans the Python grandchild and blocks `communicate()` for its full duration — measured 60.1 s against a 3 s budget (research.md R6)
- [x] T021 Implement `read_status()` in `grass_agent/executor.py` parsing `status.json` into an outcome of `executed_ok` / `runtime_failed` / `crashed` / `timeout` per data-model.md §3 (FR-007). `crashed` and `timeout` map to failure mode `general_exception`; `crashed` requires a non-null `signal_name`
- [x] T022 Implement the post-run cleanup sweep in `grass_agent/executor.py`: snapshot `<project>/tmp_*` before each attempt, delete the set difference filtered by run start time, and remove the attempt's `TMPDIR`. Do not blanket-delete all `tmp_*` — that is unsafe under concurrent runs
- [x] T023 Implement PERMANENT integrity verification in `grass_agent/executor.py`: a recursive content hash of the `PERMANENT` tree captured before and after every run, asserted equal (FR-005). A difference is a harness failure reported loudly, not a warning (SC-002)
- [x] T024 Implement the dataset write-bit guard in `grass_agent/executor.py`: drop the write bit on the dataset's `PERMANENT` directory. Verified: the workload still runs with `PERMANENT` unchanged and `g.mapset PERMANENT` then fails non-zero. The **project** directory must stay writable — `--tmp-mapset` mkdirs inside it and a read-only project raises `PermissionError`. This guard is a **permanent, documented property of the provisioned test dataset fixture** (see `benchmarks/fixtures/README.md`), not a per-run toggle: it is applied once at dataset provisioning and deliberately **not** reverted on teardown, so the dataset can never be mutated by any later Gate 1 or Gate 2 run. Provisioning scripts must `chmod -w` the mapset; no restore step exists or is wanted

### Atomic result persistence

- [x] T025 Implement `grass_agent/results.py` with the `Attempt`, `CaseResult`, and `RunSummary` dataclasses matching data-model.md §2, §5, and §10 field-for-field, including the exact enum values and nullable rules
- [x] T026 Implement atomic write in `grass_agent/results.py`: serialise to `case_result.json.part` in the same directory, `flush()` + `os.fsync()`, then `os.replace()` — atomic on POSIX. Then fsync the containing directory (FR-006a)
- [x] T027 Implement the resume-key match in `grass_agent/results.py` per contracts/case-result.md: a case is reusable only when `status == "complete"`, `schema_version` is recognised, `tc_id` matches, all four `resume_key` fields (`model`, `max_retries`, `timeout`, `attempt1_source`) match the current run, the file parses as JSON, invariants I1–I8 hold, and every referenced artifact path exists. Any failure discards the case and reruns it from attempt 1 (SC-019)
- [x] T028 Implement `.part` recovery in `grass_agent/results.py`: delete any `case_result.json.part` at startup unconditionally and never read it. A `JSONDecodeError` on `case_result.json` means torn write → treat as not reusable
- [x] T029 Implement the attempt-count guard in `grass_agent/results.py` asserting `len(attempts) ≤ max_retries + 1` (SC-017) and ordinals contiguous from 1 (invariant I2)
- [x] T030 Implement `RunSummary` aggregation in `grass_agent/results.py` computing Pass@1 (`attempts[0].outcome == "executed_ok"`), Pass@Healed (any `executed_ok`), per-mode failure counts, ordered failure-mode transitions, per-ordinal mean latency, and prompt/completion token totals. Per-mode counts must sum exactly to total failed attempts (SC-005a)

### Fixture staging

- [x] T031 Implement `grass_agent/fixtures.py` resolving a declared `auxiliary_inputs` entry to `benchmarks/fixtures/<name>`, expanding a shapefile stem to every sibling sharing it (`.shp`, `.shx`, `.dbf`, `.prj`), and rejecting absolute paths or `..` traversal after normalisation as a harness configuration error rather than a benchmark failure
- [x] T032 Implement staging in `grass_agent/fixtures.py`: copy resolved fixtures into the attempt's `scratch/` directory before execution. **Never synthesise a file** that is neither in the dataset nor declared — an undeclared reference must surface as a `missing_input` failure (clarification Q2, FR-001b)
- [x] T033 [P] Add `"auxiliary_inputs": []` to every test case in `benchmarks/benchmark_prompts_tier1.json` and `benchmarks/benchmark_prompts_tier2.json`, then populate the non-empty lists for cases referencing files absent from the dataset (e.g. `tc_11` needs `points.geojson`, `tc_25` needs the parcels file)

### Tests for Foundational

- [x] T034 [P] Unit test the classifier in `tests/test_classifier.py` against every verbatim GRASS string catalogued in research.md R7, plus: a single-line `ToolError` with the `ERROR: ` prefix stripped; a wrapped multi-line message with 7-space continuation indent; a German-localised message that must still classify correctly; `Invalid map <x>` plus `Parse error` resolving to `missing_input`; and bare `Parse error` resolving to `schema_misuse`
- [x] T035 [P] Unit test precedence and idempotency in `tests/test_classifier.py`: a string matching two content categories resolves by the mandated order; re-running `classify()` over identical output yields the identical mode; per-mode counts sum to total failed attempts
- [x] T036 [P] Unit test `grass_agent/results.py` atomicity and resume in `tests/test_results.py`: torn `.part` file discarded, truncated `case_result.json` treated as not reusable, resume key mismatch on each of the four fields independently, `len(attempts) ≤ max_retries + 1`, partial case rerun from attempt 1
- [x] T037 [P] Unit test fixture resolution and staging in `tests/test_fixtures.py`: shapefile sibling expansion, absolute-path rejection, `..` traversal rejection, undeclared-file refusal, and that staging copies rather than moves. The undeclared-file case must assert that a script referencing a file neither in the dataset nor declared surfaces as a `missing_input` failure rather than being silently satisfied — a stageable missing input must never be mistaken for a genuine agent error (SC-016, FR-001b)
- [x] T038 [P] Marked `slow`: integration test the executor in `tests/test_executor.py` — normal run exits 0; a raised exception is `general_exception` with a captured traceback; a deliberate segfault records `outcome: "crashed"` with `signal_name: "SIGSEGV"` **read from `status.json`, not inferred from exit 245**; a script exceeding `--timeout` is `timeout`; after each, the project holds only `PERMANENT`, `TMPDIR` is gone, and the `PERMANENT` hash is unchanged. Also assert that **zero** scripts written to `benchmarks/output_execution/*/attempt_*.py` import `grass.script.run_command`, call `gs.run_command`, or invoke a shell — scan the retained artifacts after the run and fail on any match (SC-010, FR-015). Assert the harness survives a hard crash and every remaining case stays evaluable — a crash in one case must cost that case only, never the suite (SC-003). Assert a hung script is bounded by `--timeout` and the suite proceeds to the next case unassisted (SC-012)
- [x] T038a [P] Add a test in `tests/test_executor.py` asserting the harness opens **zero outbound network socket connections** during a full execute-and-classify cycle (SC-011, FR-016). Install a guard that patches `socket.socket.connect` and `socket.create_connection` to record any non-loopback address, run one execution against the local dataset, and assert the recorded list is empty. Must not block loopback — the Ollama client legitimately uses `127.0.0.1`

**Checkpoint**: Foundation ready — classifier, executor, atomic persistence, and fixture staging all proven by tests. User story implementation can now begin.

---

## Phase 3: User Story 1 - Zero-Shot Runtime Baseline Measurement (Priority: P1) 🎯 MVP

**Goal**: Run generated scripts for real inside a headless GRASS session and record a defensible per-case pass/fail verdict with no healing, establishing the Gate 2 Pass@1 baseline.

**Independent Test**: Run `run_gate2.py --model qwen2.5-coder:3b --max-retries 0 --clean` against one case. Confirm it emits a pass/fail verdict and an execution log, performs **no** repair attempt, leaves `PERMANENT` byte-for-byte unchanged, and leaves zero scratch directories behind.

### Tests for User Story 1

> Write these first; confirm they FAIL before implementation

- [x] T039 [P] [US1] Contract test the CLI in `tests/test_cli_contract.py`: every flag, its default, and every documented interaction from contracts/cli.md — `--clean` winning over `--resume`, `--max-retries 0` disabling healing, negative `--max-retries` and `--timeout ≤ 0` exiting `2`, and exit code `3` naming the missing dependency. Include the newly added flags: `-k/--case` filtering (including a filter matching no case id exiting `2` and naming the unmatched ids), `--dataset` overriding auto-detection and exiting `3` on a non-project path, and `ExecutionConfig.from_env()` precedence where a CLI argument beats the environment variable and the environment variable beats the built-in default
- [x] T040 [P] [US1] Integration test the zero-shot path in `tests/test_integration_smoke.py`: one case end to end, asserting exactly one `attempt_1.py` is produced, `case_result.json` has `status: "complete"`, `pass_at_1` reflects the true verdict, and no `attempt_2.py` exists

### Implementation for User Story 1

- [x] T041 [US1] Implement the Gate 1 static guard in `benchmarks/run_gate2.py`: run `validate_syntax` and `validate_api` from `code_generator.py` against `data/grass_knowledge.db` before any execution attempt (FR-001, FR-014). On failure, record `outcome: "static_rejected"` and **skip execution entirely**, routing straight to the healing loop (FR-002). Reject any script importing `grass.script.run_command`, calling `gs.run_command`, or shelling out — treat as a failed attempt (FR-015). Enforce the same rejection on **repair** output, not just initial generation, so no executed script anywhere in `output_execution/` can use a legacy interface (SC-010)
- [x] T042 [US1] Implement the case loop in `benchmarks/run_gate2.py`: iterate the selected suite(s), write `attempt_<n>.py`, execute via `grass_agent/executor.py`, classify, and write `case_result.json` atomically after each attempt
- [x] T043 [US1] Implement artifact retention in `benchmarks/run_gate2.py` per data-model.md §9: write `attempt_<n>.py`, `attempt_<n>.stdout`, `attempt_<n>.stderr`, a combined `attempt_<n>.log`, and copy the last verified script to `final.py` (FR-019). The `.stdout` and `.stderr` files are **mandatory even when zero bytes** — reuse rule R10 requires every referenced path to exist, so a case directory missing an empty capture is not reusable
- [x] T044 [US1] Implement SIGINT handling in `benchmarks/run_gate2.py`: terminate the current child via its process group, run the cleanup sweep, leave `PERMANENT` verified unchanged, and exit promptly (FR-006, SC-002, SC-004)
- [x] T045 [US1] Wire suite and case selection in `benchmarks/run_gate2.py`: `-s/--suite` covers one file; omitting it covers both tiers, all 40 cases (SC-001, FR-017). `-k/--case` takes a comma-separated list of case ids and filters within the selected suite(s); a filter matching no case id exits `2` naming the unmatched ids. `--dataset PATH` overrides auto-detection; omit to search `$GISDBASE`, `$GRASSDATA`, `~/grassdata`, `./grassdata` for the first standard NC project (FR-023). Wire `--resume` / `--no-resume` as a single boolean pair feeding `ExecutionConfig.resume`, with `--clean` taking precedence over `--resume` (FR-006a)
- [x] T046 [US1] Emit per-case progress to stdout in `benchmarks/run_gate2.py` showing each attempt's stage, outcome, failure mode, latency, and token counts

**Checkpoint**: User Story 1 fully functional — `--max-retries 0` produces a complete Pass@1 baseline with retained artifacts and a verified-unchanged `PERMANENT`.

---

## Phase 4: User Story 2 - Autonomous Self-Healing of a Failing Script (Priority: P2)

**Goal**: Feed the exact failure back to the local model with targeted documentation so a non-executable script is repaired to one that runs, under a bounded unified budget.

**Independent Test**: Seed a deliberately broken script for a case and confirm the harness produces a script that completes execution within the retry budget, and that the repair prompt actually contained the failing tool's documentation.

### Tests for User Story 2

- [x] T047 [P] [US2] Unit test budget accounting in `tests/test_healing.py`: a static rejection consumes one retry, a runtime failure consumes one retry, `crashed` consumes one retry, `timeout` consumes one retry — all against the **same** allowance (FR-009a), and total attempts never exceed `max_retries + 1`
- [x] T048 [P] [US2] Unit test repair prompt assembly in `tests/test_healing.py`: all four elements present per FR-012 — original task, previous failing script, verbatim error or traceback, and failing-tool-targeted documentation. Assert 100% of repair attempts carry all four, with the error text byte-identical to the captured stream (SC-006). Also verify the `failing_tool is None` fallback queries with the error excerpt instead
- [x] T049 [P] [US2] Integration test the healing loop in `tests/test_integration_heal.py` with a stubbed model: a failing first attempt followed by a success on retry 1 records `pass_at_1: false`, `pass_at_healed: true`, and a `failure_mode_transitions` list ending in `null`

### Implementation for User Story 2

- [x] T050 [P] [US2] Implement targeted RAG re-query in `grass_agent/healing.py`: on failure, query `grass_knowledge.db` for documentation keyed on the tool parsed from the error by `extract_failing_tool()`, rather than reusing the initial generic context (FR-011)
- [x] T051 [US2] Implement repair prompt construction in `grass_agent/healing.py` from the persisted `CaseResult` fields per contracts/case-result.md: `CaseResult.prompt` for the task, the referenced `attempts[n].script_path` contents for the prior code, `error_excerpt` plus `stderr_path` for the exact error, and the targeted documentation. Pass the error text **verbatim**, never a paraphrase (FR-010)
- [x] T052 [US2] Implement the repair call in `grass_agent/healing.py` reusing the strict Zero-Chat contract: feed repair output through the same `extract_python_code` path so markdown fences and prose are stripped. A repair response yielding no parseable script is a failed attempt, not a harness error
- [x] T053 [US2] Implement the unified retry loop in `benchmarks/run_gate2.py`: a single budget decremented by every failed attempt regardless of stage (FR-009a), stopping at first `executed_ok` or on exhaustion (FR-013). A case may exhaust its budget without ever executing — an intended, reported outcome
- [x] T054 [P] [US2] Add `chat_with_stats()` to `llm_provider.py` returning `(text, stats)` from the response's `prompt_eval_count` and `eval_count`, leaving the existing `chat()` **untouched** so the Gate 1 caller at `code_generator.py:118` keeps working (research.md D11). Record zero rather than estimating when counters are absent
- [x] T055 [US2] Implement `--reuse-artifacts` in `benchmarks/run_gate2.py`: load `benchmarks/output/<tc_id>_<model_slug>.py` as attempt 1, set `attempt1_source: "reuse_artifacts"` in the resume key, record attempt 1 token counts as `0`, and fall back to fresh generation per case when the artifact is missing (FR-001a, SC-015)
- [x] T056 [US2] Implement `--max-retries` handling in `benchmarks/run_gate2.py` including `0` producing the pure zero-shot baseline (FR-009)

**Checkpoint**: User Stories 1 AND 2 both work independently — a real Pass@1 baseline and a bounded healing loop over it.

---

## Phase 5: User Story 3 - Failure Diagnosis and Transparency Reporting (Priority: P3)

**Goal**: Make *how* failures happen visible — dominant modes, whether healing moves cases between modes, per-attempt cost — and publish the Gate 1 versus Gate 2 comparison in one report.

**Independent Test**: Run the harness over both tiers with healing enabled, then open `benchmarks/execution_report.md` and confirm it carries the baseline and healed success rates, per-attempt latency and tokens, the ordered failure mode of every attempt, and the Gate 1 comparison.

### Tests for User Story 3

- [x] T057 [P] [US3] Unit test report aggregation in `tests/test_reporting.py`: Pass@1 and Pass@Healed computed correctly, per-mode counts summing to total failed attempts, per-ordinal latency and token means, and transition pairs counted in order
- [x] T058 [P] [US3] Unit test report rendering in `tests/test_reporting.py`: the exit-status-is-not-correctness caveat is always present (SC-014), the `attempt1_source` label is always present (SC-015), and the Gate 1 comparison is labelled as two different measurement harnesses rather than one continuous scale

### Implementation for User Story 3

- [x] T059 [US3] Implement the Gate 1 versus Gate 2 comparison in `grass_agent/reporting.py`: render the 90.0% Gate 1 static-validity baseline beside Pass@1 and Pass@Healed for the same 40 cases, explicitly labelled as two different measurement harnesses (FR-020)
- [x] T060 [US3] Implement the failure-mode transition table in `grass_agent/reporting.py` showing each case's ordered per-attempt failure mode so improvement or regression between attempts is visible (FR-018)
- [x] T061 [US3] Implement per-attempt cost reporting in `grass_agent/reporting.py`: latency and prompt/completion tokens per attempt ordinal plus totals, enabling cost-per-successful-case (SC-008)
- [x] T062 [US3] Implement the report writer in `grass_agent/reporting.py` emitting `benchmarks/execution_report.md` from the `RunSummary`, including the healed-minus-zero-shot gain as both absolute and relative difference (SC-007) and the mandatory FR-021/SC-014 caveat
- [x] T063 [US3] Implement `--report-only` in `benchmarks/run_gate2.py`: re-render the report from persisted `case_result.json` files without invoking the model or GRASS (SC-013). Report a missing or non-reusable case as **not evaluated** so the denominator is always explicit, never silently omitted
- [x] T064 [US3] Record run-level integrity evidence in `grass_agent/reporting.py`: `permanent_hash_before` / `permanent_hash_after`, `leaked_scratch_dirs` (must be empty in a clean run), and the resumed flag (SC-002, SC-004, SC-018)

**Checkpoint**: All three user stories independently functional; the report is regenerable without re-execution.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T065 [P] Verify no `NEEDS CLARIFICATION` placeholders or sample tasks remain in `specs/002-runtime-self-healing-harness/plan.md`, `specs/002-runtime-self-healing-harness/spec.md`, or `specs/002-runtime-self-healing-harness/tasks.md`
- [x] T066 [P] Document the known reporting caveats in `benchmarks/execution_report.md` generation: category 1 is under-reported because a schema error masks a missing map when GRASS's option parser aborts first; category 2 is under-reported because GRASS accepts unambiguous option prefixes, so a slightly-wrong name often works
- [x] T067 [P] Add `benchmarks/execution_report.md` and `benchmarks/output_execution/` handling to `.gitignore` policy — keep `case_result.json` artifacts out of version control while retaining the report
- [x] T068 Run the full quickstart validation: `tests/test_classifier.py`, `tests/test_executor.py`, then Scenarios C through J in `quickstart.md`
- [x] T069 Run the final evaluation with `--model qwen2.5-coder:7b --max-retries 2 --clean` and confirm the healed success rate exceeds the zero-shot rate (SC-009)
- [x] T070 Verify zero-mutation end to end after a full run: `find <dataset>/<project> -maxdepth 1 -name 'tmp_*'` returns nothing, `benchmarks/execution_report.md` shows `leaked_scratch_dirs` empty and matching `permanent_hash_before` / `permanent_hash_after` (SC-002, SC-004)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup — **BLOCKS all user stories**
- **User Stories (Phases 3–5)**: All depend on Foundational completion. US2 depends on US1's execution path; US3 depends on both
- **Polish (Phase 6)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Starts after Foundational. No dependencies on other stories. **This is the MVP.**
- **User Story 2 (P2)**: Starts after Foundational; integrates with US1's execution path but is independently testable with a stubbed model (T049)
- **User Story 3 (P3)**: Starts after Foundational; reads artifacts produced by US1 and US2 but is independently testable via `--report-only` over fixture data (T057, T058)

### Within Each User Story

- Tests written and confirmed failing before implementation
- Models before services; services before CLI wiring
- Core implementation before integration
- Story complete before moving to the next priority

### Parallel Opportunities

- T002–T006 (Setup scaffolding) all parallel
- T002a (conftest) parallel with T034–T038a once T004 registers the `slow` marker
- T007, T007a, T007b sequential — same file, `ExecutionConfig` plus its two helper layers
- T010, T011 (classifier enum + normalisation) parallel; T034, T035, T036, T037, T038, T038a, T039, T040 (all foundational and US1 tests) parallel
- T013, T014, T015 (the three classifier signature sets) parallel — disjoint pattern lists in one module, coordinate to avoid file conflicts
- T031, T032 (fixture resolution + staging) sequential — same file; T033 (benchmark JSON edit) parallel
- T050, T051, T052, T054, T055 parallel within US2 — different concerns, minimal shared state
- T057, T058 parallel; T061, T062, T064 parallel within US3
- T066, T067, T068 parallel in Polish
- US1, US2, US3 can be worked in parallel by different people once Foundational lands

---

## Parallel Example: User Story 1

```bash
# Launch both US1 tests together:
Task: "Contract test the CLI in tests/test_cli_contract.py"
Task: "Integration test the zero-shot path in tests/test_integration_smoke.py"

# Then the implementation, sequentially by dependency:
# T041 (static guard) -> T042 (case loop) -> T043 (artifacts) -> T044 (SIGINT) -> T045/T046
```

## Parallel Example: Foundational

```bash
# Classifier work splits cleanly:
Task: "Implement the missing_input signature set in grass_agent/classifier.py"
Task: "Implement the schema_misuse signature set in grass_agent/classifier.py"
Task: "Implement the unknown_method signature set in grass_agent/classifier.py"

# Fixture work runs alongside executor work:
Task: "Implement staging in grass_agent/fixtures.py"
Task: "Implement timeout enforcement in grass_agent/executor.py"
```

## Parallel Example: User Story 2

```bash
Task: "Implement targeted RAG re-query in grass_agent/healing.py"
Task: "Add chat_with_stats() to llm_provider.py"
Task: "Implement --reuse-artifacts in benchmarks/run_gate2.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational — **CRITICAL, blocks all stories**
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: run Scenario C in `quickstart.md`. Confirm one case produces a verdict, artifacts, and a verified-unchanged `PERMANENT`
5. This yields the Pass@1 zero-shot baseline — the reference point every later claim depends on

### Incremental Delivery

1. Setup + Foundational → foundation proven by unit and integration tests
2. Add US1 → validate via Scenario C → **Pass@1 baseline established (MVP)**
3. Add US2 → validate via Scenario E → healing gain measurable
4. Add US3 → validate via Scenario F → Gate 1 vs Gate 2 report published
5. Run Scenario G (`--reuse-artifacts`) to isolate runtime behaviour from generation behaviour
6. Run Scenario H to prove resumption, then Scenario I to prove report regeneration

### Parallel Team Strategy

1. Team completes Setup + Foundational together — the classifier, executor, persistence, and fixtures are the shared foundation
2. Once Foundational lands:
   - Developer A: US1 (execution path + CLI)
   - Developer B: US2 (healing + provider stats) — starts once T041's static guard exists
   - Developer C: US3 (reporting + `--report-only`) — can start against fixture `case_result.json` files immediately
3. Integrate sequentially in priority order

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same-file conflicts, cross-story dependencies that break independence
- **Gate 2 prerequisites are environmental, not code**: start `ollama serve` and provision the NC dataset before Phase 3 validation, or pre-flight will exit `3` naming the missing dependency