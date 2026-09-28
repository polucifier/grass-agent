# Implementation Plan: Pure Script Generation Engine for grass.tools (Gate 1)

**Branch**: `001-pure-script-generation` | **Date**: 2026-09-22 | **Spec**: [specs/001-pure-script-generation/spec.md](spec.md)

**Input**: Feature specification from `/specs/001-pure-script-generation/spec.md`

## Summary

Implement the Gate 1 pure script generation pipeline by refactoring existing modules (`code_generator.py`, `generate.py`, `llm_provider.py`, `rag_retriever.py`). Focus on updating `SYSTEM_PROMPT` to support multi-step pipelined tool chains, precise `Tools()` instantiation (`from grass.tools import Tools; tools = Tools()`), coordinate/extent string serialization, and creating a curated 10-prompt benchmark suite with an automated evaluation runner.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `ollama`, `sqlite-vec`, `sqlite3`, `pydantic`, `pytest` (for evaluation runner)

**Storage**: SQLite with `sqlite-vec` extension (`data/grass_knowledge.db`)

**Testing**: Python AST parser (`ast.parse()`), automated benchmark runner asserting zero-chat compliance and syntax validity across `qwen2.5-coder:3b` and `qwen2.5-coder:7b`.

**Target Platform**: Linux / offline local execution via Ollama

**Project Type**: CLI / AI Code Generator Library

**Performance Goals**: <5s generation time per prompt via local Ollama instance

**Constraints**: 100% offline, zero cloud APIs, strict `grass.tools` usage, zero-chat contract (pure Python output only)

**Scale/Scope**: 10 benchmark test cases covering single-tool, multi-step, and edge cases

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Core Mission & Scope**: PASS. Fully offline local AI agent translating NL to GRASS Python scripts using strictly "GRASS" naming.
- **II. Technology Stack & API Standards**: PASS. Exclusively uses `grass.tools` interface, Ollama local inference (`qwen2.5-coder:3b`, `qwen2.5-coder:7b`, `nomic-embed-text:latest`).
- **III. Zero-Chat & Pure Script Contract**: PASS. Enforces pure Python code output with zero conversational tokens or markdown wrappers.
- **IV. Phased Development Gates**: PASS. Strictly scoped to Gate 1 (pure script contract adherence; no runtime execution harness).
- **V. Code Quality**: PASS. Self-contained scripts with explicit imports and strongly typed parameters.

## Project Structure

### Documentation (this feature)

```text
specs/001-pure-script-generation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (benchmark suite schema & evaluation contract)
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
src/ (repository root)
├── code_generator.py     # Refactored system prompt & pipeline
├── rag_retriever.py      # SQLite vector retriever
├── llm_provider.py       # Ollama integration
├── config.py             # Configuration dataclass
├── generate.py           # CLI entry point
├── benchmarks/           # Curated 10-prompt benchmark suite (JSON/YAML) & evaluation runner
└── data/
    └── grass_knowledge.db # SQLite vector knowledge base
```

**Structure Decision**: Single project repository structure utilizing existing codebase root files with modular benchmarks and evaluation runner.

## Complexity Tracking

*No violations.*
