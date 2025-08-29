"""
Robust sanitizer for OpenEvolve
--------------------------------

This module converts arbitrary LLM output into a unified diff that
applies cleanly to exactly one target file.  The default target is
``api.py``, but this can be overridden at runtime via the
``OE_TARGET_FILE`` environment variable.  Similarly, an allow‑list of
permitted files can be set via ``OE_ALLOWED_FILES`` (comma separated).

The sanitizer performs the following steps:

* Normalize Unicode and line endings.  It removes zero–width characters,
  byte order marks, non‑breaking spaces and replaces the Unicode minus
  sign with the ASCII minus.  It also converts CR/LF line endings to
  LF.
* If the text contains Markdown‑style code fences (```diff, ```patch,
  or bare ```), the largest fenced block is chosen as the candidate
  diff.  A simple scoring heuristic favours blocks tagged ``diff`` or
  ``patch`` and those containing common diff tokens (``@@``, ``---``, etc.).
* Git headers such as ``diff --git``, ``index``, ``similarity index``
  and file mode lines are stripped completely.  These confuse the
  unified diff parser used downstream.
* File names referenced in ``---``/``+++`` headers are retargeted to
  the configured target file.  If the model tries to patch ``app.py``
  or any other file not in the allow‑list, it will be rewritten to the
  target.
* Malformed hunk tails such as ``@@ -1,2 +1,3 @...`` are repaired by
  replacing the trailing ``@...`` with ``@@``.  A valid hunk header must
  look like ``@@ -start,length +start,length @@``.
* Lines inside a hunk that do not begin with ``+``, ``-`` or a space
  are coerced into context lines by prefixing a single space.  This
  prevents plain code lines from invalidating the patch.
* If the diff has hunks but is missing ``---``/``+++`` headers, they
  are injected for the target file.
* Finally, the sanitizer verifies that the resulting diff contains at
  least one hunk and at least one added or removed line.  If not, an
  empty string is returned.  An empty result signals to the caller
  that it should re‑prompt the model rather than attempt to apply the
  patch.

When a non‑empty diff is returned, a short preview (the first few
lines) is printed to standard output.  This can help debug why a
particular patch was accepted or rejected.

The functions defined here are intended to be imported directly by
OpenEvolve.  They have no dependencies outside the standard library.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Iterable, List

__all__ = ["extract_raw_patch"]

# Determine the target file and allow‑list from environment variables.
TARGET: str = (os.environ.get("OE_TARGET_FILE") or "api.py").strip() or "api.py"
_ALLOWED: set[str] = {
    x.strip() for x in (os.environ.get("OE_ALLOWED_FILES") or f"{TARGET},data_layer.py").split(",") if x.strip()
}
try:
    MAX_LINES: int = int(os.environ.get("OE_PATCH_MAX_LINES", "5000"))
except Exception:
    MAX_LINES = 5000

###############################################################################
# Helpers for Unicode and line normalization
###############################################################################
_RE_BOM = re.compile(r"^\ufeff")
_RE_ZW = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_RE_NB = re.compile(r"[\u00a0\u202f]")
_RE_UM = re.compile(r"[\u2212]")  # unicode minus

def _normalize_text(s: str) -> str:
    """Normalize Unicode and line endings.

    Converts CR/LF sequences to LF, removes BOMs and zero‑width
    characters, replaces non‑breaking spaces with regular spaces, and
    converts the Unicode minus sign to a normal hyphen.
    """
    if not s:
        return s
    # Normalise line endings
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # Strip BOM at start
    s = _RE_BOM.sub("", s)
    # Remove zero‑width characters
    s = _RE_ZW.sub("", s)
    # Replace non‑breaking spaces
    s = _RE_NB.sub(" ", s)
    # Replace Unicode minus with ASCII minus
    s = _RE_UM.sub("-", s)
    return s

###############################################################################
# Patterns for code fences and Git headers
###############################################################################
_RE_FENCE_BLOCKS = re.compile(r"```(?P<tag>\w+)?\s*(?P<body>.*?)```", re.S | re.I)
_RE_GIT_HDRS = (
    re.compile(r"^diff --git .*$", re.I),
    re.compile(r"^index [0-9a-f]+\.[0-9a-f]+(?: \d+)?$", re.I),
    re.compile(r"^(?:new|deleted) file mode \d+$", re.I),
    re.compile(r"^similarity index \d+%$", re.I),
    re.compile(r"^rename (?:from|to) .+$", re.I),
)

_RE_OLD = re.compile(r"^---\s+(.*)$")
_RE_NEW = re.compile(r"^\+\+\+\s+(.*)$")
_RE_VALID_HUNK = re.compile(r"^@@\s*-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s*@@(?:\s.*)?$")
_RE_FIX_HUNK = re.compile(r"^(@@)\s*-(\d+(?:,\d+)?)\s+\+(\d+(?:,\d+)?)\s+@.*$")

###############################################################################
# Block extraction and scoring
###############################################################################
def _choose_best_block(text: str) -> str:
    """Pick the best fenced block from the text.

    If the text contains multiple triple‑backtick blocks, this function
    chooses the one most likely to contain a diff.  Blocks tagged with
    ``diff`` or ``patch`` are preferred.  The scoring heuristic also
    counts common diff tokens such as ``---``, ``+++``, ``@@`` and the
    presence of added/removed lines.
    """
    blocks = list(_RE_FENCE_BLOCKS.finditer(text))
    if not blocks:
        return text
    scored: List[tuple[int, str]] = []
    for m in blocks:
        tag = (m.group("tag") or "").lower()
        body = m.group("body") or ""
        score = 0
        if tag in {"diff", "patch"}:
            score += 5
        # Increase score based on diff tokens
        tokens = ("--- ", "+++ ", "@@ ", "diff --git", "\n+", "\n-", "index ")
        score += sum(body.count(t) for t in tokens)
        scored.append((score, body))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]

###############################################################################
# Line manipulation helpers
###############################################################################
def _strip_git_headers(lines: Iterable[str]) -> List[str]:
    """Remove Git headers that are irrelevant to unified diffs."""
    out: List[str] = []
    for ln in lines:
        if any(p.match(ln) for p in _RE_GIT_HDRS):
            continue
        out.append(ln)
    return out

def _retarget_path(path: str) -> str:
    """Map file paths to the allowed target file.

    Removes leading ``a/`` or ``b/``.  If the path is ``app.py`` or
    another file not in the allow‑list, it becomes ``TARGET``.
    """
    path = path.strip()
    if path.startswith(("a/", "b/")):
        path = path[2:]
    if path == "app.py":
        path = TARGET
    if path not in _ALLOWED:
        path = TARGET
    return path

def _coerce_hunk_lines(lines: List[str]) -> List[str]:
    """Ensure that lines inside hunks have proper prefixes.

    In a unified diff hunk, each line must start with ``+``, ``-`` or
    `` `` (space).  Lines that do not are treated as context lines and
    prefixed with a space.  Lines outside hunks are ignored unless
    they are part of the header.
    """
    out: List[str] = []
    in_hunk = False
    for ln in lines:
        if ln.startswith("@@"):
            in_hunk = True
            out.append(ln)
            continue
        if ln.startswith(("--- a/", "+++ b/")):
            in_hunk = False
            out.append(ln)
            continue
        if in_hunk:
            if ln.startswith(("+", "-", " ")):
                out.append(ln)
            elif ln == "":
                out.append(" ")
            else:
                out.append(" " + ln)
        else:
            # Outside hunks only headers matter; drop other lines
            if ln.startswith(("--- a/", "+++ b/")):
                out.append(ln)
            # drop stray lines
    return out

def _keep_diff_line(ln: str) -> bool:
    """Determine if a line should be kept in the diff before coercion."""
    if ln.startswith(("--- a/", "+++ b/")):
        return True
    if _RE_VALID_HUNK.match(ln):
        return True
    if ln[:1] in {"+", "-", " "}:
        return True
    return False

###############################################################################
# Public API
###############################################################################
def extract_raw_patch(text: str) -> str:
    """Normalize arbitrary LLM output to a clean unified diff.

    Returns an empty string if the output cannot be converted into a
    meaningful diff.  A non‑empty return value is a unified diff that
    applies to exactly one file (``TARGET``).
    """
    if not isinstance(text, str) or not text.strip():
        return ""
    # Normalise Unicode and line endings
    text = _normalize_text(text)
    # If there are fenced code blocks, pick the one most likely to be a diff
    candidate = _choose_best_block(text)
    candidate = _normalize_text(candidate)
    # Split into lines and limit size
    lines: List[str] = [ln.rstrip("\n") for ln in candidate.split("\n")]
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
    # Remove Git headers (diff --git, index, etc.)
    lines = _strip_git_headers(lines)
    # Fix headers, hunk tails and retarget file paths
    fixed: List[str] = []
    for ln in lines:
        mo = _RE_OLD.match(ln)
        if mo:
            fixed.append(f"--- a/{_retarget_path(mo.group(1))}")
            continue
        mn = _RE_NEW.match(ln)
        if mn:
            fixed.append(f"+++ b/{_retarget_path(mn.group(1))}")
            continue
        mf = _RE_FIX_HUNK.match(ln)
        if mf:
            fixed.append(f"@@ -{mf.group(2)} +{mf.group(3)} @@")
            continue
        fixed.append(ln)
    lines = fixed
    # Keep only diff‑related lines (headers, hunks, context/add/del)
    lines = [ln for ln in lines if _keep_diff_line(ln) or ln.startswith(("--- ", "+++ ", "@@"))]
    # Inject headers if missing but hunks exist
    has_hunk = any(ln.startswith("@@") or _RE_VALID_HUNK.match(ln) for ln in lines)
    has_headers = any(ln.startswith("--- a/") for ln in lines) and any(ln.startswith("+++ b/") for ln in lines)
    if has_hunk and not has_headers:
        lines = [f"--- a/{TARGET}", f"+++ b/{TARGET}"] + lines
    # Fix any malformed hunk lines and coerce stray lines inside hunks
    norm: List[str] = []
    for ln in lines:
        if ln.startswith("@@") and not _RE_VALID_HUNK.match(ln):
            mf = _RE_FIX_HUNK.match(ln)
            if mf:
                norm.append(f"@@ -{mf.group(2)} +{mf.group(3)} @@")
                continue
        norm.append(ln)
    lines = _coerce_hunk_lines(norm)
    # Assemble and validate
    out = "\n".join(lines).strip()
    # Must contain a hunk and at least one change
    if "@@" not in out:
        return ""
    if not any(ln.startswith(('+', '-')) for ln in out.splitlines()):
        return ""
    # Force single target headers if they drifted
    if not out.startswith(f"--- a/{TARGET}\n+++ b/{TARGET}\n"):
        parts = out.split("\n", 2)
        # parts[0]: existing first line (should be ---), parts[1]: second line
        if len(parts) >= 3:
            out = f"--- a/{TARGET}\n+++ b/{TARGET}\n" + parts[2]
        else:
            out = f"--- a/{TARGET}\n+++ b/{TARGET}\n" + out
    if not out.endswith("\n"):
        out += "\n"
    # Emit a small preview
    try:
        preview = "\n".join(out.splitlines()[:12])
        print(f"[sanitizer] Generated patch for {TARGET} ({len(out)} chars)\n[sanitizer] Preview:\n{preview}", file=sys.stdout)
    except Exception:
        pass
    return out
