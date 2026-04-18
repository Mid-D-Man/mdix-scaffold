#!/usr/bin/env python3
"""
Generate a .mdix snapshot of the repository layout.

Output is a valid DixScript file containing only a @DATA section.
Stored at others/ProjectStructure.mdix by default.

Triggers:
  - Manual:    python3 scripts/update_structure.py
  - Workflow:  include [snapshot] anywhere in your commit message
  - Actions:   workflow_dispatch

Usage (local):
  python3 scripts/update_structure.py
  python3 scripts/update_structure.py --output others/ProjectStructure.mdix
  python3 scripts/update_structure.py --repo my-org/my-repo --branch main --commit abc123
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a .mdix project structure snapshot."
    )
    parser.add_argument(
        "--output", "-o",
        default=os.environ.get("OUTPUT_FILE", "others/ProjectStructure.mdix"),
        help="Output file path (default: others/ProjectStructure.mdix)",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="Repository in owner/repo format",
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
# Rust workspace detection
# ---------------------------------------------------------------------------

def parse_workspace_members(cargo_toml_path):
    try:
        with open(cargo_toml_path) as f:
            text = f.read()
    except OSError:
        return []
    m = re.search(r"members\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if not m:
        return []
    return [
        s.strip().strip('"').strip("'")
        for s in m.group(1).split(",")
        if s.strip().strip('"').strip("'")
    ]


def collect_rs_files(member_dirs, subdir):
    files = []
    for member in member_dirs:
        d = os.path.join(member, subdir)
        if os.path.isdir(d):
            for root, _, fnames in os.walk(d):
                for f in sorted(fnames):
                    if f.endswith(".rs"):
                        files.append(os.path.join(root, f))
    return sorted(files)


def rust_workspace_info(root):
    """
    Returns a dict with workspace info if this is a Rust workspace, else None.
    {
      members: [str],
      src_files: [str],
      test_files: [str],
      bench_files: [str],
      totals: {src, tests, benches},
      per_member: {member: {src, tests, benches}}
    }
    """
    cargo_toml = os.path.join(root, "Cargo.toml")
    if not os.path.exists(cargo_toml):
        return None
    try:
        content = open(cargo_toml).read()
    except OSError:
        return None
    if not re.search(r"^\[workspace\]", content, re.MULTILINE):
        return None

    members = parse_workspace_members(cargo_toml)
    member_dirs = [os.path.join(root, m) for m in members]

    src_files   = collect_rs_files(member_dirs, "src")
    test_files  = collect_rs_files(member_dirs, "tests")
    bench_files = collect_rs_files(member_dirs, "benches")

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

    return {
        "members":     members,
        "src_files":   [os.path.relpath(f, root) for f in src_files],
        "test_files":  [os.path.relpath(f, root) for f in test_files],
        "bench_files": [os.path.relpath(f, root) for f in bench_files],
        "totals":      totals,
        "per_member":  per_member,
    }


# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------

EXCLUDE_DIRS  = {".git", "target", "node_modules"}
EXCLUDE_FILES = {".mdix/.manifest.mdix"}


def collect_layout(root):
    paths = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        rel = os.path.relpath(dirpath, root)
        paths.append("." if rel == "." else rel)
        for fname in sorted(filenames):
            frel = fname if rel == "." else os.path.join(rel, fname)
            if frel not in EXCLUDE_FILES:
                paths.append(frel)
    return paths


def collect_mdix_files(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fname in filenames:
            if fname.endswith(".mdix"):
                found.append(os.path.relpath(os.path.join(dirpath, fname), root))
    return sorted(found)


def collect_workflows(root):
    wf_dir = os.path.join(root, ".github", "workflows")
    if not os.path.isdir(wf_dir):
        return []
    return sorted(
        os.path.join(".github", "workflows", f)
        for f in os.listdir(wf_dir)
        if f.endswith(".yml")
    )


# ---------------------------------------------------------------------------
# .mdix renderer
# ---------------------------------------------------------------------------

def _q(s):
    """Quote a string value for DixScript."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _array_block(items, indent=4):
    """Render a list of strings as a DixScript group array block."""
    pad = " " * indent
    if not items:
        return f'{pad}"(none)"'
    return "\n".join(f"{pad}{_q(item)}" for item in items)


def render_mdix_snapshot(args, root, now):
    """
    Render the full .mdix snapshot. Only @DATA — no @CONFIG, no @QUICKFUNCS.
    Clean, human-readable, properly indented.
    """
    lines = []

    def ln(s=""):
        lines.append(s)

    ln("// =============================================================================")
    ln("// PROJECT STRUCTURE SNAPSHOT  ·  DixScript v1.0.0")
    ln("// Auto-generated by scripts/update_structure.py")
    ln("// Do not edit manually — regenerate with [snapshot] in your commit message")
    ln("//   or run: python3 scripts/update_structure.py")
    ln("// =============================================================================")
    ln()
    ln("@DATA(")

    # ── Header metadata ──────────────────────────────────────────────────────
    if args.repo:
        ln(f"  repository = {_q(args.repo)}")
    if args.branch:
        ln(f"  branch     = {_q(args.branch)}")
    if args.commit:
        ln(f"  commit     = {_q(args.commit[:12] if len(args.commit) > 12 else args.commit)}")
    ln(f"  generated  = {_q(now)}")
    ln()

    # ── Rust workspace (if applicable) ───────────────────────────────────────
    ws = rust_workspace_info(root)
    if ws:
        ln("  // ── Rust Workspace ───────────────────────────────────────────────────")
        ln()

        ln("  workspace_members::")
        for m in ws["members"]:
            ln(f"    {_q(m + '/')}")
        ln()

        for key, label, files in [
            ("src_files",   "source_files",    ws["src_files"]),
            ("test_files",  "test_files",       ws["test_files"]),
            ("bench_files", "benchmark_files",  ws["bench_files"]),
        ]:
            ln(f"  {label}::")
            if files:
                for f in files:
                    ln(f"    {_q(f)}")
            else:
                ln('    "(none)"')
            ln()

        # File count summary as flat properties
        ln("  // ── File count summary ─────────────────────────────────────────────────")
        ln(f"  total_source_files    = {ws['totals']['src']}")
        ln(f"  total_test_files      = {ws['totals']['tests']}")
        ln(f"  total_benchmark_files = {ws['totals']['benches']}")
        ln(f"  total_files           = {sum(ws['totals'].values())}")
        ln()

        # Per-member breakdown as table properties
        ln("  // ── Per-member breakdown ────────────────────────────────────────────────")
        for member, counts in ws["per_member"].items():
            safe_key = member.replace("-", "_").replace("/", "_")
            ln(
                f"  {safe_key}: "
                f"src = {counts['src']}, "
                f"tests = {counts['tests']}, "
                f"benches = {counts['benches']}"
            )
        ln()

    else:
        # ── Generic directory layout ──────────────────────────────────────────
        ln("  // ── Directory layout ────────────────────────────────────────────────────")
        ln()
        layout = collect_layout(root)
        ln("  directory_layout::")
        for p in layout:
            ln(f"    {_q(p)}")
        ln()

    # ── DixScript files ───────────────────────────────────────────────────────
    ln("  // ── DixScript files (.mdix) ─────────────────────────────────────────────")
    ln()
    mdix_files = collect_mdix_files(root)
    ln("  mdix_files::")
    if mdix_files:
        for f in mdix_files:
            ln(f"    {_q(f)}")
    else:
        ln('    "(none)"')
    ln()

    # ── GitHub workflows ──────────────────────────────────────────────────────
    ln("  // ── GitHub workflows ────────────────────────────────────────────────────")
    ln()
    workflows = collect_workflows(root)
    ln("  github_workflows::")
    if workflows:
        for w in workflows:
            ln(f"    {_q(w)}")
    else:
        ln('    "(none)"')
    ln()

    ln(")")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args):
    root    = os.path.abspath(args.root)
    now     = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_dir = os.path.dirname(args.output)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    content = render_mdix_snapshot(args, root, now)

    with open(args.output, "w") as f:
        f.write(content)

    print(f"=== Snapshot written to {args.output} ===")
    print(content)


if __name__ == "__main__":
    run(parse_args())
