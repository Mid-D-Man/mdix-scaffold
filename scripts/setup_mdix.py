#!/usr/bin/env python3
"""
Install midmanstudio-mdix — the Python bindings mdix-scaffold's scripts
load .mdix files through.

Called by: mdix-scaffold setup
Also usable directly: python3 scripts/setup_mdix.py

What it does:
  1. Checks if midmanstudio-mdix is already importable (exits early if so)
  2. pip installs it from scripts/requirements.txt (pre-built wheel — no
     Rust toolchain, no compiling, no cloning DixScript-Rust)

This replaces the old "clone DixScript-Rust and cargo build mdix-cli"
flow entirely — that path is gone, along with the ~2-3 minute build and
the bin/mdix binary it used to produce.
"""

import argparse
import importlib
import os
import subprocess
import sys

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REQUIREMENTS = os.path.join(_SCRIPTS_DIR, "requirements.txt")


def check_already_installed() -> bool:
    try:
        mod = importlib.import_module("midmanstudio.mdix")
    except ImportError:
        return False
    version = getattr(mod, "__version__", "unknown")
    print(f"✓ midmanstudio-mdix already installed: {version}")
    return True


def pip_install(force: bool = False):
    if not force and check_already_installed():
        return

    if os.path.isfile(_REQUIREMENTS):
        target = ["-r", _REQUIREMENTS]
    else:
        target = ["midmanstudio-mdix>=1.0,<2.0"]

    print("Installing midmanstudio-mdix …")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install"] + target,
        check=False,
    )
    if result.returncode != 0:
        print(
            "ERROR: pip install failed. Try manually:\n"
            "  pip install midmanstudio-mdix",
            file=sys.stderr,
        )
        sys.exit(result.returncode)

    importlib.invalidate_caches()
    if check_already_installed():
        print("\n✓ Setup complete.")
    else:
        print(
            "ERROR: pip reported success but the package still isn't "
            "importable — check your Python environment.",
            file=sys.stderr,
        )
        sys.exit(1)


def main():
    p = argparse.ArgumentParser(
        description="Install midmanstudio-mdix (pip, no Rust toolchain needed)."
    )
    p.add_argument("--force", action="store_true", help="Reinstall even if already present")
    args = p.parse_args()
    pip_install(force=args.force)


if __name__ == "__main__":
    main()
