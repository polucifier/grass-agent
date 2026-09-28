#!/usr/bin/env bash
set -e

# 1. Install Ollama and start daemon in the background
curl -fsSL https://ollama.com/install.sh | sh
nohup ollama serve > /dev/null 2>&1 &
sleep 3

# 2. Pull required models (Colab network downloads these in ~30 seconds)
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Run the benchmark evaluation
python3 benchmarks/run_eval.py --model qwen2.5-coder:7b
