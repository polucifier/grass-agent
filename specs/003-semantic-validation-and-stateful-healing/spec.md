# Feature Specification: Semantic Validation, Stateful Healing, and Two-Tier Retry Budget (Gate 3)

**Feature Branch**: `003-semantic-validation-and-stateful-healing`

**Created**: 2026-11-10

**Status**: Draft

**Constitution**: `.specify/memory/constitution.md` — v1.3.0. This feature advances Principle IV from Gate 2 (runtime executability) to Gate 3 (geospatial semantic correctness) and must preserve Principles I (offline-only), II (modern `grass.tools` interface), III (zero-chat script contract), and V (pre-flight execution safety and zero mutation of persistent mapsets).

**Input**: User description: "Create feature specification 003: 'Semantic Validation, Stateful Healing, and Two-Tier Retry Budget' for Gate 3 — transition GrassAgent from pure execution testing (Gate 2: Pass@1 27.5%, Pass@Healed 32.5%) to geospatial semantic correctness validation, while eliminating the 69% no-op repair loop identified in Gate 2 diagnostics. Maintain 100% regression safety for all 255 existing pytest unit and integration tests."

## Clarifications

### Session 2026-11-10

- Q: Which post-execution outcomes should consume the two runtime repair attempts? → A: Concrete execution gaps only — non-zero exits and missing/empty outputs consume runtime repairs; failed semantic assertions are report-only and are never repaired.
- Q: Should static schema failures such as unknown tools or parameter names consume the static repair budget? → A: Yes — all pre-execution rejections, including unknown tools, unknown parameters, and other static schema violations, consume the static tier.
- Q: Should the Gate 3 report retain Pass@Healed, or present only Pass@Executed and Pass@Semantic? → A: The main Gate 3 metric table presents exactly the two required metrics; Pass@Healed appears only in a separate Gate 2 comparison section.
- Q: How should the two tier budgets be exposed on the command line while keeping the existing `--max-retries` option and its tests working? → A: `--max-retries` remains as a shorthand that sets both tiers; independent static and runtime overrides take precedence when supplied.
- Q: Should the 10-case pilot deliberately include multi-step or mixed raster/vector cases, or prioritize single-tool cases? → A: Include at least two multi-step or mixed raster/vector cases; the remaining pilot cases may be single-tool.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Trust That a Successful Script Produced the Right Geospatial Result (Priority: P1)

A researcher runs the 10-case pilot suite and receives, for every case, not only whether the generated script exited cleanly but whether the maps it produced actually contain the expected geospatial result. A script that exits 0 while writing an empty raster, an all-null raster, a vector with zero features, the wrong geometry type, or missing attribute columns is reported as an execution pass but a semantic failure, with the specific assertion that failed and the observed versus expected value.

**Why this priority**: Gate 2 already shows that exit status is not correctness. Gate 3 exists to measure whether generated scripts satisfy the geospatial intent, and this is the first capability that makes that distinction visible to a user. Without it, the project cannot report a meaningful Gate 3 result.

**Independent Test**: Run a single pilot case whose generated script exits 0 but creates a raster whose values are outside the declared expected range. Confirm the case is recorded as `Pass@Executed = true` and `Pass@Semantic = false`, with a named raster assertion describing expected and observed values.

**Acceptance Scenarios**:

1. **Given** a pilot case whose script exits 0 and creates every declared output map with values satisfying all declared assertions, **When** the case runs, **Then** it is recorded as both an execution pass and a semantic pass.
2. **Given** a pilot case whose script exits 0 but whose declared raster output contains zero non-null cells, **When** the case runs, **Then** it is recorded as an execution pass and a semantic failure naming the non-null-cell assertion.
3. **Given** a pilot case whose script exits 0 but whose raster output mean lies outside the declared tolerance, **When** the case runs, **Then** it is recorded as a semantic failure reporting the expected mean, observed mean, and tolerance.
4. **Given** a pilot case whose script exits 0 but whose vector output has zero features, the wrong geometry type, or a missing required attribute column, **When** the case runs, **Then** it is recorded as a semantic failure naming the specific vector assertion.
5. **Given** a pilot case whose script exits 0 but does not create one of the declared output maps, **When** the case runs, **Then** the missing output is reported as a semantic failure rather than being silently skipped.
6. **Given** a pilot case whose script exits 0 and creates the declared outputs but fails a semantic assertion, **When** the case is processed, **Then** the case terminates with the semantic verdict and no repair attempt is launched.
7. **Given** a semantically successful case, **When** the scratch session is cleaned up, **Then** the semantic verdict and its evidence have already been persisted.

---

### User Story 2 - Escape the No-Op Repair Loop (Priority: P2)

A GIS practitioner watches a failing script get "repaired" into the same script again and again, burning attempts without progress. The harness now remembers every previous attempt for the case, shows the model the full failure history, detects when a repair is identical to any earlier attempt, refuses to execute the duplicate, and switches to a more explicit prompt strategy — including injecting the failing tool's valid parameter list — instead of repeating the same request.

**Why this priority**: Gate 2 diagnostics attribute 69% of repairs to no-op loops. A healing loop that repeats itself consumes budget without changing the outcome, so eliminating duplicates is a prerequisite for any credible Gate 3 result.

**Independent Test**: Seed a case with a first attempt that fails, then force the model to return byte-identical code for the repair. Confirm the duplicate is rejected without execution, recorded as a no-op, and followed by a parameter-injection pivot prompt; confirm no accepted attempt in the case is identical to a previous one.

**Acceptance Scenarios**:

1. **Given** a case with prior attempts, **When** a repair prompt is built, **Then** it contains the complete ordered attempt history — attempt number, generated code, failure mode, exact error excerpt, and static-versus-runtime status — plus the explicit instruction "DO NOT repeat previous scripts or failed parameter combinations."
2. **Given** a repair candidate that is byte-for-byte identical to any previous attempt for the same case, **When** it is validated, **Then** it is rejected before execution and recorded as a no-op duplicate.
3. **Given** a repair candidate that is structurally identical to a previous attempt after parsing, differing only in formatting, comments, or whitespace, **When** it is validated, **Then** it is also rejected as a no-op duplicate.
4. **Given** a rejected duplicate and remaining budget, **When** the next repair is requested, **Then** the prompt strategy pivots to an explicit parameter-list injection for the failing tool rather than repeating the prior prompt shape.
5. **Given** a pivot attempt that produces genuinely new code, **When** it is validated, **Then** it proceeds through the normal tier rules.
6. **Given** repeated duplicates that exhaust the available budget, **When** the case terminates, **Then** it is reported as an unresolved no-op failure and every duplicate is preserved in the history.
7. **Given** a 40-case benchmark run, **When** the run completes, **Then** zero duplicate repairs have been accepted for execution.

---

### User Story 3 - Spend Static and Runtime Effort Independently (Priority: P3)

A maintainer needs static repair attempts to stop stealing runtime execution attempts. A script that needs two passes to become syntactically valid still arrives at the sandbox with its full runtime repair allowance intact. Conversely, runtime failures never replenish the static budget, and a static rejection never launches a GRASS process or consumes the runtime timeout allowance.

**Why this priority**: Gate 2's single shared budget lets cheap static slips consume expensive runtime attempts and makes the 69% no-op diagnosis harder to attribute. Separating the budgets makes both failure stages measurable and prevents static churn from masking runtime behaviour.

**Independent Test**: Provide a case whose first two candidates fail static validation and whose third candidate is valid but fails at runtime. Confirm the GRASS process is launched only for the third candidate, the runtime budget still has two repairs available, and the persisted case result records two static attempts and the runtime attempts separately.

**Acceptance Scenarios**:

1. **Given** a candidate that fails static validation, **When** it is repaired, **Then** the repair candidate is charged to the static repair tier and no GRASS process is launched.
2. **Given** two static repairs and a candidate that finally passes static validation, **When** it reaches execution, **Then** the runtime tier still has its full allowance of two repairs.
3. **Given** the static tier is exhausted, **When** the case terminates, **Then** it is reported as a terminal static failure and no runtime attempt or runtime timeout is consumed.
4. **Given** a candidate that passes static validation but fails at runtime, **When** it is repaired, **Then** the attempt is charged to the runtime tier and the static tier is not replenished.
5. **Given** a runtime-tier repair candidate that fails static validation, **When** it is handled, **Then** it is charged to the runtime tier, does not refill the static tier, and does not launch GRASS.
6. **Given** a completed case, **When** `case_result.json` is inspected, **Then** each attempt identifies its tier and the result states used and remaining attempts for both tiers.
7. **Given** an operator configuring a run, **When** they set either tier's budget independently, **Then** the other tier's budget is unaffected; the default is two repairs per tier, a value of zero disables repairs for that tier, `--max-retries` sets both tiers, and tier-specific overrides take precedence over that shorthand.

---

### User Story 4 - Compare Execution Success and Semantic Success in One Report (Priority: P4)

A maintainer opens the Gate 3 report and sees two clearly defined rates side by side: `Pass@Executed` (the script completed and produced at least one new map) and `Pass@Semantic` (the produced maps passed every declared geospatial assertion). The report also exposes the gap between them, the semantic failures by assertion, duplicate-repair counts, and tier-level attempt usage, so the next improvement can be targeted.

**Why this priority**: Dual metrics only create value if they are visible, comparable, and reproducible. Reporting is the delivery surface for Stories 1–3.

**Independent Test**: Regenerate the report from persisted case results without invoking the model or GRASS, and confirm both metrics appear for every suite and for the run overall, alongside semantic failure reasons and tier-separated attempt counts.

**Acceptance Scenarios**:

1. **Given** a completed pilot run, **When** the report is generated, **Then** it reports exactly `Pass@Executed` and `Pass@Semantic` in the main Gate 3 table, and shows Gate 2's `Pass@Healed` only in a separate comparison section, with counts and rates.
2. **Given** a case that executed successfully but failed one semantic assertion, **When** the report is generated, **Then** the case contributes to `Pass@Executed` but not to `Pass@Semantic`, the failed assertion is listed with expected and observed values, and no repair was attempted.
3. **Given** any completed case, **When** its persisted result is inspected, **Then** it contains both verdicts, the semantic assertion evidence, the per-tier attempt ledger, and a no-op count.
4. **Given** persisted results, **When** the report is regenerated in report-only mode, **Then** it reproduces the same metrics without model inference or GRASS execution.
5. **Given** a run with duplicates, **When** the report is generated, **Then** it states how many duplicate candidates were detected, rejected, and resolved by a strategy pivot.
6. **Given** any report, **When** the metrics are presented, **Then** `Pass@Semantic` is never allowed to exceed `Pass@Executed`, and the report states that a semantic pass covers only the declared assertions rather than universal geospatial correctness.

---

### Edge Cases

- A script exits 0 but creates no new map, so it cannot satisfy the execution definition; this is a repairable runtime failure until the runtime tier is exhausted.
- A script exits 0 and creates its declared outputs but fails a semantic assertion; the case ends at verification with no repair attempt and no further budget consumption.
- A script creates a declared output and then deletes or overwrites it before exiting.
- A prior failed attempt leaves a map with the expected name in the scratch session, and a later attempt produces nothing; stale output must not be credited to the later attempt.
- A script writes multiple raster outputs where one passes and another fails its assertions.
- A vector output has the right feature count but the wrong geometry type, or the right geometry type with a missing attribute column.
- A raster has non-null cells but a non-finite or constant value where variation is expected.
- An output's mean falls exactly on the tolerance boundary, or differs slightly because of GRASS version or dataset revision.
- The semantic query tool itself fails or times out, so the assertion cannot be evaluated.
- A pilot prompt does not name its output maps, or names an output the model renames.
- The model returns a fix that is byte-identical to an earlier attempt.
- The model returns a fix that parses to the same structure as an earlier attempt but with different formatting, comments, or docstrings.
- The model produces code that is a no-op duplicate in a later tier after previously appearing in the static tier.
- A pivot to explicit parameter injection still yields a duplicate, or yields code that is new but invalid.
- The complete attempt history is too large for the model's context window.
- The static tier is exhausted without any candidate ever reaching execution.
- The runtime tier is exhausted while the static tier still has unused repairs.
- A case is interrupted mid-attempt, leaving a partially written result or scratch mapset.
- The dataset, GRASS installation, or local model service is unavailable at startup.
- A pilot case's declared expected value no longer matches the reference dataset because the data or GRASS version changed.
- A pilot case's expected values were accidentally derived from the candidate script rather than an independent reference execution.
- An auxiliary input declared by a pilot case is missing at staging time.

## Requirements *(mandatory)*

### Functional Requirements

#### Feature A — Two-Tier Retry Budget Architecture

- **FR-001**: The system MUST maintain two distinct repair budgets per case: a static (pre-execution) repair tier and a runtime (execution) repair tier. Each repair tier MUST default to two repair candidates and MUST be independently configurable, with a value of zero disabling repairs for that repair tier.
- **FR-001a**: The static repair tier MUST cover all pre-execution rejections, including Python syntax errors, forbidden imports such as `subprocess` and the legacy `grass.script` interface, formatting or output-contract slips, unknown tools, unknown parameters, and other static schema violations.
- **FR-001b**: The runtime repair tier MUST be available only after a candidate passes static validation. It MUST cover failures observed while executing the candidate inside the isolated headless GRASS sandbox, including a zero exit status that produces no new map. It MUST NOT cover failures of the declared semantic assertions.
- **FR-001c**: A static repair-tier candidate MUST NOT launch a GRASS process and MUST NOT consume the runtime wall-clock timeout allowance.
- **FR-001d**: A runtime repair-tier candidate MUST NOT replenish, reset, or consume the static repair-tier budget.
- **FR-001e**: A failed semantic assertion MUST NOT trigger a repair candidate, MUST NOT consume either repair tier's budget, and MUST NOT alter the generated script. Semantic verification is an independent oracle for measurement, not a repair trigger.
- **FR-001f**: The existing `--max-retries` option MUST remain available as a shorthand that sets both repair-tier budgets to the same value. Operators MUST be able to override each repair tier independently through `--max-static-retries` and `--max-runtime-retries`, which take precedence over the shorthand when supplied. Backward compatibility applies to the option and its value: `--max-retries N` still requests `N` repair candidates for each repair tier. It does not preserve the old total attempt cap; the maximum becomes `1 + N + N` candidates per case, as FR-002b states.
- **FR-002**: A static validation failure MUST NOT decrease the runtime repair tier's remaining allowance. A case that consumes its entire static repair tier MUST still reach execution with the full runtime repair allowance if a later candidate passes static validation.
- **FR-002a**: A candidate produced during the runtime repair tier that fails static validation MUST be charged to the runtime repair tier, MUST NOT launch GRASS, and MUST NOT replenish the static repair tier. This preserves repair-tier non-interference while keeping the total number of candidates bounded.
- **FR-002b**: The initial generated candidate MUST NOT consume a repair budget unit in either repair tier. The maximum number of generated candidates for one case is therefore one initial candidate plus the configured static repair limit plus the configured runtime repair limit.

#### Feature B — Stateful Self-Healing Memory

- **FR-003**: The repair context and healer MUST retain the full attempt history for a case rather than only the most recent failure. History MUST survive across tier boundaries within the case.
- **FR-004**: For every attempt, including the initial generation, the system MUST record: the attempt number, the stage that produced it (initial generation, static repair, or runtime repair), the generated code, the failure mode (or an explicit success marker when the attempt succeeded), the exact error excerpt or static diagnostic, whether the failure occurred during static validation or runtime execution, and whether the candidate was rejected as a duplicate.
- **FR-004a**: Attempt records MUST be ordered and MUST be persisted with the case result so the report and any later diagnosis can reconstruct the sequence without re-running the model.
- **FR-005**: Every repair prompt MUST include the complete ordered attempt history for the case, together with the original task and the relevant tool documentation, and MUST explicitly instruct the model: "DO NOT repeat previous scripts or failed parameter combinations."
- **FR-005a**: When the full history exceeds the model's context budget, the system MUST preserve every attempt's failure mode, error excerpt, and duplicate status, and MUST replace only older attempt code with a deterministic digest plus a bounded excerpt. The most recent attempt's full code MUST always be included.
- **FR-006**: The system MUST detect no-op repairs deterministically at two levels: exact byte equality with any previous attempt, and structural equality of the parsed program with any previous attempt. Formatting-only or comment-only differences MUST be treated as duplicates.
- **FR-006a**: A detected duplicate MUST NOT be executed. It MUST consume one attempt from the tier in which it was produced and MUST be recorded as a no-op duplicate.
- **FR-006b**: After rejecting a duplicate, if budget remains, the next repair MUST use a different prompt strategy that injects the failing tool's explicit, knowledge-base-derived parameter list. If the pivot also yields a duplicate, or no budget remains, the case MUST terminate as an unresolved no-op failure.
- **FR-006c**: Duplicate detection MUST include the initial candidate and attempts from both tiers, so a candidate that repeats an earlier tier's code is still rejected.
- **FR-006d**: The duplicate decision MUST be reproducible: identical candidate sequences MUST produce identical duplicate verdicts and identical tier accounting.

#### Feature C — Pilot Geospatial Semantic Assertions

- **FR-007**: The system MUST provide a dedicated 10-case pilot suite selected from the existing benchmark Tier 1 and benchmark Tier 2 prompts. The suite MUST contain at least four benchmark Tier 1 cases and at least four benchmark Tier 2 cases, MUST cover both raster-producing and vector-producing tasks, and MUST include at least two multi-step or mixed raster/vector cases. The remaining pilot cases MAY be single-tool.
- **FR-007a**: Pilot cases MUST be limited to deterministic, output-producing tasks. Display-only and statistics-only tasks that create no persistent map MUST be excluded, because execution success is defined in part by the creation of a new map. `validate_pilot_suite()` MUST reject a suite containing such a case as a composition violation.
- **FR-007b**: Each pilot prompt MUST explicitly name every expected output map and its type (raster or vector), so that assertions can target the outputs unambiguously.
- **FR-007c**: Each pilot case MUST declare its expected outputs, expected tools, tier, target dataset, and one or more programmatic assertions, including any numeric tolerances.
- **FR-007d**: Expected assertion values MUST be established from an independent reference execution against the target dataset and reviewed by a human before the suite is used as a benchmark. Expected values MUST NOT be derived from the candidate script being evaluated.
- **FR-008**: Raster assertions MUST verify, using an independent post-execution query, that: the non-null cell count is greater than zero, the minimum and maximum values are valid and lie within the declared expected range, and the mean lies within the declared tolerance of the expected mean.
- **FR-008a**: Vector assertions MUST verify, using an independent post-execution query, that: the feature count derived from vector topology metadata is greater than zero, the geometry type matches the declared expected type, and every required attribute column is present. Feature count and attribute-column presence MUST be evaluated as separate checks rather than inferred from one another.
- **FR-008b**: Every declared output MUST be checked. A missing output, an output of the wrong type, or a failed query MUST be recorded as a semantic failure rather than skipped or treated as a pass.
- **FR-008c**: Semantic assertions MUST run after a candidate exits successfully and before the scratch session is cleaned up. They MUST be read-only and MUST NOT modify generated outputs or the persistent mapset.
- **FR-008d**: Outputs left by earlier failed attempts MUST NOT satisfy a later attempt's assertions. The system MUST either reset the scratch session between attempts or otherwise establish that the asserted maps were created by the successful attempt.
- **FR-008e**: Semantic queries MUST have a bounded timeout. A query timeout or query-tool failure MUST be a semantic failure for that case, MUST NOT crash the run, and MUST NOT consume a repair attempt.
- **FR-008f**: For every assertion the system MUST record which output and check was evaluated, the expected value or range, the observed value, the tolerance, and the pass/fail verdict.
- **FR-008g**: Semantic verification MUST be report-only with respect to healing. A failed assertion MUST terminate the case's healing path at the semantic verdict, must not generate a repair prompt, and must not be converted into a runtime failure.
- **FR-009**: The system MUST report two distinct metrics: `Pass@Executed` and `Pass@Semantic`.
- **FR-009a**: `Pass@Executed` is true only when the successful candidate exits with status zero and the scratch session contains at least one new map created by that candidate.
- **FR-009b**: `Pass@Semantic` is true only when `Pass@Executed` is true and every declared geospatial assertion for the case passes.
- **FR-009c**: The main Gate 3 metric table MUST present exactly `Pass@Executed` and `Pass@Semantic` per suite and overall, with the gap between them, semantic failures grouped by assertion type, duplicate-repair counts, and per-tier attempt usage. Gate 2's `Pass@Healed` MAY appear only in a clearly separated Gate 2 comparison section, not as a column in the main Gate 3 table.
- **FR-009d**: `case_result.json` MUST record both verdicts, all assertion evidence, the per-tier attempt ledger, and the no-op count for every case.
- **FR-009e**: The report MUST be regenerable from persisted results alone, without model inference or GRASS execution.
- **FR-009f**: Cases without declared semantic assertions MUST be reported as semantic-not-evaluated and MUST be excluded from the `Pass@Semantic` denominator. They MUST NOT be counted as semantic passes or semantic failures. The report MUST state the execution denominator and the semantic denominator separately, and any execution-versus-semantic gap MUST be computed only over semantically evaluated cases.

#### Cross-Cutting Requirements

- **FR-010**: All existing unit and integration tests MUST remain green. The baseline is the 255-test suite recorded at Gate 2 close; if the suite grows during implementation, every pre-existing test MUST still pass and new behaviour MUST be covered by new tests.
- **FR-011**: The sandbox process isolation and the read-only guard on the persistent `PERMANENT` mapset MUST remain functionally unchanged. Semantic verification MUST NOT weaken or bypass either guarantee.
- **FR-012**: All generation, repair, static validation, execution, semantic querying, and reporting MUST operate fully offline through the local model service and local GRASS installation. No external network service may be contacted.
- **FR-013**: Attempt accounting, duplicate detection, assertion ordering, and metric computation MUST be deterministic for identical inputs. No result may depend on filesystem iteration order or unordered collections.
- **FR-014**: The system MUST clean up scratch sessions and temporary artifacts on success, failure, and operator interrupt, including after a semantic-query failure.
- **FR-015**: The run summary MUST record the model identity, GRASS version, target dataset, tier budgets, and pilot-suite identity so that a Gate 3 result can be reproduced and compared.

### Key Entities

- **Benchmark Case**: A single natural-language geospatial task with an identifier, tier, expected tools, auxiliary inputs, and — for pilot cases — declared outputs and assertions. A case owns one attempt history and produces one case result.
- **Attempt Record**: One generated candidate for a case. Attributes: attempt number, producing tier, generated code, failure mode, exact error or diagnostic excerpt, static-versus-runtime status, duplicate status, and outcome.
- **Attempt History**: The complete ordered set of attempt records for a case, carried across tiers and supplied to repair prompts. It is the memory that replaces the previous stateless "last error only" context.
- **Repair Prompt Context**: The task, tool documentation, dataset inventory, complete attempt history, and the explicit no-repeat instruction, optionally pivoted to include an explicit parameter list for the failing tool.
- **Semantic Assertion**: A declared, programmatic check on one expected output map. Raster assertions cover non-null count, value range, and mean tolerance; vector assertions cover feature count, geometry type, and required columns.
- **Assertion Result**: The evidence for one semantic check: output, check type, expected value or range, observed value, tolerance, and verdict.
- **Case Result**: The persisted outcome for one case: both pass verdicts, assertion results, all attempt records with tiers, per-tier used and remaining budgets, no-op count, and terminal status.
- **Run Report**: The regenerable summary of a suite run: `Pass@Executed` and `Pass@Semantic` rates, semantic failure breakdown, duplicate statistics, tier usage, and run metadata.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The pilot suite contains exactly 10 cases, drawn from both benchmark tiers, with at least four cases per benchmark tier, at least one raster assertion and one vector assertion represented, and at least two multi-step or mixed raster/vector cases; every case declares at least one expected output and one assertion.
- **SC-002**: For every completed case that declares semantic assertions, both `Pass@Executed` and `Pass@Semantic` are recorded, and no case is ever counted as a semantic pass without also being an execution pass. Cases without assertions are explicitly reported as semantic-not-evaluated and excluded from the semantic denominator.
- **SC-003**: A 40-case benchmark run accepts zero duplicate repairs for execution, and 100% of duplicate candidates are detected and recorded as no-ops. An injected byte-identical duplicate and an injected formatting-only duplicate are both rejected in verification tests.
- **SC-004**: For 100% of completed cases, `case_result.json` identifies the stage/tier of every attempt and states used and remaining attempts for both tiers separately.
- **SC-005**: A case that exhausts its static tier launches zero GRASS processes, consumes zero runtime session time, and is reported with the runtime tier untouched.
- **SC-006**: The main Gate 3 report table displays exactly `Pass@Executed` and `Pass@Semantic` for each suite and for the run overall, together with the gap between them, in 100% of generated reports. Both denominators are stated, non-evaluated cases are excluded from the semantic rate, and any `Pass@Healed` figure appears only in a separate Gate 2 comparison section.
- **SC-007**: All 255 pre-existing tests pass, and the new behaviour is covered by tests for static/runtime budget isolation, stateful history, byte- and AST-level duplicate rejection, parameter-injection pivoting, raster assertions, vector assertions, missing-output handling, and dual-metric reporting.
- **SC-008**: After a full benchmark run, including interrupted runs and semantic-query failures, the persistent `PERMANENT` mapset is byte-for-byte unchanged and no scratch artifacts remain.
- **SC-009**: A complete Gate 3 run makes zero external network calls and performs all inference through the local model service. Network isolation is verified by a socket connection interceptor audit (asserting zero `socket.connect` calls) alongside execution in an offline environment.
- **SC-010**: 100% of repair prompts for cases with prior attempts contain the attempt history required by FR-005 and FR-005a, the explicit "DO NOT repeat previous scripts or failed parameter combinations." instruction, and the most recent attempt's full code.
- **SC-011**: 100% of semantic failures are attributable to a named assertion with expected and observed evidence; no semantic failure is reported as an unexplained failure.
- **SC-012**: Before benchmarking, all 10 pilot cases reproduce their declared expected values on the reference dataset within the declared tolerances in 100% of reference checks; a mismatch is treated as a suite defect, not a model failure.
- **SC-013**: A 40-case run completes without an unhandled crash, report generation succeeds, and every case reaches a terminal state even when the model, GRASS, or a semantic query fails.
- **SC-014**: In 100% of cases with failed semantic assertions, no repair attempt is launched and no tier budget is consumed after verification; the case ends with its semantic verdict and assertion evidence intact.

## Assumptions

- **Existing suite baseline**: The "255 tests" figure is the Gate 2 closing baseline. Any tests added by this feature are additional; the zero-regression requirement applies to every test that existed before implementation.
- **Execution definition**: "Non-empty mapset" means at least one new map created by the successful candidate in the disposable scratch session. Read-only tasks that only print statistics or display maps are outside the pilot's execution-success definition and are excluded from the 10-case pilot.
- **Budget accounting**: The initial candidate is free. Each tier allows two repairs by default. The worst case is five generated candidates per case: one initial, two static repairs, two runtime repairs.
- **Static tier scope**: The static tier covers every rejection that occurs before execution, including syntax, forbidden imports, output-contract and formatting slips, unknown tools, unknown parameters, and other schema violations. A schema failure never reaches GRASS and is not charged to the runtime tier.
- **Tier attribution of a bad repair**: A candidate generated during the runtime tier that fails static validation is charged to the runtime tier and is not executed. This prevents an infinite static/runtime bounce while preserving the independence of the two budgets.
- **Duplicate handling**: A duplicate candidate is rejected before execution and charged to the tier that produced it. The next attempt uses the parameter-injection pivot. A pivot that is also a duplicate, or a duplicate with no remaining budget, ends the case as an unresolved no-op failure.
- **Duplicate equivalence**: Byte-level equality means identical code bytes after normalizing line endings. Structural equality means equivalent parsed programs, ignoring comments, docstrings, whitespace, and formatting. Changes that alter operations, tool names, or parameters are not duplicates.
- **Pilot output naming**: Pilot prompts are allowed to be more explicit than the general benchmark prompts and will name required output maps so assertions are unambiguous. General 40-case prompts are not required to name outputs.
- **Pilot composition**: The pilot must include at least two multi-step or mixed raster/vector cases to exercise realistic pipelines; the remaining cases may be single-tool. Single-tool cases remain valuable because their expected values are the easiest to author and defend.
- **Expected-value authority**: Expected raster ranges and means, and expected vector geometry and columns, come from an independent reference execution on the target dataset, reviewed by a human. Default mean tolerance is 1% relative unless a case declares otherwise; count and range tolerances are declared per case.
- **Semantic scope**: A semantic pass means the declared assertions passed. It is not a proof of global geospatial correctness, and reports must say so.
- **Runtime repair scope**: Non-zero exits and successful exits that create no new map are repairable runtime failures. Failed semantic assertions are report-only and must never be fed back into the repair loop, preserving the assertions as an independent oracle.
- **Semantic denominator**: Only the 10 pilot cases declare assertions. In a mixed run, non-pilot cases are excluded from the `Pass@Semantic` denominator rather than counted as failures; the report always states both denominators.
- **Vector checks**: Feature count is taken from vector topology metadata and attribute-column presence from the column inventory. These are distinct checks; a case with many features but missing required columns still fails.
- **Resource bounds**: Semantic queries run with a bounded timeout and do not consume repair attempts. Their failure is a case-level semantic failure.
- **Environment**: The target dataset is the North Carolina sample location used by Gate 2; the local model is `qwen2.5-coder:7b`; the local GRASS installation is the supported 8.x version. Offline operation is mandatory.
- **Terminology**: "Benchmark Tier 1" and "Benchmark Tier 2" refer to the existing benchmark suites. The retry budgets are canonically the "static repair tier" and the "runtime repair tier". A "candidate" is one generated Python program before and during evaluation; an "attempt" is the persisted execution record for one candidate, including its producing repair tier, outcome, diagnostics, and duplicate status. "Tier" without a qualifier is avoided in normative text.
- **Reporting source of truth**: `case_result.json` is the source of truth; the Markdown report is a derived view and must be reproducible from persisted results.
- **Metric continuity**: The main Gate 3 table is deliberately limited to `Pass@Executed` and `Pass@Semantic`. Gate 2's `Pass@Healed` is retained only in a separate comparison section so the dual-metric contract stays unambiguous while historical comparison remains available.
- **Resumption**: Case-granularity resumption from Gate 2 remains in force. An interrupted case restarts from its initial candidate with both tier budgets reset, because its history is not considered complete.

### Out of Scope

- Extending semantic assertions to all 40 benchmark cases; only the 10-case pilot is in scope.
- Automatically discovering expected geospatial values from model output or treating model output as the oracle.
- Changing the sandbox isolation mechanism, the `PERMANENT` read-only guard, or the modern `grass.tools` interface contract.
- Adding cloud model backends, network retrieval, or non-Ollama inference.
- UI work, dashboards, or interactive visualisation of semantic results.
- Performance optimisation of generation or execution beyond the bounded query timeouts required for assertions.
- Expanding the GRASS knowledge base or adding new tool documentation beyond what is needed for the parameter-injection pivot.
