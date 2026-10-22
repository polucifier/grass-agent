# Feature Specification: Headless Runtime Execution & Autonomous Self-Healing Harness (Gate 2)

**Feature Branch**: `002-runtime-self-healing-harness`

**Created**: 2026-10-06

**Status**: Draft

**Constitution**: `.specify/memory/constitution.md` — v1.1.0 at specification time; amended to **v1.2.0** at plan time to ratify the Gate 2 headless execution mechanism (CLI `--tmp-mapset` sandbox primary, `grass.script.setup.init()` fallback). No requirement in this spec changed as a result; see `plan.md` Constitution Check for the amendment rationale.

**Input**: User description: "Feature: Gate 2 — Headless Runtime Execution & Autonomous Self-Healing Harness. Transition GrassAgent from static AST/schema validation (Gate 1) to dynamic execution inside a live headless GRASS environment, augmented by a configurable, bounded self-healing feedback loop. Governed by constitution v1.1.0. Strict Zero-Chat contract, offline-first local Ollama only, modern `grass.tools` interface only, native GRASS only. Requirements: (1) pre-flight static guard reusing Gate 1 validation as a barrier; (2) subprocess-isolated headless execution harness at benchmarks/run_gate2.py using ephemeral mapsets against the North Carolina sample dataset, guaranteeing zero mutation of the persistent PERMANENT mapset and scratch cleanup on success, error, or SIGINT; (3) runtime error interception and classification into missing input map, schema/parameter misuse, non-existent attribute/method, and general exception; (4) configurable bounded self-healing loop with --max-retries (default 2, 0 = pure zero-shot baseline) that re-queries RAG context targeting the failing tool and re-prompts with task, prior code, exact error, and targeted schema docs; (5) benchmark integration over the 40-case two-tier suite tracking Pass@1, Pass@Healed, per-attempt latency and token consumption, and failure-mode transitions, saving logs/artifacts under benchmarks/output_execution/ and emitting benchmarks/execution_report.md comparing Gate 1 static validity against Gate 2 live runtime execution."

## Clarifications

### Session 2026-10-06

- Q: Should the first attempt of a Gate 2 run reuse the 40 scripts already generated during Gate 1, or generate fresh ones from the live local model? → A: Both, via a flag (default: fresh in-run generation)
- Q: Should the harness provide auxiliary input files that benchmark cases reference but the target dataset does not contain, or let those cases fail as missing-input? → A: Auxiliary inputs are declared per benchmark case and staged by the harness before execution
- Q: Should a script rejected by the static check before execution consume one of the retry attempts? → A: Yes — static rejections are charged against the same retry budget as runtime failures
- Q: When a failed script's output matches more than one failure category, which category should it be counted as? → A: A fixed precedence order, taking the first match
- Q: If a suite run is interrupted partway through, should the harness be able to pick up where it left off? → A: Resume at case granularity — completed cases are kept, a partially finished case is discarded and restarted from attempt 1

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Zero-Shot Runtime Baseline Measurement (Priority: P1)

A researcher wants an honest measure of how often GrassAgent's generated scripts actually *run* in GRASS, not merely how often they parse. They run the execution harness with healing disabled against the full two-tier benchmark suite and receive a per-case verdict for every prompt: did the script execute to completion inside a live headless GRASS session, or did it fail, and why.

**Why this priority**: Gate 1's 90.0% static-validity baseline is the only defensible reference point for Gate 2. Without a healing-free runtime measurement, the value of the self-healing loop cannot be attributed and the Gate 2 milestone cannot be reported.

**Independent Test**: Run the harness with a retry budget of zero against a single benchmark case and confirm it emits a pass/fail verdict plus a captured execution log without performing any repair.

**Acceptance Scenarios**:

1. **Given** a benchmark case whose generated script executes successfully, **When** the harness runs it with healing disabled, **Then** the case is recorded as a runtime success and the script and its execution log are retained.
2. **Given** a benchmark case whose generated script fails during execution, **When** the harness runs it with healing disabled, **Then** the case is recorded as a runtime failure, the captured error output is retained, and the failure is attributed to a named failure mode.
3. **Given** any run, **When** the run completes, **Then** the persistent mapset contents are byte-for-byte unchanged from their pre-run state.
4. **Given** a run interrupted by the operator, **When** the interrupt occurs, **Then** the harness terminates promptly, removes all scratch artifacts, and leaves the persistent mapset untouched.

---

### User Story 2 - Autonomous Self-Healing of a Failing Script (Priority: P2)

A GIS practitioner submits a natural-language task that produces a plausible but non-executable script — a hallucinated tool method, a misnamed parameter, a missing input layer. Rather than reading the traceback themselves, they rely on the harness to feed the exact failure back to the local model together with the targeted tool documentation, and to return a script that runs.

**Why this priority**: This is the capability that distinguishes Gate 2 from a plain test runner. It is the reason a user can trust generated code without becoming the debug loop.

**Independent Test**: Seed the harness with a deliberately broken script for a benchmark case and confirm that within the configured retry budget it produces a script that completes execution, and that the repair prompt actually contained the failing tool's documentation.

**Acceptance Scenarios**:

1. **Given** a script rejected by pre-flight static validation, **When** healing is enabled, **Then** the GRASS execution stage is skipped entirely and the validation issue is routed directly into the repair loop.
2. **Given** a script that fails at runtime, **When** healing is enabled, **Then** each repair attempt is given the original task, the previous failing script, the verbatim error or traceback, and documentation for the tool that failed.
3. **Given** a runtime failure, **When** the repair loop runs, **Then** the documentation supplied is re-queried from the knowledge base targeting the specific failing tool rather than reusing the original generic retrieval.
4. **Given** any failure, **When** the retry budget is exhausted without a successful execution, **Then** the case is reported as an unresolved failure with the failure mode of each attempt preserved.

---

### User Story 3 - Failure Diagnosis and Transparency Reporting (Priority: P3)

A maintainer reviewing model quality wants to know *how* failures happen, not merely that they do: which failure modes dominate, whether healing moves cases between failure modes or merely shuffles them, and what each attempt cost in wall-clock time and tokens. They open a single report and get the Gate 1 versus Gate 2 comparison.

**Why this priority**: The milestone exists to improve the agent, and improvement is only actionable when the failure distribution and its cost are visible and comparable across attempts.

**Independent Test**: Run the harness over both benchmark tiers with healing enabled and confirm the emitted report contains the baseline and healed success rates, per-attempt latency and token figures, and the failure-mode transition history for every case.

**Acceptance Scenarios**:

1. **Given** a completed suite run, **When** the report is generated, **Then** it states the zero-shot success rate and the cumulative healed success rate alongside the Gate 1 static-validity rate for the same cases.
2. **Given** a case that failed more than once, **When** the report is generated, **Then** it shows the failure mode of each attempt in order, so improvement or regression between attempts is visible.
3. **Given** any attempt, **When** metrics are recorded, **Then** wall-clock latency and prompt/completion token counts for that attempt are captured individually, not only in aggregate.
4. **Given** a completed run, **When** the operator inspects the output directory, **Then** the generated script, every intermediate failed attempt, and the execution log are stored together per case.

---

### Edge Cases

- The generated script or a GRASS library aborts the process at the C level (segmentation fault, abort) rather than raising a Python exception.
- A generated script runs indefinitely or waits on interactive input instead of terminating.
- A generated script writes to, deletes from, or re-creates the persistent mapset it was only meant to read from.
- Two retries produce scripts that fail in the *same* failure mode as the previous attempt, indicating the repair loop is not converging.
- The first attempt fails pre-flight and every subsequent attempt also fails pre-flight, so no attempt ever reaches execution.
- The model responds to a repair prompt with markdown fences, prose, or a partial snippet instead of a complete script.
- The model responds to a repair prompt by importing a legacy interface or shelling out, violating the modern-interface-only constraint.
- A benchmark prompt references an auxiliary input file or layer that exists in neither the target dataset nor the case's declared auxiliary inputs.
- A benchmark case declares an auxiliary input file that cannot be located or read at staging time.
- A generated script silently produces wrong output while exiting successfully, so execution success alone does not prove correctness.
- The dataset, the GRASS installation, or the local model service is unavailable when the harness starts.
- The retry budget is set to a value greater than 2, or the operator interrupts the run mid-suite.
- Scratch directories leak because the run is killed with an uncatchable signal rather than a handled interrupt.
- The run is resumed after an interruption and a previously completed case's persisted results are missing, truncated, or unreadable; that case is treated as not completed and rerun from attempt 1.
- A resumed run reuses a case whose recorded result came from a different model, retry budget, or attempt-1 source than the current run.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST run the existing Gate 1 static verification (syntax parsing plus knowledge-base schema validation) against every generated script before any attempt is made to execute it.
- **FR-001a**: The system MUST offer an operator-selectable source for attempt 1: either freshly generated by the live local model, or loaded from previously persisted Gate 1 scripts. Fresh generation MUST be the default, and the mode actually used MUST be recorded in the run summary.
- **FR-001b**: Each benchmark case MUST be able to declare auxiliary input files it references beyond the target dataset's contents, and the system MUST stage those declared files into the scratch session before the script is executed. A file that is neither in the dataset nor declared for the case MUST NOT be synthesised by the harness.
- **FR-002**: When static verification fails for any reason — unparsable syntax, unknown tool, unknown parameter, or an unsupported chained form — the system MUST skip the execution stage entirely and route that failure directly into the self-healing loop.
- **FR-003**: The system MUST execute each statically valid script in a separate child process so that a hard process-level crash inside GRASS or its geospatial dependencies cannot terminate or corrupt the evaluation harness.
- **FR-004**: The system MUST run every script in a session that cannot modify the persistent mapset, using a disposable location derived from the target dataset.
- **FR-005**: The system MUST verify and report that the persistent mapset is unchanged after every run, including interrupted runs.
- **FR-006**: The system MUST guarantee removal of all scratch directories and temporary artifacts on normal completion, on execution error, and on operator interrupt.
- **FR-006a**: The system MUST support resumption at case granularity. Results for a case MUST be persisted as soon as that case reaches a terminal state, and a resumed run MUST reload completed cases and skip them. A case that was interrupted partway MUST be discarded entirely and restarted from attempt 1; partial attempts MUST never be resumed or counted.
- **FR-007**: The system MUST capture, for every attempt, the child's exit status, standard output, and standard error including any Python traceback.
- **FR-008**: The system MUST assign every failed attempt to exactly one of these failure modes: missing input map or layer, schema or parameter misuse, non-existent attribute or method, or a general Python/runtime exception; an unrecognized failure MUST be assigned to the general category rather than dropped.
- **FR-008a**: Where a single failed attempt's output matches more than one failure mode, the system MUST resolve it by a fixed precedence order — missing input map or layer, then schema or parameter misuse, then non-existent attribute or method, then general Python/runtime exception — and assign the first match. The assignment MUST be deterministic and independent of output ordering.
- **FR-009**: The system MUST expose a configurable retry budget via a command-line option, defaulting to 2, where a value of 0 disables healing entirely and yields a pure zero-shot baseline.
- **FR-009a**: The retry budget is a single unified allowance shared by both failure stages. Every failed attempt — whether rejected by static verification or failed during execution — MUST consume exactly one unit of that allowance, and the budget MUST be shared rather than duplicated per stage.
- **FR-010**: When a script fails at any stage, the system MUST extract the specific error text or traceback that caused the failure and pass it verbatim into the next repair attempt.
- **FR-011**: When repairing a failure, the system MUST re-query the knowledge base for documentation targeted at the tool named in the failure, rather than reusing the initial generic tool context.
- **FR-012**: Each repair attempt MUST be given all four of: the original natural-language task, the previous failing script, the exact error or traceback, and the targeted tool documentation.
- **FR-012a**: Each repair attempt MUST additionally include the map inventory of the target dataset — the names of the rasters and vectors that actually exist — rendered as an `### Available Dataset Maps` block. This grounds the model against hallucinated map names: a missing-map failure is otherwise unhealable, because the four FR-012 elements state that some invented map does not exist but never state which maps do. The inventory MUST be sourced from the project's `PERMANENT` mapset, MUST NOT be invented, and MUST degrade to omission rather than failing the run when it cannot be read.
- **FR-012b**: Each initial (attempt 1) generation prompt MUST include the same dataset map inventory block as repairs — the `### Available Dataset Maps` block described in FR-012a — so the zero-shot baseline is grounded against hallucinated map names rather than only the healed path. The inventory MUST be read once per run and shared with every repair prompt, MUST NOT be invented, and MUST degrade to omission rather than failing the run when it cannot be read.
- **FR-013**: The repair loop MUST stop as soon as a script completes execution successfully, and MUST otherwise stop when the retry budget is exhausted.
- **FR-014**: Every generated script, whether produced initially or by repair, MUST satisfy the strict output contract: executable Python only, with no markdown fences, prose, or explanations.
- **FR-015**: The system MUST reject any generated or repaired script that uses a legacy interface or shells out to command-line geospatial tools, and MUST treat such a script as a failed attempt eligible for repair.
- **FR-016**: All model inference and embedding computation MUST occur against the local model service; the system MUST NOT contact any external network service at any point in the evaluation or healing path.
- **FR-017**: The system MUST support running against both benchmark tiers, covering all 40 cases, and MUST support selecting either the primary evaluation model or the lightweight smoke-test model.
- **FR-018**: The system MUST record, per case: zero-shot success, cumulative healed success, the ordered failure mode of every attempt, and per-attempt latency and prompt/completion token counts.
- **FR-019**: The system MUST retain, per case, the final verified script, every intermediate failed attempt, and the execution logs, all grouped so they can be found together.
- **FR-020**: The system MUST emit a single markdown report that presents the zero-shot success rate, the cumulative healed success rate, per-attempt cost figures, failure-mode transitions, and a side-by-side comparison against the Gate 1 static-validity result for the same cases.
- **FR-021**: The system MUST NOT attempt to validate output *correctness* beyond exit status in this milestone; a case that exits successfully with wrong results is recorded as a runtime success, and the report MUST state this limitation explicitly.
- **FR-022**: The system MUST apply an upper bound on the wall-clock time of a single execution attempt so that a hung or interactive script cannot stall the suite indefinitely.
- **FR-023**: The system MUST exit with a non-zero status when the required runtime environment (GRASS installation, target dataset, or local model service) is unavailable, and MUST state which dependency was missing.

### Key Entities

- **Benchmark Case**: A single natural-language task under evaluation, carrying a stable identifier, a category, the tool set expected to satisfy it, and an optional list of auxiliary input files the harness must stage before execution.
- **Attempt**: One generation-and-evaluation cycle for a benchmark case. An attempt has an ordinal (first, retry 1, retry 2, …), the script it produced, its outcome, its failure mode if any, its captured logs, its latency, and its token counts.
- **Outcome**: The verdict for an attempt — statically rejected, executed successfully, or failed at execution — paired with a failure mode when it failed.
- **Failure Mode**: One of four mutually exclusive categories describing why an attempt did not succeed: missing input map or layer; schema or parameter misuse; non-existent attribute or method; general Python or runtime exception. Assignment is single-valued and resolved by fixed precedence.
- **Run Summary**: The aggregate record for one harness invocation: suites and cases covered, model used, retry budget, attempt-1 source, zero-shot and healed success rates, and the emitted report location. Written incrementally so it survives an interruption.
- **Scratch Session**: A disposable evaluation session created for one attempt and destroyed afterwards, guaranteed not to outlive the attempt or affect the persistent mapset.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All 40 benchmark cases across both tiers can be evaluated end to end, and every case yields a recorded verdict with a retained artifact set.
- **SC-002**: The persistent mapset is verifiably byte-for-byte identical before and after every run, including runs terminated by operator interrupt — zero observed mutations.
- **SC-003**: A hard process-level crash occurring in any single case leaves the harness running and all remaining cases still evaluable; across the suite, zero cases are lost to harness termination.
- **SC-004**: Every completed or interrupted run leaves zero scratch directories behind, confirmed by an explicit post-run sweep.
- **SC-005**: 100% of failed attempts are assigned to one of the four defined failure modes, with zero unclassified failures.
- **SC-005a**: For any attempt whose output matches two or more failure signatures, re-running classification over the identical captured output yields the same assigned mode every time, and the per-mode counts across the suite sum exactly to the number of failed attempts.
- **SC-006**: 100% of repair attempts include the verbatim error text, the previous failing script, the original task, and failing-tool-targeted documentation in their inputs.
- **SC-006a**: 100% of repair attempts made in response to a `missing_input` failure include the dataset map inventory (FR-012a); over a suite run, no repair prompt for that failure mode is sent without it, verified by the presence of the `### Available Dataset Maps` block.
- **SC-006b**: 100% of initial generation prompts for a readable dataset include the `### Available Dataset Maps` block (FR-012b), verified by its presence; when the dataset cannot be read, the prompt is still constructed without it and the run does not fail.
- **SC-007**: The report quantifies the gain from healing as the absolute and relative difference between zero-shot success rate and cumulative healed success rate, over the same 40 cases.
- **SC-008**: Per-attempt latency and token consumption are recorded for 100% of attempts, enabling cost-per-successful-case to be stated in the report.
- **SC-009**: The healed success rate exceeds the zero-shot success rate, demonstrating the loop converges on at least one case that failed without healing.
- **SC-010**: 100% of scripts that pass both static and runtime stages use only the modern tooling interface, with zero legacy or shell-based invocations among executed scripts.
- **SC-011**: No attempt contacts an external network service; the run completes with the machine's outbound network unavailable.
- **SC-012**: A single case that hard-crashes or hangs is bounded by the per-attempt time limit, and the suite proceeds to the next case without manual intervention.
- **SC-013**: A maintainer can produce the Gate 1 versus Gate 2 comparison for a completed run by opening one report file, without recomputing anything.
- **SC-014**: The report explicitly discloses that exit-status success is not a correctness guarantee, so the healed success rate is not misread as an accuracy figure.
- **SC-015**: The report and run summary state whether attempt 1 was freshly generated or reused from persisted Gate 1 scripts, and reuse-based runs show zero token consumption for attempt 1.
- **SC-016**: Every benchmark case that references an auxiliary input file declares it, and 0 cases fail for a missing input that the harness was able to stage; a missing-input failure therefore always indicates a genuine agent error rather than an unprepared dataset.
- **SC-017**: For every case, the number of recorded attempts never exceeds the configured budget plus one, regardless of how its failures split between static rejection and runtime failure.
- **SC-018**: Interrupting a suite run and restarting it in resume mode re-runs zero already-completed cases, and every case interrupted mid-flight is restarted from attempt 1 with no partial attempt counted in the final metrics.
- **SC-019**: A resumed run either reuses a persisted case only when its recorded model, retry budget, and attempt-1 source match the current run, or reruns it; zero results are carried across a changed configuration.

## Assumptions

- The Gate 1 pipeline — prompt construction, local model invocation, syntax verification, and knowledge-base schema validation — already exists and is reused unchanged; this feature adds an execution and healing layer rather than reworking generation.
- When attempt 1 is sourced from persisted Gate 1 scripts rather than regenerated, no model inference occurs for that attempt and its token consumption is recorded as zero; the run summary and report MUST label such runs so reuse-based figures are never presented as freshly measured.
- A working local model service and the knowledge base are available on the evaluation host; the host is offline.
- The North Carolina sample dataset is present and named as either `nc_basic_spm_grass8` or `nc_spm_08_grass7`; the harness detects which is available rather than hard-coding one.
- A disposable session is derived from the dataset per attempt, so the persistent mapset serves only as a read-only source.
- Per-attempt wall-clock limit defaults to a value chosen during planning and is configurable; it exists to bound hangs, not to judge correctness.
- Token accounting is obtained from the local model service's own reported counts; no external metering is involved.
- "Bounded" healing means a fixed attempt ceiling per case, with no convergence-based early stop other than first success — cases that oscillate between failure modes still consume the full budget.
- Because the retry budget is unified across stages, a case may exhaust its entire budget without ever reaching execution. This is an intended and reported outcome, not a harness fault, and such cases MUST be counted as unresolved failures.
- Model output for repair attempts is subject to the same strict output contract as initial generation; malformed output is treated as a failed attempt, not a harness error.
- Run resumption is keyed on the case identifier together with the model, retry budget, and attempt-1 source; changing any of those invalidates prior results for that case.
- Per-case results are persisted independently of the final report, so the report can always be regenerated from stored results without re-executing anything.
- Cross-model comparability is out of scope: a run mixes only one model, and comparing the smoke-test model against the primary model requires separate runs.
- The QGIS plugin surface, the native GRASS graphical interface, and any cloud model backend remain out of scope, per the constitution's subsequent-milestones list.
- Result-correctness checking (comparing produced maps against expected outputs) is deferred beyond Gate 2.
- Authoring the auxiliary input data files themselves is out of scope; this feature consumes them once declared on a case and reports any that are missing or unreadable.

## Out of Scope

- Verifying that a successfully executed script produced *geospatially correct* output.
- A GRASS graphical-interface extension or any interactive session tooling.
- Any cloud model backend or hybrid local/cloud model switching.
- QGIS plugin integration or any non-GRASS execution environment.
- Parallel or distributed execution of benchmark cases.
- Changing the Zero-Chat output contract, the modern-tooling-only constraint, or the offline-first mandate.
- Expanding the knowledge base, the retriever, or the benchmark prompt suites.