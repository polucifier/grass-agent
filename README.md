# Grass Agent — Pure Script Generation Engine

A fully offline AI agent that turns a natural-language GIS request into a **self-contained, runnable `grass.tools` Python script**. Generated scripts are pure code — no chat, no markdown fences, no explanation — so they can be dropped straight into a GRASS Python console or a `.py` file and run.

> **Status:** Gate 1 — pure script contract. Grounded in the official GRASS 8.6 documentation via RAG, validated for syntax and API signatures, and benchmarked at **10/10 on `qwen2.5-coder:7b`**.

Everything runs locally. No cloud APIs, no outbound network calls at generation time.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1. Pull models (starts with qwen2.5-coder:7b + nomic-embed-text)
./scripts/pull_models.sh

# 2. Generate code — the knowledge base ships with the repo, no build step needed
.venv/bin/python generate.py "create a 200-meter buffer around the stream network lines"
# → generated/create_a_200_meter_buffer_around_the_stream_network_lines.py
```

Print straight to stdout instead of writing a file:

```bash
.venv/bin/python generate.py --print "create a 200-meter buffer around the stream network lines"
```

```python
from grass.tools import Tools
tools = Tools()
tools.v_buffer(input="streams", output="streams_buffer", distance=200)
```

Multi-step requests chain tools and pass intermediates along:

```bash
.venv/bin/python generate.py --print "Compute slope from the elevation raster and then generate 10m contour lines from the elevation."
```

```python
from grass.tools import Tools
tools = Tools()

# Compute slope from the elevation raster
slope_output = "slope_output"
tools.r_slope_aspect(elevation="elevation", slope=slope_output)

# Generate 10m contour lines from the elevation
contour_output = "contour_output"
tools.r_contour(input="elevation", output=contour_output, step="10")
```

## What the output guarantees

| Guarantee | How it is enforced |
|-----------|--------------------|
| Pure Python only, zero conversational text | System prompt + `extract_python_code()` drops markdown fences and trailing prose |
| Exactly `from grass.tools import Tools` / `tools = Tools()` | System prompt; enforced by the zero-chat check in the benchmark runner |
| Underscore method names (`tools.v_buffer`) | System prompt, **plus** `normalize_dotted_calls()` rewrites `tools.v.buffer` → `tools.v_buffer` after extraction |
| Real tool names, correct parameters, no missing required args | `validate_api()` checks every `tools.*` call against the knowledge base |
| Parses under `ast.parse()` | `validate_syntax()`; a syntax error fails generation outright |

## Architecture

```
generate.py               CLI entry point
├── code_generator.py     Pipeline: retrieve → prompt → LLM → normalize → validate
│                         + SYSTEM_PROMPT rules, CANONICAL_EXAMPLES, debug header
├── rag_retriever.py      Hybrid retrieval: sqlite-vec + lexical LIKE + boosts
├── llm_provider.py       OllamaProvider (chat + embeddings)
├── config.py             Settings via environment variables
├── benchmarks/
│   ├── run_eval.py       Evaluation runner (10 cases, asserts + saves artifacts)
│   └── benchmark_prompts.json   Immutable benchmark suite
├── data/grass_knowledge.db      543 tools + embeddings (committed)
└── scripts/
    ├── build_knowledge_base.py  Ingest the GRASS tool pages → SQLite
    └── pull_models.sh           Pull the three Ollama models
```

**Pipeline:**

```
User request
  → embed request (nomic-embed-text)
  → hybrid retrieval: vector top-k ∪ synonym-expanded LIKE matches
  → re-rank by score, then de-duplicate by functional step
  → prompt = system rules + real signatures (generic params stripped)
  → qwen2.5-coder:7b generates the script
  → normalize dotted calls → ast.parse → validate_api against knowledge base
  → writes generated/<slug>.py
```

### Retrieval

Pure vector similarity is not enough on short prompts — general terrain modules outrank direct functional tools. `rag_retriever.py` blends several signals:

- **Vector similarity** via `sqlite-vec` over 768-dim embeddings.
- **Lexical matching** via SQL `LIKE` on `name` and `description`, using tokens expanded through a `SYNONYMS` map (`statistics`→`stats`, `zonal`→`v.rast.stats`, `rasterize`→`to.rast`, `import`→`v.import`, …). Underscore API names (`v_rast_stats`) are normalized back to dotted form so both conventions match.
- **Wrapper preference:** `v.import` / `r.import` outrank the raw drivers `v.in.ogr` / `r.in.gdal`, unless the prompt explicitly names ogr/gdal.
- **Anti-crowding:** tools are mapped to *functional steps* and only one tool per step is kept, so the top-k holds distinct operations rather than several variants of the first. Cross-type counterparts (`r.buffer` on a vector-scoped prompt) and off-topic display tools are penalised.
- **Category and keyword boosts**, plus a small set of `KEYWORD_TOOL_OVERRIDES` guaranteeing core tools (`d.rast`, `v.buffer`, `r.mapcalc`, …) are always candidates.

### Prompt hygiene

To keep the context small and the model honest:

- Generic parameters (`flags`, `overwrite`, `verbose`, `quiet`, `superquiet`) are stripped from signatures and required-parameter summaries.
- `CANONICAL_EXAMPLES` supplies a correct call pattern for outlier tools whose scraped docs lack one — currently `r.mapcalc` and `r.mapcalc.simple`. This is deliberately a small, targeted map, not 500+ hand-written examples.

### Debug output

Every saved file (from `generate.py` and from the benchmark runner) begins with a commented header recording the retrieved tool docs and the **exact** system and user prompts sent to the model — so any bad output can be traced back to the prompt that produced it:

```python
# ==============================================================================
# DEBUG: RAG RETRIEVAL & LLM PROMPT
# ==============================================================================
# Task: create a 200-meter buffer around the stream network lines
# Retrieved RAG Tools:
#   - v.buffer: Creates a buffer around vector features of given type.
#     Signature: grass.tools.Tools.v_buffer(input,
#     ...
```

## Benchmark Suite

`benchmarks/benchmark_prompts.json` holds 10 curated cases — 4 single-tool, 3 multi-step, 3 edge cases — covering buffers, slope/aspect, import, display, contours, rasterization, zonal statistics, viewshed, raster calculation, and overlay.

```bash
.venv/bin/python benchmarks/run_eval.py --model qwen2.5-coder:7b
.venv/bin/python benchmarks/run_eval.py --model qwen2.5-coder:3b
```

Each case must pass **all** of:

1. `ast.parse()` syntax validity
2. Zero-chat compliance (starts with the `Tools` import, no fences, no prose)
3. No `validate_api()` issues
4. Expected tools actually called — a case may list an alias group like `["v.in.ogr", "v.import"]` and passes if **any** member is used

Artifacts are always written to `benchmarks/output/`, pass or fail, each prefixed with the debug header.

**Latest result — 10/10 on `qwen2.5-coder:7b`.** The 3B model is usable as a fast smoke test but fails several tool-selection cases, which is why 7B is the default.

> The benchmark prompts are treated as **immutable**: they represent realistic user input. Behaviour changes are made in `code_generator.py`, `SYSTEM_PROMPT`, or the retrieval configuration — never by editing the prompts.

## Knowledge Base

Built from the official GRASS 8.6 documentation (not hand-written or AI-generated):

- `Tools - GRASS 8.6 Documentation.html` — the local full index of tool names and descriptions
- Per-tool manual pages — the **"Python (grass.tools)"** tab provides the real method signature, parameter types, required flags, defaults, and a usage example

`data/grass_knowledge.db` stores each tool's name, category, description, signature, example, parsed parameters, and a 768-dim embedding in a `vec0` virtual table. It is **committed to the repository** (3.8 MB), so a fresh clone works immediately. To rebuild from scratch, run `scripts/build_knowledge_base.py` — cached HTML in `data/cache/` (not committed) makes rebuilds network-free.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GRASS_OLLAMA_MODEL` | `qwen2.5-coder:7b` | Ollama chat model for code generation |
| `GRASS_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Ollama model for embeddings |
| `GRASS_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `GRASS_RAG_DB` | `data/grass_knowledge.db` | Path to the knowledge base |
| `GRASS_RAG_TOP_K` / `RAG_TOP_K` | `5` | Tool docs included in the prompt context |
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

- **Model choice:** 7B is the default and passes the full suite. 3B is a faster smoke test but picks the wrong tool on several cases. On a machine without a suitable GPU, 7B runs on CPU and is noticeably slower.
- **Tool recall depends on retrieval.** Failures are usually recall failures (the right tool never reached the prompt) rather than model failures; the debug header makes this visible.
- **No execution.** This engine only generates scripts. It does not run GRASS, resolve input data, or verify results — it validates syntax and API signatures, nothing more.
- Generated scripts assume an already-initialized GRASS session with the relevant input maps present.
- Parameter *names* are checked against the knowledge base; parameter *values* are not checked for real-world validity.

## License

[MIT](LICENSE) - Copyright (c) 2026 Mykhailo Radchenko
