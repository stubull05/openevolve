# openevolve/utils/code_utils.py
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

log = logging.getLogger(__name__)

__all__ = [
    # core data & parsers
    "DiffBlock",
    "extract_diffs",
    # single-file apply
    "apply_diffs_to_code",
    # repo-wide apply
    "apply_diffs_across_repo",
    # back-compat shims (expected by older modules)
    "apply_diff",
    "calculate_edit_distance",
    "extract_code_language",
    "format_diff_summary",
]

# ======================================================================================
# Data structures
# ======================================================================================

@dataclass
class DiffBlock:
    """
    A simple SEARCH/REPLACE edit, optionally scoped to a repo-relative file.

    Attributes:
        search:  The exact (or near-exact) text to find.
        replace: The replacement text.
        target_file: Optional repo-relative path to apply this change to a specific file.
    """
    search: str
    replace: str
    target_file: Optional[str] = None


# ======================================================================================
# Parsing LLM output into diffs (lenient; accepts multiple formats)
# ======================================================================================

# Capture fenced blocks of any common type; we'll parse inside them
_TRIPLE_FENCE = re.compile(
    r"```(?:diff|patch|python|py|javascript|js|ts|tsx|json|yaml|yml|text|md|html|bash|sh)?\s*(.*?)```",
    re.DOTALL | re.IGNORECASE,
)

def _strip_code_fences(text: str) -> str:
    m = _TRIPLE_FENCE.search(text)
    return m.group(1) if m else text

def _parse_search_replace_block(text: str) -> Optional[DiffBlock]:
    """
    Accepts one of the following shapes (case-insensitive markers):

    Style A (conflict-like markers, optional FILE header):
        FILE: path/to/file.py
        <<<<<<< SEARCH
        <search>
        =======
        <replace>
        >>>>>>> REPLACE

    Style B (labeled sections, optional FILE header):
        FILE: path/to/file.py
        SEARCH:
        <search>
        REPLACE:
        <replace>

    If FILE is omitted, the diff applies to the "current" in-memory code string.
    """
    body = _strip_code_fences(text).strip()

    # Optional FILE header
    target_file = None
    m_file = re.search(r"^\s*FILE\s*:\s*(.+)$", body, re.IGNORECASE | re.MULTILINE)
    if m_file:
        target_file = m_file.group(1).strip()
        body = re.sub(r"^\s*FILE\s*:\s*.+\n?", "", body, flags=re.IGNORECASE | re.MULTILINE)

    # Style A
    m = re.search(
        r"<<<<<<<\s*SEARCH\s*\n(.*?)\n=======\n(.*?)\n>>>>>>>\s*REPLACE\s*$",
        body,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        return DiffBlock(search=m.group(1), replace=m.group(2), target_file=target_file)

    # Style B
    m = re.search(
        r"SEARCH\s*:\s*\n(.*?)\nREPLACE\s*:\s*\n(.*)$",
        body,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        return DiffBlock(search=m.group(1), replace=m.group(2), target_file=target_file)

    return None

def extract_diffs(response_text: str) -> List[DiffBlock]:
    """
    Extract one or more DiffBlock objects from an LLM response.
    We’re permissive and try multiple strategies to increase hit-rate.
    """
    blocks: List[DiffBlock] = []

    # 1) Try each fenced block as a candidate
    for chunk in _TRIPLE_FENCE.findall(response_text):
        db = _parse_search_replace_block(f"```{chunk}```")
        if db:
            blocks.append(db)

    # 2) If none found, try whole response body
    if not blocks:
        db = _parse_search_replace_block(response_text)
        if db:
            blocks.append(db)

    return blocks


# ======================================================================================
# Applying diffs to code
# ======================================================================================

def _ws_regex_escape(s: str) -> str:
    """
    Escape text and make whitespace flexible so the SEARCH can match with
    minor formatting differences (spaces/newlines/comments).
    """
    parts = re.split(r"\s+", s.strip())
    if not parts:
        return r"(?:^$)"
    escaped = r"\s+".join(map(re.escape, parts))
    return escaped

def _try_apply_exact(haystack: str, needle: str, repl: str) -> Tuple[str, bool]:
    if needle in haystack:
        return haystack.replace(needle, repl, 1), True
    return haystack, False

def _try_apply_ws_tolerant(haystack: str, needle: str, repl: str) -> Tuple[str, bool]:
    pattern = re.compile(_ws_regex_escape(needle), re.DOTALL)
    if pattern.search(haystack):
        return pattern.sub(repl, haystack, count=1), True
    return haystack, False

def apply_diffs_to_code(
    code: str,
    diff_blocks: Iterable[Union[DiffBlock, Dict[str, str]]],
) -> Tuple[str, Dict[str, int]]:
    """
    Apply a list of search/replace edits to a single code string.
    Returns (new_code, stats).
    """
    applied = 0
    skipped = 0
    new_code = code

    for i, raw in enumerate(diff_blocks, 1):
        if isinstance(raw, DiffBlock):
            db = raw
        else:
            db = DiffBlock(
                search=raw.get("search", ""),
                replace=raw.get("replace", ""),
                target_file=raw.get("target_file"),
            )

        if not db.search:
            skipped += 1
            log.warning("Diff %d has empty SEARCH; skipping.", i)
            continue

        # 1) Exact first
        updated, ok = _try_apply_exact(new_code, db.search, db.replace)
        if ok:
            applied += 1
            new_code = updated
            log.info("Applied diff %d via exact match.", i)
            continue

        # 2) Whitespace tolerant fallback
        updated, ok = _try_apply_ws_tolerant(new_code, db.search, db.replace)
        if ok:
            applied += 1
            new_code = updated
            log.info("Applied diff %d via whitespace-tolerant regex.", i)
            continue

        skipped += 1
        log.warning("Diff %d search text not found (even after tolerant strategies).", i)

    if applied:
        log.info("Code was modified! Original: %d chars, New: %d chars", len(code), len(new_code))
    else:
        log.info("No changes applied to code.")

    return new_code, {"applied_count": applied, "skipped_count": skipped, "total": applied + skipped}


# --------------------------------------------------------------------------------------
# Filesystem helpers & repo-wide apply
# --------------------------------------------------------------------------------------

def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return path.read_text(encoding="utf-8", errors="ignore")

def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def apply_diffs_across_repo(
    repo_root: Union[str, Path],
    blocks: Iterable[Union[DiffBlock, Dict[str, str]]],
    create_missing_files: bool = True,
) -> Dict[str, Dict[str, int]]:
    """
    Apply blocks that have target_file set across a repo tree.
    Returns per-file stats. Blocks without target_file are ignored here.
    """
    root = Path(repo_root)
    per_file_stats: Dict[str, Dict[str, int]] = {}

    grouped: Dict[str, List[DiffBlock]] = {}
    for raw in blocks:
        db = raw if isinstance(raw, DiffBlock) else DiffBlock(
            search=raw.get("search", ""),
            replace=raw.get("replace", ""),
            target_file=raw.get("target_file"),
        )
        if not db.target_file:
            log.debug("Skipping block without target_file during repo apply.")
            continue
        grouped.setdefault(db.target_file, []).append(db)

    for rel, dbs in grouped.items():
        out_path = root / rel
        if not out_path.exists():
            if not create_missing_files:
                log.warning("Target file %s missing and create_missing_files=False; skipping.", out_path)
                continue
            log.info("Creating missing target file: %s", out_path)
            _write_text(out_path, "")

        original = _read_text(out_path)
        updated, stats = apply_diffs_to_code(original, dbs)
        if updated != original:
            _write_text(out_path, updated)

        per_file_stats[rel] = stats

    return per_file_stats


# ======================================================================================
# Back-compat helpers expected by older modules
# ======================================================================================

def apply_diff(code: str, search_text: str, replace_text: str) -> Tuple[str, bool]:
    """
    Backward-compatible singular apply function.
    Returns (new_code, applied_bool).
    """
    updated, stats = apply_diffs_to_code(code, [DiffBlock(search=search_text, replace=replace_text)])
    return updated, bool(stats.get("applied_count", 0))

def calculate_edit_distance(a: str, b: str, max_distance: Optional[int] = None) -> int:
    """
    Levenshtein edit distance (insert/delete/replace, all cost 1).
    Uses two rolling rows for O(min(len(a), len(b))) memory.
    If max_distance is provided, we abort early once the running lower bound exceeds it.
    """
    if a == b:
        return 0
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    # Ensure n <= m to use less memory
    if n > m:
        a, b = b, a
        n, m = m, n

    previous = list(range(n + 1))
    current = [0] * (n + 1)

    for j in range(1, m + 1):
        current[0] = j
        bj = b[j - 1]
        row_best = current[0]

        for i in range(1, n + 1):
            cost = 0 if a[i - 1] == bj else 1
            current[i] = min(
                previous[i] + 1,      # deletion
                current[i - 1] + 1,   # insertion
                previous[i - 1] + cost,  # substitution
            )
            if current[i] < row_best:
                row_best = current[i]

        if max_distance is not None and row_best > max_distance:
            return row_best

        previous, current = current, previous

    return previous[n]

def format_diff_summary(blocks: Iterable[Union[DiffBlock, Dict[str, str]]]) -> str:
    """
    Produce a short human-readable summary of diff blocks for logging or UI.
    """
    normalized: List[DiffBlock] = []
    for raw in blocks:
        if isinstance(raw, DiffBlock):
            normalized.append(raw)
        else:
            normalized.append(
                DiffBlock(
                    search=raw.get("search", ""),
                    replace=raw.get("replace", ""),
                    target_file=raw.get("target_file"),
                )
            )

    total = len(normalized)
    with_file = sum(1 for b in normalized if b.target_file)
    targets = {}
    for b in normalized:
        key = b.target_file or "<current file>"
        targets.setdefault(key, 0)
        targets[key] += 1

    lines = [
        f"{total} diff block(s); {with_file} targeted to specific files.",
        "Per-target counts:"
    ]
    for tgt, cnt in sorted(targets.items(), key=lambda x: (x[0] != "<current file>", x[0])):
        lines.append(f"  - {tgt}: {cnt}")

    # Add a tiny preview of each block (trimmed)
    def _trim(s: str, n: int = 80) -> str:
        s = re.sub(r"\s+", " ", s.strip())
        return (s[: n - 1] + "…") if len(s) > n else s

    for i, b in enumerate(normalized, 1):
        lines.append(f"\n[{i}] target={b.target_file or '<current file>'}")
        lines.append(f"  SEARCH : {_trim(b.search)}")
        lines.append(f"  REPLACE: {_trim(b.replace)}")

    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Language detection (back-compat: extract_code_language)
# --------------------------------------------------------------------------------------

_EXT_TO_LANG = {
    "py": "python",
    "ipynb": "python",
    "js": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "jsx": "javascript",
    "json": "json",
    "yml": "yaml",
    "yaml": "yaml",
    "md": "markdown",
    "html": "html",
    "htm": "html",
    "css": "css",
    "sh": "bash",
    "bash": "bash",
    "zsh": "bash",
    "Dockerfile": "dockerfile",
}

def _lang_from_extension(s: str) -> Optional[str]:
    try:
        p = Path(s)
        if p.suffix:
            ext = p.suffix.lstrip(".").lower()
            return _EXT_TO_LANG.get(ext)
        # Handle "Dockerfile", "Makefile", etc.
        name = p.name
        return _EXT_TO_LANG.get(name)
    except Exception:
        return None

_FENCE_LANG = re.compile(r"```([A-Za-z0-9_\-]+)\b")

def _lang_from_fence(s: str) -> Optional[str]:
    m = _FENCE_LANG.search(s)
    if m:
        return m.group(1).lower()
    return None

def _lang_from_heuristics(s: str) -> Optional[str]:
    head = s if len(s) < 4000 else s[:4000]

    # Shebangs
    if re.search(r"^#!.*\bpython[0-9.]*\b", head, re.MULTILINE):
        return "python"
    if re.search(r"^#!.*\b(node|bash|sh|zsh)\b", head, re.MULTILINE):
        if "node" in head:
            return "javascript"
        return "bash"

    # Quick tokens
    if re.search(r"\bdef\s+\w+\(", head) and "import " in head:
        return "python"
    if re.search(r"\bconsole\.log\(|\bfunction\s+\w+\(|\bexport\s+(default|const|function)\b", head):
        return "javascript"
    if re.search(r"\binterface\s+\w+|:\s*\{.*\}\s*;", head) and "import " in head:
        return "typescript"
    if re.search(r"^{\s*\"[^\n]+\":", head):
        return "json"
    if re.search(r"^\s*(FROM|RUN|COPY|ENTRYPOINT|CMD)\b", head, re.IGNORECASE | re.MULTILINE):
        return "dockerfile"
    if re.search(r"^\s*<html[^>]*>|^\s*<!DOCTYPE html>", head, re.IGNORECASE | re.MULTILINE):
        return "html"
    if re.search(r"^\s*---\s*$", head, re.MULTILINE) and ":" in head:
        return "yaml"
    return None

def extract_code_language(code_or_filename: str, default: str = "python") -> str:
    """
    Best-effort language detection used by prompt builders & formatters.
    - If given a path/filename, use its extension or special name.
    - Else, try a code-fence language tag.
    - Else, light heuristics on content.
    - Fallback to `default`.
    """
    # Filename/Path?
    lang = _lang_from_extension(code_or_filename)
    if lang:
        return lang

    # Code fence?
    lang = _lang_from_fence(code_or_filename)
    if lang:
        # normalize aliases
        if lang in ("py",):
            return "python"
        if lang in ("js",):
            return "javascript"
        if lang in ("ts", "tsx"):
            return "typescript"
        return lang

    # Heuristics
    lang = _lang_from_heuristics(code_or_filename)
    return lang or default

# ------------------------------
# Back-compat shims (append only)
# ------------------------------

def _safe_get(attr, default=""):
    try:
        return getattr(attr, "__dict__", {}) or attr
    except Exception:
        return default

# 1) Old name -> new extractor
try:
    parse_evolve_blocks  # type: ignore[name-defined]
except NameError:
    def parse_evolve_blocks(response_text: str, *_, **__) -> list:
        """
        Back-compat: older code imported parse_evolve_blocks(). Delegate to the
        newer extractor (e.g., extract_diffs/parse_diff_blocks/etc.).
        """
        try:
            # Prefer the most capable parser present in this module
            if "parse_diff_blocks" in globals():
                return parse_diff_blocks(response_text)  # type: ignore[misc]
            if "extract_diffs" in globals():
                return extract_diffs(response_text)  # type: ignore[misc]
            if "extract_diffs_from_response" in globals():
                return extract_diffs_from_response(response_text)  # type: ignore[misc]
        except Exception as e:
            log.exception("parse_evolve_blocks failed: %s", e)
        return []

# 2) Single-block applier expected by older code
try:
    apply_diff  # type: ignore[name-defined]
except NameError:
    def apply_diff(original_text: str, block, **kwargs):
        """
        Back-compat: apply a single diff block using the newer multi-block applier
        if available. Returns (new_text, changed: bool).
        """
        try:
            if "apply_diffs" in globals():
                res = apply_diffs(original_text, [block], **kwargs)  # type: ignore[misc]
                # Support either (text, applied_count) or just text
                if isinstance(res, tuple) and len(res) >= 2:
                    new_text, applied_count = res[0], res[1]
                    return new_text, bool(applied_count)
                return res, True
        except Exception as e:
            log.exception("apply_diff failed: %s", e)
        return original_text, False

# 3) Human-readable summary of blocks
try:
    format_diff_summary  # type: ignore[name-defined]
except NameError:
    def format_diff_summary(blocks) -> str:
        """Back-compat: summarize a list of diff blocks for logs/UI."""
        lines = []
        for i, b in enumerate(blocks, 1):
            try:
                # Support dict-like or object-like blocks
                search = b.get("search") if hasattr(b, "get") else getattr(b, "search", "")
                replace = b.get("replace") if hasattr(b, "get") else getattr(b, "replace", "")
                path = b.get("path") if hasattr(b, "get") else getattr(b, "path", "")
                tag  = b.get("tag")  if hasattr(b, "get") else getattr(b, "tag", "")
                head = (search or "")[:40].replace("\n", " ")
                lines.append(f"{i:02d}. {('['+path+'] ') if path else ''}{head!r}  ->  {('['+tag+']') if tag else ''}")
            except Exception:
                lines.append(f"{i:02d}. {str(b)[:80]}")
        return "\n".join(lines)

# 4) Simple Levenshtein edit distance (used for fuzzy matching in some versions)
try:
    calculate_edit_distance  # type: ignore[name-defined]
except NameError:
    def calculate_edit_distance(a: str, b: str) -> int:
        la, lb = len(a), len(b)
        if la == 0: return lb
        if lb == 0: return la
        # O(min(la,lb)) space DP
        if la < lb:
            a, b = b, a
            la, lb = lb, la
        prev = list(range(lb + 1))
        for i in range(1, la + 1):
            curr = [i] + [0] * lb
            ca = a[i - 1]
            for j in range(1, lb + 1):
                cb = b[j - 1]
                cost = 0 if ca == cb else 1
                curr[j] = min(prev[j] + 1,      # deletion
                              curr[j - 1] + 1,  # insertion
                              prev[j - 1] + cost)  # substitution
            prev = curr
        return prev[lb]

# 5) Language inference from fenced code blocks
try:
    extract_code_language  # type: ignore[name-defined]
except NameError:
    def extract_code_language(text: str) -> str:
        """
        Back-compat: guess language from a fenced block like ```python or ```diff.
        Returns a lowercase language token ('' if unknown).
        """
        m = re.search(r"```([A-Za-z0-9_+-]+)", text)
        if m:
            return (m.group(1) or "").strip().lower()
        # quick fallbacks
        if "def " in text or "import " in text:
            return "python"
        if "function " in text or "const " in text or "=> {" in text:
            return "javascript"
        if text.lstrip().startswith("diff") or text.lstrip().startswith("--- a/"):
            return "diff"
        return ""
    
# ------------------------------
# Back-compat shim: parse_full_rewrite
# ------------------------------
try:
    parse_full_rewrite  # type: ignore[name-defined]
except NameError:  # only define if missing
    import re, logging
    _log = logging.getLogger(__name__)

    # ```lang\n...content...\n``` matcher (simple + robust)
    _FENCE_RE = re.compile(r"```(?P<lang>[A-Za-z0-9_+\-]*)\s*\n(?P<body>.*?)\n```", re.DOTALL)

    def _strip_header_lines(s: str) -> str:
        """Strip lines like 'file: path/to.py', 'path: ...', 'BEGIN FILE: ...'."""
        out = []
        for line in s.splitlines():
            if re.match(r"\s*(#|//|/\*+)?\s*(file|path)\s*:", line, re.IGNORECASE):
                continue
            if re.match(r"\s*(BEGIN\s+FILE|FILE)\s*:", line, re.IGNORECASE):
                continue
            out.append(line)
        return "\n".join(out)

    def _find_path_hint(header_chunk: str) -> str:
        m = re.search(r"(?:^|\n)\s*(?:file|path)\s*:\s*(?P<p>.+)$", header_chunk, re.IGNORECASE)
        if not m:
            m = re.search(r"(?:^|\n)\s*(?:BEGIN\s+FILE|FILE)\s*:\s*(?P<p>.+)$", header_chunk, re.IGNORECASE)
        return (m.group("p").strip().strip("`'\"") if m else "")

    def parse_full_rewrite(response_text: str, *_, return_tuple: bool = False, **__) :
        """
        Back-compat: extract a full-file rewrite from an LLM response.

        Returns:
          - By default: [ { "type": "rewrite", "path": <maybe empty>, "content": <str> } ]
          - If return_tuple=True: (path, content)

        The parser looks for the first fenced code block (```lang ... ```). If none
        exists, it treats the whole response as the content. It also recognizes header
        hints like 'file: path/to.py', 'path: ...', or 'BEGIN FILE: ...' in the first
        few lines to populate 'path'.
        """
        try:
            fence = _FENCE_RE.search(response_text)
            if fence:
                candidate = fence.group("body")
            else:
                candidate = response_text

            # Try to extract a path hint from the first 5 lines
            head = "\n".join(candidate.splitlines()[:5])
            path = _find_path_hint(head)

            content = _strip_header_lines(candidate).strip("\n")
            if return_tuple:
                return (path, content)
            return [{"type": "rewrite", "path": path, "content": content}]
        except Exception as e:
            _log.exception("parse_full_rewrite failed: %s", e)
            if return_tuple:
                return ("", "")
            return []
