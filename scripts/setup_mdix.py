#!/usr/bin/env python3
"""
Install the mdix CLI binary from source.

Called by: mdix-scaffold setup
Also usable directly: python3 scripts/setup_mdix.py

What it does:
  1. Checks if mdix is already on PATH (exits early if so)
  2. Checks if cargo (Rust) is available
  3. Clones DixScript-Rust into a temp dir
  4. Builds mdix-cli --release
  5. Copies the binary to bin/mdix (local) AND offers to copy to /usr/local/bin/mdix
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile


DIXSCRIPT_REPO = "https://github.com/Mid-D-Man/DixScript-Rust.git"

# Where we put the binary relative to this script's parent (the pkg root)
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT     = os.path.dirname(_SCRIPTS_DIR)
LOCAL_BIN    = os.path.join(PKG_ROOT, "bin", "mdix")


def _run(args, **kwargs):
    result = subprocess.run(args, **kwargs)
    if result.returncode != 0:
        sys.exit(result.returncode)
    return result


def check_already_installed() -> bool:
    r = subprocess.run(["mdix", "--version"], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"✓ mdix already on PATH: {r.stdout.strip()}")
        return True
    if os.path.isfile(LOCAL_BIN) and os.access(LOCAL_BIN, os.X_OK):
        r2 = subprocess.run([LOCAL_BIN, "--version"], capture_output=True, text=True)
        if r2.returncode == 0:
            print(f"✓ mdix already installed at {LOCAL_BIN}: {r2.stdout.strip()}")
            return True
    return False


def check_cargo():
    r = subprocess.run(["cargo", "--version"], capture_output=True, text=True)
    if r.returncode != 0:
        print(
            "ERROR: cargo (Rust toolchain) not found.\n"
            "Install Rust from https://rustup.rs then re-run this command.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"✓ cargo found: {r.stdout.strip()}")


def build_from_source(force: bool = False):
    if not force and check_already_installed():
        return

    check_cargo()

    print(f"\nCloning {DIXSCRIPT_REPO} …")
    with tempfile.TemporaryDirectory() as tmp:
        _run(
            ["git", "clone", "--depth", "1", DIXSCRIPT_REPO, tmp],
            check=True,
        )

        print("\nBuilding mdix-cli (this takes ~2–3 min the first time) …")
        _run(
            ["cargo", "build", "-p", "mdix-cli", "--release"],
            cwd=tmp,
            check=True,
        )

        src = os.path.join(tmp, "target", "release", "mdix")
        if not os.path.isfile(src):
            print("ERROR: Build succeeded but binary not found.", file=sys.stderr)
            sys.exit(1)

        # Copy to pkg bin/
        os.makedirs(os.path.join(PKG_ROOT, "bin"), exist_ok=True)
        shutil.copy2(src, LOCAL_BIN)
        os.chmod(LOCAL_BIN, 0o755)
        print(f"\n✓ mdix installed → {LOCAL_BIN}")

        # Offer to also copy to /usr/local/bin for system-wide access
        system_bin = "/usr/local/bin/mdix"
        if sys.platform != "win32":
            print(f"\nTo make mdix available system-wide run:")
            print(f"  sudo cp {LOCAL_BIN} {system_bin}")


def main():
    p = argparse.ArgumentParser(description="Install the mdix CLI binary from source.")
    p.add_argument("--force", action="store_true", help="Rebuild even if already installed")
    args = p.parse_args()
    build_from_source(force=args.force)


if __name__ == "__main__":
    main()
