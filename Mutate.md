What OpenEvolve Is (and how we’re using it)

OpenEvolve is an LLM-driven evolutionary optimizer for code. It generates program variants, scores them by running your test/evaluation pipeline, and keeps the best ones in a MAP-Elites “grid” (optionally with multiple “islands”) to explore diverse solutions. In our setup:

Driver loop picks one file at a time from the Rysky repo and invokes OpenEvolve.

OpenEvolve asks the model to rewrite that single file (full contents).

The container runs evaluation.py, which:

executes Python tests (pytest -q /workspace/target/tests)

runs a JS/TS syntax check (esbuild) across *.js|*.jsx|*.ts|*.tsx

If the variant scores better or equal (tests pass / syntax OK), OpenEvolve checkpoint(s) it.

The driver applies the latest best_program back to the real repo file and moves on.

How the Model Should Mutate the Rysky Repo

Prime directive: make minimal, correct changes to the one file provided, so that overall repo evaluation improves (more tests pass, fewer errors, better behaviors). Emit only the complete file content—no commentary, no JSON, no markdown.

Global rules for all files

Keep public APIs and component props stable unless tests demand a change.

No secrets, no external network calls beyond the app’s expected endpoints.

Prefer small, surgical edits over big refactors.

Deterministic output (no randomness unless already present).

Add imports you need; remove unused imports you eliminate.

Logging: keep it minimal and purposeful.

Timezone: market time defaults to America/New_York where applicable.

Mutation Map (what to improve, by area)
Python backend

Targets

api.py (Flask app, logout endpoint, WebSocket hooks, AI proxy)

data_layer.py (DuckDB integration)

brokers/ (e.g., paper_trading.py, robinhood.py)

core/ (e.g., ticker_extractor.py, helpers)

Goals

Logout flow: endpoint must reset broker state to paper-trading on logout and clear session context safely.

DuckDB:

Single-writer pattern (one connection for writes), safe concurrent reads.

Ensure explicit COMMIT/CLOSE.

Idempotent schema creation; sensible types for timestamps/prices.

No silent failure: raise or log clear errors.

Real-time:

Non-blocking WebSocket/BG workers; avoid long sync calls on request path.

Debounce / coalesce high-frequency writes to DuckDB if needed.

AI provider:

OpenAIOllamaProvider usage should be clean; no hard-coded keys.

Robust error handling (timeouts, bad responses) with graceful fallbacks.

Quality checklist (Python)

File imports resolve; type hints where cheap.

No global mutable state introduced (unless existing pattern).

Defensive handling for missing tickers / invalid intervals.

Unit of work boundaries are clear (connect → write → commit → close).

JavaScript / React frontend (Desktop app)

Targets

desktop/src/Chart.js (lightweight-charts + Konva overlay)

desktop/src/TickerInput.js, TradingControls.js, AccountPanel.js, Chat.js

desktop/src/App.js or main.js (wiring, routing)

desktop/package.json (only if needed to fix scripts, but avoid adding heavy deps)

Goals

Axes & time:

rightPriceScale configured and visible.

timeScale set so dates/times render correctly (no “Invalid Date” / “00:00”).

Timeframe buttons:

1d, 1w, 1m, 3m, 1y all work: correct interval mapping + formatting.

Drawing overlay (Konva):

Pencil (freehand) and straight-line modes toggle properly.

Drawing layer sits above chart; pointer events don’t break chart interactions.

Real-time UI:

Socket events update chart/controls without blocking or memory leaks.

Tooltips/timezone handling are consistent and accurate.

Chat UI:

Card-style messages, timestamps, clean send button behavior.

Quality checklist (JS/TS/React)

The file parses under esbuild (JSX/TSX correct).

No new heavy deps; no broad global state leakage.

Clean and accessible controls; no hard-coded secrets or URLs.

SQL / Config / Misc

Targets

sql_queries.sql, small JSON configs you actually use (avoid lockfiles)

Minimal changes—only when needed to support tests or cleanup.

Goals

Keep SQL compatible with DuckDB; avoid engine-specific quirks.

Ensure queries match the current schema (no dangling columns).

Acceptance Criteria (what “better” means)

Backend tests pass (including DuckDB round-trip, logout behavior).

JS/TS parses repository-wide; no syntax/JSX/TS errors.

Feature expectations are closer to true than before (axes/time, timeframe buttons, Konva overlay, real-time update flow, AI provider safety).

No regressions in public endpoints or component props unless tests require it.

Output Format (strict)

The model receives one file path and its current content as context.

The model must emit only the complete, final contents of that single file.
No backticks, no diffs, no JSON wrappers, no explanations.

Common pitfalls to avoid

Editing multiple files indirectly (only the provided file is writable per iteration).

Returning a diff or a summary instead of the full file content.

Introducing new runtime dependencies that aren’t already present.

Breaking time formatting or timezone assumptions.

Leaving database connections open or missing commits.

How this process evolves the repo

The driver selects a file (biased to code files).

OpenEvolve asks the model for a full rewrite of that file.

The container runs:

pytest for backend,

esbuild parse for JS/TS.

If equal/better, OpenEvolve checkpoints it; the driver applies best_program.* to the actual file.

Repeat for the next file and iterate across the repo indefinitely.