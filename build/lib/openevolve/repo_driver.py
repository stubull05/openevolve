import os, sys, json, time, fnmatch, shutil, subprocess, random, re
from pathlib import Path

ROOT = Path("/workspace/openevolve")
EVAL_FILE = ROOT / "evaluation.py"
CONFIG = ROOT / "config.yaml"
LANG_TAG_RE = re.compile(r'^[ \t]*([a-zA-Z0-9.+_-]{1,16})[ \t]*\r?$', re.MULTILINE)

# Default globs (skip lockfiles & build dirs)
DEFAULT_PATTERNS = ["**/*.py", "**/*.js", "**/*.jsx", "**/*.ts", "**/*.tsx"]
DEFAULT_EXCLUDES = [
    ".git/**", "node_modules/**", "**/__pycache__/**", ".venv/**", "venv/**",
    "dist/**", "build/**", ".next/**", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"
]


def strip_fences_and_lang_tag(s: str) -> str:
    """
    Remove ```fences``` and a leading language tag line like 'javascript'/'python'.
    Picks the largest fenced block if multiple are present.
    """
    blocks = list(re.finditer(r"```[ \t]*[a-zA-Z0-9.+_-]*[ \t]*\r?\n(.*?)\r?\n```", s, re.DOTALL))
    inner = max(blocks, key=lambda m: len(m.group(1))).group(1) if blocks else s
    inner = inner.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    lines = inner.split("\n")
    if lines and LANG_TAG_RE.fullmatch(lines[0]) and lines[0].lower() in {"js","javascript","jsx","ts","tsx","py","python"}:
        lines = lines[1:]
    return "\n".join(lines).rstrip()


def load_cfg():
    cfg = {}
    if CONFIG.exists():
        try:
            import yaml
            cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[driver] WARNING: failed to read {CONFIG}: {e}")
    patterns = cfg.get("mutation_targets", DEFAULT_PATTERNS)
    excludes = cfg.get("exclude", DEFAULT_EXCLUDES)
    iterations = int(os.getenv("OE_PER_FILE_ITER", "20"))
    return patterns, excludes, iterations

def match_excluded(root: Path, p: Path, excludes):
    rel = str(p.relative_to(root)).replace("\\", "/")
    return any(fnmatch.fnmatch(rel, pat) for pat in excludes)

def collect_files(target_root: Path, patterns, excludes):
    files = []
    for pat in patterns:
        for p in target_root.glob(pat):
            if p.is_file() and not match_excluded(target_root, p, excludes):
                files.append(p)
    # Prefer .py then .ts/.js etc. (JS later so we warm up evaluator quickly on PY)
    files.sort(key=lambda p: {".py": 0, ".ts": 1, ".tsx": 2, ".js": 3, ".jsx": 4}.get(p.suffix.lower(), 9))
    return files

def pick_cli():
    """Return an explicit CLI path (no module fallback)."""
    cli = os.getenv("OE_CLI")
    if cli and (os.path.isfile(cli) or shutil.which(cli)):  # explicit override
        return cli
    exe = shutil.which("openevolve-run")                     # console script
    if exe:
        return exe
    for cand in ("/workspace/openevolve/openevolve-run.py",  # repo scripts
                 "/workspace/openevolve/openevolve/openevolve-run.py"):
        if os.path.isfile(cand):
            return cand
    return None

def build_cmd(cli_path: str, initial_file: Path, outdir: Path, iterations: int):
    base = [str(initial_file), str(EVAL_FILE),
            "--config", str(CONFIG), "--output", str(outdir),
            "--iterations", str(iterations)]
    if cli_path.endswith(".py"):
        return [sys.executable, cli_path] + base
    return [cli_path] + base


def _prefer_artifact(latest_ckpt: Path, target_suffix: str) -> Path | None:
    """
    Pick the best 'best_program.*' file, preferring target suffix (.py/.js/.tsx/...)
    and avoiding metadata json.
    """
    # explicit common names first
    candidates = [
        latest_ckpt / "best_program_code.txt",
        latest_ckpt / "best_program.py",
        latest_ckpt / "best_program.tsx",
        latest_ckpt / "best_program.ts",
        latest_ckpt / "best_program.jsx",
        latest_ckpt / "best_program.js",
    ]
    for c in candidates:
        if c.exists() and c.is_file() and not c.name.endswith("_info.json"):
            return c

    # Any best_program* except json
    pool = [p for p in latest_ckpt.glob("best_program*") if p.is_file() and not p.name.endswith(".json")]
    if not pool:
        return None
    # Prefer matching suffix
    by_suffix = [p for p in pool if p.suffix.lower() == target_suffix.lower()]
    if by_suffix:
        return sorted(by_suffix, key=lambda p: p.stat().st_size, reverse=True)[0]
    # Otherwise largest code-like file
    pool.sort(key=lambda p: p.stat().st_size, reverse=True)
    return pool[0]

def apply_best_checkpoint(output_dir: Path, target_file: Path) -> bool:
    """
    Find latest checkpoint in output_dir/checkpoints/ and write the best program
    back into target_file (with .bak backup). Returns True if applied.
    """
    ck_root = output_dir / "checkpoints"
    if not ck_root.exists():
        return False
    checkpoints = sorted(
        (p for p in ck_root.glob("checkpoint_*") if p.is_dir()),
        key=lambda p: int(p.name.split("_")[-1]),
        reverse=True,
    )
    if not checkpoints:
        return False
    latest = checkpoints[0]
    best_path = _prefer_artifact(latest, target_file.suffix)
    if not best_path:
        print(f"[driver] No best_program code file found in {latest}.")
        return False

    raw = best_path.read_text(encoding="utf-8", errors="ignore")
    code = strip_fences_and_lang_tag(raw)
    if not code.strip():
        print("[driver] best_program is empty after fence extraction; skipping.")
        return False

    current = target_file.read_text(encoding="utf-8", errors="ignore") if target_file.exists() else ""
    if current.strip() == code.strip():
        print("[driver] best_program has no changes vs current file; skipping apply.")
        return False

    backup = target_file.with_suffix(target_file.suffix + ".bak")
    shutil.copy2(str(target_file), str(backup)) if target_file.exists() else None
    target_file.write_text(code + ("\n" if not code.endswith("\n") else ""), encoding="utf-8")
    print(f"[driver] Applied evolved code to {target_file} (backup: {backup.name if target_file.exists() else 'n/a'})")

    # Optional auto-commit
    if os.getenv("OE_AUTOCOMMIT", "0") in ("1", "true", "True"):
        try:
            subprocess.run(["git", "add", str(target_file)], cwd="/workspace/target")
            subprocess.run(["git", "commit", "-m", f"OpenEvolve apply: {target_file.name}"], cwd="/workspace/target")
        except Exception as e:
            print(f"[driver] git auto-commit failed (non-fatal): {e}")
    return True

def run_openevolve_for_file(filepath: Path, iterations: int, cli_path: str):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(filepath).strip("/"))
    outdir = ROOT.parent / f"openevolve_output_{safe}"
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    cmd = build_cmd(cli_path, filepath, outdir, iterations)
    print(f"\n=== Evolving: {filepath} (iterations={iterations}) ===", flush=True)
    print(" ".join(cmd), flush=True)
    env = os.environ.copy()
    env["OE_TARGET_FILE"] = str(filepath)   
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env)
    print(f"[openevolve] exit code: {proc.returncode}", flush=True)

    applied = apply_best_checkpoint(outdir, filepath)
    if not applied:
        print(f"[driver] No applicable checkpoint for {filepath}.")
    time.sleep(0.2)

def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/workspace/target")
    if not target.exists():
        print(f"[driver] Target repo not mounted at {target}")
        sys.exit(1)
    if not EVAL_FILE.exists():
        print(f"[driver] evaluation.py missing at {EVAL_FILE}")
        sys.exit(1)

    cli_path = pick_cli()
    if not cli_path:
        print("[driver] ERROR: Could not find OpenEvolve CLI. Set OE_CLI to either "
              "the full path of openevolve-run or /workspace/openevolve/openevolve-run.py")
        sys.exit(1)

    patterns, excludes, iterations = load_cfg()
    print(f"[driver] Using CLI: {cli_path}")
    print(f"[driver] Patterns: {patterns}")
    print(f"[driver] Excludes: {excludes}")
    print(f"[driver] Scanning repo at {target}…")
    files = collect_files(target, patterns, excludes)
    if not files:
        print("[driver] No candidate files found. Adjust mutation_targets in config.yaml.")
        sys.exit(1)

    print(f"[driver] {len(files)} files queued for evolution.")
    while True:
        random.shuffle(files)
        for f in files:
            try:
                if f.stat().st_size > 2_000_000:
                    print(f"[driver] Skipping large file: {f}")
                    continue
            except Exception:
                continue
            run_openevolve_for_file(f, iterations, cli_path)
        time.sleep(2)

if __name__ == "__main__":
    main()
