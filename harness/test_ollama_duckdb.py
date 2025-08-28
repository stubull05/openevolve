import os, sys
from pathlib import Path
here = Path(__file__).parent
sys.path.insert(0, str(here))

from openai_ollama_provider import OpenAIOllamaProvider

try:
    import duckdb
except ImportError:
    duckdb = None

def test_duckdb_roundtrip():
    if duckdb is None:
        print("[TEST] duckdb not installed; skipping DB test.")
        return
    db_path = here / 'data' / 'market.duckdb'
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE IF NOT EXISTS chat_history(ts TIMESTAMP, prompt TEXT, reply TEXT);")
    con.execute("INSERT INTO chat_history VALUES (CURRENT_TIMESTAMP, 'hello', 'world');")
    rows = con.execute("SELECT COUNT(*) FROM chat_history;").fetchone()
    assert rows[0] >= 1
    con.close()
    print(f"[TEST] duckdb rows now: {rows[0]}")

def test_ollama_stream_minimal():
    provider = OpenAIOllamaProvider()
    chunks = []
    for tok in provider.get_stream("Give a one-sentence trading tip about AAPL"):
        chunks.append(tok)
        if sum(len(c) for c in chunks) > 120:
            break
    text = ''.join(chunks).strip()
    assert len(text) > 0
    print("[TEST] ollama stream sample:", text[:120])

if __name__ == '__main__':
    test_duckdb_roundtrip()
    test_ollama_stream_minimal()
    print("[TEST] All checks complete.")
