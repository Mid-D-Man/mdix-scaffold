#!/usr/bin/env python3
"""
Remote content fetcher for mdix-scaffold.

Supports:
  https://...                  — direct HTTPS fetch
  http://...                   — direct HTTP fetch
  github://owner/repo/branch/path/to/file  — GitHub raw fetch
  githubhttps://...            — same as github://
  raw://owner/repo/branch/path — shorthand for GitHub raw

All fetches are cached in ~/.mdix-scaffold/cache/ keyed by a
SHA-256 of the URL so repeated runs don't re-download.
"""

import hashlib
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_dir() -> Path:
    d = Path.home() / ".mdix-scaffold" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(url: str) -> Path:
    key = hashlib.sha256(url.encode()).hexdigest()
    return _cache_dir() / key


def _cache_get(url: str):
    p = _cache_path(url)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


def _cache_set(url: str, content: str):
    _cache_path(url).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------

def _resolve_url(raw: str) -> str:
    """
    Convert shorthand protocols to real HTTPS URLs.

    github://owner/repo/branch/path/to/file
    githubhttps://owner/repo/branch/path/to/file
    raw://owner/repo/branch/path/to/file
      → https://raw.githubusercontent.com/owner/repo/branch/path/to/file
    """
    for prefix in ("github://", "githubhttps://", "raw://"):
        if raw.startswith(prefix):
            rest = raw[len(prefix):]
            # rest = owner/repo/branch/path
            parts = rest.split("/", 3)
            if len(parts) < 4:
                raise ValueError(
                    f"Invalid GitHub path '{raw}'. "
                    "Expected github://owner/repo/branch/path/to/file"
                )
            owner, repo, branch, path = parts
            return (
                f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
            )
    # Pass http/https through as-is
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    raise ValueError(f"Unsupported remote URL scheme: '{raw}'")


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch(url: str, timeout: int = 15, use_cache: bool = True) -> str:
    """
    Fetch text content from a URL.

    Raises:
        ValueError   — unsupported scheme or bad GitHub path
        RuntimeError — network error or non-200 response
    """
    resolved = _resolve_url(url)

    if use_cache:
        cached = _cache_get(resolved)
        if cached is not None:
            return cached

    try:
        req = urllib.request.Request(
            resolved,
            headers={"User-Agent": "mdix-scaffold/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"HTTP {resp.status} fetching '{resolved}'"
                )
            content = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} fetching '{resolved}': {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error fetching '{resolved}': {e.reason}") from e

    if use_cache:
        _cache_set(resolved, content)

    return content


def clear_cache():
    """Remove all cached remote files."""
    d = _cache_dir()
    for f in d.iterdir():
        if f.is_file():
            f.unlink()
    print(f"Cache cleared: {d}")


# ---------------------------------------------------------------------------
# Content prefix helpers used by generate_structure.py
# ---------------------------------------------------------------------------

REMOTE_PREFIX = "remote::"

def is_remote(content: str) -> bool:
    return isinstance(content, str) and content.startswith(REMOTE_PREFIX)

def strip_remote(content: str) -> str:
    return content[len(REMOTE_PREFIX):]

def resolve_content(content: str, verbose: bool = False) -> str:
    """
    If content is a remote:: reference, fetch and return it.
    Otherwise return content unchanged.
    """
    if not is_remote(content):
        return content
    url = strip_remote(content)
    if verbose:
        print(f"  FETCH  {url}")
    try:
        return fetch(url)
    except Exception as e:
        print(f"  WARNING: remote fetch failed for '{url}': {e}", file=sys.stderr)
        return f"# Remote fetch failed: {url}\n# Error: {e}\n"
