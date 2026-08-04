#!/usr/bin/env bash
set -euo pipefail

# qwen2.5-coder:3b fits the integrated GPU (7b crashes with
# "Not enough memory for command submission"); use 7b only with more VRAM or CPU.
ollama pull qwen2.5-coder:3b
ollama pull nomic-embed-text
