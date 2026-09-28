---
description: "Task list for Pure Script Generation Engine for grass.tools (Gate 1)"
---

# Tasks: Pure Script Generation Engine for grass.tools (Gate 1)

**Input**: Design documents from `/specs/001-pure-script-generation/`

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure verification

- [X] T001 Verify project structure and python environment per implementation plan in repository root
- [X] T002 [P] Verify required dependencies in requirements.txt (ollama, sqlite-vec, pydantic)
- [X] T003 [P] Verify local Ollama service connectivity and model availability (qwen2.5-coder:3b, qwen2.5-coder:7b, nomic-embed-text:latest)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure and vector knowledge base that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 Verify knowledge base database file at data/grass_knowledge.db and sqlite-vec extension loading in rag_retriever.py
- [X] T005 [P] Verify generation configuration dataclass in config.py
- [X] T006 [P] Verify local Ollama LLM provider and embedding methods in llm_provider.py

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Single-Tool Workflow (Priority: P1) 🎯 MVP

**Goal**: Enable GIS users to input single-operation natural language commands and receive self-contained Python scripts using exclusively `grass.tools` with properly typed arguments.

**Independent Test**: Can be fully tested by providing a single-operation prompt (e.g. "create a 200m buffer around vector streams") to `generate.py` and verifying the output parses via `ast.parse()` and uses `from grass.tools import Tools; tools = Tools()` exclusively.

### Implementation for User Story 1

- [X] T007 [US1] Refactor `SYSTEM_PROMPT` in code_generator.py to enforce exact `Tools()` instantiation (`from grass.tools import Tools; tools = Tools()`) per FR-003
- [X] T008 [US1] Update `code_generator.py` prompt instructions and parameter typing rules to ensure strongly typed parameters (int, float, str, bool) matching tool definitions
- [X] T009 [US1] Update `code_generator.py` to serialize coordinate pairs and extent bounding boxes to comma-separated string format (`'x,y'`, `'n,s,e,w'`) per FR-014
- [X] T010 [US1] Update `code_generator.py` to extract first parseable Python block and discard trailing conversational residue per FR-015
- [X] T011 [US1] Test single-tool generation via CLI entry point in generate.py for single-operation prompt

**Checkpoint**: At this point, User Story 1 (Single-Tool Workflow) should be fully functional and testable independently

---

## Phase 4: User Story 2 - Multi-Step Chained Pipeline (Priority: P2)

**Goal**: Enable GIS users to input chained natural language commands (e.g., compute slope from elevation raster and generate contours) and receive sequential Python scripts passing intermediate outputs correctly.

**Independent Test**: Can be tested by providing a multi-step prompt to `generate.py` and verifying the generated script chains multiple `grass.tools` calls with correct intermediate variable passing.

### Implementation for User Story 2

- [X] T012 [US2] Lift single-tool restriction in `SYSTEM_PROMPT` within code_generator.py to permit multi-step chained tool sequences (User Story 2)
- [X] T013 [US2] Add explicit prompt guidelines in `code_generator.py` for assigning intermediate raster/vector outputs to variables and passing them as inputs to subsequent `tools.*` calls
- [X] T014 [US2] Verify syntax validity and API signature validation for multi-step scripts via validate_syntax and validate_api in code_generator.py
- [X] T015 [US2] Test multi-step pipeline generation via CLI entry point in generate.py for chained operation prompt

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - Model Switching & Benchmark Evaluation Suite (Priority: P3)

**Goal**: Provide capability to route prompts through either `qwen2.5-coder:7b` (evaluation) or `qwen2.5-coder:3b` (smoke test) via local Ollama and assert pure-code compliance across a curated benchmark suite.

**Independent Test**: Can be tested by running the evaluation runner script across the 10-prompt benchmark suite and asserting 100% `ast.parse()` validity and 0% conversational phrases.

### Implementation for User Story 3

- [X] T016 [US3] Create curated benchmark suite JSON file containing 10 diverse geospatial test prompts (4 single-tool, 3 multi-step, 3 edge cases) in benchmarks/benchmark_prompts.json adhering to specs/001-pure-script-generation/contracts/benchmark-schema.json
- [X] T017 [US3] Implement evaluation runner script in benchmarks/run_eval.py to test benchmark prompts against specified model (`qwen2.5-coder:3b` or `qwen2.5-coder:7b`) via Ollama provider
- [X] T018 [US3] Add automated assertions in benchmarks/run_eval.py for 100% `ast.parse()` syntax validity and 0% conversational residue (zero-chat compliance) across all benchmark test cases (SC-002)
- [X] T019 [US3] Run benchmark evaluation suite against both `qwen2.5-coder:3b` and `qwen2.5-coder:7b` and verify successful completion

**Checkpoint**: All user stories should now be independently functional and evaluated

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation updates, quickstart validation, and constitution adherence verification

- [X] T020 [P] Update README.md with instructions for running the Pure Script Generation Engine and evaluation suite
- [X] T021 [P] Verify full offline compliance (zero external network calls, strict Ollama local usage) across all modules
- [X] T022 [P] Verify strict adherence to GRASS naming convention (no "GRASS GIS") across all files and code comments
- [X] T023 Run quickstart.md validation guide to ensure end-to-end functionality

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - US1 (Single-tool workflow) → US2 (Multi-step pipeline) → US3 (Benchmark evaluation suite)
- **Polish (Final Phase)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - Foundation for all code generation
- **User Story 2 (P2)**: Depends on US1 prompt foundation in code_generator.py; extends single-tool to multi-step pipelines
- **User Story 3 (P3)**: Depends on US1 and US2 generation engine being fully operational to evaluate prompts against benchmark suite

### Parallel Opportunities

- T002, T003 can run in parallel during Setup
- T005, T006 can run in parallel during Foundational
- T020, T021, T022 can run in parallel during Polish

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1 (Single-Tool Workflow)
4. **STOP and VALIDATE**: Test single-tool generation via `generate.py`

### Incremental Delivery

1. Complete Setup + Foundational
2. Add User Story 1 (Single-tool) → Test independently (MVP)
3. Add User Story 2 (Multi-step pipeline) → Test independently
4. Add User Story 3 (Benchmark evaluation suite) → Run evaluation across models
5. Complete Polish phase

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
