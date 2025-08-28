
# openevolve/utils/diff_parser.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple
import re

@dataclass
class DiffBlock:
    search: Optional[str]
    replace: str
    filepath: Optional[str] = None
    format: str = "auto"  # "search_replace" | "conflict" | "unified" | "auto"

# --- Utilities
_CODEBLOCK_RE = re.compile(r"```(?P<lang>[^\n`]*)\n(?P<body>.*?)```", re.DOTALL)
_UNIFIED_HEADER = re.compile(r"^---\s+a/(?P<a>.+)\n\+\+\+\s+b/(?P<b>.+)\n", re.MULTILINE)
_HUNK_START = re.compile(r"^@@", re.MULTILINE)

def _extract_code_blocks(text: str) -> List[Tuple[str,str]]:
    blocks: List[Tuple[str,str]] = []
    for m in _CODEBLOCK_RE.finditer(text):
        lang = (m.group('lang') or '').strip().lower()
        body = m.group('body')
        blocks.append((lang, body))
    return blocks

def _parse_search_replace_block(body: str) -> Optional[DiffBlock]:
    # support optional "file=path" on replace fence header already removed
    # Expect two fences already: handled externally. Here `body` contains full block including markers?
    return None  # handled in high-level parser

def _parse_conflict_style(text: str) -> List[DiffBlock]:
    out: List[DiffBlock] = []
    pat = re.compile(
        r"<<<<<<<\s*SEARCH\n(?P<search>.*?)\n=======\n(?P<replace>.*?)\n>>>>>>>\s*REPLACE(?:\s*file=(?P<file>[^\n]+))?",
        re.DOTALL
    )
    for m in pat.finditer(text):
        out.append(DiffBlock(search=m.group('search'), replace=m.group('replace'), filepath=m.group('file'), format="conflict"))
    return out

def _parse_unified_blocks(lang: str, body: str) -> List[DiffBlock]:
    if "diff" not in lang:
        return []
    # If headers present, try to capture file path from them. For each @@ hunk, create a single replace of full body.
    # For simplicity, we convert unified diff to a naive SEARCH/REPLACE by removing '-' lines and keeping '+'/context.
    # This is crude but works well when diff applies to full file content.
    # If multiple files in one block, split.
    res: List[DiffBlock] = []
    segments = re.split(r"(?m)^---\s+a/", body)
    if len(segments) == 1:
        # single, maybe still a valid unified diff
        m = _UNIFIED_HEADER.search(body)
        if not m:
            return []
        file_path = m.group('b')
        clean_lines = []
        for ln in body.splitlines():
            if ln.startswith('+++') or ln.startswith('---') or ln.startswith('@@'):
                continue
            if ln.startswith('+'):
                clean_lines.append(ln[1:])
            elif ln.startswith('-'):
                # drop removed line from replacement, search is not specified
                continue
            else:
                clean_lines.append(ln[0:] if ln else "")
        replacement = "\n".join(clean_lines).rstrip() + "\n"
        res.append(DiffBlock(search=None, replace=replacement, filepath=file_path, format="unified"))
        return res
    # multiple file segments
    for seg in segments:
        if not seg.strip():
            continue
        hdr = "a/" + seg  # restore split artifact
        m = _UNIFIED_HEADER.match("--- a/" + seg)
        if not m:
            continue
        file_path = m.group('b')
        clean_lines = []
        for ln in hdr.splitlines():
            if ln.startswith('+++') or ln.startswith('---') or ln.startswith('@@'):
                continue
            if ln.startswith('+'):
                clean_lines.append(ln[1:])
            elif ln.startswith('-'):
                continue
            else:
                # skip header artifacts
                if ln.startswith('a/') or ln.startswith('b/'):
                    continue
                clean_lines.append(ln)
        if clean_lines:
            res.append(DiffBlock(search=None, replace="\n".join(clean_lines).rstrip() + "\n", filepath=file_path, format="unified"))
    return res

def extract_diffs_from_response(text: str) -> List[DiffBlock]:
    diffs: List[DiffBlock] = []
    # 1) conflict-style inline blocks
    diffs.extend(_parse_conflict_style(text))

    # 2) SEARCH/REPLACE paired code fences
    #    ```search\n...``` then ```replace file=path\n...```
    code_blocks = _extract_code_blocks(text)
    # map search blocks to following replace block
    i = 0
    while i < len(code_blocks):
        lang, body = code_blocks[i]
        if lang.strip().lower() == "search":
            search_body = body
            file_path = None
            replace_body = None
            if i + 1 < len(code_blocks) and code_blocks[i+1][0].startswith("replace"):
                # extract optional file= param
                hdr = code_blocks[i+1][0]
                m = re.search(r"file\s*=\s*([^\s]+)", hdr)
                if m:
                    file_path = m.group(1).strip()
                replace_body = code_blocks[i+1][1]
                diffs.append(DiffBlock(search=search_body, replace=replace_body, filepath=file_path, format="search_replace"))
                i += 2
                continue
        i += 1

    # 3) Unified ` ```diff ` blocks
    for lang, body in code_blocks:
        if "diff" in lang:
            diffs.extend(_parse_unified_blocks(lang, body))

    # 4) Fallback: single Python/JS fenced block titled PATCH..., treat as full-file replacement
    for lang, body in code_blocks:
        if lang in ("python","py","javascript","js","ts","tsx"):
            m = re.search(r"^#\s*FILE:\s*(?P<fp>\S+)", body, re.MULTILINE)
            if m:
                diffs.append(DiffBlock(search=None, replace=body, filepath=m.group('fp'), format="fullfile"))
    return diffs
