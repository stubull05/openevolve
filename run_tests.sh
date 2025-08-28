#!/bin/bash
set -e
cd /workspace/target
echo "▶️ Running DuckDB + Ollama integration tests (inside container)..."
python -m pytest -q test_ollama_duckdb.py || python test_ollama_duckdb.py
