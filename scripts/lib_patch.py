#!/usr/bin/env python3
"""
lib_patch.py — Surgical file-patch operations for mdix-scaffold.

Imported by generate_structure.py.  Do not run directly.

Op types (discriminated by the 'op' field in each patch_files[] JSON entry):

  insert_after      path, anchor, content
      Insert `content` immediately AFTER the first line containing `anchor`.
      Anchor matching is whitespace-normalised (safe against indentation drift).

  insert_before     path, anchor, content
      Insert `content` immediately BEFORE the first line containing `anchor`.

  replace_text      path, anchor, content
      Two-mode replacement:
        Mode 1 — exact literal substring found in the file → replace first occurrence.
        Mode 2 — whitespace-normalised match against individual lines →
                  replace the entire matching line with `content`.
      Falls through to Mode 2 only when Mode 1 finds nothing.

  replace_lines     path, from_line, to_line, content
      Replace lines from_line..to_line (1-indexed, inclusive) with `content`.
      `content` may contain embedded newlines for multi-line replacement.

  replace_range     path, from_char, to_char, content
      Replace characters [from_char, to_char) (0-indexed, exclusive end)
      with `content`.  Strict bounds check — errors if out of range.

  replace_function  path, fn_name, content
      Locate the first function/method named `fn_name`:
        - Curly-brace languages (Rust, C, C++, Java, JS/TS, Go, C#):
            brace-balanced scan from the declaration line.
        - Python: indentation-based scan from the `def` line.
      Replaces the entire definition (signature + body) with `content`.

Safety contract
───────────────
  • Zero anchor matches       → error printed, op skipped, False returned.
  • Multiple anchor matches   → warning with all line numbers printed,
                                 first match used.
  • Out-of-bounds line/char   → error printed, op skipped.
  • Unbalanced braces         → error printed, op skipped.
  • Content strings should include trailing newlines where needed;
    the patcher does not inject newlines automatically.
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
    """Collapse whitespace runs to a single space and strip."""
    return re.sub(r'\s+', ' ', s).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Anchor helpers
# ─────────────────────────────────────────────────────────────────────────────

def _anchor_lines(lines: List[str], anchor: str) -> List[int]:
    """Return 0-indexed line indices where the normalised anchor appears."""
    na = _norm(anchor)
    return [i for i, ln in enumerate(lines) if na in _norm(ln)]


def _resolve_anchor(
    lines: List[str],
    anchor: str,
    op: str,
    path: str,
) -> Optional[int]:
    """
    Find a unique anchor line.
    Errors on zero matches; warns and returns first index on multiple matches.
    Returns 0-indexed line index or None on failure.
    """
    hits = _anchor_lines(lines, anchor)
    if not hits:
        print(
            f"  PATCH ERROR  {path}: [{op}] anchor not found: {anchor!r}",
            file=sys.stderr,
        )
        return None
    if len(hits) > 1:
        nums = [h + 1 for h in hits]
        print(
            f"  PATCH WARN   {path}: [{op}] anchor matches {len(hits)} lines "
            f"{nums} — applying to first (line {nums[0]})"
        )
    return hits[0]


# ─────────────────────────────────────────────────────────────────────────────
# Op implementations
# ─────────────────────────────────────────────────────────────────────────────

def op_insert_after(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    anchor  = entry.get("anchor", "")
    content = entry.get("content", "")
    idx = _resolve_anchor(lines, anchor, "insert_after", path)
    if idx is None:
        return None
    return lines[: idx + 1] + [content] + lines[idx + 1 :]


def op_insert_before(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    anchor  = entry.get("anchor", "")
    content = entry.get("content", "")
    idx = _resolve_anchor(lines, anchor, "insert_before", path)
    if idx is None:
        return None
    return lines[:idx] + [content] + lines[idx:]


def op_replace_text(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    """
    Mode 1: exact literal substring in full file text → replace first occurrence.
    Mode 2: whitespace-normalised line match → replace whole matching line.
    """
    anchor  = entry.get("anchor", "")
    content = entry.get("content", "")

    if not anchor:
        print(f"  PATCH ERROR  {path}: [replace_text] anchor is empty", file=sys.stderr)
        return None

    full_text = "".join(lines)

    # ── Mode 1: exact literal match ───────────────────────────────────────────
    if anchor in full_text:
        new_text = full_text.replace(anchor, content, 1)
        return new_text.splitlines(keepends=True)

    # ── Mode 2: normalised line-level match ───────────────────────────────────
    hits = _anchor_lines(lines, anchor)
    if not hits:
        print(
            f"  PATCH ERROR  {path}: [replace_text] anchor not found "
            f"(tried exact and whitespace-normalised): {anchor!r}",
            file=sys.stderr,
        )
        return None
    if len(hits) > 1:
        nums = [h + 1 for h in hits]
        print(
            f"  PATCH WARN   {path}: [replace_text] normalised anchor matches "
            f"{len(hits)} lines {nums} — replacing first (line {nums[0]})"
        )
    idx = hits[0]
    replacement = content if content.endswith("\n") else content + "\n"
    return lines[:idx] + [replacement] + lines[idx + 1 :]


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

    # Convert 1-indexed inclusive → 0-indexed Python slice
    start = from_line - 1
    end   = to_line        # exclusive

    replacement = [content] if content else []
    return lines[:start] + replacement + lines[end:]


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


def op_replace_function(lines: List[str], entry: dict, path: str) -> Optional[List[str]]:
    """
    Locate a function by name and replace its entire definition.

    Curly-brace languages: finds declaration line → scans for opening '{' →
    brace-balances to closing '}', respecting strings and // /* */ comments.

    Python (.py): indentation-based heuristic — finds 'def fn_name(' →
    captures until next line at same or lower indentation level.
    """
    fn_name = entry.get("fn_name", "")
    content = entry.get("content", "")

    if not fn_name:
        print(f"  PATCH ERROR  {path}: [replace_function] fn_name is empty", file=sys.stderr)
        return None

    ext = os.path.splitext(path)[1].lower()

    if ext == ".py":
        return _replace_python_fn(lines, fn_name, content, path)

    return _replace_brace_fn(lines, fn_name, content, path)


# ── Brace-balanced function replacement ──────────────────────────────────────

def _replace_brace_fn(
    lines: List[str], fn_name: str, content: str, path: str
) -> Optional[List[str]]:
    """Curly-brace language function replacement via brace balancing."""
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

    full_text  = "".join(lines)
    char_offset = sum(len(l) for l in lines[:decl_idx])
    text_from_decl = full_text[char_offset:]

    open_pos = text_from_decl.find('{')
    if open_pos == -1:
        print(
            f"  PATCH ERROR  {path}: [replace_function] no opening '{{' found "
            f"for '{fn_name}' after line {decl_idx + 1}",
            file=sys.stderr,
        )
        return None

    close_pos = _balance_braces(text_from_decl, open_pos, path, fn_name)
    if close_pos == -1:
        return None

    abs_close = char_offset + close_pos

    # Find the line index containing the closing brace
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
    """
    Starting at open_pos (which must be '{'), scan forward balancing braces.
    Skips string literals and // / /* */ comments.
    Returns the index of the matching '}' or -1 on failure.
    """
    depth           = 0
    i               = open_pos
    in_dbl          = False
    in_sgl          = False
    in_line_comment = False
    in_blk_comment  = False

    while i < len(text):
        c = text[i]

        if in_blk_comment:
            if c == '*' and i + 1 < len(text) and text[i + 1] == '/':
                in_blk_comment = False
                i += 2
            else:
                i += 1
            continue

        if in_line_comment:
            if c == '\n':
                in_line_comment = False
            i += 1
            continue

        if in_dbl:
            if c == '\\':
                i += 2
                continue
            if c == '"':
                in_dbl = False
            i += 1
            continue

        if in_sgl:
            if c == '\\':
                i += 2
                continue
            if c == '\'':
                in_sgl = False
            i += 1
            continue

        # Start of comments
        if c == '/' and i + 1 < len(text):
            if text[i + 1] == '/':
                in_line_comment = True
                i += 2
                continue
            if text[i + 1] == '*':
                in_blk_comment = True
                i += 2
                continue

        # Start of strings
        if c == '"':
            in_dbl = True
            i += 1
            continue
        if c == '\'':
            in_sgl = True
            i += 1
            continue

        # Brace tracking
        if c == '{':
            depth += 1
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


# ── Python indentation heuristic ─────────────────────────────────────────────

def _replace_python_fn(
    lines: List[str], fn_name: str, content: str, path: str
) -> Optional[List[str]]:
    """Indentation-aware Python function replacement."""
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
        raw = lines[end_idx]
        stripped = raw.rstrip('\n\r')
        if stripped == "":          # blank lines belong to the body
            end_idx += 1
            continue
        indent = len(stripped) - len(stripped.lstrip())
        if indent <= len(base_indent) and stripped.lstrip():
            break                   # back at same/outer scope
        end_idx += 1

    replacement = [content] if content else []
    return lines[:start_idx] + replacement + lines[end_idx:]


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
}

VALID_OPS = sorted(_OPS)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def apply_patch(path: str, entry: dict, dry_run: bool = False) -> bool:
    """
    Apply a single patch operation described by `entry` to the file at `path`.

    Returns True on success, False on failure (error already printed to stderr).
    In dry-run mode, reads the file and validates the operation but writes nothing.
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
        return False  # error already printed by the op function

    if not dry_run:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.writelines(new_lines)
        except OSError as exc:
            print(f"  PATCH ERROR  {path}: cannot write — {exc}", file=sys.stderr)
            return False

    return True
