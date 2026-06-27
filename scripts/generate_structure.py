# scripts/generate_structure.py
#!/usr/bin/env python3
"""
Generate project structure from a .mdix template.
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

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    from lib_remote   import resolve_content, clear_cache
    from lib_mappings import load_mappings, apply_mappings, list_placeholders
    _HAS_REMOTE   = True
    _HAS_MAPPINGS = True
except ImportError:
    _HAS_REMOTE   = False
    _HAS_MAPPINGS = False
    def resolve_content(c, verbose=False): return c
    def clear_cache(): pass
    def load_mappings(p): return {}
    def apply_mappings(c, m): return c
    def list_placeholders(c): return []

try:
    import lib_patch
    _HAS_PATCH = True
except ImportError:
    _HAS_PATCH = False


def parse_args():
    p = argparse.ArgumentParser(description="Generate project structure from a .mdix template.")
    p.add_argument("--template", "-t",
        default=os.environ.get("TEMPLATE_PATH",
                               ".mdix/project_structure/project_structure.mdix"))
    p.add_argument("--override-stubs", action="store_true",
        default=os.environ.get("OVERRIDE_STUBS", "false").lower() == "true")
    p.add_argument("--file-strategy",
        choices=["skip", "overwrite", "backup", "rename"],
        default=os.environ.get("FILE_STRATEGY", "skip"))
    p.add_argument("--backup", default=os.environ.get("BACKUP_DIR"))
    p.add_argument("--dry-run", action="store_true",
        default=os.environ.get("DRY_RUN", "false").lower() == "true")
    p.add_argument("--diff", action="store_true", default=False)
    p.add_argument("--mappings", "-m", default=os.environ.get("MAPPINGS_FILE"))
    p.add_argument("--structure-json",
        default=os.environ.get("STRUCTURE_JSON", "/tmp/structure.json"))
    p.add_argument("--manifest-json",
        default=os.environ.get("MANIFEST_JSON", "/tmp/manifest.json"))
    p.add_argument("--clear-cache", action="store_true", default=False)
    p.add_argument("--no-cache",    action="store_true", default=False)
    p.add_argument("--verbose", action="store_true",
        default=os.environ.get("VERBOSE", "false").lower() == "true")

    args = p.parse_args()
    if args.override_stubs:
        args.file_strategy = "overwrite"
    return args


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
    "update_files", "pre_hooks",   "post_hooks",
    "move_files",   "patch_files",
}


# ---------------------------------------------------------------------------
# iter_section — handles BOTH JSON formats from the DixScript compiler:
#   Array format  (new):  {"delete_files": [{...}, ...]}
#   Flat-indexed  (old):  {"delete_files[0]": {...}, "delete_files[1]": {...}}
# ---------------------------------------------------------------------------

def iter_section(data, prefix):
    val = data.get(prefix)
    if isinstance(val, list):
        yield from val
        return
    i = 0
    while True:
        key = f"{prefix}[{i}]"
        if key not in data:
            break
        yield data[key]
        i += 1


def iter_string_section(data, prefix):
    val = data.get(prefix)
    if isinstance(val, list):
        for item in val:
            if isinstance(item, str):
                yield item
            elif isinstance(item, dict) and "value" in item:
                yield item["value"]
        return
    i = 0
    while True:
        key = f"{prefix}[{i}]"
        if key not in data:
            break
        v = data[key]
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict) and "value" in v:
            yield v["value"]
        i += 1


def key_to_dir(dotted_key, hidden_set):
    if dotted_key == "root":
        return ""
    parts    = dotted_key.split(".")
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
    for entry in iter_section(data, "hidden_dirs"):
        if isinstance(entry, dict) and "segment" in entry:
            hidden_set.add(entry["segment"].strip())
    return hidden_set


def collect_dir_groups(data):
    """
    Collect directory-group entries (arrays of file objects, each with at
    least a 'name' key) from BOTH JSON formats produced by the DixScript
    compiler:
      Array format  (new):  {"src": [{"name": ..., "ext": ..., ...}, ...]}
      Flat-indexed  (old):  {"src[0]": {...}, "src[1]": {...}}

    NOTE: this must stay in sync with iter_section()/iter_string_section()
    above, which already handle both formats. This function previously
    only matched the old flat-indexed format via regex, which silently
    produced zero directory groups against current compiler output.
    """
    entry_re   = re.compile(r"^(.+)\[(\d+)\]$")
    dir_groups = {}
    for key, value in data.items():
        # --- New array format ---
        if isinstance(value, list):
            if key in RESERVED_PREFIXES:
                continue
            items = {}
            for idx, item in enumerate(value):
                if isinstance(item, dict) and "name" in item:
                    items[idx] = item
            if items:
                dir_groups[key] = items
            continue

        # --- Old flat-indexed format ---
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
    return list(iter_string_section(data, prefix))


def load_manifest(manifest_json_path, current_template=None):
    """
    Load previously-tracked files from the manifest JSON.

    KEY SAFETY RULE: if the manifest was written by a *different* template
    (e.g. workspace-restructure), do NOT inherit its file list.  Inheriting
    across templates causes the stale-deletion pass to remove files that the
    current template knows nothing about.  Each template owns only the files
    it created.
    """
    previously_created = set()
    if not os.path.exists(manifest_json_path):
        return previously_created

    try:
        with open(manifest_json_path) as fh:
            mdata = json.load(fh)

        # Check template ownership — bail out on mismatch
        manifest_template = mdata.get("template", "")
        if current_template and manifest_template:
            if manifest_template != current_template:
                print(
                    f"  Manifest belongs to a different template\n"
                    f"    stored : {manifest_template!r}\n"
                    f"    current: {current_template!r}\n"
                    f"  Skipping inherited file list — treating as first run for this template."
                )
                return previously_created

        for entry in iter_string_section(mdata, "created_files"):
            previously_created.add(entry)

    except Exception as e:
        print(f"  WARNING: could not read manifest ({e}) — treating as first run.")

    return previously_created


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
            print(f"  ERROR: {hook_type}-hook failed (exit {result.returncode}): {cmd}",
                  file=sys.stderr)
            return False
    return True


def handle_existing_file(filepath, new_content, args):
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
            print("  WARNING: --file-strategy=backup requires --backup <dir>; skipping",
                  file=sys.stderr)
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

    return "overwritten", True


def process_content(raw_content, name_part, ext_part, mappings, args):
    if raw_content == "":
        raw_content = STUB_DEFAULTS.get(ext_part, "").replace("{name}", name_part)

    if _HAS_REMOTE:
        raw_content = resolve_content(raw_content, verbose=args.verbose)

    if mappings and _HAS_MAPPINGS:
        placeholders = list_placeholders(raw_content)
        if placeholders and args.verbose:
            missing = [k for k in placeholders if k not in mappings]
            if missing:
                print(f"  NOTE: unmapped placeholders: {missing}")
        raw_content = apply_mappings(raw_content, mappings)

    return raw_content


def write_manifest(
    template_path,
    previously_created,
    created, overridden, updated, deleted, renamed, moved, skipped,
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
    for from_p, to_p in moved:
        all_tracked.discard(from_p)
        all_tracked.add(to_p)
    all_tracked = sorted(all_tracked)

    files_block = (
        "\n    ".join(f'"{p}"' for p in all_tracked)
        if all_tracked else ""
    )

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # No @QUICKFUNCS, no fc() calls, no features line (defaults to advanced).
    # Plain key=value metadata + bare string list — safe to re-parse on any run.
    # 'template' is stored so the next run can detect cross-template contamination.
    manifest_content = (
        "@CONFIG(\n"
        f'  version    -> "1.0.0"\n'
        f'  generated  -> "{ts}"\n'
        f'  debug_mode -> "off"\n'
        ")\n\n"
        "@DATA(\n"
        f'  template      = "{template_path}"\n'
        f'  template_hash = "{template_hash}"\n'
        f'  last_run      = "{ts}"\n'
        f'  new_this_run  = {len(created)}\n'
        f'  overridden    = {len(overridden)}\n'
        f'  skipped       = {len(skipped)}\n'
        f'  deleted       = {len(deleted)}\n'
        f'  renamed       = {len(renamed)}\n'
        f'  moved         = {len(moved)}\n'
        f'  updated       = {len(updated)}\n'
        "\n"
        "  created_files::\n"
        f"    {files_block}\n"
        ")\n"
    )

    with open(".mdix/.manifest.mdix", "w") as mf:
        mf.write(manifest_content)
    print(f"\n  Manifest → .mdix/.manifest.mdix  (tracking {len(all_tracked)} file(s))")


def run(args):
    if args.clear_cache:
        clear_cache()
        print("Cache cleared.")
        return

    with open(args.structure_json) as fh:
        data = json.load(fh)

    # Pass current template so manifest can detect cross-template contamination
    previously_created = load_manifest(args.manifest_json, current_template=args.template)

    mappings   = load_mappings(args.mappings) if args.mappings and _HAS_MAPPINGS else {}
    hidden_set = resolve_hidden_set(data)
    dir_groups = collect_dir_groups(data)
    pre_hooks  = collect_string_array(data, "pre_hooks")
    post_hooks = collect_string_array(data, "post_hooks")

    print(f"Project        : {os.path.basename(os.getcwd())}")
    print(f"Template       : {args.template}")
    print(f"Hidden dirs    : {', '.join(sorted(hidden_set)) or '(none)'}")
    print(f"File strategy  : {args.file_strategy}")
    print(f"Dry run        : {args.dry_run}")
    print(f"Remote content : {_HAS_REMOTE}")
    print(f"Mappings       : {bool(mappings)}")
    print(f"Patch support  : {_HAS_PATCH}")
    print()
    print(f"Template defines {len(dir_groups)} directory group(s)")

    if pre_hooks:
        print()
        print("=== Pre-hooks ===")
        print()
        if not run_hooks(pre_hooks, "pre", args.dry_run):
            sys.exit(1)

    # ------------------------------------------------------------------
    # PASS 1 — Delete manifest-tracked files no longer in the template
    # ------------------------------------------------------------------
    deleted      = []
    header_shown = False

    all_current = set()
    for dir_key, items in dir_groups.items():
        dir_path = key_to_dir(dir_key, hidden_set)
        for entry in items.values():
            fn = assemble_filename(entry)
            if fn:
                all_current.add(os.path.join(dir_path, fn) if dir_path else fn)

    for fp in sorted(previously_created - all_current):
        if os.path.isfile(fp):          # guard: never attempt os.remove on a dir
            if not header_shown:
                print()
                print("=== Deleting stale scaffold files ===")
                print()
                header_shown = True
            if not args.dry_run:
                os.remove(fp)
            deleted.append(fp)
            print(f"  DEL  {fp}")
        elif os.path.isdir(fp):
            print(f"  ---  {fp}  (is a directory — skipped)")

    # ------------------------------------------------------------------
    # PASS 2a — Delete explicitly listed files
    # ------------------------------------------------------------------
    header_shown = False
    for entry in iter_section(data, "delete_files"):
        if not isinstance(entry, dict) or "path" not in entry:
            continue
        path = entry["path"].strip()
        if not path:
            continue
        if not header_shown:
            print()
            print("=== Deleting listed files ===")
            print()
            header_shown = True
        if os.path.isfile(path):
            if not args.dry_run:
                os.remove(path)
            deleted.append(path)
            print(f"  DEL  {path}")
        elif os.path.isdir(path):
            print(f"  ---  {path}  (is a directory — use move_files to relocate)")
        else:
            print(f"  ---  {path}  (not found, skipped)")

    # ------------------------------------------------------------------
    # PASS 2b — Rename files
    # ------------------------------------------------------------------
    renamed      = []
    header_shown = False
    for entry in iter_section(data, "rename_files"):
        if not isinstance(entry, dict):
            continue
        from_path = entry.get("from_path", "").strip()
        to_path   = entry.get("to_path",   "").strip()
        if not from_path or not to_path:
            continue
        if not header_shown:
            print()
            print("=== Renaming files ===")
            print()
            header_shown = True
        if os.path.exists(from_path):
            if not args.dry_run:
                os.rename(from_path, to_path)
            renamed.append((from_path, to_path))
            print(f"  REN  {from_path} → {to_path}")
        else:
            print(f"  ---  {from_path}  (not found, skipped)")

    # ------------------------------------------------------------------
    # PASS 2c — Move files / directories (cross-filesystem safe)
    # ------------------------------------------------------------------
    moved        = []
    header_shown = False
    for entry in iter_section(data, "move_files"):
        if not isinstance(entry, dict):
            continue
        from_path = entry.get("from_path", "").strip()
        to_path   = entry.get("to_path",   "").strip()
        if not from_path or not to_path:
            continue
        if not header_shown:
            print()
            print("=== Moving files / directories ===")
            print()
            header_shown = True
        if os.path.exists(from_path):
            if not args.dry_run:
                parent = os.path.dirname(to_path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                shutil.move(from_path, to_path)
            moved.append((from_path, to_path))
            print(f"  MOV  {from_path} → {to_path}")
        else:
            print(f"  ---  {from_path}  (not found, skipped)")

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
            entry        = items[idx]
            filename     = assemble_filename(entry)
            if not filename:
                continue

            name_part     = entry.get("name", "")
            ext_part      = entry.get("ext",  "")
            raw_content   = entry.get("content", "")
            final_content = process_content(raw_content, name_part, ext_part, mappings, args)
            filepath      = os.path.join(dir_path, filename) if dir_path else filename

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
    # PASS 4 — Update file contents (always-overwrite, creates if missing)
    # ------------------------------------------------------------------
    updated      = []
    header_shown = False
    for entry in iter_section(data, "update_files"):
        if not isinstance(entry, dict) or "path" not in entry:
            continue
        file_path   = entry["path"].strip()
        new_content = entry.get("content", "")
        if not file_path:
            continue
        if not header_shown:
            print()
            print("=== Updating file contents ===")
            print()
            header_shown = True

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

    # ------------------------------------------------------------------
    # PASS 5 — Surgical file patches
    # ------------------------------------------------------------------
    patched      = []
    patch_errors = []
    header_shown = False
    for entry in iter_section(data, "patch_files"):
        if not isinstance(entry, dict) or "path" not in entry or "op" not in entry:
            continue
        file_path = entry["path"].strip()
        op_type   = entry.get("op", "").strip()
        if not file_path or not op_type:
            continue
        if not header_shown:
            print()
            print("=== Patching file contents ===")
            print()
            header_shown = True

        if not _HAS_PATCH:
            print(f"  ---  {file_path}  (lib_patch.py not found — skipped [{op_type}])")
        else:
            ok = lib_patch.apply_patch(file_path, entry, dry_run=args.dry_run)
            if ok:
                patched.append(file_path)
                print(f"  PCH  {file_path}  ({op_type})")
            else:
                patch_errors.append(file_path)

    if post_hooks:
        print()
        print("=== Post-hooks ===")
        print()
        if not run_hooks(post_hooks, "post", args.dry_run):
            print("WARNING: post-hook failed.", file=sys.stderr)

    write_manifest(
        template_path=args.template,
        previously_created=previously_created,
        created=created,
        overridden=overridden,
        updated=updated,
        deleted=deleted,
        renamed=renamed,
        moved=moved,
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
    print(f"  moved      : {len(moved)}")
    print(f"  updated    : {len(updated)}")
    print(f"  patched    : {len(patched)}")
    if patch_errors:
        print(f"  patch_err  : {len(patch_errors)}")
    print("=" * 56)

    if args.dry_run:
        print()
        print("DRY RUN complete — re-run without --dry-run to apply.")


if __name__ == "__main__":
    run(parse_args())
