#!/usr/bin/env python3
"""
Generate a plain-text snapshot of the repository layout and write it to a file.

Usage (local):
  python3 scripts/update_structure.py
  python3 scripts/update_structure.py --output others/ProjectStructure.txt
  python3 scripts/update_structure.py --repo my-org/my-repo --branch main --commit abc123

Usage (from GitHub Actions):
  Called by update-project-structure.yml — env vars are injected by the workflow.
"""

import argparse
import os
import re
import subprocess
import sys


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a project structure snapshot file."
    )
    parser.add_argument(
        "--output", "-o",
        default=os.environ.get("OUTPUT_FILE", "others/ProjectStructure.txt"),
        help="Output file path (default: others/ProjectStructure.txt)",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="Repository name in owner/repo format",
    )
    parser.add_argument(
        "--branch",
        default=os.environ.get("GITHUB_REF_NAME", ""),
        help="Current branch name",
    )
    parser.add_argument(
        "--commit",
        default=os.environ.get("GITHUB_SHA", ""),
        help="Current commit SHA",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root directory (default: current directory)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Rust workspace helpers
# ---------------------------------------------------------------------------

def parse_workspace_members(cargo_toml_path):
    """Extract workspace members from a Cargo.toml file."""
    try:
        with open(cargo_toml_path) as f:
            text = f.read()
    except OSError:
        return []

    m = re.search(r"members\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if not m:
        return []

    raw = m.group(1)
    return [
        s.strip().strip('"').strip("'")
        for s in raw.split(",")
        if s.strip().strip('"').strip("'")
    ]


def collect_rs_files(members, subdir):
    """Walk subdir under each workspace member and collect .rs files."""
    files = []
    for member in members:
        d = os.path.join(member, subdir)
        if os.path.isdir(d):
            for root, _, fnames in os.walk(d):
                for f in sorted(fnames):
                    if f.endswith(".rs"):
                        files.append(os.path.join(root, f))
    return sorted(files)


def rust_workspace_section(root, lines):
    cargo_toml = os.path.join(root, "Cargo.toml")
    if not (os.path.exists(cargo_toml) and
            re.search(r"^\[workspace\]", open(cargo_toml).read(), re.MULTILINE)):
        return False

    members = parse_workspace_members(cargo_toml)

    lines.append("Rust Workspace Members")
    lines.append("======================")
    for m in members:
        status = "✓" if os.path.isdir(os.path.join(root, m)) else "✗ (missing)"
        lines.append(f"  {status} {m}/")
    lines.append("")

    for category, label in [
        ("src",    "Source Files"),
        ("tests",  "Test Files"),
        ("benches","Benchmark Files"),
    ]:
        rs_files = collect_rs_files(
            [os.path.join(root, m) for m in members],
            category,
        )
        lines.append(label)
        lines.append("=" * len(label))
        if rs_files:
            for f in rs_files:
                # Make path relative to root
                lines.append("  " + os.path.relpath(f, root))
        else:
            lines.append("  (none found)")
        lines.append("")

    # File count summary
    lines.append("File Count Summary")
    lines.append("==================")
    totals = {"src": 0, "tests": 0, "benches": 0}
    per_member = {}
    for member in members:
        full = os.path.join(root, member)
        if not os.path.isdir(full):
            continue
        counts = {}
        for cat in totals:
            d = os.path.join(full, cat)
            count = 0
            if os.path.isdir(d):
                for r, _, fns in os.walk(d):
                    count += sum(1 for fn in fns if fn.endswith(".rs"))
            counts[cat] = count
            totals[cat] += count
        per_member[member] = counts

    lines.append(f"  Source files    : {totals['src']}")
    lines.append(f"  Test files      : {totals['tests']}")
    lines.append(f"  Benchmark files : {totals['benches']}")
    lines.append(f"  Total           : {sum(totals.values())}")
    lines.append("")
    lines.append("  Per-member breakdown:")
    for member, counts in per_member.items():
        lines.append(
            f"    {member}: src={counts['src']}  "
            f"tests={counts['tests']}  benches={counts['benches']}"
        )
    lines.append("")
    return True


# ---------------------------------------------------------------------------
# Generic directory layout
# ---------------------------------------------------------------------------

EXCLUDE_DIRS = {".git", "target", "node_modules", ".mdix"}
EXCLUDE_FILES = {".mdix/.manifest.mdix"}


def generic_layout_section(root, lines):
    lines.append("Directory Layout")
    lines.append("================")
    all_paths = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded directories in-place
        dirnames[:] = [
            d for d in sorted(dirnames)
            if d not in EXCLUDE_DIRS
        ]
        rel = os.path.relpath(dirpath, root)
        if rel == ".":
            all_paths.append(".")
        else:
            all_paths.append(rel)
        for fname in sorted(filenames):
            frel = os.path.join(rel, fname) if rel != "." else fname
            if frel not in EXCLUDE_FILES:
                all_paths.append(frel)

    for p in all_paths:
        lines.append("  " + p)
    lines.append("")


# ---------------------------------------------------------------------------
# Always-included sections
# ---------------------------------------------------------------------------

def mdix_files_section(root, lines):
    lines.append("DixScript Files (.mdix)")
    lines.append("=======================")
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fname in filenames:
            if fname.endswith(".mdix"):
                found.append(os.path.relpath(os.path.join(dirpath, fname), root))
    if found:
        for f in sorted(found):
            lines.append("  " + f)
    else:
        lines.append("  (none)")
    lines.append("")


def workflows_section(root, lines):
    lines.append("GitHub Workflows")
    lines.append("================")
    wf_dir = os.path.join(root, ".github", "workflows")
    if os.path.isdir(wf_dir):
        yamls = sorted(
            f for f in os.listdir(wf_dir) if f.endswith(".yml")
        )
        if yamls:
            for y in yamls:
                lines.append("  " + os.path.join(".github", "workflows", y))
        else:
            lines.append("  (none)")
    else:
        lines.append("  (none)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args):
    root = os.path.abspath(args.root)

    # Ensure output directory exists
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = []
    lines.append("Project Structure Snapshot")
    lines.append("==========================")
    if args.repo:
        lines.append(f"Repository : {args.repo}")
    if args.branch:
        lines.append(f"Branch     : {args.branch}")
    if args.commit:
        lines.append(f"Commit     : {args.commit}")
    lines.append(f"Generated  : {now}")
    lines.append("")

    is_rust = rust_workspace_section(root, lines)
    if not is_rust:
        generic_layout_section(root, lines)

    mdix_files_section(root, lines)
    workflows_section(root, lines)

    output = "\n".join(lines) + "\n"

    with open(args.output, "w") as f:
        f.write(output)

    print(f"=== Snapshot written to {args.output} ===")
    print(output)


if __name__ == "__main__":
    run(parse_args())
