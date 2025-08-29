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
    """Retarget file paths to allowed files, defaulting to TARGET"""
    path = path.strip()
    if path.startswith(("a/","b/")):
        path = path[2:]
    # Common hallucinations - map to target
    if path in ("app.py", "main.py", "server.py"):
        path = TARGET
    # Only allow files in the allowlist
    if path not in _ALLOWED:
        path = TARGET
    return path

def _fix_hunk_context(lines: List[str]) -> List[str]:
    """
    Ensure hunk lines have proper prefixes and fix common formatting issues.
    """
    out: List[str] = []
    in_hunk = False
    
    for ln in lines:
        # File headers and hunk headers end the current hunk context
        if ln.startswith(("--- ", "+++ ", "@@")) or _RE_VALID_HUNK.match(ln):
            in_hunk = ln.startswith("@@") or _RE_VALID_HUNK.match(ln)
            out.append(ln)
            continue
            
        if in_hunk:
            # Already properly prefixed
            if ln.startswith(("+", "-", " ")):
                out.append(ln)
            # Empty line becomes context
            elif not ln.strip():
                out.append(" ")
            # Non-prefixed line in hunk becomes context  
            else:
                out.append(" " + ln)
        else:
            # Outside hunks, keep as-is (will be filtered later)
            out.append(ln)
    
    return out

def _is_valid_diff_line(line: str) -> bool:
    """Check if a line belongs in a unified diff"""
    if not line:
        return True  # Empty lines are OK
    
    # File headers
    if line.startswith(("--- a/", "+++ b/")):
        return True
        
    # Hunk headers
    if _RE_VALID_HUNK.match(line):
        return True
        
    # Hunk content
    if line.startswith(("+", "-", " ")):
        return True
        
    return False

def extract_raw_patch(text: str) -> str:
    """
    OpenEvolve calls this to obtain a raw unified diff string.
    Returns '' when unusable, prompting a safe re-ask upstream.
    """
    if not isinstance(text, str) or not text.strip():
        return ""

    text = _normalize_text(text)

    # Choose the best fenced block if present
    candidate = _choose_best_block(text)
    candidate = _normalize_text(candidate)

    # Split into lines and truncate if too long
    lines = [ln.rstrip() for ln in candidate.split("\n")]
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]

    # Remove git headers that confuse patch
    lines = _strip_git_headers(lines)
    
    if not lines:
        return ""

    # Fix file headers and retarget paths
    fixed_lines: List[str] = []
    has_old_header = False
    has_new_header = False
    
    for ln in lines:
        # Handle old file header (--- a/file or --- file)
        mo = _RE_OLD.match(ln)
        if mo:
            path = _retarget_path(mo.group(1))
            fixed_lines.append(f"--- a/{path}")
            has_old_header = True
            continue
            
        # Handle new file header (+++ b/file or +++ file)  
        mn = _RE_NEW.match(ln)
        if mn:
            path = _retarget_path(mn.group(1))
            fixed_lines.append(f"+++ b/{path}")
            has_new_header = True
            continue
            
        # Fix malformed hunk headers
        if ln.startswith("@@"):
            mf = _RE_FIX_HUNK.match(ln)
            if mf:
                fixed_lines.append(f"@@ -{mf.group(1)} +{mf.group(2)} @@")
            elif _RE_VALID_HUNK.match(ln):
                fixed_lines.append(ln)
            else:
                # Try to extract valid hunk info
                parts = re.findall(r'-(\d+(?:,\d+)?)\s+\+(\d+(?:,\d+)?)', ln)
                if parts:
                    fixed_lines.append(f"@@ -{parts[0][0]} +{parts[0][1]} @@")
                else:
                    # Skip malformed hunk header
                    continue
            continue
            
        fixed_lines.append(ln)

    lines = fixed_lines

    # Check if we have hunk content
    has_hunks = any(ln.startswith("@@") or _RE_VALID_HUNK.match(ln) for ln in lines)
    has_changes = any(ln.startswith(("+", "-")) for ln in lines)
    
    if not has_hunks and not has_changes:
        return ""

    # Add missing file headers if we have hunk content
    if not (has_old_header and has_new_header) and (has_hunks or has_changes):
        header_lines = []
        if not has_old_header:
            header_lines.append(f"--- a/{TARGET}")
        if not has_new_header:
            header_lines.append(f"+++ b/{TARGET}")
        
        # Insert headers before first non-header line
        insert_pos = 0
        for i, ln in enumerate(lines):
            if not ln.startswith(("--- ", "+++ ")):
                insert_pos = i
                break
        
        lines = lines[:insert_pos] + header_lines + lines[insert_pos:]

    # Fix hunk line formatting
    lines = _fix_hunk_context(lines)

    # Keep only valid diff lines
    valid_lines = []
    for ln in lines:
        if _is_valid_diff_line(ln):
            valid_lines.append(ln)

    lines = valid_lines

    # Remove trailing empty lines
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        return ""

    # Final assembly
    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"

    # Final validation - must have both hunks and changes
    final_lines = result.splitlines()
    has_final_hunks = any(_RE_VALID_HUNK.match(ln) for ln in final_lines)
    has_final_changes = any(ln.startswith(("+", "-")) for ln in final_lines)
    
    if not (has_final_hunks and has_final_changes):
        return ""

    # Ensure proper file headers exist
    has_proper_headers = (
        any(ln.startswith(f"--- a/{TARGET}") for ln in final_lines) and
        any(ln.startswith(f"+++ b/{TARGET}") for ln in final_lines)
    )
    
    if not has_proper_headers:
        # Prepend proper headers
        content_lines = [ln for ln in final_lines if not ln.startswith(("--- ", "+++ "))]
        result = f"--- a/{TARGET}\n+++ b/{TARGET}\n" + "\n".join(content_lines)
        if not result.endswith("\n"):
            result += "\n"

    # Debug output
    preview_lines = result.splitlines()[:10]
    preview = "\n".join(preview_lines)
    if len(result.splitlines()) > 10:
        preview += "\n... (truncated)"
    
    print(f"[sanitizer] Generated patch for {TARGET}:", file=sys.stderr)
    print(f"[sanitizer] Preview:\n{preview}", file=sys.stderr)

    return result