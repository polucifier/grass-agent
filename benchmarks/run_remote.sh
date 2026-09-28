#!/usr/bin/env bash
set -e

# Install Ollama and start the daemon in the background.
# zstd must be present first: the Ollama installer refuses to extract its
# tarball without it, and stock Colab images do not ship it.
apt-get update -qq
apt-get install -y -qq zstd
curl -fsSL https://ollama.com/install.sh | sh
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 8

# Pull required models
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text

# Install Python dependencies
pip install -q -r requirements.txt

# Run the benchmark evaluation
python3 benchmarks/run_eval.py --model qwen2.5-coder:7b
