#!/usr/bin/env python3
"""
Dump a .mdix file as JSON — replaces `mdix convert <file> --to json`.

No filesystem side effects beyond the optional -o/--output write; this is
a read-only inspection tool. Loads and validates via lib_mdix_load, so a
malformed template is reported the same way generate_structure.py reports
it.

Usage:
  python3 scripts/convert_mdix.py path/to/template.mdix
  python3 scripts/convert_mdix.py path/to/template.mdix -o out.json
  python3 scripts/convert_mdix.py path/to/template.mdix --no-validate
"""

import argparse
import json
import os
import sys

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from lib_mdix_load import load_table, MdixLoadError


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", help="Path to the .mdix file to convert")
    p.add_argument("--output", "-o", default=None,
        help="Write JSON here instead of stdout")
    p.add_argument("--no-validate", action="store_true", default=False,
        help="Skip strict [Error]-diagnostic checking on load")
    return p.parse_args()


def main():
    args = parse_args()
    try:
        data = load_table(args.path, strict=not args.no_validate)
    except MdixLoadError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    text = json.dumps(data, indent=2, sort_keys=True, default=str)
    if args.output:
        with open(args.output, "w") as f:
            f.write(text + "\n")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
