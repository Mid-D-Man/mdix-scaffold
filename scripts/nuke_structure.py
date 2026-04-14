#!/usr/bin/env python3
"""
Remove all files previously generated from a .mdix template.

Usage (local):
  python3 scripts/nuke_structure.py --confirm DELETE
  python3 scripts/nuke_structure.py --confirm DELETE --template path/to/template.mdix

Usage (from GitHub Actions):
  Called by nuke-structure.yml after the mdix convert step.
"""

import argparse
import json
import os
import re
import sys


# ---------------------------------------------------------------------------
# Shared helpers (duplicated from generate_structure.py so each script is
# self-contained; factor out to scripts/lib.py later if desired)
# ---------------------------------------------------------------------------

RESERVED_PREFIXES = {
    "hidden_dirs",
    "delete_files",
    "rename_files",
    "update_files",
}


def resolve_hidden_set(data):
    hidden_set = set()
    i = 0
    while True:
        key = f"hidden_dirs[{i}]"
        if key not in data:
            break
        entry = data[key]
        if isinstance(entry, dict) and "segment" in entry:
            hidden_set.add(entry["segment"].strip())
        i += 1
    return hidden_set


def key_to_dir(dotted_key, hidden_set):
    if dotted_key == "root":
        return ""
    parts = dotted_key.split(".")
    fs_parts = []
    for idx, part in enumerate(parts):
        if idx == 0 and part in hidden_set:
            fs_parts.append("." + part)
        else:
            fs_parts.append(part)
    return "/".join(fs_parts)


def assemble_filename(entry):
    name = entry.get("name", "").strip()
    ext  = entry.get("ext",  "").strip()
    if not name:
        return None
    return f"{name}.{ext}" if ext else name


def collect_dir_groups(data):
    entry_re   = re.compile(r"^(.+)\[(\d+)\]$")
    dir_groups = {}
    for key, value in data.items():
        m = entry_re.match(key)
        if not m:
            continue
        if not isinstance(value, dict) or "name" not in value:
            continue
        dir_key = m.group(1)
        if dir_key in RESERVED_PREFIXES:
            continue
        idx = int(m.group(2))
        if dir_key not in dir_groups:
            dir_groups[dir_key] = {}
        dir_groups[dir_key][idx] = value
    return dir_groups


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Remove all scaffold-generated files from a .mdix template."
    )
    parser.add_argument(
        "--confirm",
        required=True,
        help="Must be exactly 'DELETE' to proceed",
    )
    parser.add_argument(
        "--template", "-t",
        default=".mdix/project_structure/project_structure.mdix",
        help="Path to the .mdix template (so we know what to remove)",
    )
    parser.add_argument(
        "--structure-json",
        default=os.environ.get("STRUCTURE_JSON", "/tmp/structure.json"),
        help="Path to the converted structure JSON (default: /tmp/structure.json)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main nuke logic
# ---------------------------------------------------------------------------

def run(args):
    if args.confirm != "DELETE":
        print(
            "ERROR: You must pass --confirm DELETE to proceed.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.path.exists(args.structure_json):
        print(
            f"ERROR: Structure JSON not found at '{args.structure_json}'.\n"
            "Run 'mdix convert <template> --to json' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(args.structure_json) as fh:
        data = json.load(fh)

    hidden_set  = resolve_hidden_set(data)
    dir_groups  = collect_dir_groups(data)

    removed = []
    missing = []

    print("=== Removing scaffold-generated files ===\n")

    for dir_key in sorted(dir_groups.keys()):
        items    = dir_groups[dir_key]
        dir_path = key_to_dir(dir_key, hidden_set)
        for idx in sorted(items.keys()):
            filename = assemble_filename(items[idx])
            if not filename:
                continue
            filepath = os.path.join(dir_path, filename) if dir_path else filename
            if os.path.exists(filepath):
                os.remove(filepath)
                removed.append(filepath)
                print(f"  DEL  {filepath}")
            else:
                missing.append(filepath)
                print(f"  ---  {filepath}  (already absent)")

    # Remove empty directories (deepest first)
    dirs_seen = set()
    for dir_key in dir_groups.keys():
        dir_path = key_to_dir(dir_key, hidden_set)
        if dir_path:
            parts = dir_path.split("/")
            for depth in range(len(parts), 0, -1):
                dirs_seen.add("/".join(parts[:depth]))

    for dir_path in sorted(dirs_seen, reverse=True):
        if os.path.isdir(dir_path) and not os.listdir(dir_path):
            os.rmdir(dir_path)
            print(f"  RMD  {dir_path}/")

    # Remove manifest
    manifest = ".mdix/.manifest.mdix"
    if os.path.exists(manifest):
        os.remove(manifest)
        print(f"  DEL  {manifest}")
    if os.path.isdir(".mdix") and not os.listdir(".mdix"):
        os.rmdir(".mdix")
        print("  RMD  .mdix/")

    print()
    print("=" * 48)
    print(f"  removed : {len(removed)}")
    print(f"  absent  : {len(missing)}")
    print("=" * 48)


if __name__ == "__main__":
    run(parse_args())
