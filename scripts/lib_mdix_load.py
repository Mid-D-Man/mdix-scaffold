# scripts/lib_mdix_load.py
#!/usr/bin/env python3
"""
Shared .mdix loading for mdix-scaffold.

This replaces the old pipeline:

    Node spawns `mdix convert <file> --to json -o /tmp/x.json`
                        │
                        ▼
              Python `json.load()`s the temp file

with a single in-process call:

    MdixDatabase.load(path).to_table()

via the published `midmanstudio-mdix` package (pip install midmanstudio-mdix
— pre-built wheels, no Rust toolchain required). No subprocess, no temp
file, no dependency on the `mdix` CLI binary being built/available.

FORMAT COMPATIBILITY
---------------------
`MdixDatabase.to_json()` / `.to_table()` and the CLI's `mdix convert --to
json` both route through the same core `to_hashmap()` / `flatten_entry`
logic — same flat, "key[N]"-indexed GroupArray keys, PLUS the clean
"key": [...] array at the base key. This has been verified against the
real DixScript-Rust source and against mdix-scaffold's own production
template (.mdix/project_structure/project_structure.mdix). Every existing
`normalize_data()` / `collect_dir_groups()` consumer needs zero changes.

VALIDATION CAVEAT
------------------
`MdixDatabase.load()` is a lenient *runtime* loader by design: DATA-section
parse errors get logged via the core's ErrorManager and the load continues
with partial data rather than raising. A bare `try/except MdixError` is
therefore NOT equivalent to `mdix validate`'s strict tokenize → parse →
semantic-analyze pipeline (confirmed empirically — a source with an
unclosed paren loads "successfully" with entry_count=0, no exception).

The Python bindings don't expose a structured error/warning count either
(no `error_count` / `has_fatal_errors` on MdixDatabase — checked
mdix-python's src/lib.rs and the _mdix.pyi stub). The only signal that
crosses the FFI boundary at all is the diagnostic text the Rust core
writes straight to the OS-level stderr fd via `eprintln!` (bypassing
Python's `sys.stdout`/`sys.stderr`, so it can only be caught with an
fd-level dup2 swap — plain `contextlib.redirect_stderr` will not see it).

So `load_table(..., strict=True)` (the default) captures fd 1+2 during the
load and treats any `[Error]`-tagged line as a hard failure, surfacing the
exact diagnostic text (error code, message, and the core's own quick-fix
suggestions). It's a log-scrape, not a structured API — the honest
approximation available without a Rust CLI dependency. If mdix-python
later exposes a real validation report, swap the internals of
`_check_diagnostics` for that and every caller here is unaffected.
"""

import os
import re

try:
    from midmanstudio.mdix import MdixDatabase, MdixError
    _HAS_BINDING = True
except ImportError:
    MdixDatabase = None
    MdixError = Exception  # placeholder so `except MdixError` still parses
    _HAS_BINDING = False

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class MdixLoadError(Exception):
    """Raised when a .mdix file fails to load, fails validation, or the
    midmanstudio-mdix package isn't installed."""


def _require_binding():
    if not _HAS_BINDING:
        raise MdixLoadError(
            "midmanstudio-mdix is not installed.\n"
            "  pip install midmanstudio-mdix\n"
            "(or: pip install -r scripts/requirements.txt)"
        )


def _load_capturing_diagnostics(loader_call):
    """
    Run `loader_call()` (a zero-arg callable that calls into the Rust
    extension) with real fd 1/2 captured, returning (result, captured_text).
    """
    stdout_fd, stderr_fd = 1, 2
    saved_out, saved_err = os.dup(stdout_fd), os.dup(stderr_fd)
    r_out, w_out = os.pipe()
    r_err, w_err = os.pipe()
    os.dup2(w_out, stdout_fd)
    os.dup2(w_err, stderr_fd)
    os.close(w_out)
    os.close(w_err)
    try:
        result = loader_call()
    finally:
        os.dup2(saved_out, stdout_fd)
        os.dup2(saved_err, stderr_fd)
        os.close(saved_out)
        os.close(saved_err)
        out = os.read(r_out, 10_000_000).decode("utf-8", "replace")
        err = os.read(r_err, 10_000_000).decode("utf-8", "replace")
        os.close(r_out)
        os.close(r_err)
    return result, out + err


def _check_diagnostics(captured: str, source_label: str):
    error_lines = [ln for ln in captured.splitlines() if "[Error]" in ln]
    if error_lines:
        clean = [_ANSI_RE.sub("", ln) for ln in error_lines]
        raise MdixLoadError(
            f"'{source_label}' failed validation:\n" + "\n".join(clean)
        )


def load_table(path: str, strict: bool = True) -> dict:
    """
    Load a .mdix file and return its flat hashmap (same "key[N]"-indexed
    shape normalize_data() already expects) as a native Python dict.

    strict=True (default): additionally scan the load's captured
    diagnostics for [Error]-tagged lines and raise MdixLoadError if any
    are found — see module docstring for what this can and can't catch.
    """
    _require_binding()
    if not os.path.exists(path):
        raise MdixLoadError(f"File not found: '{path}'")

    try:
        db, captured = _load_capturing_diagnostics(lambda: MdixDatabase.load(path))
    except MdixError as e:
        raise MdixLoadError(f"'{path}' failed to load: {e}") from e

    if strict:
        _check_diagnostics(captured, path)

    return db.to_table()


def load_table_str(source: str, label: str, strict: bool = True) -> dict:
    """Same as load_table(), for in-memory .mdix source text."""
    _require_binding()
    try:
        db, captured = _load_capturing_diagnostics(lambda: MdixDatabase.load_str(source))
    except MdixError as e:
        raise MdixLoadError(f"'{label}' failed to load: {e}") from e

    if strict:
        _check_diagnostics(captured, label)

    return db.to_table()


def validate(path: str) -> None:
    """Raise MdixLoadError if `path` doesn't load cleanly (see caveat above)."""
    load_table(path, strict=True)
