This harness seeds a target repo with:
- openai_ollama_provider.py (Ollama client using host.docker.internal)
- test_ollama_duckdb.py (DuckDB + Ollama integration tests)

The Docker image sets OLLAMA_BASE_URL to http://host.docker.internal:11434/v1 by default,
so it talks to your host's running Ollama instance.
