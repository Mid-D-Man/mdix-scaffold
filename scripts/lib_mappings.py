#!/usr/bin/env python3
"""
Mappings support for mdix-scaffold.

A mappings file is a YAML file with a flat or nested key→value structure.
In template content strings, [[key]] placeholders are replaced with their
mapped values. Nested keys are accessed with dots: [[section.key]]

Example mappings.yaml:
  author: "Abdulhamid"
  org: "MidManStudio"
  ci:
    node_version: "20"
    python_version: "3.12"

In a template content string:
  "# Built by [[author]] at [[org]]"
  "node-version: [[ci.node_version]]"
"""

import json
import os
import re
import sys


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_mappings(path: str) -> dict:
    """Load a YAML or JSON mappings file. Returns a flat dot-keyed dict."""
    if not os.path.exists(path):
        print(f"ERROR: Mappings file not found: '{path}'", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        text = f.read()

    # Try JSON first (no extra deps), then YAML via stdlib workaround
    if path.endswith(".json"):
        raw = json.loads(text)
    else:
        # YAML — use stdlib tomllib if .toml, otherwise attempt json-like parse
        # For proper YAML support we use a small built-in parser for the
        # simple key: value format that mappings files typically use.
        raw = _parse_simple_yaml(text)

    return _flatten(raw)


def _parse_simple_yaml(text: str) -> dict:
    """
    Parse a simple YAML subset: key: value and nested blocks.
    Handles strings, numbers, booleans. No lists, no anchors.
    Falls back to a best-effort parse — complex YAML should use .json.
    """
    try:
        # If PyYAML is available, use it
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        pass

    # Manual simple parser for key: value and indented blocks
    result: dict = {}
    stack: list = [result]
    indent_stack: list = [-1]
    current: dict = result

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        # Pop stack when indent decreases
        while len(indent_stack) > 1 and indent <= indent_stack[-1]:
            stack.pop()
            indent_stack.pop()
        current = stack[-1]

        stripped = line.strip()
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "" or val is None:
                # Nested block
                new_dict: dict = {}
                current[key] = new_dict
                stack.append(new_dict)
                indent_stack.append(indent)
            else:
                current[key] = _coerce(val)

    return result


def _coerce(v: str):
    """Coerce a string value to int, float, bool, or strip quotes."""
    if v.lower() == "true":  return True
    if v.lower() == "false": return False
    if v.lower() in ("null", "~", "none"): return None
    # Strip surrounding quotes
    if (v.startswith('"') and v.endswith('"')) or \
       (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    try: return int(v)
    except ValueError: pass
    try: return float(v)
    except ValueError: pass
    return v


def _flatten(d: dict, prefix: str = "") -> dict:
    """Flatten a nested dict to dot-keyed entries."""
    out: dict = {}
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, full_key))
        elif v is not None:
            out[full_key] = str(v)
    return out


# ---------------------------------------------------------------------------
# Substitute
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\[\[([a-zA-Z0-9_.\-]+)\]\]")


def apply_mappings(content: str, mappings: dict) -> str:
    """
    Replace [[key]] placeholders in content with values from mappings.
    Unknown keys are left as-is with a warning.
    """
    if not mappings or not content:
        return content

    def replacer(m: re.Match) -> str:
        key = m.group(1)
        if key in mappings:
            return mappings[key]
        # Leave unknown placeholders untouched — don't silently break content
        return m.group(0)

    return _PLACEHOLDER_RE.sub(replacer, content)


def list_placeholders(content: str) -> list:
    """Return all [[key]] placeholder names found in content."""
    return list(dict.fromkeys(m.group(1) for m in _PLACEHOLDER_RE.finditer(content)))
