# Feature Specification: Pure Script Generation Engine for grass.tools (Gate 1)

**Feature Branch**: `001-pure-script-generation`

**Created**: 2026-09-22

**Status**: Draft

**Input**: User description: "Feature: Pure Script Generation Engine for grass.tools (Gate 1)

Create a feature specification based on spec-template.md for implementing the core prompt and generation pipeline of GrassAgent, strictly scoped to Gate 1 (Pure Script Contract Adherence).

Key specifications to cover:

1. Target Feature Scope:
- Core prompt engineering and agent inference pipeline that translates natural language geospatial commands into raw, executable Python scripts using exclusively the `grass.tools` interface.
- Complete adherence to the Zero-Chat contract: output must be purely valid Python code with zero conversational tokens, explanations, preambles, or markdown chattiness.

2. User Stories & Priorities:
- P1 (Single-tool workflow): A GIS user inputs a single-operation command (e.g., "create a 200m buffer around vector streams") -> Agent outputs a self-contained Python script importing and calling `grass.tools` with properly typed arguments.
- P2 (Multi-step pipeline): A GIS user inputs a chained operation (e.g., "compute slope from elevation raster and generate contours") -> Agent outputs a sequential `grass.tools` Python script passing intermediate outputs correctly.
- P3 (Model switching & verification): Capability to route the prompt through either `qwen2.5-coder:7b` (evaluation) or `qwen2.5-coder:3b` (smoke test) via local Ollama and assert pure-code compliance.

3. Functional Requirements:
- System MUST interface exclusively with local Ollama instances (no external/cloud network calls).
- Generated code MUST import and instantiate `Tools` (`from grass.tools import Tools; tools = Tools()`).
- Output MUST be 100% executable Python syntax without conversational text.
- Generated code MUST avoid legacy modules (`grass.script.run_command`, raw subprocesses).
- Parameters must be strictly typed (int, float, str, bool) matching the GRASS tool definitions.

4. Edge Cases:
- Missing optional parameters (system must infer sane defaults per standard GRASS conventions).
- Complex spatial queries where the tool name is not obvious from user text.
- Model attempts to emit Markdown backticks or commentary (prompt/pipeline must prevent or strip any conversational residue).

5. Success Criteria (Measurable):
- 100% of generated outputs parse cleanly via Python `ast.parse()` without syntax errors.
- 0% conversational phrases or natural language summaries in model output across 10 benchmark test cases.
- 100% of generated scripts use `grass.tools` exclusively.

6. Invariants & Assumptions:
- Gate 1 strictly forbids runtime execution harnesses or automated execution inside GRASS until syntax and zero-chat compliance pass 100%.
- Host environment is offline with Ollama running locally.
- Naming convention is strictly GRASS (not GRASS GIS)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Single-Tool Geospatial Operation (Priority: P1)

A GIS user inputs a single-operation natural language command (e.g., "create a 200m buffer around vector streams") and receives a self-contained Python script that imports `grass.tools`, instantiates `Tools`, and invokes the appropriate tool with properly typed arguments.

**Why this priority**: This is the foundational use case that validates the core prompt-to-code pipeline. All multi-step workflows depend on reliable single-tool generation.

**Independent Test**: Can be fully tested by providing a single-operation prompt and verifying the output is syntactically valid Python using `grass.tools` exclusively, with no conversational content.

**Acceptance Scenarios**:

1. **Given** a natural language prompt describing a single GRASS operation, **When** the agent processes the prompt, **Then** the output is a Python script that imports `from grass.tools import Tools` and instantiates `tools = Tools()`.
2. **Given** a prompt with explicit parameter values (e.g., "200m buffer"), **When** the agent generates the script, **Then** all tool arguments are strongly typed (int, float, str, bool) matching the target GRASS tool's parameter definitions.
3. **Given** a prompt with missing optional parameters, **When** the agent generates the script, **Then** sensible defaults per standard GRASS conventions are inferred and included.

---

### User Story 2 - Multi-Step Chained Pipeline (Priority: P2)

A GIS user inputs a chained natural language command (e.g., "compute slope from elevation raster and generate contours") and receives a sequential Python script where intermediate outputs from one `grass.tools` call are correctly passed as inputs to subsequent calls.

**Why this priority**: Real-world geospatial workflows are rarely single-step; this validates the agent's ability to decompose complex requests into ordered tool sequences with proper data flow.

**Independent Test**: Can be tested by providing a multi-step prompt and verifying the generated script chains multiple `grass.tools` calls with correct intermediate variable passing.

**Acceptance Scenarios**:

1. **Given** a natural language prompt describing a sequence of dependent operations, **When** the agent generates the script, **Then** the output contains multiple `tools.<tool_name>(...)` calls where outputs of earlier calls feed into inputs of later calls.
2. **Given** a multi-step prompt, **When** the agent generates the script, **Then** each intermediate result is assigned to a variable and reused, avoiding redundant computation.

---

### User Story 3 - Model Selection and Pure-Code Verification (Priority: P3)

A developer or evaluator selects between `qwen2.5-coder:7b` (full evaluation) and `qwen2.5-coder:3b` (rapid smoke testing) via local Ollama, and the system verifies that model output contains zero conversational residue.

**Why this priority**: Enables continuous evaluation of model quality and fast iteration during development while maintaining the zero-chat invariant.

**Independent Test**: Can be tested by routing identical prompts through both models and asserting both produce syntactically valid Python with zero natural language content.

**Acceptance Scenarios**:

1. **Given** a prompt and model selector set to `qwen2.5-coder:7b`, **When** the agent invokes Ollama, **Then** the request is sent exclusively to the local Ollama endpoint with no external network calls.
2. **Given** a prompt and model selector set to `qwen2.5-coder:3b`, **When** the agent invokes Ollama, **Then** the response is received and validated for pure-code compliance.
3. **Given** a model output containing Markdown backticks or explanatory text, **When** the pipeline processes the response, **Then** all conversational residue is stripped or the output is rejected.

### Edge Cases

- What happens when the user prompt references a GRASS tool that doesn't exist or is ambiguously named?
- How does the system handle prompts requiring parameters with complex types (e.g., coordinate pairs, extent bounding boxes)? → Serialize to GRASS CLI string format (e.g., 'x,y' for coords, 'n,s,e,w' for extents).
- What happens when the local Ollama service is unavailable or returns an error? → Fail fast with clear error (no retry, no fallback).
- How does the pipeline handle model outputs that are partially valid Python but contain trailing commentary? → Strip residue, keep first valid Python block; discard trailing commentary/Markdown.
- What happens when a prompt requires a tool with many optional parameters—are all defaults explicitly included or only required ones? → Bundled defaults registry provides all optional parameter defaults; required params must be user-specified or inferred from context.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST translate natural language geospatial instructions into executable Python scripts using exclusively the `grass.tools` interface.
- **FR-002**: System MUST interface exclusively with local Ollama instances for all LLM inference and embedding operations; no external or cloud API calls are permitted.
- **FR-003**: Generated scripts MUST import and instantiate `Tools` via `from grass.tools import Tools; tools = Tools()`.
- **FR-004**: Generated code MUST be 100% valid Python syntax parseable by `ast.parse()` with zero syntax errors.
- **FR-005**: Generated code MUST contain zero conversational text, explanations, summaries, Markdown formatting, or any non-code tokens.
- **FR-006**: Generated code MUST NOT use legacy modules including `grass.script.run_command`, `grass.script`, or raw `subprocess` calls to GRASS CLI.
- **FR-007**: All `grass.tools` invocations in generated scripts MUST use strongly typed parameters (int, float, str, bool) matching the target GRASS tool's parameter definitions.
- **FR-008**: System MUST support model selection between `qwen2.5-coder:7b` (evaluation) and `qwen2.5-coder:3b` (smoke testing) via configuration.
- **FR-009**: System MUST use `nomic-embed-text:latest` via local Ollama for any semantic search, RAG, or tool discovery operations.
- **FR-010**: Pipeline MUST prevent or strip Markdown code fences, conversational preamble, or trailing commentary from model output.
- **FR-011**: For missing optional parameters, system MUST infer sensible defaults per standard GRASS conventions.
- **FR-012**: System MUST operate in a fully offline environment with no network connectivity required beyond local Ollama.
- **FR-013**: On Ollama service unavailability or error, pipeline MUST fail fast and surface a clear error to the user; no automatic retry or fallback behavior.
- **FR-014**: Complex parameter types (coordinate pairs, extent bounding boxes) MUST be serialized to GRASS CLI-compatible string representations in generated code.
- **FR-015**: Model output containing valid Python with trailing conversational residue MUST be processed by extracting the first parseable Python block and discarding non-code content.
- **FR-016**: System MUST maintain a bundled defaults registry (JSON/YAML) containing standard GRASS optional parameter defaults for all supported tools; registry is used when user omits optional parameters.

### Key Entities

- **Prompt**: Natural language geospatial instruction from the user; contains operation intent, target data, and explicit parameters.
- **Generated Script**: Self-contained Python code artifact; imports `grass.tools`, instantiates `Tools`, contains one or more typed tool invocations.
- **Model Configuration**: Selection of LLM (`qwen2.5-coder:7b` or `qwen2.5-coder:3b`) and embedding model (`nomic-embed-text:latest`) with local Ollama endpoint.
- **Tool Definition**: GRASS tool metadata including name, parameter names, types, required/optional status, and default values.
- **Defaults Registry**: Bundled JSON/YAML file mapping tool names to their optional parameter default values per standard GRASS conventions.
- **Benchmark Suite**: Fixed curated set of 10 diverse geospatial prompts covering single-tool operations, multi-step pipelines, and edge cases for zero-chat compliance validation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of generated outputs parse cleanly via Python `ast.parse()` without syntax errors across all test cases.
- **SC-002**: 0% conversational phrases or natural language summaries detected in model output across 10 benchmark test cases (fixed curated suite covering single-tool, multi-step, and edge cases).
- **SC-003**: 100% of generated scripts use `grass.tools` exclusively with zero legacy API usage.
- **SC-004**: 100% of `grass.tools` invocations use strongly typed parameters matching tool definitions.
- **SC-005**: Model routing correctly invokes the selected model (`qwen2.5-coder:7b` or `qwen2.5-coder:3b`) via local Ollama in 100% of test runs.
- **SC-006**: Zero external network calls observed during generation pipeline execution.

## Assumptions

- Target users are GIS analysts familiar with GRASS concepts but not necessarily Python or `grass.tools` API.
- Host environment has Ollama installed and running locally with required models pulled (`qwen2.5-coder:7b`, `qwen2.5-coder:3b`, `nomic-embed-text:latest`).
- GRASS is installed and the `grass.tools` module is available in the Python environment.
- Gate 1 scope explicitly excludes runtime execution, automated testing harnesses, or execution inside a GRASS session—these are deferred to Gates 2 and 3 per the constitution.
- Naming convention "GRASS" (not "GRASS GIS") is enforced in all generated code, prompts, and documentation.
- The agent operates as a code generator only; no conversational interface or chat history is maintained.
- Standard GRASS conventions for optional parameter defaults are documented and accessible for inference.

## Clarifications

### Session 2026-09-22

- Q: When the local Ollama service is unavailable or returns an error, how should the generation pipeline behave? → A: Fail fast with clear error (no retry, no fallback).
- Q: How should the system handle prompts requiring parameters with complex types (e.g., coordinate pairs, extent bounding boxes) that go beyond basic int/float/str/bool? → A: Serialize to GRASS CLI string format (e.g., 'x,y' for coords, 'n,s,e,w' for extents).
- Q: When model output contains valid Python code but has trailing commentary or partial Markdown, should the pipeline strip the residue or reject the entire output? → A: Strip residue, keep first valid Python block; discard trailing commentary/Markdown.
- Q: Where should the system obtain 'standard GRASS conventions' for optional parameter defaults when not explicitly provided by the user? → A: Bundled defaults registry (JSON/YAML) maintained with the agent.
- Q: What defines the '10 benchmark test cases' referenced in SC-002 for measuring zero conversational phrases? → A: Fixed curated benchmark suite covering single-tool, multi-step, and edge cases.