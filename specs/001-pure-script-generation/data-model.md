# Data Model: Pure Script Generation Engine (Gate 1)

**Feature**: `001-pure-script-generation`

## Entities

### 1. Generation Request (Prompt)
- **Description**: Natural language input from the GIS user describing the geospatial operation.
- **Attributes**:
  - `request_id`: Unique identifier (string / UUID).
  - `raw_text`: Natural language prompt string.
  - `timestamp`: Creation ISO timestamp.

### 2. Tool Definition (Knowledge Base Entry)
- **Description**: Metadata stored in `data/grass_knowledge.db` describing each GRASS tool.
- **Attributes**:
  - `name`: Canonical tool name (e.g., `v.buffer`, `r.slope.aspect`).
  - `category`: Tool prefix category (`v`, `r`, `i`, `d`, `g`, etc.).
  - `description`: Human-readable summary.
  - `signature`: Python method signature for `grass.tools`.
  - `params_json`: JSON dictionary mapping parameter names to metadata (type, required status, default value).
  - `embedding`: Vector representation for semantic search via `sqlite-vec`.

### 3. Generated Script
- **Description**: Pure Python code output produced by the LLM pipeline.
- **Attributes**:
  - `code`: Valid Python code string containing `from grass.tools import Tools; tools = Tools()` and tool calls.
  - `ast_valid`: Boolean indicating whether `ast.parse(code)` succeeded without syntax errors.
  - `api_issues`: List of validation warnings from `validate_api()`.
  - `zero_chat_compliant`: Boolean verifying absence of markdown fences or conversational text.

### 4. Benchmark Case
- **Description**: Test item in the curated 10-prompt benchmark suite.
- **Attributes**:
  - `id`: Test case identifier (e.g., `tc_01`).
  - `category`: `single_tool`, `multi_step`, or `edge_case`.
  - `prompt`: Natural language query.
  - `expected_tools`: List of expected tool invocations.
