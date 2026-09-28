# Quickstart Guide: Pure Script Generation Engine (Gate 1)

**Feature**: `001-pure-script-generation`

## Prerequisites
1. Local Ollama running at `http://localhost:11434` with required models pulled:
   - `qwen2.5-coder:3b` (rapid smoke testing)
   - `qwen2.5-coder:7b` (primary evaluation)
   - `nomic-embed-text:latest` (embeddings)
2. Python environment with dependencies installed (`pip install -r requirements.txt`).
3. Knowledge base initialized (`data/grass_knowledge.db`).

## Running Code Generation (CLI)
Generate a script from a natural language prompt:
```bash
python generate.py "create a 200m buffer around vector streams"
```

Print generated code directly to stdout (zero-chat contract enforcement):
```bash
python generate.py --print "compute slope from elevation raster and generate contours"
```

## Running the Curated Benchmark Suite
Execute the evaluation runner to verify `ast.parse()` validity and zero-chat compliance across all 10 benchmark test cases:
```bash
python benchmarks/run_eval.py --model qwen2.5-coder:3b
python benchmarks/run_eval.py --model qwen2.5-coder:7b
```
