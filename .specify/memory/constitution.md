# GrassAgent Constitution
<!-- Sync Impact Report
Version change: N/A → 1.0.0
Modified principles: N/A (initial constitution)
Added sections: Core Mission & Scope, Technology Stack & API Standards, Zero-Chat & Pure Script Contract, Phased Development Gates, Code Quality, Governance
Removed sections: N/A
Follow-up TODOs: RATIFICATION_DATE confirmed as 2026-09-22
-->

## Core Principles

### I. Core Mission & Scope
GrassAgent is an open-source, fully offline local AI agent that translates natural language geospatial instructions directly into executable GRASS Python scripts. The agent must operate completely autonomously without any network connectivity. The software shall always be referred to as GRASS (not GRASS GIS) in all generated scripts, documentation, and communications.

### II. Technology Stack & API Standards
All generated scripts must strictly use the modern `grass.tools` interface (`from grass.tools import Tools`). Legacy `grass.script.run_command` or raw CLI calls are strictly prohibited. All inference and embeddings must run strictly offline via Ollama. No external cloud APIs are permitted. The approved model stack is:
- LLM Code Generation: `qwen2.5-coder:7b` (primary evaluation) and `qwen2.5-coder:3b` (rapid smoke testing)
- Embeddings & Retrieval: `nomic-embed-text:latest` for semantic search, RAG, and tool discovery

### III. Zero-Chat & Pure Script Contract
The agent is a code generator, not a chatbot. Model output must be strictly executable Python code only. All conversational pleasantries, explanations, summaries, and Markdown conversational wrappers are prohibited. The output must contain only valid Python syntax needed to execute the requested task.

### IV. Phased Development Gates
Development proceeds through strictly ordered gates. Gate 1 (current): Pure script contract adherence—the model must reliably produce raw, valid `grass.tools` scripts with zero conversational filler. Strict Testing Invariant: Absolutely no test suite or automated execution harness shall be developed or run until Gate 1 is passed with 100% reliability. Subsequent gates: Gate 2—Execution harness inside a running GRASS session; Gate 3—Automated error feedback and self-correction loop.

### V. Code Quality
Every generated script must be fully self-contained with explicit imports. All `grass.tools` invocations must use strongly typed parameters. No implicit defaults or ambiguous type coercion are permitted in generated code.

## Governance

This constitution supersedes all other development practices. Amendments require documented rationale, version increment per semantic versioning (MAJOR for backward-incompatible principle changes, MINOR for new principles or material expansions, PATCH for clarifications), and migration plan for affected components. All PRs and reviews must verify compliance with these principles. Complexity must be justified against the zero-chat contract and offline-first mandate.

**Version**: 1.0.0 | **Ratified**: 2026-09-22 | **Last Amended**: 2026-09-22