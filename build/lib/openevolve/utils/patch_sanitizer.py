# openevolve/utils/patch_sanitizer.py
"""
Robust sanitizer: converts model output to a valid unified diff for ONE target file.

Fixes:
- strip ``` fences & git headers (diff --git, index, file mode, similarity index…)
- repair malformed hunk tails ('@...' -> '@@')
- coerce stray lines IN HUNKS to context (' ' prefix)
- retarget filenames to OE_TARGET_FILE (default 'api.py')
- enforce OE_ALLOWED_FILES allowlist
- normalize Unicode (BOM/ZWSP/NBSP/unicode minus) + line endings
- select the best fenced block if multiple are present
- return '' when there are no hunks or no +/- lines (so caller re-prompts safely)

Env (optional):
  OE_TARGET_FILE     default: api.py
  OE_ALLOWED_FILES   default: "<OE_TARGET_FILE>,data_layer.py"
  OE_PATCH_MAX_LINES default: 5000
"""

from __future__ import annotations
import os, re, sys
from typing import Iterable, List

TARGET = (os.environ.get("OE_TARGET_FILE") or "api.py").strip() or "api.py"
_ALLOWED = {
    x for x in (os.environ.get("OE_ALLOWED_FILES") or f"{TARGET},data_layer.py")
    .replace(" ", "").split(",") if x
}
try:
    MAX_LINES = int(os.environ.get("OE_PATCH_MAX_LINES", "5000"))
except Exception:
    MAX_LINES = 5000

# --- unicode & line-ending normalization ---
_RE_BOM = re.compile(r"^\ufeff")
_RE_ZW  = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_RE_NB  = re.compile(r"[\u00a0\u202f]")
_RE_UM  = re.compile(r"[\u2212]")  # unicode minus
def _normalize_text(s: str) -> str:
    if not s:
        return s
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _RE_BOM.sub("", s)
    s = _RE_ZW.sub("", s)
    s = _RE_NB.sub(" ", s)
    s = _RE_UM.sub("-", s)
    return s

# --- patterns ---
_RE_FENCE_BLOCKS = re.compile(r"```(?P<tag>\w+)?\s*(?P<body>.*?)```", re.S | re.I)
_RE_GIT_HDRS     = (
    re.compile(r"^diff --git .*$", re.I),
    re.compile(r"^index [0-9a-f]+\.\.[0-9a-f]+(?: \d+)?$", re.I),
    re.compile(r"^(?:new|deleted) file mode \d+$", re.I),
    re.compile(r"^similarity index \d+%$", re.I),
    re.compile(r"^rename (?:from|to) .+$", re.I),
)
_RE_OLD = re.compile(r"^---\s+(.*)$")
_RE_NEW = re.compile(r"^\+\+\+\s+(.*)$")
_RE_VALID_HUNK = re.compile(r"^@@\s*-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s*@@(?:\s.*)?$")
# malformed tails like '@...' → make '@@'
_RE_FIX_HUNK = re.compile(r"^@@\s*-(\d+(?:,\d+)?)\s+\+(\d+(?:,\d+)?)\s*@.*$")

def _choose_best_block(text: str) -> str:
    """
    If multiple fenced blocks exist, pick the one most likely to be a diff.
    Preference order: tag is 'diff'/'patch', highest presence of diff tokens.
    """
    blocks = list(_RE_FENCE_BLOCKS.finditer(text))
    if not blocks:
        return text
    scored = []
    for m in blocks:
        tag = (m.group("tag") or "").lower()
        body = m.group("body") or ""
        score = 0
        if tag in {"diff","patch"}:
            score += 5
        # token counts
        tokens = ("--- ", "+++ ", "@@ ", "diff --git", "\n+","\n-","index ")
        score += sum(body.count(t) for t in tokens)
        scored.append((score, body))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]

def _strip_git_headers(lines: Iterable[str]) -> List[str]:
    out: List[str] = []
    for ln in lines:
        if any(p.match(ln) for p in _RE_GIT_HDRS):
            continue
        out.append(ln)
    return out

def _retarget_path(path: str) -> str:
    path = path.strip()
    if path.startswith(("a/","b/")):
        path = path[2:]
    # common hallucination
    if path == "app.py":
        path = TARGET
    if path not in _ALLOWED:
        path = TARGET
    return path

def _coerce_hunk_lines(lines: List[str]) -> List[str]:
    """
    Inside hunks: ensure each line starts with '+', '-', or ' '.
    Outside hunks: keep only headers or start of next hunk.
    """
    out: List[str] = []
    in_hunk = False
    i = 0
    
    while i < len(lines):
        ln = lines[i]
        
        # Check for hunk header
        if ln.startswith("@@") or _RE_VALID_HUNK.match(ln):
            in_hunk = True
            out.append(ln)
            i += 1
            continue
            
        # Check for file headers
        if ln.startswith(("--- ", "+++ ")):
            in_hunk = False
            out.append(ln)
            i += 1
            continue
            
        # Handle lines inside hunks
        if in_hunk:
            if ln.startswith(("+", "-", " ")):
                out.append(ln)
            elif ln == "":
                # Empty line in hunk becomes context
                out.append(" ")
            elif ln.strip() == "":
                # Whitespace-only line becomes context
                out.append(" ")
            else:
                # Non-prefixed line in hunk becomes context
                out.append(" " + ln)
        else:
            # Outside hunks, only keep headers and hunk starts
            if ln.startswith(("--- ", "+++ ", "@@")) or _RE_VALID_HUNK.match(ln):
                out.append(ln)
                if ln.startswith("@@") or _RE_VALID_HUNK.match(ln):
                    in_hunk = True
            # Skip other lines outside hunks
        
        i += 1
    
    return out

def _is_diff_content(ln: str) -> bool:
    """
    Check if a line is valid diff content.
    More permissive than the original _keep_diff_line.
    """
    if not ln:
        return False
    
    # File headers
    if ln.startswith(("--- ", "+++ ")):
        return True
    
    # Hunk headers 
    if ln.startswith("@@") and ("+" in ln and "-" in ln):
        return True
    
    # Hunk content lines
    if ln.startswith(("+", "-", " ")):
        return True
    
    # Check for valid hunk with regex
    if _RE_VALID_HUNK.match(ln):
        return True
        
    return False

def extract_raw_patch(text: str) -> str:
    """
    OpenEvolve calls this to obtain a raw unified diff string.
    Returns '' when unusable, prompting a safe re-ask upstream.
    """
    if not isinstance(text, str) or not text.strip():
        print("[sanitizer] Empty or invalid input text", file=sys.stderr)
        return ""

    text = _normalize_text(text)

    # pick the best fenced block if present
    candidate = _choose_best_block(text)
    candidate = _normalize_text(candidate)

    # split & trim
    lines = [ln.rstrip() for ln in candidate.split("\n")]
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]

    # drop obvious git headers
    lines = _strip_git_headers(lines)
    
    if not lines:
        print("[sanitizer] No lines after git header removal", file=sys.stderr)
        return ""

    # rewrite headers & repair malformed hunks; retarget filenames
    fixed: List[str] = []
    for ln in lines:
        # Handle old file header (--- a/file)
        mo = _RE_OLD.match(ln)
        if mo:
            path = _retarget_path(mo.group(1))
            fixed.append(f"--- a/{path}")
            continue
            
        # Handle new file header (+++ b/file)
        mn = _RE_NEW.match(ln)
        if mn:
            path = _retarget_path(mn.group(1))
            fixed.append(f"+++ b/{path}")
            continue
            
        # Fix malformed hunk headers
        mf = _RE_FIX_HUNK.match(ln)
        if mf:
            fixed.append(f"@@ -{mf.group(1)} +{mf.group(2)} @@")
            continue
            
        fixed.append(ln)
    
    lines = fixed

    # More permissive filtering - keep anything that looks like diff content
    filtered_lines = []
    for ln in lines:
        if _is_diff_content(ln) or ln.strip() == "":
            filtered_lines.append(ln)
        # Also keep lines that might be context but got mangled
        elif any(lines[max(0, i-2):i+3] for i, l in enumerate(lines) 
                if l.startswith("@@") and abs(lines.index(ln) - i) <= 10):
            # Line is near a hunk, probably content
            if not ln.startswith(("+", "-", " ")) and ln.strip():
                filtered_lines.append(" " + ln)
            else:
                filtered_lines.append(ln)
    
    lines = filtered_lines
    
    if not lines:
        print("[sanitizer] No valid diff lines found after filtering", file=sys.stderr)
        return ""

    # Check if we have any hunk-like content
    has_hunk_header = any(ln.startswith("@@") or _RE_VALID_HUNK.match(ln) for ln in lines)
    has_changes = any(ln.startswith(("+", "-")) for ln in lines)
    
    if not has_hunk_header and not has_changes:
        print("[sanitizer] No hunks or changes detected", file=sys.stderr)
        return ""

    # inject headers if missing but we appear to have content
    has_headers = any(ln.startswith("--- a/") for ln in lines) and any(ln.startswith("+++ b/") for ln in lines)
    
    if not has_headers and (has_hunk_header or has_changes):
        lines = [f"--- a/{TARGET}", f"+++ b/{TARGET}"] + lines

    # Fix malformed hunk headers and coerce lines to proper format
    normalized = []
    for ln in lines:
        if ln.startswith("@@") and not _RE_VALID_HUNK.match(ln):
            # Try to fix malformed hunk headers
            mf = _RE_FIX_HUNK.match(ln)
            if mf:
                normalized.append(f"@@ -{mf.group(1)} +{mf.group(2)} @@")
                continue
            # If we can't fix it, try a simple repair
            elif "@" in ln and "-" in ln and "+" in ln:
                # Extract numbers if possible
                numbers = re.findall(r'-(\d+(?:,\d+)?)\s+\+(\d+(?:,\d+)?)', ln)
                if numbers:
                    normalized.append(f"@@ -{numbers[0][0]} +{numbers[0][1]} @@")
                    continue
        normalized.append(ln)
    
    lines = _coerce_hunk_lines(normalized)

    # Remove empty lines at the end
    while lines and not lines[-1].strip():
        lines.pop()

    # final assembly & validation
    out = "\n".join(lines)
    
    if not out.strip():
        print("[sanitizer] Empty output after processing", file=sys.stderr)
        return ""

    # Must contain a hunk and at least one actual +/- change
    if "@@" not in out:
        print("[sanitizer] No hunk headers found in final output", file=sys.stderr)
        return ""
    
    final_lines = out.splitlines()
    if not any(ln.startswith(("+", "-")) for ln in final_lines):
        print("[sanitizer] No actual changes (+/-) found in final output", file=sys.stderr)
        return ""

    # Ensure proper headers
    if not out.startswith(f"--- a/{TARGET}"):
        out_lines = out.splitlines()
        # Find first non-header line
        content_start = 0
        for i, ln in enumerate(out_lines):
            if not ln.startswith(("--- ", "+++ ")):
                content_start = i
                break
        
        out = f"--- a/{TARGET}\n+++ b/{TARGET}\n" + "\n".join(out_lines[content_start:])

    if not out.endswith("\n"):
        out += "\n"

    # Debug preview
    try:
        preview_lines = out.splitlines()[:15]
        preview = "\n".join(preview_lines)
        if len(out.splitlines()) > 15:
            preview += "\n... (truncated)"
        print(f"[sanitizer] target={TARGET} allowed={sorted(_ALLOWED)}", file=sys.stdout)
        print(f"[sanitizer] preview:\n{preview}", file=sys.stdout)
    except Exception as e:
        print(f"[sanitizer] Preview generation error: {e}", file=sys.stderr)

    return out