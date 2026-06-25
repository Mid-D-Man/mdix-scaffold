#!/usr/bin/env python3
"""
lib_patch.py — Surgical file-patch operations for mdix-scaffold.

Imported by generate_structure.py.  Do not run directly.

Op types (discriminated by the 'op' field in each patch_files[] JSON entry):

  insert_after      path, anchor, content [, match_index]
  insert_before     path, anchor, content [, match_index]
  replace_text      path, anchor, content [, match_index]
  replace_lines     path, from_line, to_line, content
  replace_range     path, from_char, to_char, content
  replace_function  path, fn_name, content
  replace_block     path, start_anchor, end_anchor, content [, keep_anchors]
  replace_regex     path, pattern, content [, flags] [, match_index]

  delete_text       path, anchor [, match_index]       — anchor is removed entirely
  delete_lines      path, from_line, to_line           — range removed entirely
  delete_function   path, fn_name                      — entire fn removed

match_index (optional, default 0)
  All anchor-based ops accept match_index to target the Nth match (0 = first).
  Without it, multiple matches warn + use first. Errors if index out of range.

replace_regex flags (optional string, default "")
  Combine: "i" = IGNORECASE, "m" = MULTILINE, "s" = DOTALL
  content may use \\1, \\2 … for capture groups.

replace_block keep_anchors (optional bool, default false)
  false: anchor lines are replaced too (inclusive replacement)
  true : anchor lines are kept, only content between them is replaced

Safety contract
  zero anchor matches  → error printed, op skipped
  multiple matches     → warn with line numbers, use match_index-th (default 0)
  out-of-bounds index  → error printed, op skipped
  bad regex pattern    → error printed, op skipped
  unbalanced braces    → error printed, op skipped
"""

from __future__ import annotations

import os
import re
import sys
from typing import List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Whitespace normalisation
# ─────────────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Anchor helpers
# ─────────────────────────────────────────────────────────────────────────────

def _anchor_lines(lines: List[str], anchor: str) -> List[int]:
    na = _norm(anchor)
    return [i for i, ln in enumerate(lines) if na in _norm(ln)]


def _resolve_anchor(
    lines:       List[str],
    anchor:      str,
    op:          str,
    path:        str,
    match_index: int = 0,
) -> Optional[int]:
    hits = _anchor_lines(lines, anchor)
    if not hits:
        print(
            f"  PATCH ERROR  {path}: [{op}] anchor not found: {anchor!r}",
            file=sys.stderr,
        )
        return None
    if match_index >= len(hits):
        nums = [h + 1 for h in hits]
        print(
            f"  PATCH ERROR  {path}: [{op}] match_index {match_index} out of range "
            f"({len(hits)} match(es) at lines {nums})",
            file=sys.stderr,
        )
        return None
    if len(hits) > 1:
        nums = [h + 1 for h in hits]
        if match_index == 0:
            print(
                f"  PATCH WARN   {path}: [{op}] anchor matches {len(hits)} lines "
                f"{nums} — using first; set match_index to target others"
            )
        else:
            print(
                f"  PATCH INFO   {path}: [{op}] match_index={match_index} "
                f"→ line {hits[match_index] + 1} of {len(hits)} matches {nums}"
            )
    return hits[match_index]


def _get_match_index(entry: dict) -> int:
    try:
        return max(0, int(entry.get("match_index", 0)))
    except (ValueError, TypeError):
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Insert ops
# ─────────────────────────────────────────────────────────────────────────────

def op_insert_after(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    anchor  = entry.get("anchor", "")
    content = entry.get("content", "")
    idx = _resolve_anchor(lines, anchor, "insert_after", path, _get_match_index(entry))
    if idx is None:
        return None
    return lines[: idx + 1] + [content] + lines[idx + 1 :]


def op_insert_before(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    anchor  = entry.get("anchor", "")
    content = entry.get("content", "")
    idx = _resolve_anchor(lines, anchor, "insert_before", path, _get_match_index(entry))
    if idx is None:
        return None
    return lines[:idx] + [content] + lines[idx:]


# ─────────────────────────────────────────────────────────────────────────────
# Replace — text
# ─────────────────────────────────────────────────────────────────────────────

def op_replace_text(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    """
    Mode 1: exact literal substring found in full file text → replace first occurrence.
    Mode 2: whitespace-normalised line match → replace the entire matching line.
    match_index applies to Mode 2 (line-level) only.
    """
    anchor      = entry.get("anchor", "")
    content     = entry.get("content", "")
    match_index = _get_match_index(entry)

    if not anchor:
        print(f"  PATCH ERROR  {path}: [replace_text] anchor is empty", file=sys.stderr)
        return None

    full_text = "".join(lines)

    # Mode 1 — exact literal (only for match_index 0)
    if match_index == 0 and anchor in full_text:
        new_text = full_text.replace(anchor, content, 1)
        return new_text.splitlines(keepends=True)

    # Mode 2 — normalised line match
    idx = _resolve_anchor(lines, anchor, "replace_text", path, match_index)
    if idx is None:
        return None
    replacement = content if content.endswith("\n") else content + "\n"
    return lines[:idx] + [replacement] + lines[idx + 1 :]


# ─────────────────────────────────────────────────────────────────────────────
# Replace — line range
# ─────────────────────────────────────────────────────────────────────────────

def op_replace_lines(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    try:
        from_line = int(entry["from_line"])
        to_line   = int(entry["to_line"])
    except (KeyError, ValueError, TypeError) as exc:
        print(
            f"  PATCH ERROR  {path}: [replace_lines] bad from_line/to_line: {exc}",
            file=sys.stderr,
        )
        return None

    content = entry.get("content", "")
    n = len(lines)

    if from_line < 1 or to_line < from_line or to_line > n:
        print(
            f"  PATCH ERROR  {path}: [replace_lines] range {from_line}..{to_line} "
            f"out of bounds (file has {n} lines)",
            file=sys.stderr,
        )
        return None

    start = from_line - 1
    end   = to_line
    replacement = [content] if content else []
    return lines[:start] + replacement + lines[end:]


# ─────────────────────────────────────────────────────────────────────────────
# Replace — char range
# ─────────────────────────────────────────────────────────────────────────────

def op_replace_range(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    try:
        from_char = int(entry["from_char"])
        to_char   = int(entry["to_char"])
    except (KeyError, ValueError, TypeError) as exc:
        print(
            f"  PATCH ERROR  {path}: [replace_range] bad from_char/to_char: {exc}",
            file=sys.stderr,
        )
        return None

    content   = entry.get("content", "")
    full_text = "".join(lines)
    n         = len(full_text)

    if from_char < 0 or to_char < from_char or to_char > n:
        print(
            f"  PATCH ERROR  {path}: [replace_range] range [{from_char}, {to_char}) "
            f"out of bounds (file is {n} chars)",
            file=sys.stderr,
        )
        return None

    new_text = full_text[:from_char] + content + full_text[to_char:]
    return new_text.splitlines(keepends=True)


# ─────────────────────────────────────────────────────────────────────────────
# Replace — between two anchors (block)
# ─────────────────────────────────────────────────────────────────────────────

def op_replace_block(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    """
    Replace everything between start_anchor and end_anchor with content.

    keep_anchors (default false):
      false — both anchor lines are consumed and replaced with content.
      true  — anchor lines are kept; only the lines strictly between them are replaced.
    """
    start_anchor  = entry.get("start_anchor", "")
    end_anchor    = entry.get("end_anchor",   "")
    content       = entry.get("content",      "")
    keep_anchors  = str(entry.get("keep_anchors", "false")).lower() == "true"

    if not start_anchor or not end_anchor:
        print(
            f"  PATCH ERROR  {path}: [replace_block] "
            f"start_anchor and end_anchor are both required",
            file=sys.stderr,
        )
        return None

    start_hits = _anchor_lines(lines, start_anchor)
    if not start_hits:
        print(
            f"  PATCH ERROR  {path}: [replace_block] start_anchor not found: {start_anchor!r}",
            file=sys.stderr,
        )
        return None
    if len(start_hits) > 1:
        nums = [h + 1 for h in start_hits]
        print(
            f"  PATCH WARN   {path}: [replace_block] start_anchor matches "
            f"{len(start_hits)} lines {nums} — using first"
        )
    start_idx = start_hits[0]

    # Search for end_anchor only AFTER start_idx
    end_hits = [i for i in _anchor_lines(lines, end_anchor) if i > start_idx]
    if not end_hits:
        print(
            f"  PATCH ERROR  {path}: [replace_block] end_anchor not found "
            f"after line {start_idx + 1}: {end_anchor!r}",
            file=sys.stderr,
        )
        return None
    end_idx = end_hits[0]

    replacement = [content] if content else []

    if keep_anchors:
        # Keep anchor lines, replace only what's strictly between them
        return (
            lines[:start_idx + 1]
            + replacement
            + lines[end_idx:]
        )
    else:
        # Consume anchor lines too
        return lines[:start_idx] + replacement + lines[end_idx + 1:]


# ─────────────────────────────────────────────────────────────────────────────
# Replace — regex
# ─────────────────────────────────────────────────────────────────────────────

def op_replace_regex(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    """
    Replace the match_index-th occurrence of a regex pattern with content.

    pattern   — Python re pattern string
    content   — replacement string; may use \\1, \\2 … for capture groups
    flags     — optional string of flag chars: i=IGNORECASE, m=MULTILINE, s=DOTALL
    match_index — 0-indexed occurrence to replace (default 0 = first)
    """
    pattern     = entry.get("pattern", "")
    content     = entry.get("content", "")
    flags_str   = entry.get("flags",   "")
    match_index = _get_match_index(entry)

    if not pattern:
        print(f"  PATCH ERROR  {path}: [replace_regex] pattern is empty", file=sys.stderr)
        return None

    flags = 0
    for ch in flags_str:
        if ch == 'i': flags |= re.IGNORECASE
        elif ch == 'm': flags |= re.MULTILINE
        elif ch == 's': flags |= re.DOTALL
        else:
            print(
                f"  PATCH WARN   {path}: [replace_regex] unknown flag {ch!r} ignored "
                f"(valid: i, m, s)"
            )

    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        print(
            f"  PATCH ERROR  {path}: [replace_regex] invalid pattern {pattern!r}: {exc}",
            file=sys.stderr,
        )
        return None

    full_text = "".join(lines)
    all_matches = list(compiled.finditer(full_text))

    if not all_matches:
        print(
            f"  PATCH ERROR  {path}: [replace_regex] no matches for {pattern!r}",
            file=sys.stderr,
        )
        return None

    if match_index >= len(all_matches):
        print(
            f"  PATCH ERROR  {path}: [replace_regex] match_index {match_index} "
            f"out of range ({len(all_matches)} match(es))",
            file=sys.stderr,
        )
        return None

    if len(all_matches) > 1 and match_index == 0:
        print(
            f"  PATCH WARN   {path}: [replace_regex] {len(all_matches)} matches "
            f"— using first; set match_index to target others"
        )

    m = all_matches[match_index]
    try:
        replacement_text = m.expand(content)
    except re.error as exc:
        print(
            f"  PATCH ERROR  {path}: [replace_regex] bad replacement string "
            f"{content!r}: {exc}",
            file=sys.stderr,
        )
        return None

    new_text = full_text[: m.start()] + replacement_text + full_text[m.end() :]
    return new_text.splitlines(keepends=True)


# ─────────────────────────────────────────────────────────────────────────────
# Replace — function (brace-balanced / Python indent)
# ─────────────────────────────────────────────────────────────────────────────

def op_replace_function(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    fn_name = entry.get("fn_name", "")
    content = entry.get("content", "")

    if not fn_name:
        print(f"  PATCH ERROR  {path}: [replace_function] fn_name is empty", file=sys.stderr)
        return None

    ext = os.path.splitext(path)[1].lower()
    if ext == ".py":
        return _replace_python_fn(lines, fn_name, content, path)
    return _replace_brace_fn(lines, fn_name, content, path)


def _replace_brace_fn(
    lines: List[str], fn_name: str, content: str, path: str
) -> Optional[List[str]]:
    pattern = re.compile(r'\b' + re.escape(fn_name) + r'\s*[\(<]')
    decl_idx: Optional[int] = None
    for i, line in enumerate(lines):
        if pattern.search(line):
            decl_idx = i
            break
    if decl_idx is None:
        print(
            f"  PATCH ERROR  {path}: [replace_function] '{fn_name}' not found",
            file=sys.stderr,
        )
        return None

    full_text    = "".join(lines)
    char_offset  = sum(len(l) for l in lines[:decl_idx])
    text_segment = full_text[char_offset:]

    open_pos = text_segment.find('{')
    if open_pos == -1:
        print(
            f"  PATCH ERROR  {path}: [replace_function] no '{{' found "
            f"for '{fn_name}' after line {decl_idx + 1}",
            file=sys.stderr,
        )
        return None

    close_pos = _balance_braces(text_segment, open_pos, path, fn_name)
    if close_pos == -1:
        return None

    abs_close = char_offset + close_pos
    cumulative = 0
    end_idx = len(lines) - 1
    for i, ln in enumerate(lines):
        cumulative += len(ln)
        if cumulative > abs_close:
            end_idx = i
            break

    replacement = [content] if content else []
    return lines[:decl_idx] + replacement + lines[end_idx + 1 :]


def _balance_braces(text: str, open_pos: int, path: str, fn_name: str) -> int:
    depth = 0
    i     = open_pos
    in_dbl = in_sgl = in_line = in_blk = False

    while i < len(text):
        c = text[i]
        if in_blk:
            if c == '*' and i + 1 < len(text) and text[i + 1] == '/':
                in_blk = False; i += 2
            else:
                i += 1
            continue
        if in_line:
            if c == '\n': in_line = False
            i += 1; continue
        if in_dbl:
            if c == '\\': i += 2; continue
            if c == '"': in_dbl = False
            i += 1; continue
        if in_sgl:
            if c == '\\': i += 2; continue
            if c == '\'': in_sgl = False
            i += 1; continue
        if c == '/' and i + 1 < len(text):
            if text[i + 1] == '/': in_line = True; i += 2; continue
            if text[i + 1] == '*': in_blk  = True; i += 2; continue
        if c == '"':  in_dbl = True; i += 1; continue
        if c == '\'': in_sgl = True; i += 1; continue
        if c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1

    print(
        f"  PATCH ERROR  {path}: [replace_function] unbalanced braces for '{fn_name}'",
        file=sys.stderr,
    )
    return -1


def _replace_python_fn(
    lines: List[str], fn_name: str, content: str, path: str
) -> Optional[List[str]]:
    def_pat = re.compile(r'^(\s*)def\s+' + re.escape(fn_name) + r'\s*\(')
    start_idx: Optional[int] = None
    base_indent = ""
    for i, ln in enumerate(lines):
        m = def_pat.match(ln)
        if m:
            start_idx = i
            base_indent = m.group(1)
            break
    if start_idx is None:
        print(
            f"  PATCH ERROR  {path}: [replace_function] 'def {fn_name}' not found",
            file=sys.stderr,
        )
        return None
    end_idx = start_idx + 1
    while end_idx < len(lines):
        raw     = lines[end_idx]
        stripped = raw.rstrip('\n\r')
        if not stripped:
            end_idx += 1; continue
        indent = len(stripped) - len(stripped.lstrip())
        if indent <= len(base_indent) and stripped.lstrip():
            break
        end_idx += 1
    replacement = [content] if content else []
    return lines[:start_idx] + replacement + lines[end_idx:]


# ─────────────────────────────────────────────────────────────────────────────
# Delete ops (wrappers that set content = "")
# ─────────────────────────────────────────────────────────────────────────────

def op_delete_text(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    return op_replace_text(lines, dict(entry, content=""), path)


def op_delete_lines(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    return op_replace_lines(lines, dict(entry, content=""), path)


def op_delete_function(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    return op_replace_function(lines, dict(entry, content=""), path)


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch table
# ─────────────────────────────────────────────────────────────────────────────

_OPS = {
    "insert_after":     op_insert_after,
    "insert_before":    op_insert_before,
    "replace_text":     op_replace_text,
    "replace_lines":    op_replace_lines,
    "replace_range":    op_replace_range,
    "replace_function": op_replace_function,
    "replace_block":    op_replace_block,
    "replace_regex":    op_replace_regex,
    "delete_text":      op_delete_text,
    "delete_lines":     op_delete_lines,
    "delete_function":  op_delete_function,
}

VALID_OPS = sorted(_OPS)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def apply_patch(path: str, entry: dict, dry_run: bool = False) -> bool:
    """
    Apply a single patch operation described by `entry` to the file at `path`.
    Returns True on success, False on failure (error already printed to stderr).
    In dry-run mode reads + validates but writes nothing.
    """
    op_type = entry.get("op", "").strip()
    if op_type not in _OPS:
        print(
            f"  PATCH ERROR  {path}: unknown op {op_type!r}. Valid: {VALID_OPS}",
            file=sys.stderr,
        )
        return False

    if not os.path.exists(path):
        print(f"  PATCH ERROR  {path}: file not found", file=sys.stderr)
        return False

    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        print(f"  PATCH ERROR  {path}: cannot read — {exc}", file=sys.stderr)
        return False

    new_lines = _OPS[op_type](lines, entry, path)
    if new_lines is None:
        return False

    if not dry_run:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.writelines(new_lines)
        except OSError as exc:
            print(f"  PATCH ERROR  {path}: cannot write — {exc}", file=sys.stderr)
            return False

    return True
