#!/usr/bin/env python3
"""
Mappings support for mdix-scaffold.

A mappings file is a .mdix file (preferred) or .json file.
In template content strings, [[key]] placeholders are replaced with values.
Nested DixScript table properties are accessed with dots: [[ci.node_version]]

Example .mdix mappings file:
  @DATA(
    author       = "Abdulhamid"
    org: name = "MidManStudio", url = "https://mid-d-man.github.io"
  )

In template content:
  "# Built by [[author]] at [[org.name]]"
  "node-version: [[ci.node_version]]"
"""

import json
import os
import re
import subprocess
import sys
import tempfile


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_mappings(path: str) -> dict:
    """
    Load a .mdix or .json mappings file.
    Returns a flat dot-keyed dict of string values.
    """
    if not os.path.exists(path):
        print(f"ERROR: Mappings file not found: '{path}'", file=sys.stderr)
        sys.exit(1)

    if path.endswith(".mdix"):
        return _load_mdix(path)
    elif path.endswith(".json"):
        with open(path) as f:
            raw = json.load(f)
        return _flatten(raw)
    else:
        print(
            f"ERROR: Unsupported mappings format: '{path}'.\n"
            "Use a .mdix file (recommended) or .json.",
            file=sys.stderr,
        )
        sys.exit(1)


def _load_mdix(mdix_path: str) -> dict:
    """
    Convert a .mdix mappings file to JSON using the mdix CLI,
    then load and flatten the result.
    """
    # Find mdix binary
    mdix_bin = _find_mdix()
    if mdix_bin is None:
        print(
            "ERROR: 'mdix' CLI not found — required to load .mdix mappings.\n"
            "Run 'mdix-scaffold setup' to install it.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Write to a temp JSON file
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [mdix_bin, "convert", mdix_path, "--to", "json", "-o", tmp_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(
                f"ERROR: Failed to convert mappings file '{mdix_path}':\n"
                f"{result.stderr.strip()}",
                file=sys.stderr,
            )
            sys.exit(1)

        with open(tmp_path) as f:
            raw = json.load(f)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return _flatten(raw)


def _find_mdix() -> str | None:
    """Return path to the mdix binary, or None if not found."""
    # Check PATH
    result = subprocess.run(
        ["mdix", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return "mdix"

    # Check local bin/mdix (sibling of scripts/)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(script_dir, "..", "bin", "mdix")
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return os.path.abspath(local)

    return None


def _flatten(d: dict, prefix: str = "") -> dict:
    """Flatten a nested dict to dot-keyed string entries."""
    out: dict = {}
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else str(k)
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
    Unknown keys are left unchanged.
    """
    if not mappings or not content:
        return content

    def replacer(m: re.Match) -> str:
        key = m.group(1)
        return mappings.get(key, m.group(0))

    return _PLACEHOLDER_RE.sub(replacer, content)


def list_placeholders(content: str) -> list:
    """Return all [[key]] placeholder names found in content."""
    return list(dict.fromkeys(
        m.group(1) for m in _PLACEHOLDER_RE.finditer(content)
    ))
