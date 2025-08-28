import sys
import os
import subprocess
import ast
import re
from pathlib import Path
from typing import Any, Dict

# ----- Paths inside the container -----
TARGET_ROOT       = Path("/workspace/target")
BACKEND_TEST_DIR  = TARGET_ROOT / "tests"                         # your repo's pytest suite root
JS_HARNESS        = Path("/opt/js-harness/js_eval_runner.mjs")    # Node-based syntax/JSX/TS check
PW_CONFIG         = Path("/opt/playwright/playwright.config.ts")  # Playwright config
PW_TEST_DIR       = Path("/opt/playwright/tests")                 # Playwright tests directory

# ----- Env toggles -----
SKIP_PY = os.getenv("EVAL_SKIP_PY", "0").lower() in ("1", "true", "yes")
SKIP_UI = os.getenv("EVAL_SKIP_UI", "0").lower() in ("1", "true", "yes")
SKIP_PW = os.getenv("EVAL_SKIP_PW", "0").lower() in ("1", "true", "yes")

# Require PW by default since logs indicated it's needed for login testing
REQUIRE_PW = os.getenv("EVAL_REQUIRE_PW", "1").lower() in ("1", "true", "yes")

# ----- Timeouts (seconds) -----
PY_TIMEOUT = int(os.getenv("EVAL_PY_TIMEOUT", "900"))   # 15m
UI_TIMEOUT = int(os.getenv("EVAL_UI_TIMEOUT", "300"))   # 5m
PW_TIMEOUT = int(os.getenv("EVAL_PW_TIMEOUT", "180"))   # 3m

# ===========================
# Optional static analyzers
# ===========================
def evaluate_python_code(code_content: str) -> Dict[str, Any]:
    """Basic Python static metrics (kept for completeness)."""
    metrics = {
        "length_score": min(len(code_content) / 1000.0, 1.0),
        "complexity_score": 0,
        "syntax_valid": False,
    }
    try:
        tree = ast.parse(code_content)
        metrics["syntax_valid"] = True
        metrics["complexity_score"] = sum(
            isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.FunctionDef, ast.AsyncFunctionDef))
            for node in ast.walk(tree)
        )
    except SyntaxError:
        metrics["syntax_valid"] = False
    return metrics

def evaluate_javascript_code(code_content: str) -> Dict[str, Any]:
    """Basic JS static metrics (kept for completeness)."""
    function_like = len(re.findall(r"function\s+\w+|=>", code_content))
    return {
        "length_score": min(len(code_content) / 1000.0, 1.0),
        "function_count": function_like,
        "syntax_valid": function_like > 0 or bool(re.search(r"\b(import|export)\b", code_content)),
    }

# ===========================
# Runner helpers (CLI steps)
# ===========================
def _run(cmd, cwd=None, timeout=None, env=None):
    print("[eval]", " ".join(cmd), flush=True)
    try:
        return subprocess.run(cmd, cwd=cwd, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        print(f"[eval] TIMEOUT: {' '.join(cmd)}", flush=True)
        return subprocess.CompletedProcess(cmd, returncode=124)

def _run_pytests() -> int:
    if SKIP_PY:
        print("[eval] Skipping Python tests (EVAL_SKIP_PY=1).", flush=True)
        return 0
    if not BACKEND_TEST_DIR.exists():
        print(f"[eval] No backend test directory at {BACKEND_TEST_DIR}. Treating as pass.", flush=True)
        return 0

    # Ensure repo imports like `import api` / `import data_layer` work:
    env = os.environ.copy()
    extra_paths = ["/workspace/target", "/workspace/target/TradingApp"]
    existing = env.get("PYTHONPATH", "")
    if existing:
        env["PYTHONPATH"] = os.pathsep.join(extra_paths + [existing])
    else:
        env["PYTHONPATH"] = os.pathsep.join(extra_paths)

    # Run from repo root so tests can resolve relative imports/paths
    proc = _run(["pytest", "-q"], cwd=str(TARGET_ROOT), timeout=PY_TIMEOUT, env=env)
    return proc.returncode

def _run_js_harness() -> int:
    if SKIP_UI:
        print("[eval] Skipping UI static checks (EVAL_SKIP_UI=1).", flush=True)
        return 0
    if not JS_HARNESS.exists():
        print(f"[eval] JS harness not found at {JS_HARNESS}. Treating as pass.", flush=True)
        return 0
    proc = _run(["node", str(JS_HARNESS), str(TARGET_ROOT)], timeout=UI_TIMEOUT)
    return proc.returncode

def _run_playwright() -> int:
    if SKIP_PW:
        print("[eval] Skipping Playwright E2E (EVAL_SKIP_PW=1).", flush=True)
        return 0

    missing = []
    if not PW_CONFIG.exists(): missing.append(str(PW_CONFIG))
    if not PW_TEST_DIR.exists(): missing.append(str(PW_TEST_DIR))

    if missing:
        msg = f"[eval] Playwright required but missing: {', '.join(missing)}."
        if REQUIRE_PW:
            print(msg + " Failing.", flush=True)
            return 2
        else:
            print(msg + " Treating as pass (EVAL_REQUIRE_PW=0).", flush=True)
            return 0

    # FRONTEND_URL should be set in docker-compose; playwright.config.ts reads it
    cmd = ["npx", "playwright", "test", "--config", str(PW_CONFIG), "--reporter", "line"]
    proc = _run(cmd, timeout=PW_TIMEOUT)
    return proc.returncode

# ======================================================
# REQUIRED by OpenEvolve: evaluate(program_code, **kwargs)
# ======================================================
def evaluate(program_code: str, file_path: str = None, suffix: str = None, **kwargs) -> Dict[str, Any]:
    """
    OpenEvolve calls this with the candidate program text.
    We temporarily write it into the target repo file, run tests (pytest + JS harness + Playwright),
    then restore the original file. Returns a metrics dict with 'combined_score'.
    """
    # Determine which file is being evolved
    target_path = (file_path or os.getenv("OE_TARGET_FILE") or "").strip()
    if not target_path:
        # Fallback: if no explicit path, try to do static-only scoring (low weight)
        print("[eval] WARNING: No file_path/OE_TARGET_FILE provided; running static analyzers only.", flush=True)
        py_m = evaluate_python_code(program_code)
        js_m = evaluate_javascript_code(program_code)
        # Favor syntax_valid signals
        combined = 0.25 * (1.0 if py_m.get("syntax_valid") else 0.0) + 0.25 * (1.0 if js_m.get("syntax_valid") else 0.0)
        return {
            "length_score": max(py_m.get("length_score", 0.0), js_m.get("length_score", 0.0)),
            "combined_score": combined,
            "py_syntax": py_m.get("syntax_valid", False),
            "js_syntax": js_m.get("syntax_valid", False),
        }

    tfile = Path(target_path)
    if not tfile.is_absolute():
        tfile = TARGET_ROOT / tfile

    tfile.parent.mkdir(parents=True, exist_ok=True)

    # Backup current file (if exists), write candidate, run tests, restore
    original_text = None
    existed = tfile.exists()
    if existed:
        try:
            original_text = tfile.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            original_text = None

    try:
        tfile.write_text(program_code, encoding="utf-8")

        # Run test suites
        py_rc = _run_pytests()
        ui_rc = _run_js_harness()
        pw_rc = _run_playwright()

        # Compute combined_score: all pass => 1.0; partial credit otherwise
        parts = [py_rc == 0, ui_rc == 0, pw_rc == 0]
        combined = sum(1.0 for p in parts if p) / 3.0

        # Provide additional metrics for logging/selection
        length_score = min(len(program_code) / 2000.0, 1.0)

        metrics = {
            "py_pass": py_rc == 0,
            "ui_pass": ui_rc == 0,
            "pw_pass": pw_rc == 0,
            "combined_score": combined,
            "length_score": length_score,
        }
        print(f"[eval] METRICS {metrics}", flush=True)
        return metrics

    finally:
        # Restore prior contents
        try:
            if existed and original_text is not None:
                tfile.write_text(original_text, encoding="utf-8")
            elif not existed:
                # Remove file we created
                try:
                    tfile.unlink(missing_ok=True)
                except TypeError:
                    # Python <3.8 compat
                    if tfile.exists():
                        os.remove(str(tfile))
        except Exception as e:
            print(f"[eval] WARNING: could not restore {tfile}: {e}", flush=True)

# ===========================
# Optional CLI entry (unused)
# ===========================
def main() -> int:
    # Allow running the three suites when invoked directly (not used by OpenEvolve).
    py_rc = _run_pytests()
    ui_rc = _run_js_harness()
    pw_rc = _run_playwright()
    overall = 0 if (py_rc == 0 and ui_rc == 0 and pw_rc == 0) else 1
    print(f"[eval] DONE  py={py_rc} ui={ui_rc} pw={pw_rc} -> exit {overall}", flush=True)
    return overall

if __name__ == "__main__":
    sys.exit(main())
