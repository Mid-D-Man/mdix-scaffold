#!/usr/bin/env python3
"""
Generate project structure from a .mdix template.

Features (v3):
  - File strategies : skip (default), overwrite, backup, rename
  - Pre/post hooks  : shell commands from pre_hooks:: / post_hooks:: in @DATA
  - Diff preview    : --diff shows unified diffs alongside --dry-run
  - Remote content  : file entries whose content starts with remote:: are fetched
                      Supports https://, http://, github://owner/repo/branch/path
  - Mappings        : --mappings <file.yaml> replaces [[key]] placeholders in content
  - Cache           : remote files cached in ~/.mdix-scaffold/cache/

Usage (local):
  python3 scripts/generate_structure.py
  python3 scripts/generate_structure.py --dry-run
  python3 scripts/generate_structure.py --dry-run --diff
  python3 scripts/generate_structure.py --file-strategy backup --backup /tmp/bak
  python3 scripts/generate_structure.py --mappings mappings.yaml
  python3 scripts/generate_structure.py --clear-cache

GitHub Actions env vars (backward compat):
  TEMPLATE_PATH, OVERRIDE_STUBS, DRY_RUN, FILE_STRATEGY, STRUCTURE_JSON,
  MANIFEST_JSON, MAPPINGS_FILE, BACKUP_DIR
"""

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Optional local libs — resolve relative to this script so it works when
# called from any working directory
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    from lib_remote   import resolve_content, clear_cache
    from lib_mappings import load_mappings, apply_mappings, list_placeholders
    _HAS_REMOTE   = True
    _HAS_MAPPINGS = True
except ImportError:
    # Graceful degradation — remote/mappings features disabled but core works
    _HAS_REMOTE   = False
    _HAS_MAPPINGS = False
    def resolve_content(c, verbose=False): return c  # type: ignore
    def clear_cache(): pass                           # type: ignore
    def load_mappings(p): return {}                   # type: ignore
    def apply_mappings(c, m): return c                # type: ignore
    def list_placeholders(c): return []               # type: ignore


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Generate project structure from a .mdix template.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--template", "-t",
        default=os.environ.get("TEMPLATE_PATH",
                               ".mdix/project_structure/project_structure.mdix"),
        help="Path to the .mdix template",
    )
    p.add_argument(
        "--override-stubs",
        action="store_true",
        default=os.environ.get("OVERRIDE_STUBS", "false").lower() == "true",
        help="Alias for --file-strategy overwrite",
    )
    p.add_argument(
        "--file-strategy",
        choices=["skip", "overwrite", "backup", "rename"],
        default=os.environ.get("FILE_STRATEGY", "skip"),
        help="How to handle existing files (default: skip)",
    )
    p.add_argument(
        "--backup",
        default=os.environ.get("BACKUP_DIR"),
        help="Backup directory when --file-strategy=backup",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("DRY_RUN", "false").lower() == "true",
        help="Preview actions without writing anything",
    )
    p.add_argument(
        "--diff",
        action="store_true",
        default=False,
        help="Show unified diffs alongside --dry-run",
    )
    p.add_argument(
        "--mappings", "-m",
        default=os.environ.get("MAPPINGS_FILE"),
        help="Path to a YAML/JSON mappings file for [[key]] substitution",
    )
    p.add_argument(
        "--structure-json",
        default=os.environ.get("STRUCTURE_JSON", "/tmp/structure.json"),
        help="Path to converted structure JSON",
    )
    p.add_argument(
        "--manifest-json",
        default=os.environ.get("MANIFEST_JSON", "/tmp/manifest.json"),
        help="Path to existing manifest JSON, if any",
    )
    p.add_argument(
        "--clear-cache",
        action="store_true",
        default=False,
        help="Clear the remote-content cache and exit",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Skip cache reads/writes for remote content",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        default=os.environ.get("VERBOSE", "false").lower() == "true",
        help="Print extra detail (remote fetches, mapping substitutions)",
    )

    args = p.parse_args()

    if args.override_stubs:
        args.file_strategy = "overwrite"

    return args


# ---------------------------------------------------------------------------
# Built-in stub defaults
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
    "hidden_dirs", "delete_files", "rename_files",
    "update_files", "pre_hooks", "post_hooks",
}


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

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


def collect_string_array(data, prefix):
    items = []
    i = 0
    while True:
        key = f"{prefix}[{i}]"
        if key not in data:
            break
        val = data[key]
        if isinstance(val, str):
            items.append(val)
        i += 1
    return items


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


# ---------------------------------------------------------------------------
# Hook runner
# ---------------------------------------------------------------------------

def run_hooks(hooks, hook_type="pre", dry_run=False):
    if not hooks:
        return True
    for cmd in hooks:
        print(f"  [{hook_type}-hook] {cmd}")
        if dry_run:
            print("           (skipped — dry run)")
            continue
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.stdout.strip():
            print(f"           stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            print(f"           stderr: {result.stderr.strip()}")
        if result.returncode != 0:
            print(
                f"  ERROR: {hook_type}-hook failed (exit {result.returncode}): {cmd}",
                file=sys.stderr,
            )
            return False
    return True


# ---------------------------------------------------------------------------
# File strategy
# ---------------------------------------------------------------------------

def handle_existing_file(filepath, new_content, args):
    """
    Apply the configured file strategy to an existing file.
    Returns (label, should_write).
    """
    strategy = args.file_strategy

    if args.diff:
        try:
            with open(filepath) as f:
                old_content = f.read()
        except OSError:
            old_content = ""
        diff = list(difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{filepath}",
            tofile=f"b/{filepath}",
        ))
        if diff:
            print("".join(diff), end="")

    if strategy == "skip":
        return "skipped", False

    if strategy == "backup":
        if not args.backup:
            print(
                "  WARNING: --file-strategy=backup requires --backup <dir>; skipping",
                file=sys.stderr,
            )
            return "skipped (no backup dir)", False
        os.makedirs(args.backup, exist_ok=True)
        backup_dest = os.path.join(args.backup, os.path.basename(filepath))
        if not args.dry_run:
            shutil.copy2(filepath, backup_dest)
        return f"backed up → {backup_dest}", True

    if strategy == "rename":
        new_name = f"{filepath}.{int(time.time())}"
        if not args.dry_run:
            os.rename(filepath, new_name)
        return f"renamed → {new_name}", True

    # overwrite
    return "overwritten", True


# ---------------------------------------------------------------------------
# Content pipeline
# ---------------------------------------------------------------------------

def process_content(raw_content, name_part, ext_part, mappings, args):
    """
    Full content pipeline:
      1. Fill stub default if empty
      2. Resolve remote:: references
      3. Apply [[key]] mappings substitution
    """
    # Step 1: stub default
    if raw_content == "":
        raw_content = STUB_DEFAULTS.get(ext_part, "").replace("{name}", name_part)

    # Step 2: remote content
    if _HAS_REMOTE:
        use_cache = not getattr(args, "no_cache", False)
        raw_content = resolve_content(raw_content, verbose=args.verbose)

    # Step 3: mappings
    if mappings and _HAS_MAPPINGS:
        placeholders = list_placeholders(raw_content)
        if placeholders and args.verbose:
            missing = [k for k in placeholders if k not in mappings]
            if missing:
                print(f"  NOTE: unmapped placeholders: {missing}")
        raw_content = apply_mappings(raw_content, mappings)

    return raw_content


# ---------------------------------------------------------------------------
# Manifest writer
# ---------------------------------------------------------------------------

def write_manifest(
    template_path,
    previously_created,
    created, overridden, updated, deleted, renamed, skipped,
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
        if all_tracked else '"(none)"'
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
# Main
# ---------------------------------------------------------------------------

def run(args):
    # Handle --clear-cache early
    if args.clear_cache:
        clear_cache()
        sys.exit(0)

    if not os.path.exists(args.structure_json):
        print(
            f"ERROR: Structure JSON not found at '{args.structure_json}'.\n"
            "Run 'mdix convert <template> --to json' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(args.structure_json) as fh:
        data = json.load(fh)

    hidden_set         = resolve_hidden_set(data)
    dir_groups         = collect_dir_groups(data)
    previously_created = load_manifest(args.manifest_json)
    pre_hooks          = collect_string_array(data, "pre_hooks")
    post_hooks         = collect_string_array(data, "post_hooks")
    project_name       = data.get("project_name", "unknown-project")

    # Load mappings
    mappings = {}
    if args.mappings:
        if _HAS_MAPPINGS:
            mappings = load_mappings(args.mappings)
            print(f"Mappings       : {len(mappings)} keys loaded from {args.mappings}")
        else:
            print(
                "WARNING: lib_mappings.py not found — --mappings flag ignored.",
                file=sys.stderr,
            )

    if args.dry_run:
        print("=" * 56)
        print("  DRY RUN — no files will be written or deleted")
        print("=" * 56)
        print()

    print(f"Project        : {project_name}")
    print(f"Template       : {args.template}")
    print(f"Hidden dirs    : {hidden_set or '(none)'}")
    print(f"File strategy  : {args.file_strategy}")
    print(f"Dry run        : {args.dry_run}")
    print(f"Remote content : {_HAS_REMOTE}")
    print(f"Mappings       : {bool(mappings)}")
    if previously_created:
        print(f"Manifest       : {len(previously_created)} previously tracked file(s)")
    if pre_hooks:
        print(f"Pre-hooks      : {len(pre_hooks)}")
    if post_hooks:
        print(f"Post-hooks     : {len(post_hooks)}")
    print()
    print(f"Template defines {len(dir_groups)} directory group(s)")

    # ------------------------------------------------------------------
    # Pre-hooks
    # ------------------------------------------------------------------
    if pre_hooks:
        print()
        print("=== Pre-hooks ===")
        print()
        if not run_hooks(pre_hooks, "pre", args.dry_run):
            print("Aborting — pre-hook failed.", file=sys.stderr)
            sys.exit(1)

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
            fp = entry["path"].strip()
            if fp:
                if not header_shown:
                    print()
                    print("=== Deleting files / directories ===")
                    print()
                    header_shown = True
                if os.path.exists(fp):
                    if not args.dry_run:
                        shutil.rmtree(fp) if os.path.isdir(fp) else os.remove(fp)
                    deleted.append(fp)
                    print(f"  DEL  {fp}")
                else:
                    print(f"  ---  {fp}  (not found, skipped)")
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

            # Full content pipeline: stub → remote → mappings
            final_content = process_content(raw_content, name_part, ext_part, mappings, args)

            filepath = os.path.join(dir_path, filename) if dir_path else filename

            if os.path.exists(filepath):
                label, should_write = handle_existing_file(filepath, final_content, args)
                if should_write:
                    if not args.dry_run:
                        with open(filepath, "w") as fh:
                            fh.write(final_content)
                    overridden.append(filepath)
                    print(f"  OVR  {filepath}  ({label})")
                else:
                    skipped.append(filepath)
                    print(f"  ---  {filepath}  ({label})")
            else:
                if not args.dry_run:
                    parent = os.path.dirname(filepath)
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    with open(filepath, "w") as fh:
                        fh.write(final_content)
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

                # Apply remote + mappings to update content too
                new_content = process_content(new_content, "", "", mappings, args)

                if args.diff and os.path.exists(file_path):
                    with open(file_path) as f:
                        old_content = f.read()
                    diff = list(difflib.unified_diff(
                        old_content.splitlines(keepends=True),
                        new_content.splitlines(keepends=True),
                        fromfile=f"a/{file_path}",
                        tofile=f"b/{file_path}",
                    ))
                    if diff:
                        print("".join(diff), end="")

                existed_before = os.path.exists(file_path)
                if not args.dry_run:
                    parent = os.path.dirname(file_path)
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    with open(file_path, "w") as fh:
                        fh.write(new_content)
                updated.append(file_path)
                print(f"  {'UPD' if existed_before else 'NEW'}  {file_path}")
        i += 1

    # ------------------------------------------------------------------
    # Post-hooks
    # ------------------------------------------------------------------
    if post_hooks:
        print()
        print("=== Post-hooks ===")
        print()
        if not run_hooks(post_hooks, "post", args.dry_run):
            print("WARNING: post-hook failed.", file=sys.stderr)

    # ------------------------------------------------------------------
    # Manifest + summary
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
    print(f"  created    : {len(created)}")
    print(f"  overridden : {len(overridden)}")
    print(f"  skipped    : {len(skipped)}")
    print(f"  deleted    : {len(deleted)}")
    print(f"  renamed    : {len(renamed)}")
    print(f"  updated    : {len(updated)}")
    print("=" * 56)

    if args.dry_run:
        print()
        print("DRY RUN complete — re-run without --dry-run to apply.")


if __name__ == "__main__":
    run(parse_args())
