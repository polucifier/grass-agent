# Grass Agent

An AI-powered assistant for [GRASS GIS](https://grass.osgeo.org/) that lets you perform geospatial analysis through natural language. Describe what you want in plain English, and the agent selects the right GRASS tool, executes it, and explains the results.

Built on [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) with support for both local and API-based LLMs.

> **Status:** Agent-only MVP — core architecture works with realistic GRASS-like mock tools. Real GRASS integration is planned.

## Demo

```
Provider: OllamaProvider | Model: qwen2.5-coder:3b
Location: nc_spm_08 | CRS: EPSG:3358
Tool registry: 31 tools
Agent ready. Type your request (or 'quit' to exit).

> buffer roads by 100 meters
Tools available to LLM: ['v.buffer']
Calling: v.buffer({'input': 'roads', 'output': 'buffer_roads_100', 'distance': 100.0})
Result: Success: A buffer zone of 100.0 meters was created around vector layer 'roads'.

Agent: The buffer operation has been successful. The output 'buffer_roads_100' contains
a 100-meter buffer around each road feature. You can view it with d.vect map=buffer_roads_100.

> show me info about the dem
Tools available to LLM: ['r.info', ...]
Calling: r.info({'map': 'elevation'})
Result: Map: elevation | Rows: 521 | Cols: 846 | Range: 55.58 to 1563.30

> what did we just do?
Agent: We created a buffer zone around "roads" using v.buffer (100m, output: buffer_roads_100),
then inspected the "elevation" raster using r.info.

> quit
Exiting.
```

## Features

- **Natural language to GRASS commands** — describe your analysis in plain English, the agent picks the right tool
- **Smart tool selection** — two-stage pipeline: keyword filtering + semantic ranking across 31 GRASS tools
- **Multi-turn conversations** — the agent remembers what you've done and builds on previous results
- **Conversational fallback** — non-tool queries get natural responses without forcing a tool call
- **Multi-step tool chains** — the agent can call multiple tools in sequence when an operation requires it
- **Dual LLM support** — works with local Ollama models (offline, private) or API providers (OpenAI, Anthropic)
- **GRASS session context** — the system prompt includes your current location, CRS, region, and available data
- **Input validation** — tool parameters are validated before execution with clear error messages
- **Error recovery** — failed tool calls are reported back to the LLM, which suggests alternatives

## Architecture

```
agent.py                 Main REPL loop, conversation management, tool execution
├── llm_provider.py      LLM abstraction (OllamaProvider, APIProvider)
├── tool_selector.py     31-tool registry, keyword filter, semantic ranking
├── rag_module.py        Embedding-based similarity search (legacy, used by tool_selector)
├── grass_context.py     GRASS session context for system prompt
├── config.py            Configuration via environment variables
└── grass_mcp_server.py  MCP server with 20 GRASS-like mock tools
```

**Data flow:**

```
User input
  → Tool Selector (keyword filter → semantic rank)
  → LLM sees top relevant tools + GRASS context
  → LLM decides: call tool(s) or respond conversationally
  → MCP Server executes GRASS command
  → LLM summarizes result
```

## Quick Start

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) (for local LLM) or an API key (for OpenAI/Anthropic)
- GRASS GIS 8+ (for real integration; not required for mock mode)

### Installation

```bash
git clone https://github.com/polucifier/grass-agent.git
cd grass-agent
python3 -m venv .venv
source .venv/bin/activate
pip install ollama mcp fastmcp
```

### Pull required models

```bash
ollama pull qwen2.5-coder:3b    # or :7b for better quality
ollama pull nomic-embed-text     # for semantic tool selection
```

### Run

```bash
python3 agent.py
```

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `GRASS_AGENT_USE_API` | `false` | Set to `true` to use API provider instead of Ollama |
| `GRASS_OLLAMA_MODEL` | `qwen2.5-coder:3b` | Ollama model for chat |
| `GRASS_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Ollama model for embeddings |
| `GRASS_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `GRASS_API_PROVIDER` | `openai` | API provider: `openai` or `anthropic` |
| `GRASS_API_MODEL` | `gpt-4o` | API model name |
| `GRASS_API_KEY` | — | API key (required when using API) |
| `GRASS_API_BASE_URL` | — | Custom API endpoint (optional) |
| `GRASS_SIMILARITY_THRESHOLD` | `0.4` | Minimum similarity for tool selection |
| `GRASS_MAX_TOOL_CALLS` | `10` | Max tool calls per conversation turn |

### Using with OpenAI

```bash
export GRASS_AGENT_USE_API=true
export GRASS_API_KEY=sk-your-key-here
export GRASS_API_MODEL=gpt-4o
python3 agent.py
```

### Using with Anthropic

```bash
export GRASS_AGENT_USE_API=true
export GRASS_API_PROVIDER=anthropic
export GRASS_API_KEY=sk-ant-your-key-here
export GRASS_API_MODEL=claude-sonnet-4-20250514
python3 agent.py
```

## Available Tools

The agent knows about 31 GRASS tools organized by category. 20 are currently implemented as mock tools:

| Category | Tools | Implemented |
|----------|-------|-------------|
| **Raster** | `r.slope.aspect`, `r.mapcalc`, `r.univar`, `r.colors`, `r.resamp.stats`, `r.grow`, `r.clump`, `r.distance`, `r.info` | 5/9 |
| **Vector** | `v.buffer`, `v.info`, `v.clean`, `v.overlay`, `v.dissolve`, `v.centroids`, `v.to.rast`, `v.extract`, `v.category` | 7/9 |
| **General** | `g.region`, `g.list`, `g.gisenv`, `g.rename`, `g.copy`, `g.remove` | 3/6 |
| **Display** | `d.rast`, `d.vect`, `d.mon`, `d.out.file` | 2/4 |
| **Analysis** | `r.cost`, `r.surf.idw`, `v.surf.rst` | 1/3 |

### Tool Selection Pipeline

1. **Keyword filter** — fast inverted index matches query words to tool keywords (e.g., "buffer" matches `v.buffer`)
2. **Semantic ranking** — Ollama embeddings compute cosine similarity between query and tool descriptions
3. **LLM decides** — top 10-15 tools are exposed to the model, which chooses whether to call one (or respond conversationally)

## REPL Commands

| Command | Action |
|---------|--------|
| `quit` / `exit` / `q` | Exit the agent |
| `clear` | Reset conversation history |
| *(anything else)* | Process as a GIS query |

## Roadmap

- [ ] Real GRASS GIS integration via `grass.script` API
- [ ] GRASS session initialization (location, mapset, region management)
- [ ] Dynamic tool discovery from installed GRASS modules
- [ ] Security validation layer (parameter bounds, path sanitization)
- [ ] Production error handling with retry/resilience
- [ ] wxGUI plugin integration

## License

[MIT](LICENSE) - Copyright (c) 2026 Mykhailo Radchenko
