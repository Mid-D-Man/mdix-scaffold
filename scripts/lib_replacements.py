# scripts/lib_replacements.py
"""
Replacements pass — the third .mdix template kind (alongside project_structure
and patch). See ai/claude/MDIX_SCAFFOLD_SKILL.md, "Replacements templates".

A replacements manifest lives at a fixed path:

    .mdix/replacements/replacements.mdix

Every other file sitting under that same folder IS real, verbatim content
under its real target filename — no DixScript string-escaping required.
Files can sit flat next to the manifest, or nested in subdirectories:

  - Flat file (no subdirectory): resolved by basename search under
    target_root, same as before.
      - exactly one match  -> overwrite it (respects --file-strategy/--diff/
        --dry-run, same as the update_files pass)
      - zero matches       -> create it at target_root/<basename>
      - multiple matches   -> hard error; must be resolved via `overrides::`
        or by moving the file into a subdirectory here (see below)

  - Nested file (sits in a subdirectory here): its relative path under
    replacements/ IS the target path under target_root, directly — no
    search, no ambiguity possible. This is what lets multiple files share a
    basename (e.g. `sse2/mat4.rs` and `neon/mat4.rs` side by side) without
    needing an override:: entry for each one.

  - `overrides::` always wins outright over either of the above, checked
    against both the file's bare basename and its full relative path.
    IMPORTANT: this check happens *before* the nested-path check, so an
    override keyed by a bare basename (e.g. "Cargo.toml") will also catch
    any *nested* file that happens to share that basename, not just a flat
    one — if your replacement set has multiple files with the same
    basename, only key an override by a name that's actually unique across
    the whole replacements tree (rename the flat file on disk here if you
    have to; the override's `path` is what controls its real destination).

  - Archive file (`.tar.gz`, `.tgz`, `.tar`, or `.zip`, anywhere in this
    tree, flat or nested): NOT copied as a literal file. It's extracted
    into a temporary staging area at the exact position it occupies in the
    tree, and its internal contents are then treated as ordinary
    candidates — same flat/nested resolution rules as above, recursively
    (an archive containing another archive gets extracted again). This
    exists so a whole replacement set can be delivered as one file where
    committing dozens of individual files isn't practical (e.g. from a
    mobile client with no local shell to run `tar xzf` first) — drop
    `replacements.mdix` and one `.tar.gz` next to it, nothing else. See
    `stage_replacements_dir()` below for the extraction mechanics and the
    path-traversal safety checks — archive contents are untrusted input
    and are validated before any extraction happens, not after.

    Optional: pass delete_processed_archives=True on args (workflow input
    `delete_processed_archives`, env `DELETE_PROCESSED_ARCHIVES`) to delete
    a top-level archive from its real location in replacements_dir once a
    run completes with zero errors and args.dry_run is False. This is
    purely opt-in and off by default — stage_replacements_dir() itself
    still never touches replacements_dir; the deletion (if requested)
    happens afterward, in run_replacements(), and only for archives that
    were genuinely sitting in replacements_dir (not ones that only existed
    inside another archive's extracted contents). The point is avoiding an
    accidental re-run of the same archive later, at the cost of losing the
    "idempotent, nothing to lose track of" property `stage_replacements_dir`
    otherwise guarantees — a deliberate trade the caller opts into, not a
    default.

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
import tarfile
import tempfile
import time
import zipfile

ARCHIVE_EXTENSIONS = (".tar.gz", ".tgz", ".tar", ".zip")


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


def collect_candidates(replacements_dir: str, ignore_names: set) -> list:
    """
    Walk replacements_dir recursively. Returns relative paths (forward-slash,
    relative to replacements_dir) for every real file, skipping dotfiles/dirs
    and anything named in ignore_names (checked against both the bare
    basename and the full relative path, so ignore:: entries written either
    way still work).

    A file found directly inside replacements_dir (no subdirectory component)
    is "flat" — resolved the original way, by basename search under
    target_root. A file found inside a subdirectory is "nested" — its
    relative path IS the target path under target_root directly, no search,
    no ambiguity possible (this is what lets multiple files share a basename,
    e.g. sse2/mat4.rs and neon/mat4.rs side by side, as long as they sit in
    matching subdirectories here).
    """
    candidates = []
    for dirpath, dirnames, filenames in os.walk(replacements_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in filenames:
            if f.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), replacements_dir)
            rel = rel.replace(os.sep, "/")
            if f in ignore_names or rel in ignore_names:
                continue
            candidates.append(rel)
    return sorted(candidates)


def _is_archive(filename: str) -> bool:
    return filename.lower().endswith(ARCHIVE_EXTENSIONS)


def _member_is_safe(dest_dir: str, member_path: str) -> bool:
    """
    Standard "zip slip"/tar path-traversal check: rejects an absolute
    member path outright, then resolves the member against dest_dir and
    confirms the result is still inside dest_dir. Archive contents are
    untrusted input (they could have come from anywhere before landing in
    a commit) — this runs BEFORE extraction, on every member, not as a
    post-hoc cleanup after something's already been written to disk.
    """
    if os.path.isabs(member_path) or member_path.startswith(("/", "\\")):
        return False
    dest_abs = os.path.normpath(os.path.abspath(dest_dir))
    resolved = os.path.normpath(os.path.abspath(os.path.join(dest_dir, member_path)))
    return resolved == dest_abs or resolved.startswith(dest_abs + os.sep)


def _extract_archive_safely(archive_path: str, dest_dir: str) -> None:
    """
    Validates every member of the archive before extracting anything — an
    archive that fails validation raises ValueError with nothing written,
    rather than extracting the safe members and silently skipping the
    unsafe ones. Symlinks/hardlinks in tar archives are rejected outright
    too, since a symlink is itself a path-traversal vector independent of
    where its own archive entry name points.
    """
    lower = archive_path.lower()
    if lower.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zf:
            for name in zf.namelist():
                if not _member_is_safe(dest_dir, name):
                    raise ValueError(
                        f"archive member '{name}' in {os.path.basename(archive_path)} "
                        f"resolves outside the replacements folder — refusing to extract "
                        f"(path-traversal attempt)"
                    )
            zf.extractall(dest_dir)
    else:
        mode = "r:gz" if lower.endswith((".tar.gz", ".tgz")) else "r:"
        with tarfile.open(archive_path, mode) as tf:
            for member in tf.getmembers():
                if member.issym() or member.islnk():
                    raise ValueError(
                        f"archive member '{member.name}' in {os.path.basename(archive_path)} "
                        f"is a symlink/hardlink — refusing to extract (path-traversal risk)"
                    )
                if not _member_is_safe(dest_dir, member.name):
                    raise ValueError(
                        f"archive member '{member.name}' in {os.path.basename(archive_path)} "
                        f"resolves outside the replacements folder — refusing to extract "
                        f"(path-traversal attempt)"
                    )
            tf.extractall(dest_dir)


def stage_replacements_dir(replacements_dir: str, ignore_names: set):
    """
    Builds a temporary staging copy of replacements_dir: every ordinary
    file is copied across as-is, and every archive file (anywhere in the
    tree, flat or nested — see ARCHIVE_EXTENSIONS) is extracted into the
    staging copy at the exact position the archive itself occupies, so its
    internal paths become real nested files exactly as if they'd been
    committed individually. Extraction recurses via a work queue — an
    archive containing another archive gets extracted again, since the
    inner archive is just another file the next queue entry walks over.

    This NEVER modifies replacements_dir itself: the archive is neither
    deleted nor extracted in place. Two consequences, both intentional:
      - Idempotent. Re-running later re-extracts from the same
        still-present archive — nothing to accidentally lose track of.
      - Naturally dry-run-safe, with zero special-casing needed elsewhere.
        The staging copy is thrown away either way (see the returned
        cleanup callable); a real run only ever writes to target_root,
        exactly like every other candidate already does.

    Returns (staging_dir, cleanup, extracted_archives), where
    extracted_archives is a list of (rel_path, is_top_level) tuples —
    is_top_level is True only for an archive sourced directly from
    replacements_dir itself (a real, committed file); False for an archive
    that only existed inside another archive's extracted contents
    (staging-only, never a real file under replacements_dir). A caller that
    wants to act on the real committed archive file (e.g. deleting a
    processed archive from the repo, see delete_processed_archives in
    run_replacements below) MUST filter to is_top_level entries — deleting
    a staging-only rel_path against replacements_dir would either no-op
    against a path that never existed there, or, worse, coincidentally
    collide with an unrelated real file that happens to share that
    relative path.

    Always call cleanup() when done, success or failure — wrap the caller in
    try/finally, not just a straight-line call.

    Raises ValueError (propagated from _extract_archive_safely) if any
    archive fails its path-traversal check — nothing is left half-staged
    in that case; the partial staging_dir is removed before raising.
    """
    staging_dir = tempfile.mkdtemp(prefix="mdix-replacements-")
    extracted = []

    def cleanup():
        shutil.rmtree(staging_dir, ignore_errors=True)

    # Work queue of (source_dir, dest_dir, apply_ignore, copy_needed) tuples.
    # apply_ignore is only True for the original replacements_dir itself —
    # ignore:: entries are meant for what's committed there, not for an
    # archive's internal paths, which are a separate namespace. copy_needed
    # is False when src_root and dest_root are the same directory (the
    # rescan-for-nested-archives pass below) — those files are already
    # exactly where they need to be; copying them onto themselves would
    # both be pointless and raise shutil.SameFileError.
    queue = [(replacements_dir, staging_dir, True, True)]

    try:
        while queue:
            src_root, dest_root, apply_ignore, copy_needed = queue.pop()
            for dirpath, dirnames, filenames in os.walk(src_root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                rel_dir = os.path.relpath(dirpath, src_root)
                dest_dir = dest_root if rel_dir == "." else os.path.join(dest_root, rel_dir)
                if copy_needed:
                    os.makedirs(dest_dir, exist_ok=True)

                for f in filenames:
                    if f.startswith("."):
                        continue
                    rel = os.path.normpath(os.path.join(rel_dir, f)).replace(os.sep, "/")
                    if rel.startswith("./"):
                        rel = rel[2:]
                    if apply_ignore and (f in ignore_names or rel in ignore_names):
                        continue

                    src = os.path.join(dirpath, f)
                    if _is_archive(f):
                        _extract_archive_safely(src, dest_dir)
                        extracted.append((rel, copy_needed))
                        if not copy_needed:
                            # This archive was itself sitting in staging as
                            # a byproduct of a PARENT extraction (nested
                            # archive-within-archive case) — remove it now
                            # that its contents are extracted alongside it,
                            # or the next rescan pass would keep
                            # rediscovering and re-extracting it forever.
                            # (Top-level archives never reach here: they're
                            # sourced directly from replacements_dir, which
                            # is never touched — see copy_needed's docstring
                            # note above.)
                            os.remove(src)
                        queue.append((dest_dir, dest_dir, False, False))
                    elif copy_needed:
                        shutil.copy2(src, os.path.join(dest_dir, f))
                    # else: copy_needed is False, meaning this file is
                    # already sitting in staging from a prior extraction —
                    # nothing to do but leave it there.
    except Exception:
        cleanup()
        raise

    return staging_dir, cleanup, extracted


def _handle_existing(filepath, new_content, args):
    """
    Returns (status_string, wrote: bool). `wrote` means "the replacement
    content is what's at filepath now" — every branch that returns
    wrote=True must actually put new_content there (respecting
    args.dry_run), not just perform its side effect and report success.
    """
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
        # Mirror filepath's relative structure under the backup dir rather
        # than flattening to its basename — multiple candidates can
        # legitimately share a basename (that's the whole point of nested
        # replacement paths: three different crates can each have their
        # own Cargo.toml), and backing all of them up to the same flat
        # backups/Cargo.toml would silently keep only the last one
        # processed, discarding the rest with no error or warning.
        if os.path.isabs(filepath):
            backup_dest = os.path.join(args.backup, os.path.basename(filepath))
        else:
            backup_dest = os.path.join(args.backup, filepath.lstrip("./"))
        if not args.dry_run:
            backup_parent = os.path.dirname(backup_dest)
            if backup_parent:
                os.makedirs(backup_parent, exist_ok=True)
            shutil.copy2(filepath, backup_dest)
            with open(filepath, "w") as fh:
                fh.write(new_content)
        return f"backed up -> {backup_dest}, then overwritten", True

    if strategy == "rename":
        new_name = f"{filepath}.{int(time.time())}"
        if not args.dry_run:
            os.rename(filepath, new_name)
            with open(filepath, "w") as fh:
                fh.write(new_content)
        return f"renamed old -> {new_name}, wrote new at original path", True

    # strategy == "overwrite" (the default)
    if not args.dry_run:
        with open(filepath, "w") as fh:
            fh.write(new_content)
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

    # Stage into a temp copy so any archives sitting in replacements_dir
    # (see ARCHIVE_EXTENSIONS / stage_replacements_dir's docstring above)
    # get extracted before candidate collection, without ever touching
    # replacements_dir itself — everything below reads from staging_dir,
    # not replacements_dir, from this point on.
    try:
        staging_dir, cleanup, extracted_archives = stage_replacements_dir(replacements_dir, ignore_names)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        candidates = collect_candidates(staging_dir, ignore_names)

        top_level_archives = [rel for rel, is_top in extracted_archives if is_top]

        print(f"Replacements   : {replacements_dir}")
        if extracted_archives:
            nested_count = len(extracted_archives) - len(top_level_archives)
            print(f"Archives       : {len(extracted_archives)} extracted "
                  f"({len(top_level_archives)} top-level, {nested_count} nested-in-archive, "
                  f"staged only, not written back to replacements/)")
            for rel, is_top in extracted_archives:
                suffix = "" if is_top else "  (nested-in-archive, staging-only)"
                print(f"                 {rel}{suffix}")
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

        for rel_path in candidates:
            src_path = os.path.join(staging_dir, *rel_path.split("/"))
            with open(src_path) as fh:
                content = fh.read()

            basename = os.path.basename(rel_path)
            is_nested = "/" in rel_path

            if rel_path in overrides:
                dest = overrides[rel_path]
            elif basename in overrides:
                dest = overrides[basename]
            elif is_nested:
                # Relative path under replacements/ IS the target path under
                # target_root, directly — no search, can't be ambiguous.
                dest = os.path.join(target_root, *rel_path.split("/"))
            else:
                matches = find_target_matches(target_root, basename)
                if len(matches) > 1:
                    errors.append(rel_path)
                    print(f"  ERR  {rel_path}  — ambiguous, {len(matches)} matches under "
                          f"{target_root}:", file=sys.stderr)
                    for m in matches:
                        print(f"         {m}", file=sys.stderr)
                    print(f"         Resolve with:  overrides:: target(\"{basename}\", "
                          f"\"<exact path>\")  —  or just move this file into a "
                          f"subdirectory here that mirrors its real location.",
                          file=sys.stderr)
                    continue
                dest = matches[0] if matches else os.path.join(target_root, basename)

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

        deleted_archives = []
        if (not args.dry_run and not errors and top_level_archives
                and getattr(args, "delete_processed_archives", False)):
            print()
            print("=== Deleting processed archives ===")
            for rel in top_level_archives:
                archive_path = os.path.join(replacements_dir, *rel.split("/"))
                try:
                    os.remove(archive_path)
                    deleted_archives.append(archive_path)
                    print(f"  DEL  {archive_path}")
                except OSError as e:
                    print(f"  WARN could not delete {archive_path}: {e}", file=sys.stderr)

        skipped = len(candidates) - len(created) - len(replaced) - len(errors)
        print()
        print(f"Done. {len(created)} created, {len(replaced)} replaced, "
              f"{skipped} skipped, {len(errors)} error(s)"
              + (f", {len(deleted_archives)} archive(s) deleted." if deleted_archives else "."))

        return 1 if errors else 0
    finally:
        cleanup()
