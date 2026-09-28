#!/usr/bin/env bash
set -euo pipefail

ollama pull qwen2.5-coder:3b
ollama pull nomic-embed-text
ollama pull qwen2.5-coder:7b
