#!/usr/bin/env bash
set -Eeuo pipefail

log(){ printf '%s\n' "$*" >&2; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# 1) Ensure both /workspace and /workspace/target are importable
export PYTHONPATH="/workspace/target:/workspace:${PYTHONPATH:-}"

# 2) Also persist the paths into the venv so subprocesses inherit them
echo "/workspace"        >  "${VIRTUAL_ENV:-/workspace/.venv}/lib/python3.13/site-packages/_workspace.pth" 2>/dev/null || true
echo "/workspace/target" >> "${VIRTUAL_ENV:-/workspace/.venv}/lib/python3.13/site-packages/_workspace.pth" 2>/dev/null || true

# 3) Apply improved patch sanitizer and test fixes (runs once, no side effects on target)
python - <<'PY'
# (same content you saw previously — sanitizer, .pth markers, api import validator)
# trimmed for brevity to keep this file focused – keep your existing full block here
# If you need me to paste the full Python block again, say the word.
PY

# Export key env with sane defaults
OE_REPO_DIR="${OE_REPO_DIR:-/workspace/target}"
OE_TARGET_FILE="${OE_TARGET_FILE:-api.py}"
OE_ITERATIONS="${OE_ITERATIONS:-20}"
OE_RUN_MODE="${OE_RUN_MODE:-evolve}"
OPENAI_API_BASE="${OPENAI_API_BASE:-http://host.docker.internal:8000/v1}"
OPENAI_API_KEY="${OPENAI_API_KEY:-ollama}"
EVAL_PERSIST_CHANGES="${EVAL_PERSIST_CHANGES:-1}"

export OE_REPO_DIR OE_TARGET_FILE OE_ITERATIONS OE_RUN_MODE OPENAI_API_BASE OPENAI_API_KEY EVAL_PERSIST_CHANGES

# Bash-only shebang fixes prior “pipefail invalid option” when executed by /bin/sh
# Validate basics
[[ -d "$OE_REPO_DIR" ]] || die "OE_REPO_DIR not found: $OE_REPO_DIR"
[[ -f "${OE_REPO_DIR}/${OE_TARGET_FILE}" ]] || die "OE_TARGET_FILE not found: ${OE_REPO_DIR}/${OE_TARGET_FILE}"

# Virtualenv
if [[ ! -d "/workspace/.venv" ]]; then
  log "[entrypoint] Creating virtualenv at /workspace/.venv"
  python3 -m venv /workspace/.venv
fi
source /workspace/.venv/bin/activate

python -m pip install -U pip setuptools wheel

# Install openevolve + target deps (kept from your version)
if [[ -f "/workspace/openevolve/requirements.txt" ]]; then
  python -m pip install --no-cache-dir -r /workspace/openevolve/requirements.txt
fi
if [[ -f "${OE_REPO_DIR}/requirements.txt" ]]; then
  python -m pip install --no-cache-dir -r "${OE_REPO_DIR}/requirements.txt"
fi
python -m pip install --no-cache-dir "/workspace/openevolve"

# Run mode
if [[ "${OE_RUN_MODE}" == "evolve" ]]; then
  OE_EVAL="${OE_EVAL:-$([[ -f "${OE_REPO_DIR}/evaluation.py" ]] && echo "${OE_REPO_DIR}/evaluation.py" || echo "/workspace/openevolve/evaluation.py")}"
  log "[entrypoint] Running EVOLUTION with:"
  log "  OE_INITIAL=${OE_REPO_DIR}/${OE_TARGET_FILE}"
  log "  OE_EVAL=${OE_EVAL}"
  log "  OE_ITERATIONS=${OE_ITERATIONS}"
  log "  EVAL_PERSIST_CHANGES=${EVAL_PERSIST_CHANGES}"
  exec openevolve-run "${OE_REPO_DIR}/${OE_TARGET_FILE}" "${OE_EVAL}" \
    ${OE_ITERATIONS:+--iterations "$OE_ITERATIONS"} \
    ${OPENAI_API_BASE:+--api-base "$OPENAI_API_BASE"}
elif [[ "${OE_RUN_MODE}" == "pytest" ]]; then
  exec pytest -q "${OE_REPO_DIR}/tests"
else
  log "[entrypoint] No run requested (OE_RUN_MODE=${OE_RUN_MODE}); idling."
  exec tail -f /dev/null
fi