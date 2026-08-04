# Grass Agent — Milestone 1: Code Generation

An AI-powered generator that produces **`grass.tools` Python code** (GRASS 8.5+) from a natural-language GIS request. The user pastes the generated script into their GRASS Python console and runs it.

> **Status:** Milestone 1 — the model generates valid `grass.tools` Python code grounded in the official GRASS 8.6 documentation (RAG), validated for syntax.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1. Pull models
./scripts/pull_models.sh          # qwen2.5-coder:3b + nomic-embed-text

# 2. Build the knowledge base (one-time, fetches all ~540 GRASS tool docs)
.venv/bin/python scripts/build_knowledge_base.py

# 3. Generate code
.venv/bin/python generate.py "create a 500 meter buffer around the roads"
# → generated/create_a_500_meter_buffer_around_the_roads.py
```

## Example

```
$ python generate.py "create a 500 meter buffer around the roads"
Generating grass.tools code for: create a 500 meter buffer around the roads
Generated: generated/create_a_500_meter_buffer_around_the_roads.py
```

```python
from grass.tools import Tools

tools = Tools(overwrite=True)

tools.v_buffer(
    input="roads",
    layer="-1",
    cats=None,
    where=None,
    type="line",
    output="roads_500m_buffer",
    distance=500.0,
)
```

## Architecture

```
generate.py               CLI entry point
├── code_generator.py     Pipeline: retrieve → prompt → LLM → extract → validate
├── rag_retriever.py      sqlite-vec cosine search over the tool docs
├── llm_provider.py       OllamaProvider (chat + embeddings)
├── config.py             Settings via environment variables
└── scripts/
    └── build_knowledge_base.py   Ingest the 543 GRASS tool pages → SQLite
```

**Pipeline:**

```
User request
  → embed request (nomic-embed-text)
  → sqlite-vec cosine top-k tool docs (+ raster/vector keyword boost)
  → prompt = system rules + real tool signatures/examples
  → qwen2.5-coder:3b generates the script
  → ast.parse syntax validation
  → writes generated/<slug>.py
```

## Knowledge Base

Built from the official GRASS 8.6 documentation (not hand-written or AI-generated):

- `Tools - GRASS 8.6 Documentation.html` — the local full index (544 tools, name + description)
- Per-tool manual pages fetched from `grass.osgeo.org` — the **"Python (grass.tools)" tab** provides the real method signature, parameter types, required flags, defaults, and a usage example

The DB (`data/grass_knowledge.db`) stores each tool's name, category, description, signature, example, parsed parameters, and a 768-dim embedding in a `vec0` virtual table. It is gitignored; rebuild it with `scripts/build_knowledge_base.py` (cached HTML in `data/cache/` makes rebuilds network-free).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GRASS_OLLAMA_MODEL` | `qwen2.5-coder:3b` | Ollama chat model for code generation |
| `GRASS_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Ollama model for embeddings |
| `GRASS_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `GRASS_RAG_DB` | `data/grass_knowledge.db` | Path to the knowledge base |
| `GRASS_RAG_TOP_K` | `8` | Number of tool docs included in the prompt context |
| `GRASS_OUTPUT_DIR` | `generated` | Output directory for generated scripts |

## CLI

```
usage: generate.py [-h] [-o OUTPUT] [--model MODEL] [--print] request

positional arguments:
  request               Natural language description of the GRASS task

options:
  -o, --output OUTPUT   Output file path (default: generated/<slug>.py)
  --model MODEL         Override the Ollama model
  --print               Print code to stdout instead of writing a file
```

## Notes & Known Limitations

- **Model choice:** `qwen2.5-coder:3b` fits the integrated GPU. A larger model (7B+) is more reliable but requires CPU inference (`num_gpu=0`) or more VRAM.
- **Semantic quality:** the 3B model can choose a plausible-but-wrong tool (e.g., raster buffer for roads). The RAG context and raster/vector keyword boost mitigate this; a larger model reduces it further.
- Generated scripts assume an already-initialized GRASS session (`tools = Tools()`).

## License

[MIT](LICENSE) - Copyright (c) 2026 Mykhailo Radchenko
