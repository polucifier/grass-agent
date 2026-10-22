# GrassAgent Constitution
<!-- Sync Impact Report
Version change: 1.1.0 → 1.2.0
Modified principles: IV (Phased Development Gates — Gate 2 headless execution mechanism)
Added sections: N/A
Removed sections: N/A
Amendment rationale: Gate 2 planning verified that `grass.script.setup.init()` provides no
temp-mapset support, requires manual removal of the `.gislock` left by `g.mapset -c`, and is
strictly more fragile than the GRASS CLI sandbox. Principle IV.2 is amended to name
`grass --tmp-mapset <dataset> --exec python3` as the primary execution mechanism, retaining
`grass.script.setup.init()` as a fallback worker for hosts where the CLI sandbox is unsupported.
The four Gate 2 sub-gates, their ordering, and Principle V's isolation mandate are unchanged.
Affected components: spec 002 plan/tasks (all references to the execution mechanism).
Migration plan: none — Gate 2 is unreleased; no prior implementation depends on the old wording.
Follow-up TODOs: none for Gate 2
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
Development proceeds through strictly ordered, verifiable milestones:
- **Gate 1 (Completed):** Pure script contract adherence, static AST validity, and schema verification against `grass_knowledge.db`. Established baseline: 90.0% zero-shot static verification across the 40-case two-tier benchmark suite.
- **Gate 2 (Current Focus — Runtime Execution & Self-Healing):** Dynamic execution and closed-loop error correction.
  1. *Pre-flight Static Guard:* Generated scripts must pass Gate 1 static AST/schema validation before execution.
  2. *Headless Runtime Execution:* Scripts execute headlessly against designated sample datasets (e.g., North Carolina sample location) inside isolated scratch mapsets. Execution **primarily** uses the GRASS CLI sandbox `grass --tmp-mapset <dataset> --exec python3 <script>`, which provides process-level isolation so that C-level crashes in GRASS or its geospatial dependencies cannot terminate the evaluation harness. `grass.script.setup.init()` is **retained as a fallback worker** for host environments where the CLI sandbox is unsupported. Because the CLI sandbox provides a writable *default mapset* rather than a true sandbox, Principle V's zero-mutation mandate additionally requires an explicit filesystem-level guard on the persistent mapset.
  3. *Runtime Traceback Interception:* Capture and classify runtime `stderr` (missing layers, schema exceptions, syntax slips).
  4. *Autonomous Self-Healing Loop:* Re-prompt the local LLM with the execution traceback, previous code, and targeted RAG documentation under a bounded retry budget to achieve runtime convergence.
- **Subsequent Milestones (Future Work):**
  1. *Hybrid Model Backends:* Optional cloud API adapter allowing users to toggle between local offline inference (Ollama) and cloud LLMs.
  2. *Native GRASS UI Integration:* Native GRASS wxGUI extension and interactive session tooling.

### V. Code Quality & Pre-flight Execution Safety
Every generated script must be fully self-contained with explicit imports. All `grass.tools` invocations must use strongly typed keyword arguments. Positional arguments and hallucinated parameters are prohibited. Generated scripts must never be executed against persistent production mapsets; all runtime evaluations must occur in isolated, ephemeral test mapsets.

## Governance

This constitution supersedes all other development practices. Amendments require documented rationale, version increment per semantic versioning (MAJOR for backward-incompatible principle changes, MINOR for new principles or material expansions, PATCH for clarifications), and migration plan for affected components. All PRs and reviews must verify compliance with these principles. Complexity must be justified against the zero-chat contract and offline-first mandate.

**Version**: 1.2.0 | **Ratified**: 2026-09-22 | **Last Amended**: 2026-10-06
