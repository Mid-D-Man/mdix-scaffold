#!/usr/bin/env python3
"""
Generate project structure from a .mdix template.

Usage (local):
  python3 scripts/generate_structure.py
  python3 scripts/generate_structure.py --template .mdix/project_structure/project_structure.mdix
  python3 scripts/generate_structure.py --dry-run
  python3 scripts/generate_structure.py --override-stubs

Usage (from GitHub Actions - env vars still respected for backward compat):
  OVERRIDE_STUBS=false DRY_RUN=false python3 scripts/generate_structure.py
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Argument parsing — accepts both CLI flags and env-var fallbacks so the
# script works locally AND from GitHub Actions without changing the workflow.
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate project structure from a .mdix template."
    )
    parser.add_argument(
        "--template", "-t",
        default=os.environ.get(
            "TEMPLATE_PATH",
            ".mdix/project_structure/project_structure.mdix",
        ),
        help="Path to the .mdix template file (default: .mdix/project_structure/project_structure.mdix)",
    )
    parser.add_argument(
        "--override-stubs",
        action="store_true",
        default=os.environ.get("OVERRIDE_STUBS", "false").lower() == "true",
        help="Overwrite existing stub files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("DRY_RUN", "false").lower() == "true",
        help="Preview actions without writing anything",
    )
    parser.add_argument(
        "--structure-json",
        default=os.environ.get("STRUCTURE_JSON", "/tmp/structure.json"),
        help="Path to the converted structure JSON (default: /tmp/structure.json)",
    )
    parser.add_argument(
        "--manifest-json",
        default=os.environ.get("MANIFEST_JSON", "/tmp/manifest.json"),
        help="Path to an existing manifest JSON, if any",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STUB_DEFAULTS = {
    "rs":     "// Auto-generated stub\n",
    "cs":     "// Auto-generated stub\n",
    "py":     "# Auto-generated stub\n",
    "ts":     "// Auto-generated stub\n",
    "js":     "// Auto-generated stub\n",
    "go":     "// Auto-generated stub\n",
    "java":   "// Auto-generated stub\n",
    "cpp":    "// Auto-generated stub\n",
    "c":      "// Auto-generated stub\n",
    "h":      "// Auto-generated stub\n",
    "hpp":    "// Auto-generated stub\n",
    "kt":     "// Auto-generated stub\n",
    "swift":  "// Auto-generated stub\n",
    "lua":    "-- Auto-generated stub\n",
    "shader": "// Auto-generated shader stub\n",
    "yml":    "# Auto-generated stub\n",
    "yaml":   "# Auto-generated stub\n",
    "sh":     "#!/usr/bin/env bash\nset -euo pipefail\n\n# Auto-generated stub\n",
    "bash":   "#!/usr/bin/env bash\nset -euo pipefail\n\n# Auto-generated stub\n",
    "ps1":    "# Auto-generated stub\n",
    "toml":   "# Auto-generated config\n",
    "json":   "{}\n",
    "md":     "# {name}\n",
    "xml":    '<?xml version="1.0" encoding="utf-8"?>\n',
    "html":   "<!DOCTYPE html>\n<html>\n<head><title>{name}</title></head>\n<body>\n</body>\n</html>\n",
    "css":    "/* Auto-generated stub */\n",
}

RESERVED_PREFIXES = {
    "hidden_dirs",
    "delete_files",
    "rename_files",
    "update_files",
}


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


def load_manifest(manifest_json_path):
    previously_created = set()
    if os.path.exists(manifest_json_path):
        with open(manifest_json_path) as fh:
            mdata = json.load(fh)
        j = 0
        while f"created_files[{j}]" in mdata:
            val = mdata[f"created_files[{j}]"]
            if isinstance(val, str):
                previously_created.add(val)
            j += 1
    return previously_created


def write_manifest(
    template_path,
    previously_created,
    created, overridden, updated, deleted, renamed,
    skipped,
    dry_run,
):
    if dry_run:
        return

    os.makedirs(".mdix", exist_ok=True)

    template_hash = ""
    if os.path.exists(template_path):
        with open(template_path, "rb") as tf:
            template_hash = hashlib.sha256(tf.read()).hexdigest()[:12]

    all_tracked = previously_created | set(created) | set(overridden) | set(updated)
    all_tracked -= set(deleted)
    for from_p, to_p in renamed:
        all_tracked.discard(from_p)
        all_tracked.add(to_p)
    all_tracked = sorted(all_tracked)

    files_block = (
        "\n    ".join(f'"{p}"' for p in all_tracked)
        if all_tracked
        else '"(none)"'
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest_content = (
        "@CONFIG(\n"
        f'  version    -> "1.0.0"\n'
        f'  generated  -> "{now}"\n'
        f'  features   -> "data"\n'
        f'  debug_mode -> "off"\n'
        ")\n\n"
        "@DATA(\n"
        f'  template      = "{template_path}"\n'
        f'  template_hash = "{template_hash}"\n'
        f'  last_run      = "{now}"\n'
        f'  new_this_run  = {len(created)}\n'
        f'  overridden    = {len(overridden)}\n'
        f'  skipped       = {len(skipped)}\n'
        f'  deleted       = {len(deleted)}\n'
        f'  renamed       = {len(renamed)}\n'
        f'  updated       = {len(updated)}\n'
        "\n"
        "  created_files::\n"
        f"    {files_block}\n"
        ")\n"
    )

    with open(".mdix/.manifest.mdix", "w") as mf:
        mf.write(manifest_content)

    print(f"\n  Manifest → .mdix/.manifest.mdix  (tracking {len(all_tracked)} file(s))")


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------

def run(args):
    if not os.path.exists(args.structure_json):
        print(
            f"ERROR: Structure JSON not found at '{args.structure_json}'.\n"
            "Run 'mdix convert <template> --to json' first, or use the full\n"
            "workflow which calls 'mdix validate' and 'mdix convert' before this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(args.structure_json) as fh:
        data = json.load(fh)

    hidden_set       = resolve_hidden_set(data)
    dir_groups       = collect_dir_groups(data)
    previously_created = load_manifest(args.manifest_json)

    project_name = data.get("project_name", "unknown-project")

    if args.dry_run:
        print("=" * 56)
        print("  DRY RUN — no files will be written or deleted")
        print("=" * 56)
        print()

    print(f"Project    : {project_name}")
    print(f"Template   : {args.template}")
    print(f"Hidden     : {hidden_set or '(none)'}")
    print(f"Dry run    : {args.dry_run}")
    print(f"Override   : {args.override_stubs}")
    if previously_created:
        print(f"Manifest   : {len(previously_created)} previously tracked file(s)")
    print()
    print(f"Template defines {len(dir_groups)} directory group(s)")

    # ------------------------------------------------------------------
    # PASS 1 — Delete files / directories
    # ------------------------------------------------------------------
    deleted = []
    header_shown = False
    i = 0
    while True:
        key = f"delete_files[{i}]"
        if key not in data:
            break
        entry = data[key]
        if isinstance(entry, dict) and "path" in entry:
            path = entry["path"].strip()
            if path:
                if not header_shown:
                    print()
                    print("=== Deleting files / directories ===")
                    print()
                    header_shown = True
                if os.path.exists(path):
                    if not args.dry_run:
                        if os.path.isdir(path):
                            shutil.rmtree(path)
                        else:
                            os.remove(path)
                    deleted.append(path)
                    print(f"  DEL  {path}")
                else:
                    print(f"  ---  {path}  (not found, skipped)")
        i += 1

    # ------------------------------------------------------------------
    # PASS 2 — Rename files / directories
    # ------------------------------------------------------------------
    renamed = []
    header_shown = False
    i = 0
    while True:
        key = f"rename_files[{i}]"
        if key not in data:
            break
        entry = data[key]
        if isinstance(entry, dict) and "from_path" in entry and "to_path" in entry:
            from_path = entry["from_path"].strip()
            to_path   = entry["to_path"].strip()
            if from_path and to_path:
                if not header_shown:
                    print()
                    print("=== Renaming files / directories ===")
                    print()
                    header_shown = True
                if os.path.exists(from_path):
                    if not args.dry_run:
                        parent = os.path.dirname(to_path)
                        if parent:
                            os.makedirs(parent, exist_ok=True)
                        os.rename(from_path, to_path)
                    renamed.append((from_path, to_path))
                    print(f"  REN  {from_path} → {to_path}")
                else:
                    print(f"  ---  {from_path}  (not found, skipped)")
        i += 1

    # ------------------------------------------------------------------
    # PASS 3 — Create / skip / override scaffold files
    # ------------------------------------------------------------------
    created    = []
    skipped    = []
    overridden = []

    print()
    print("=== Processing scaffold files ===")
    print()

    for dir_key in sorted(dir_groups.keys()):
        items    = dir_groups[dir_key]
        dir_path = key_to_dir(dir_key, hidden_set)

        if dir_path and not os.path.isdir(dir_path):
            if not args.dry_run:
                os.makedirs(dir_path, exist_ok=True)
            print(f"  DIR  {dir_path}/")

        for idx in sorted(items.keys()):
            entry    = items[idx]
            filename = assemble_filename(entry)
            if not filename:
                continue

            name_part   = entry.get("name", "")
            ext_part    = entry.get("ext",  "")
            raw_content = entry.get("content", "")

            if raw_content == "":
                raw_content = STUB_DEFAULTS.get(ext_part, "").replace("{name}", name_part)

            filepath = os.path.join(dir_path, filename) if dir_path else filename

            if os.path.exists(filepath):
                if args.override_stubs:
                    if not args.dry_run:
                        with open(filepath, "w") as fh:
                            fh.write(raw_content)
                    overridden.append(filepath)
                    print(f"  OVR  {filepath}")
                else:
                    skipped.append(filepath)
                    print(f"  ---  {filepath}  (exists, kept)")
            else:
                if not args.dry_run:
                    parent = os.path.dirname(filepath)
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    with open(filepath, "w") as fh:
                        fh.write(raw_content)
                created.append(filepath)
                print(f"  NEW  {filepath}")

    # ------------------------------------------------------------------
    # PASS 4 — Update file contents (always-overwrite)
    # ------------------------------------------------------------------
    updated = []
    header_shown = False
    i = 0
    while True:
        key = f"update_files[{i}]"
        if key not in data:
            break
        entry = data[key]
        if isinstance(entry, dict) and "path" in entry:
            file_path   = entry["path"].strip()
            new_content = entry.get("content", "")
            if file_path:
                if not header_shown:
                    print()
                    print("=== Updating file contents ===")
                    print()
                    header_shown = True
                existed_before = os.path.exists(file_path)
                if not args.dry_run:
                    parent = os.path.dirname(file_path)
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    with open(file_path, "w") as fh:
                        fh.write(new_content)
                updated.append(file_path)
                label = "UPD" if existed_before else "NEW"
                print(f"  {label}  {file_path}")
        i += 1

    # ------------------------------------------------------------------
    # Write manifest + print summary
    # ------------------------------------------------------------------
    write_manifest(
        template_path=args.template,
        previously_created=previously_created,
        created=created,
        overridden=overridden,
        updated=updated,
        deleted=deleted,
        renamed=renamed,
        skipped=skipped,
        dry_run=args.dry_run,
    )

    print()
    print("=" * 56)
    print(f"  created   : {len(created)}")
    print(f"  overridden: {len(overridden)}")
    print(f"  skipped   : {len(skipped)}")
    print(f"  deleted   : {len(deleted)}")
    print(f"  renamed   : {len(renamed)}")
    print(f"  updated   : {len(updated)}")
    print("=" * 56)

    if args.dry_run:
        print()
        print("DRY RUN complete — re-run without --dry-run to apply.")


if __name__ == "__main__":
    run(parse_args())
