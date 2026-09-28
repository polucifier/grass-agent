# Research: Pure Script Generation Engine (Gate 1)

**Feature**: `001-pure-script-generation`

## 1. Multi-Step Pipeline Prompting Strategy
- **Decision**: Update `SYSTEM_PROMPT` in `code_generator.py` to lift the single-tool constraint. Allow sequential tool calls where outputs of preceding tools (e.g. raster/vector names) are passed as input parameters to subsequent tools.
- **Rationale**: User Story 2 requires chained operations (e.g., compute slope then generate contours). The prompt must instruct the model to assign intermediate results to variables and chain them logically using `tools.<tool_name>(...)`.
- **Alternatives Considered**: Multi-turn agent loop (rejected for Gate 1 as it introduces runtime execution and state management outside pure script generation).

## 2. Coordinate Pairs & Extents Serialization
- **Decision**: Instruct the model via `SYSTEM_PROMPT` and validate via schema guidelines that coordinate pairs (`x,y`) and bounding box extents (`n,s,e,w`) must be passed as comma-separated string literals (e.g., `"635000,216500"` or `"0,10,0,10"`).
- **Rationale**: GRASS tool parameters expecting coordinates or spatial extents accept formatted string arguments in `grass.tools`.
- **Alternatives Considered**: Python tuples or dicts (rejected because GRASS CLI / `grass.tools` expects string representations for spatial bounding boxes and coordinates).

## 3. `Tools()` Instantiation Standard
- **Decision**: Enforce `from grass.tools import Tools; tools = Tools()` without arguments (or with default instantiation).
- **Rationale**: Matches FR-003 and constitution requirements, removing obsolete arguments like `overwrite=True` if not strictly required, or standardizing exact compliance.
- **Alternatives Considered**: `Tools(overwrite=True)` (rejected as FR-003 explicitly specifies `Tools()` instantiation).

## 4. Curated Benchmark Suite & Evaluation Runner
- **Decision**: Create a JSON benchmark file (`benchmarks/benchmark_prompts.json`) containing 10 prompts (4 single-tool, 3 multi-step, 3 edge cases) and an evaluation script (`benchmarks/run_eval.py`) that tests generation across `qwen2.5-coder:3b` and `qwen2.5-coder:7b`.
- **Rationale**: Satisfies SC-002 (0% conversational phrases across 10 benchmark test cases) and enables automated regression testing of pure-code compliance and `ast.parse()` validity.
- **Alternatives Considered**: Manual testing (rejected due to lack of scalability and objective verification).
