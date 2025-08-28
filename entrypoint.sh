#!/usr/bin/env bash
set -Eeuo pipefail

log(){ printf '%s\n' "$*" >&2; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# 1) Ensure both /workspace and /workspace/target are importable
export PYTHONPATH="/workspace/target:/workspace:${PYTHONPATH:-}"

# 2) Also persist the paths into the venv so subprocesses inherit them
echo "/workspace"        >  "${VIRTUAL_ENV:-/workspace/.venv}/lib/python3.13/site-packages/_workspace.pth" 2>/dev/null || true
echo "/workspace/target" >> "${VIRTUAL_ENV:-/workspace/.venv}/lib/python3.13/site-packages/_workspace.pth" 2>/dev/null || true


python - <<'PY'
import importlib, os, re, sys

TARGET = (os.environ.get("OE_TARGET_FILE") or "api.py").strip() or "api.py"
ALLOWED = set(x for x in (os.environ.get("OE_ALLOWED_FILES") or f"{TARGET},data_layer.py").replace(" ","").split(",") if x)

ZW = "[\u200b\u200c\u200d\u2060\ufeff]"      # zero-width + BOM
NBSP = "[\u00a0\u202f]"                       # nbsp / narrow nbsp
UMINUS = "[\u2212]"                            # unicode minus

def _clean(s: str) -> str:
    s = re.sub(ZW, "", s)
    s = re.sub(NBSP, " ", s)
    s = re.sub(UMINUS, "-", s)
    return s

HDR_OLD = re.compile(r"^---\s+(.*)$")
HDR_NEW = re.compile(r"^\+\+\+\s+(.*)$")
HUNK_OK = re.compile(r"^@@\s*-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s*@@(?:\s.*)?$")
HUNK_FIX = re.compile(r"^(@@)\s*-(\d+(?:,\d+)?)\s+\+(\d+(?:,\d+)?)\s+@.*$")  # '@...' → '@@'

def _retarget(path: str) -> str:
    if path.startswith(("a/","b/")): path = path[2:]
    if path == "app.py": path = TARGET
    if path not in ALLOWED: path = TARGET
    return path

def _sanitize(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        return ""
    text = _clean(text)

    # strip code fences
    m = re.search(r"```(?:diff|patch)?(.*?)```", text, flags=re.S|re.I)
    if m:
        text = m.group(1)

    lines = [ln.rstrip("\r") for ln in text.strip().splitlines()]

    # drop git headers
    lines = [ln for ln in lines if not (ln.startswith("diff --git") or ln.startswith("index "))]

    # rewrite headers + repair hunk tails
    had_old = any(ln.startswith("--- ") for ln in lines)
    had_new = any(ln.startswith("+++ ") for ln in lines)
    fixed = []
    for ln in lines:
        mo = HDR_OLD.match(ln)
        if mo:
            fixed.append(f"--- a/{_retarget(mo.group(1).strip())}")
            continue
        mn = HDR_NEW.match(ln)
        if mn:
            fixed.append(f"+++ b/{_retarget(mn.group(1).strip())}")
            continue
        mf = HUNK_FIX.match(ln)
        if mf:
            fixed.append(f"@@ -{mf.group(2)} +{mf.group(3)} @@")
            continue
        fixed.append(ln)
    lines = fixed

    # keep only diff-relevant lines
    kept = []
    for ln in lines:
        if ln.startswith(("--- a/","+++ b/")) or HUNK_OK.match(ln) or ln[:1] in {"+","-"," "}:
            kept.append(ln)
    lines = kept

    # inject headers if missing but hunks exist
    if not (any(l.startswith("--- a/") for l in lines) and any(l.startswith("+++ b/") for l in lines)):
        if any(l.startswith("@@ ") or HUNK_OK.match(l) for l in lines):
            lines = [f"--- a/{TARGET}", f"+++ b/{TARGET}"] + lines

    out = "\n".join(lines).strip()
    if "@@" not in out or not any(l.startswith(("+","-")) for l in lines):
        return ""  # no actual changes
    if not out.endswith("\n"):
        out += "\n"
    # short preview
    print("[entrypoint] sanitized patch preview:\n" + "\n".join(out.splitlines()[:8]), file=sys.stderr)
    return out

try:
    ps = importlib.import_module("openevolve.utils.patch_sanitizer")
    orig = getattr(ps, "extract_raw_patch", None)
    def extract_raw_patch(text: str) -> str:
        cleaned = _sanitize(text)
        return cleaned if cleaned else (orig(text) if callable(orig) else "")
    ps.extract_raw_patch = extract_raw_patch
    print("[entrypoint] Patched patch_sanitizer.extract_raw_patch", file=sys.stderr)
except Exception as e:
    print(f"[entrypoint] WARNING: sanitizer patch failed: {e}", file=sys.stderr)
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
# 7) If a command was provided, run it directly
# -----------------------------------------------------------------------------
if [[ "$#" -gt 0 ]]; then
  exec "$@"
fi

# -----------------------------------------------------------------------------
# 8) Run mode
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
  exec pytest -q "$TEST_PATH"
fi

log "[entrypoint] No run requested (OE_RUN_MODE=${OE_RUN_MODE}); idling."
exec tail -f /dev/null

python - <<'PY'
import importlib, os, re

TARGET = (os.environ.get("OE_TARGET_FILE") or "api.py").strip() or "api.py"
ALLOWED = set(
    x for x in (os.environ.get("OE_ALLOWED_FILES") or f"{TARGET},data_layer.py")
    .replace(" ", "")
    .split(",") if x
)

def _sanitize(text: str) -> str:
    if not isinstance(text, str):
        return ""
    # strip code fences
    m = re.search(r"```(?:diff|patch)?(.*?)```", text, flags=re.S|re.I)
    if m:
        text = m.group(1)
    lines = [ln.rstrip("\r") for ln in text.strip().splitlines()]

    # drop git headers that confuse patch apply
    lines = [ln for ln in lines if not (ln.startswith("diff --git") or ln.startswith("index "))]

    def _retarget(p: str) -> str:
        if p.startswith(("a/","b/")): p = p[2:]
        if p == "app.py": p = TARGET
        if p not in ALLOWED: p = TARGET
        return p

    # rewrite headers if present
    has_old = any(ln.startswith("--- ") for ln in lines)
    has_new = any(ln.startswith("+++ ") for ln in lines)
    new = []
    for ln in lines:
        if ln.startswith("--- "):
            new.append(f"--- a/{_retarget(ln[4:].strip())}")
        elif ln.startswith("+++ "):
            new.append(f"+++ b/{_retarget(ln[4:].strip())}")
        else:
            new.append(ln)
    lines = new

    # inject headers if missing but hunks exist
    if not (has_old and has_new) and any(ln.startswith("@@") for ln in lines):
        lines = [f"--- a/{TARGET}", f"+++ b/{TARGET}"] + lines

    out = "\n".join(lines).strip()
    if "@@" not in out:
        return ""
    if not out.endswith("\n"):
        out += "\n"
    return out

try:
    ps = importlib.import_module("openevolve.utils.patch_sanitizer")
    _orig = getattr(ps, "extract_raw_patch", None)

    def extract_raw_patch(text: str) -> str:
        cleaned = _sanitize(text)
        return cleaned if cleaned else (_orig(text) if callable(_orig) else "")

    ps.extract_raw_patch = extract_raw_patch  # hot-patch
    print("[entrypoint] Patched patch_sanitizer.extract_raw_patch to normalize diffs")
except Exception as e:
    print(f"[entrypoint] WARNING: could not patch sanitizer: {e}")
PY
