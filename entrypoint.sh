#!/usr/bin/env bash
set -Eeuo pipefail

log(){ printf '%s\n' "$*" >&2; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# 1) Ensure both /workspace and /workspace/target are importable
export PYTHONPATH="/workspace/target:/workspace:${PYTHONPATH:-}"

# 2) Also persist the paths into the venv so subprocesses inherit them
echo "/workspace"        >  "${VIRTUAL_ENV:-/workspace/.venv}/lib/python3.13/site-packages/_workspace.pth" 2>/dev/null || true
echo "/workspace/target" >> "${VIRTUAL_ENV:-/workspace/.venv}/lib/python3.13/site-packages/_workspace.pth" 2>/dev/null || true

# 3) Apply improved patch sanitizer and test fixes
python - <<'PY'
import importlib, os, re, sys, subprocess
from pathlib import Path

TARGET = (os.environ.get("OE_TARGET_FILE") or "api.py").strip() or "api.py"
ALLOWED = set(x for x in (os.environ.get("OE_ALLOWED_FILES") or f"{TARGET},data_layer.py").replace(" ","").split(",") if x)

def _clean_unicode(s: str) -> str:
    """Remove problematic unicode characters"""
    if not s:
        return s
    # Remove zero-width chars, BOM, replace unicode spaces/minus
    s = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", s)
    s = re.sub(r"[\u00a0\u202f]", " ", s)
    s = re.sub(r"[\u2212]", "-", s)
    return s

def _retarget_file(path: str) -> str:
    """Map file paths to allowed files"""
    path = path.strip()
    if path.startswith(("a/","b/")):
        path = path[2:]
    # Common model hallucinations
    if path in ("app.py", "main.py", "server.py"):
        path = TARGET
    if path not in ALLOWED:
        path = TARGET
    return path

def _validate_python_syntax(file_path: str) -> tuple[bool, str]:
    """Check if a Python file has valid syntax"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Try to compile the source
        compile(source, file_path, 'exec')
        return True, ""
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"Error reading/compiling {file_path}: {e}"

def _fix_common_syntax_issues(file_path: str) -> bool:
    """Apply common fixes to Python syntax issues"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Fix common issues
        # 1. Remove duplicate imports
        import_lines = []
        other_lines = []
        seen_imports = set()
        
        for line in content.splitlines():
            if line.strip().startswith(('import ', 'from ')):
                if line.strip() not in seen_imports:
                    seen_imports.add(line.strip())
                    import_lines.append(line)
            else:
                other_lines.append(line)
        
        # 2. Fix common indentation issues
        fixed_lines = []
        for line in import_lines + other_lines:
            # Fix mixed tabs/spaces (convert tabs to 4 spaces)
            line = line.expandtabs(4)
            fixed_lines.append(line)
        
        content = '\n'.join(fixed_lines)
        
        # 3. Ensure file ends with newline
        if content and not content.endswith('\n'):
            content += '\n'
        
        # Only write if we made changes
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"[entrypoint] Fixed syntax issues in {file_path}")
            return True
        
        return False
    except Exception as e:
        print(f"[entrypoint] Error fixing syntax in {file_path}: {e}")
        return False

def _sanitize_patch(text: str) -> str:
    """Clean and validate a patch to ensure it applies correctly"""
    if not isinstance(text, str) or not text.strip():
        return ""
    
    text = _clean_unicode(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    
    # Extract from fenced blocks
    fence_match = re.search(r"```(?:diff|patch)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1)
    
    lines = [line.rstrip() for line in text.splitlines()]
    
    # Remove git headers that confuse patch
    git_header_patterns = [
        r"^diff --git ",
        r"^index [0-9a-f]+\.\.[0-9a-f]+",
        r"^(?:new|deleted) file mode ",
        r"^similarity index ",
        r"^rename (?:from|to) "
    ]
    
    filtered_lines = []
    for line in lines:
        if any(re.match(pattern, line) for pattern in git_header_patterns):
            continue
        filtered_lines.append(line)
    
    lines = filtered_lines
    
    # Fix headers and retarget files
    fixed_lines = []
    for line in lines:
        if line.startswith("--- "):
            path = _retarget_file(line[4:])
            fixed_lines.append(f"--- a/{path}")
        elif line.startswith("+++ "):
            path = _retarget_file(line[4:])
            fixed_lines.append(f"+++ b/{path}")
        elif line.startswith("@@") and not re.match(r"^@@\s*-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s*@@", line):
            # Fix malformed hunk headers
            numbers = re.findall(r'-(\d+(?:,\d+)?)\s+\+(\d+(?:,\d+)?)', line)
            if numbers:
                fixed_lines.append(f"@@ -{numbers[0][0]} +{numbers[0][1]} @@")
            else:
                # Skip malformed hunk
                continue
        else:
            fixed_lines.append(line)
    
    lines = fixed_lines
    
    # Ensure we have proper headers
    has_old = any(line.startswith("--- a/") for line in lines)
    has_new = any(line.startswith("+++ b/") for line in lines)
    has_hunks = any(line.startswith("@@") for line in lines)
    has_changes = any(line.startswith(("+", "-")) for line in lines)
    
    if not (has_hunks and has_changes):
        return ""  # No valid diff content
    
    if not (has_old and has_new):
        # Add missing headers
        header_lines = []
        if not has_old:
            header_lines.append(f"--- a/{TARGET}")
        if not has_new:
            header_lines.append(f"+++ b/{TARGET}")
        
        # Insert at the beginning or before first hunk
        insert_pos = 0
        for i, line in enumerate(lines):
            if line.startswith("@@"):
                insert_pos = i
                break
        
        lines = lines[:insert_pos] + header_lines + lines[insert_pos:]
    
    # Ensure hunk lines are properly formatted
    in_hunk = False
    validated_lines = []
    
    for line in lines:
        if line.startswith(("--- a/", "+++ b/")):
            in_hunk = False
            validated_lines.append(line)
        elif line.startswith("@@"):
            in_hunk = True
            validated_lines.append(line)
        elif in_hunk:
            if line.startswith(("+", "-", " ")):
                validated_lines.append(line)
            elif not line.strip():
                validated_lines.append(" ")  # Empty line becomes context
            else:
                validated_lines.append(" " + line)  # Non-prefixed becomes context
        else:
            # Outside hunk, only keep headers/hunks
            if line.startswith(("--- ", "+++ ", "@@")):
                validated_lines.append(line)
    
    result = "\n".join(validated_lines).strip()
    if not result:
        return ""
    
    if not result.endswith("\n"):
        result += "\n"
    
    # Final validation
    final_lines = result.splitlines()
    if not any(line.startswith("@@") for line in final_lines):
        return ""
    if not any(line.startswith(("+", "-")) for line in final_lines):
        return ""
    
    return result

# Check and fix syntax issues in target file
target_file = Path(os.environ.get("OE_REPO_DIR", "/workspace/target")) / TARGET
if target_file.exists():
    valid, error = _validate_python_syntax(str(target_file))
    if not valid:
        print(f"[entrypoint] Syntax error in {target_file}: {error}")
        if _fix_common_syntax_issues(str(target_file)):
            # Check again after fixes
            valid, error = _validate_python_syntax(str(target_file))
            if valid:
                print(f"[entrypoint] Successfully fixed syntax issues in {target_file}")
            else:
                print(f"[entrypoint] Could not fix syntax issues in {target_file}: {error}")
        else:
            print(f"[entrypoint] No automatic fixes available for {target_file}")
    else:
        print(f"[entrypoint] {target_file} has valid Python syntax")

try:
    ps = importlib.import_module("openevolve.utils.patch_sanitizer")
    original_extract = getattr(ps, "extract_raw_patch", None)
    
    def patched_extract_raw_patch(text: str) -> str:
        result = _sanitize_patch(text)
        if result:
            print(f"[entrypoint] Sanitized patch ({len(result)} chars)", file=sys.stderr)
            preview = "\n".join(result.splitlines()[:8])
            print(f"[entrypoint] Preview:\n{preview}", file=sys.stderr)
        else:
            print("[entrypoint] Failed to sanitize patch", file=sys.stderr)
        return result
    
    ps.extract_raw_patch = patched_extract_raw_patch
    print("[entrypoint] Applied improved patch sanitizer", file=sys.stderr)
    
except Exception as e:
    print(f"[entrypoint] WARNING: Failed to patch sanitizer: {e}", file=sys.stderr)

# Create a test helper module to improve import reliability
test_helper_content = '''
"""
Test helper module to improve import reliability and provide common test utilities.
"""
import sys
import os
from pathlib import Path

# Ensure target directory is in path
target_dir = Path("/workspace/target")
if str(target_dir) not in sys.path:
    sys.path.insert(0, str(target_dir))

def safe_import_api():
    """Safely import the api module with better error handling"""
    try:
        # First try direct import
        import api
        return api
    except ImportError as e:
        print(f"Import error: {e}")
        # Try adding current directory to path
        current_dir = Path.cwd()
        if str(current_dir) not in sys.path:
            sys.path.insert(0, str(current_dir))
        try:
            import api
            return api
        except ImportError:
            # Try importing from target directory explicitly
            target_api = target_dir / "api.py"
            if target_api.exists():
                import importlib.util
                spec = importlib.util.spec_from_file_location("api", target_api)
                if spec and spec.loader:
                    api = importlib.util.module_from_spec(spec)
                    sys.modules["api"] = api
                    spec.loader.exec_module(api)
                    return api
            raise
    except SyntaxError as e:
        print(f"Syntax error in api.py: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error importing api: {e}")
        raise

def validate_api_module():
    """Validate that the api module can be imported and has expected attributes"""
    try:
        api = safe_import_api()
        
        # Check for common Flask app attributes
        required_attrs = ['app']
        missing_attrs = [attr for attr in required_attrs if not hasattr(api, attr)]
        
        if missing_attrs:
            print(f"Warning: api module missing attributes: {missing_attrs}")
            return False, f"Missing attributes: {missing_attrs}"
        
        return True, "API module validation passed"
    except Exception as e:
        return False, f"API module validation failed: {e}"

# Auto-validate when imported
if __name__ != "__main__":
    try:
        is_valid, message = validate_api_module()
        if not is_valid:
            print(f"[test_helper] {message}")
    except Exception as e:
        print(f"[test_helper] Validation error: {e}")
'''

# Write the test helper
try:
    helper_path = Path("/workspace/target/test_helper.py")
    helper_path.write_text(test_helper_content, encoding="utf-8")
    print(f"[entrypoint] Created test helper at {helper_path}")
except Exception as e:
    print(f"[entrypoint] WARNING: Could not create test helper: {e}")

PY

# Make repo + target importable for pytest/subprocesses
export PYTHONPATH="/workspace/target:/workspace:${PYTHONPATH:-}"

# -----------------------------------------------------------------------------
# 2) Defaults (overridable via compose env and repo-level .env)
#    - Set local defaults first (without export)
#    - Then source repo .env if present (can override)
#    - Finally export sanitized values
# -----------------------------------------------------------------------------
OE_REPO_DIR="${OE_REPO_DIR:-/workspace/target}"     # evolving repo
OE_TARGET_FILE="${OE_TARGET_FILE:-api.py}"          # entry file in repo
OE_ITERATIONS="${OE_ITERATIONS:-20}"
OE_RUN_MODE="${OE_RUN_MODE:-evolve}"                # evolve | pytest | idle
OPENAI_API_BASE="${OPENAI_API_BASE:-http://host.docker.internal:8000/v1}"
OPENAI_API_KEY="${OPENAI_API_KEY:-ollama}"          # local OpenAI-compatible servers ignore it

# Also load a .env inside the target repo if present (can override the above)
if [[ -f "${OE_REPO_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "${OE_REPO_DIR}/.env"
  set +a
fi

# Strip any stray CRs (Windows line endings) from critical vars
OE_RUN_MODE="${OE_RUN_MODE//$'\r'/}"
OPENAI_API_BASE="${OPENAI_API_BASE//$'\r'/}"

# Export final values
export OE_REPO_DIR OE_TARGET_FILE OE_ITERATIONS OE_RUN_MODE OPENAI_API_BASE OPENAI_API_KEY

# Normalize & validate OE_RUN_MODE (trim trailing tokens/whitespace)
OE_RUN_MODE="${OE_RUN_MODE%%[[:space:]]*}"
case "$OE_RUN_MODE" in evolve|pytest|idle) ;; 
  *) log "[entrypoint] Invalid OE_RUN_MODE='${OE_RUN_MODE}' → using 'evolve'"; OE_RUN_MODE="evolve";;
esac
export OE_RUN_MODE

# Prefer venv tools; also ensure user-local bin is visible
export PATH="/workspace/.venv/bin:${HOME}/.local/bin:${PATH}"

log "[entrypoint] OE_REPO_DIR=${OE_REPO_DIR}"
log "[entrypoint] OE_TARGET_FILE=${OE_TARGET_FILE}"
log "[entrypoint] OE_RUN_MODE=${OE_RUN_MODE}"
log "[entrypoint] OPENAI_API_BASE=${OPENAI_API_BASE}"
log "[entrypoint] OPENAI_API_KEY=$([[ -n "${OPENAI_API_KEY:-}" ]] && echo "<set>" || echo "<unset>")"

# Optional non-fatal probe of model server (helps catch wrong port)
if command -v curl >/dev/null 2>&1; then
  if ! curl -sS --max-time 2 "${OPENAI_API_BASE%/}/models" >/dev/null; then
    log "[entrypoint] WARNING: Can't reach ${OPENAI_API_BASE%/} (is the model server up / port correct?)"
  fi
fi

# Sanity
[[ -d "$OE_REPO_DIR" ]] || die "OE_REPO_DIR not found: $OE_REPO_DIR"
[[ -f "${OE_REPO_DIR}/${OE_TARGET_FILE}" ]] || die "OE_TARGET_FILE not found: ${OE_REPO_DIR}/${OE_TARGET_FILE}"

# -----------------------------------------------------------------------------
# Python environment setup (create & activate venv)
# -----------------------------------------------------------------------------
if [[ ! -d "/workspace/.venv" ]]; then
  log "[entrypoint] Creating virtualenv at /workspace/.venv"
  python3 -m venv /workspace/.venv
fi

log "[entrypoint] Activating virtualenv at /workspace/.venv"
# shellcheck disable=SC1091
source /workspace/.venv/bin/activate

# Persist import paths for all Python children via .pth markers
python - <<'PY'
import sysconfig, pathlib
pure = sysconfig.get_paths().get("purelib")
if pure:
    pure = pathlib.Path(pure)
    for name, path in [("workspace_root.pth","/workspace"),
                       ("workspace_target.pth","/workspace/target")]:
        p = pure / name
        try:
            if not p.exists() or p.read_text(encoding="utf-8").strip() != path:
                p.write_text(path + "\n", encoding="utf-8")
                print(f"[entrypoint] wrote {p}")
        except Exception as e:
            print(f"[entrypoint] WARNING: could not write {p}: {e}")
PY

rm -rf build/ *.egg-info *.dist-info
python -m pip install -U pip setuptools wheel

# -----------------------------------------------------------------------------
# 4) Install requirements
# -----------------------------------------------------------------------------
OE_SRC="/workspace/openevolve"

# openevolve dev requirements (if present)
if [[ -f "${OE_SRC}/requirements.txt" ]]; then
  log "[entrypoint] Installing openevolve requirements.txt…"
  python -m pip install --no-cache-dir -r "${OE_SRC}/requirements.txt"
fi

# target repo requirements (so tests & imports work)
if [[ -f "${OE_REPO_DIR}/requirements.txt" ]]; then
  log "[entrypoint] Installing target requirements.txt from ${OE_REPO_DIR}…"
  python -m pip install --no-cache-dir -r "${OE_REPO_DIR}/requirements.txt"
else
  # lightweight safety net
  python - <<'PY'
import subprocess, sys
def need(m):
    try: __import__(m); return False
    except Exception: return True
pk=[]
if need("flask_socketio"): pk.append("flask-socketio")
try:
    import flask_cors  # noqa
except Exception:
    pk.append("Flask-Cors")
if pk:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", *pk])
PY
fi

# Install *our* openevolve (non-editable) so our utils/diff code is used
log "[entrypoint] Installing openevolve (non-editable)…"
python -m pip install --no-cache-dir "${OE_SRC}"

# -----------------------------------------------------------------------------
# 5) Seed/patch prompt templates inside installed package (needed for evolution_history)
# -----------------------------------------------------------------------------
python - <<'PY'
import importlib, shutil
from pathlib import Path

try:
    op = importlib.import_module("openevolve")
except Exception as e:
    print(f"[entrypoint] ERROR importing openevolve: {e}")
    raise SystemExit(1)

pkg_dir = Path(op.__file__).parent
want = pkg_dir / "prompt" / "templates"
src  = Path("/workspace/openevolve/openevolve/prompt/templates")

if not want.exists():
    if src.exists():
        want.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, want)
        print(f"[entrypoint] Seeded templates into {want}")
else:
    if not any(p.name.startswith("evolution_history") for p in want.glob("*")) and src.exists():
        evo_src = next((p for p in src.glob("evolution_history*")), None)
        if evo_src:
            shutil.copy2(evo_src, want / "evolution_history.jinja")
            print("[entrypoint] Seeded missing evolution_history.jinja")
PY

# -----------------------------------------------------------------------------
# 6) Compatibility shim for TemplateManager kwargs/signature drift
# -----------------------------------------------------------------------------
python - <<'PY'
import inspect
try:
    from openevolve.prompt import templates as T
except Exception as e:
    print(f"[entrypoint] WARNING: cannot import templates to shim: {e}")
else:
    # __init__: accept custom_template_dir and map to template_dir if needed
    try:
        sig = inspect.signature(T.TemplateManager.__init__)
        if "custom_template_dir" not in sig.parameters:
            orig = T.TemplateManager.__init__
            def _shim_init(self, *a, **kw):
                if "custom_template_dir" in kw and "template_dir" not in kw:
                    kw["template_dir"] = kw.pop("custom_template_dir")
                return orig(self, *a, **kw)
            T.TemplateManager.__init__ = _shim_init  # type: ignore
            print("[entrypoint] Shimmed TemplateManager.__init__ to accept custom_template_dir")
    except Exception as e:
        print(f"[entrypoint] Shim __init__ failed: {e}")

    # get_fragment: accept current=… and map to current_value if needed
    try:
        sig2 = inspect.signature(T.TemplateManager.get_fragment)
        if "current" not in sig2.parameters and "current_value" in sig2.parameters:
            orig_gf = T.TemplateManager.get_fragment
            def _shim_gf(self, name, **kw):
                if "current" in kw and "current_value" not in kw:
                    kw["current_value"] = kw.pop("current")
                return orig_gf(self, name, **kw)
            T.TemplateManager.get_fragment = _shim_gf  # type: ignore
            print("[entrypoint] Shimmed TemplateManager.get_fragment to accept current=")
    except Exception as e:
        print(f"[entrypoint] Shim get_fragment failed: {e}")
PY

# -----------------------------------------------------------------------------
# 7) Test environment validation and fixes
# -----------------------------------------------------------------------------
log "[entrypoint] Validating test environment…"

# Test that we can import the target module
python - <<'PY'
import sys
from pathlib import Path

# Add target directory to Python path
target_dir = Path("/workspace/target")
if str(target_dir) not in sys.path:
    sys.path.insert(0, str(target_dir))

try:
    import api
    print("[entrypoint] Successfully imported api module")
    
    # Check if it has expected Flask app
    if hasattr(api, 'app'):
        print("[entrypoint] Found Flask app in api module")
    else:
        print("[entrypoint] WARNING: No 'app' attribute found in api module")
        
except ImportError as e:
    print(f"[entrypoint] ERROR: Cannot import api module: {e}")
    
except SyntaxError as e:
    print(f"[entrypoint] ERROR: Syntax error in api module: {e}")
    
except Exception as e:
    print(f"[entrypoint] ERROR: Unexpected error importing api: {e}")

# Check if tests directory exists and is properly structured
test_dir = target_dir / "tests"
if test_dir.exists():
    print(f"[entrypoint] Found tests directory: {test_dir}")
    
    # Look for test files
    test_files = list(test_dir.rglob("test_*.py"))
    print(f"[entrypoint] Found {len(test_files)} test files")
    
    # Check if tests can access the api module
    for test_file in test_files[:3]:  # Check first few test files
        try:
            with open(test_file, 'r') as f:
                content = f.read()
                if 'import api' in content or 'importlib.import_module("api")' in content:
                    print(f"[entrypoint] {test_file.name} imports api module")
        except Exception as e:
            print(f"[entrypoint] Could not read {test_file}: {e}")
else:
    print(f"[entrypoint] WARNING: No tests directory found at {test_dir}")
PY

# -----------------------------------------------------------------------------
# 8) If a command was provided, run it directly
# -----------------------------------------------------------------------------
if [[ "$#" -gt 0 ]]; then
  exec "$@"
fi

# -----------------------------------------------------------------------------
# 9) Run mode
# -----------------------------------------------------------------------------
if [[ "${OE_RUN_MODE}" == "evolve" ]]; then
  : "${OE_INITIAL:=${OE_REPO_DIR}/${OE_TARGET_FILE}}"

  if [[ -z "${OE_EVAL:-}" ]]; then
    if [[ -f "${OE_REPO_DIR}/evaluation.py" ]]; then
      OE_EVAL="${OE_REPO_DIR}/evaluation.py"
    else
      OE_EVAL="/workspace/openevolve/evaluation.py"
    fi
  fi

  log "[entrypoint] Running EVOLUTION with:"
  log "  OE_INITIAL=${OE_INITIAL}"
  log "  OE_EVAL=${OE_EVAL}"
  log "  OE_ITERATIONS=${OE_ITERATIONS}"

  exec openevolve-run "${OE_INITIAL}" "${OE_EVAL}" \
    ${OE_ITERATIONS:+--iterations "$OE_ITERATIONS"} \
    ${OE_TARGET_SCORE:+--target-score "$OE_TARGET_SCORE"} \
    ${OE_LOG_LEVEL:+--log-level "$OE_LOG_LEVEL"} \
    ${OPENAI_API_BASE:+--api-base "$OPENAI_API_BASE"} \
    ${OE_PRIMARY_MODEL:+--primary-model "$OE_PRIMARY_MODEL"} \
    ${OE_SECONDARY_MODEL:+--secondary-model "$OE_SECONDARY_MODEL"}
fi

if [[ "${OE_RUN_MODE}" == "pytest" ]]; then
  TEST_PATH="${OE_REPO_DIR}/tests"
  [[ -d "$TEST_PATH" ]] || die "pytest mode requested but ${TEST_PATH} not found."
  log "[entrypoint] Running PYTEST at ${TEST_PATH}…"
  exec pytest -v "$TEST_PATH"  # Use -v for more verbose output to debug issues
fi

log "[entrypoint] No run requested (OE_RUN_MODE=${OE_RUN_MODE}); idling."
exec tail -f /dev/null