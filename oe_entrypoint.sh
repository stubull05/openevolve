#!/usr/bin/env sh
set -eu

log() { printf '%s\n' "$*" >&2; }

# Make sure user-local bin is on PATH (pip installs here as non-root)
export PATH="${HOME}/.local/bin:${PATH}"

# Prefer the cloned source over any installed package
export PYTHONPATH="/workspace/openevolve:${PYTHONPATH:-}"

log "[entrypoint] OPENAI_API_BASE=${OPENAI_API_BASE:-<unset>}"

# -----------------------------
# Install third-party deps once
# -----------------------------
PYPROJ="/workspace/openevolve/pyproject.toml"
STAMP="/var/tmp/openevolve.deps.sha"

if [ -f "$PYPROJ" ]; then
  CURR_HASH="$(
    python - <<'PY'
import hashlib, sys
try:
    import tomllib
except Exception:
    tomllib = None

p = "/workspace/openevolve/pyproject.toml"
if tomllib is None:
    print("no-tomllib")
else:
    data = tomllib.load(open(p, 'rb'))
    deps = data.get('project', {}).get('dependencies', []) or []
    h = hashlib.sha256()
    for d in sorted(deps):
        h.update(d.encode())
    print(h.hexdigest())
PY
  )"

  if [ "$CURR_HASH" = "no-tomllib" ]; then
    log "[entrypoint] Bootstrapping pip/setuptools/wheel to read pyproject…"
    python -m pip install --upgrade pip setuptools wheel
    CURR_HASH="$(
      python - <<'PY'
import hashlib, tomllib
p = "/workspace/openevolve/pyproject.toml"
data = tomllib.load(open(p, 'rb'))
deps = data.get('project', {}).get('dependencies', []) or []
h = hashlib.sha256()
for d in sorted(deps):
    h.update(d.encode())
print(h.hexdigest())
PY
    )"
  fi

  PREV_HASH="$(cat "$STAMP" 2>/dev/null || echo "")"

  if [ "$CURR_HASH" != "$PREV_HASH" ]; then
    log "[entrypoint] Installing third-party dependencies from pyproject…"
    python -m pip install --upgrade pip
    python - <<'PY'
import tomllib, subprocess, sys
deps = tomllib.load(open("/workspace/openevolve/pyproject.toml",'rb')).get('project',{}).get('dependencies',[]) or []
if deps:
    subprocess.check_call([sys.executable,"-m","pip","install","--no-cache-dir", *deps])
else:
    print("[entrypoint] No dependencies listed.")
PY
    echo "$CURR_HASH" > "$STAMP"
    log "[entrypoint] Dependencies ready."
  else
    log "[entrypoint] Dependencies unchanged; skipping install."
  fi
else
  log "[entrypoint] No pyproject.toml; skipping dependency install."
fi

# ---------------------------------------------
# Ensure the missing template exists in BOTH:
#  - the repo source tree, and
#  - the directory of the actually imported package
# ---------------------------------------------
python - <<'PY'
from pathlib import Path
import sys

def ensure_template(dirpath: Path):
    dirpath.mkdir(parents=True, exist_ok=True)
    candidates = [
        dirpath / "evolution_history",
        dirpath / "evolution_history.txt",
        dirpath / "evolution_history.md",
        dirpath / "evolution_history.j2",
    ]
    if not any(p.exists() for p in candidates):
        # Minimal but valid template with fields sampler expects
        (dirpath / "evolution_history").write_text(
            "You are evolving code in {language}.\n"
            "Feature dimensions: {feature_dimensions}\n\n"
            "=== Previous Programs ===\n{previous_programs}\n\n"
            "=== Top Programs ===\n{top_programs}\n\n"
            "=== Inspirations ===\n{inspirations}\n",
            encoding="utf-8",
        )
        print(f"[entrypoint] created default template at {dirpath}/evolution_history")

# 1) source tree path
src_tpl = Path("/workspace/openeolve/openevolve/prompt/templates")
# typo-guard: if above is wrong, correct path below
if not src_tpl.parent.exists():
    src_tpl = Path("/workspace/openevolve/openevolve/prompt/templates")
ensure_template(src_tpl)

# 2) imported package path
try:
    import openevolve  # type: ignore
    pkg_dir = Path(openevolve.__file__).resolve().parent
    print(f"[entrypoint] using openevolve from: {openevolve.__file__}")
    ensure_template(pkg_dir / "prompt" / "templates")
except Exception as e:
    print(f"[entrypoint] warning: cannot import openevolve yet: {e}", file=sys.stderr)
PY

# ---------------------------------------------
# If a command is provided, run it.
# ---------------------------------------------
if [ "$#" -gt 0 ]; then
  exec "$@"
fi

# ---------------------------------------------
# Default: run the CLI from source
# (set OE_* to pass flags; otherwise just run)
# ---------------------------------------------
MAIN_ARGS=""
[ -n "${OE_INITIAL:-}"       ] && MAIN_ARGS="$MAIN_ARGS ${OE_INITIAL}"
[ -n "${OE_EVAL:-}"          ] && MAIN_ARGS="$MAIN_ARGS ${OE_EVAL}"
[ -n "${OE_ITERATIONS:-}"    ] && MAIN_ARGS="$MAIN_ARGS --iterations ${OE_ITERATIONS}"
[ -n "${OE_TARGET_SCORE:-}"  ] && MAIN_ARGS="$MAIN_ARGS --target-score ${OE_TARGET_SCORE}"
[ -n "${OE_LOG_LEVEL:-}"     ] && MAIN_ARGS="$MAIN_ARGS --log-level ${OE_LOG_LEVEL}"
[ -n "${OE_API_BASE:-}"      ] && MAIN_ARGS="$MAIN_ARGS --api-base ${OE_API_BASE}"
[ -n "${OE_PRIMARY_MODEL:-}" ] && MAIN_ARGS="$MAIN_ARGS --primary-model ${OE_PRIMARY_MODEL}"
[ -n "${OE_SECONDARY_MODEL:-}" ] && MAIN_ARGS="$MAIN_ARGS --secondary-model ${OE_SECONDARY_MODEL}"

log "[entrypoint] Launching: python -m openevolve.cli $MAIN_ARGS"
exec python -m openevolve.cli $MAIN_ARGS
