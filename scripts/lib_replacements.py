# scripts/lib_replacements.py
"""
Replacements pass — the third .mdix template kind (alongside project_structure
and patch). See ai/claude/MDIX_SCAFFOLD_SKILL.md, "Replacements templates".

A replacements manifest lives at a fixed path:

    .mdix/replacements/replacements.mdix

Every other file sitting in that same folder IS real, verbatim content under
its real target filename — no DixScript string-escaping required. This module:

  1. Lists every file next to the manifest, excluding the manifest itself,
     dotfiles, and anything named in `ignore::`.
  2. For each file, checks `overrides::` first — an explicit filename -> path
     entry always wins outright, no search performed.
  3. Otherwise walks `target_root` for a file with the same basename:
       - exactly one match  -> overwrite it (respects --file-strategy/--diff/
         --dry-run, same as the update_files pass)
       - zero matches       -> create it at target_root/<basename>
       - multiple matches   -> hard error; must be resolved via `overrides::`

This module is intentionally self-contained (no imports from
generate_structure.py) to avoid a circular import, since generate_structure.py
imports this module. The small file-write / hook-running helpers below are
deliberate, minimal duplicates of the equivalents there — mirror any behavior
change in both places.
"""

import difflib
import os
import shutil
import subprocess
import sys
import time


def iter_section(data: dict, key: str):
    val = data.get(key)
    if isinstance(val, list):
        yield from val


def collect_string_array(data: dict, key: str) -> list:
    out = []
    for item in iter_section(data, key):
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and "value" in item:
            out.append(item["value"])
    return out


def resolve_overrides(data: dict) -> dict:
    """overrides:: target("name.ext", "exact/path/name.ext") entries."""
    overrides = {}
    for entry in iter_section(data, "overrides"):
        if isinstance(entry, dict) and "name" in entry and "path" in entry:
            overrides[entry["name"].strip()] = entry["path"].strip()
    return overrides


def find_target_matches(target_root: str, filename: str) -> list:
    matches = []
    if not os.path.isdir(target_root):
        return matches
    for dirpath, _dirnames, filenames in os.walk(target_root):
        if filename in filenames:
            matches.append(os.path.join(dirpath, filename))
    return sorted(matches)


def _handle_existing(filepath, new_content, args):
    strategy = args.file_strategy

    if getattr(args, "diff", False):
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
        if not getattr(args, "backup", None):
            print("  WARNING: --file-strategy=backup requires --backup <dir>; skipping",
                  file=sys.stderr)
            return "skipped (no backup dir)", False
        os.makedirs(args.backup, exist_ok=True)
        backup_dest = os.path.join(args.backup, os.path.basename(filepath))
        if not args.dry_run:
            shutil.copy2(filepath, backup_dest)
        return f"backed up -> {backup_dest}", True

    if strategy == "rename":
        new_name = f"{filepath}.{int(time.time())}"
        if not args.dry_run:
            os.rename(filepath, new_name)
        return f"renamed -> {new_name}", True

    return "overwritten", True


def _run_hooks(hooks, hook_type, dry_run):
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


def run_replacements(data: dict, template_path: str, args) -> int:
    target_root = str(data.get("target_root", "")).strip()
    if not target_root:
        print("ERROR: replacements manifest has no target_root set in @DATA.",
              file=sys.stderr)
        return 1

    replacements_dir = os.path.dirname(os.path.abspath(template_path))
    manifest_name    = os.path.basename(template_path)
    ignore_names     = set(collect_string_array(data, "ignore")) | {manifest_name}
    overrides        = resolve_overrides(data)
    pre_hooks        = collect_string_array(data, "pre_hooks")
    post_hooks       = collect_string_array(data, "post_hooks")

    candidates = sorted(
        f for f in os.listdir(replacements_dir)
        if os.path.isfile(os.path.join(replacements_dir, f))
        and f not in ignore_names
        and not f.startswith(".")
    )

    print(f"Replacements   : {replacements_dir}")
    print(f"Target root    : {target_root}")
    print(f"Overrides      : {len(overrides)}")
    print(f"Candidates     : {len(candidates)}")
    print()

    if pre_hooks:
        print("=== Pre-hooks ===")
        print()
        if not _run_hooks(pre_hooks, "pre", args.dry_run):
            return 1

    created, replaced, errors = [], [], []

    for filename in candidates:
        src_path = os.path.join(replacements_dir, filename)
        with open(src_path) as fh:
            content = fh.read()

        if filename in overrides:
            dest = overrides[filename]
        else:
            matches = find_target_matches(target_root, filename)
            if len(matches) > 1:
                errors.append(filename)
                print(f"  ERR  {filename}  — ambiguous, {len(matches)} matches under "
                      f"{target_root}:", file=sys.stderr)
                for m in matches:
                    print(f"         {m}", file=sys.stderr)
                print(f"         Resolve with:  overrides:: target(\"{filename}\", "
                      f"\"<exact path>\")", file=sys.stderr)
                continue
            dest = matches[0] if matches else os.path.join(target_root, filename)

        if os.path.exists(dest):
            status, wrote = _handle_existing(dest, content, args)
            print(f"  {'REP' if wrote else '---'}  {dest}  ({status})")
            if wrote:
                replaced.append(dest)
        else:
            if not args.dry_run:
                parent = os.path.dirname(dest)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(dest, "w") as fh:
                    fh.write(content)
            created.append(dest)
            print(f"  NEW  {dest}")

    if post_hooks:
        print()
        print("=== Post-hooks ===")
        print()
        _run_hooks(post_hooks, "post", args.dry_run)

    skipped = len(candidates) - len(created) - len(replaced) - len(errors)
    print()
    print(f"Done. {len(created)} created, {len(replaced)} replaced, "
          f"{skipped} skipped, {len(errors)} error(s).")

    return 1 if errors else 0
