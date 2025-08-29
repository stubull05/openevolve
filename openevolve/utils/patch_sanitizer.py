# openevolve/utils/patch_sanitizer.py
"""
Robust sanitizer: converts model output to a valid unified diff for ONE target file.

This version specifically handles the common case where models generate patches for
'app.py' but the target file is 'api.py', and ensures proper diff format.
"""

from __future__ import annotations
import os, re, sys
from typing import List

TARGET = (os.environ.get("OE_TARGET_FILE") or "api.py").strip() or "api.py"
_ALLOWED = {
    x for x in (os.environ.get("OE_ALLOWED_FILES") or f"{TARGET},data_layer.py")
    .replace(" ", "").split(",") if x
}
try:
    MAX_LINES = int(os.environ.get("OE_PATCH_MAX_LINES", "5000"))
except Exception:
    MAX_LINES = 5000

def _normalize_text(s: str) -> str:
    """Normalize unicode and line endings"""
    if not s:
        return s
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # Remove BOM and zero-width chars
    s = re.sub(r"[\ufeff\u200b\u200c\u200d\u2060]", "", s)
    # Replace unicode spaces and minus
    s = re.sub(r"[\u00a0\u202f]", " ", s)
    s = re.sub(r"[\u2212]", "-", s)
    return s

def _extract_from_fences(text: str) -> str:
    """Extract diff content from markdown code fences"""
    # Look for ```diff, ```patch, or plain ``` blocks
    patterns = [
        r"```(?:diff|patch)\s*\n(.*?)```",
        r"```\s*\n(.*?)```"
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        if matches:
            # Return the largest match (likely the main diff)
            return max(matches, key=len)
    
    return text

def _remove_git_headers(lines: List[str]) -> List[str]:
    """Remove git headers that confuse patch application"""
    git_patterns = [
        r"^diff --git ",
        r"^index [0-9a-f]+\.\.[0-9a-f]+",
        r"^(?:new|deleted) file mode ",
        r"^similarity index ",
        r"^rename (?:from|to) "
    ]
    
    filtered = []
    for line in lines:
        if not any(re.match(pattern, line, re.IGNORECASE) for pattern in git_patterns):
            filtered.append(line)
    
    return filtered

def _retarget_filename(path: str) -> str:
    """Map file paths to the target file"""
    path = path.strip()
    
    # Remove a/ or b/ prefixes
    if path.startswith(("a/", "b/")):
        path = path[2:]
    
    # Common model hallucinations -> map to target
    common_names = ["app.py", "main.py", "server.py", "application.py"]
    if path in common_names:
        return TARGET
    
    # Only allow files in the allowed list
    if path not in _ALLOWED:
        return TARGET
    
    return path

def _fix_file_headers(lines: List[str]) -> List[str]:
    """Fix and normalize file headers"""
    fixed = []
    
    for line in lines:
        if line.startswith("--- "):
            # Extract path and retarget it
            path = _retarget_filename(line[4:])
            fixed.append(f"--- a/{path}")
        elif line.startswith("+++ "):
            # Extract path and retarget it  
            path = _retarget_filename(line[4:])
            fixed.append(f"+++ b/{path}")
        else:
            fixed.append(line)
    
    return fixed

def _fix_hunk_headers(lines: List[str]) -> List[str]:
    """Fix malformed hunk headers"""
    fixed = []
    
    for line in lines:
        if line.startswith("@@"):
            # Check if it's already valid
            if re.match(r"^@@\s*-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s*@@", line):
                fixed.append(line)
            else:
                # Try to extract numbers and fix
                numbers = re.findall(r'-(\d+(?:,\d+)?)\s+\+(\d+(?:,\d+)?)', line)
                if numbers:
                    fixed.append(f"@@ -{numbers[0][0]} +{numbers[0][1]} @@")
                # Skip if can't fix
        else:
            fixed.append(line)
    
    return fixed

def _ensure_proper_headers(lines: List[str]) -> List[str]:
    """Ensure the patch has proper file headers"""
    has_old_header = any(line.startswith(f"--- a/{TARGET}") for line in lines)
    has_new_header = any(line.startswith(f"+++ b/{TARGET}") for line in lines)
    has_hunks = any(line.startswith("@@") for line in lines)
    
    if has_hunks and not (has_old_header and has_new_header):
        # Find where to insert headers (before first hunk or at start)
        insert_pos = 0
        for i, line in enumerate(lines):
            if line.startswith("@@"):
                insert_pos = i
                break
        
        headers = []
        if not has_old_header:
            headers.append(f"--- a/{TARGET}")
        if not has_new_header:
            headers.append(f"+++ b/{TARGET}")
        
        lines = lines[:insert_pos] + headers + lines[insert_pos:]
    
    return lines

def _validate_hunk_content(lines: List[str]) -> List[str]:
    """Ensure hunk lines have proper prefixes"""
    validated = []
    in_hunk = False
    
    for line in lines:
        if line.startswith(("--- a/", "+++ b/")):
            in_hunk = False
            validated.append(line)
        elif line.startswith("@@"):
            in_hunk = True
            validated.append(line)
        elif in_hunk:
            # Must start with +, -, or space
            if line.startswith(("+", "-", " ")):
                validated.append(line)
            elif not line.strip():
                # Empty line becomes context
                validated.append(" ")
            else:
                # Add space prefix for context
                validated.append(" " + line)
        else:
            # Outside hunk, only keep diff-related lines
            if line.startswith(("--- ", "+++ ", "@@")):
                validated.append(line)
    
    return validated

def extract_raw_patch(text: str) -> str:
    """
    Main entry point called by OpenEvolve to sanitize patches.
    Returns clean unified diff or empty string if unusable.
    """
    if not isinstance(text, str) or not text.strip():
        print("[sanitizer] Empty input text", file=sys.stderr)
        return ""

    # Normalize the text
    text = _normalize_text(text)
    
    # Extract from code fences if present
    text = _extract_from_fences(text)
    
    # Split into lines
    lines = [line.rstrip() for line in text.splitlines()]
    
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
    
    if not lines:
        print("[sanitizer] No lines to process", file=sys.stderr)
        return ""
    
    # Apply fixes in order
    lines = _remove_git_headers(lines)
    lines = _fix_file_headers(lines)
    lines = _fix_hunk_headers(lines)
    lines = _ensure_proper_headers(lines)
    lines = _validate_hunk_content(lines)
    
    # Final validation
    has_hunks = any(line.startswith("@@") for line in lines)
    has_changes = any(line.startswith(("+", "-")) for line in lines)
    
    if not (has_hunks and has_changes):
        print(f"[sanitizer] Invalid patch: hunks={has_hunks}, changes={has_changes}", file=sys.stderr)
        return ""
    
    # Assemble result
    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    
    # Debug output
    print(f"[sanitizer] Generated patch for {TARGET} ({len(result)} chars)", file=sys.stderr)
    preview_lines = result.splitlines()[:8]
    preview = "\n".join(preview_lines)
    print(f"[sanitizer] Preview:\n{preview}", file=sys.stderr)
    
    return result