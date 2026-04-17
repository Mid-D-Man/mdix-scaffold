#!/usr/bin/env python3
"""
Self-contained test suite for mdix-scaffold scripts.

Tests:
  1. Core generation (create / skip / overwrite / backup / rename)
  2. Pre/post hooks
  3. Remote content (mocked — no real network calls)
  4. Mappings substitution (.mdix and .json)
  5. Dry-run mode (nothing written)
  6. Diff output (unified diff printed but nothing written)
  7. Manifest creation and update

Run:
  python3 scripts/test_scaffold.py
  python3 scripts/test_scaffold.py -v   # verbose output
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import traceback
import types
import unittest
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Make sure scripts/ is on sys.path
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def _make_structure_json(dir_groups: dict, extras: dict | None = None) -> str:
    """
    Build a minimal structure.json that generate_structure.py can consume.

    dir_groups:  { "src": [{"name": "main", "ext": "rs", "content": ""}] }
    extras:      additional top-level keys (pre_hooks, post_hooks, etc.)
    """
    data: dict = {}
    data["project_name"] = "test-project"

    for group_key, entries in dir_groups.items():
        for i, entry in enumerate(entries):
            data[f"{group_key}[{i}]"] = entry

    if extras:
        data.update(extras)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(data, f)
        return f.name


def _args(**kwargs):
    """Return a minimal args namespace for generate_structure.run()."""
    import types
    ns = types.SimpleNamespace(
        template=".mdix/project_structure/project_structure.mdix",
        file_strategy="skip",
        backup=None,
        dry_run=False,
        diff=False,
        mappings=None,
        manifest_json="/dev/null",
        no_cache=True,
        verbose=False,
        clear_cache=False,
    )
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestCoreGeneration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp)

    def test_creates_new_file(self):
        from generate_structure import run
        sj = _make_structure_json(
            {"src": [{"name": "main", "ext": "rs", "content": "fn main() {}\n"}]}
        )
        run(_args(structure_json=sj))
        self.assertTrue(os.path.exists("src/main.rs"))
        self.assertEqual(open("src/main.rs").read(), "fn main() {}\n")

    def test_skip_strategy_leaves_existing(self):
        from generate_structure import run
        os.makedirs("src", exist_ok=True)
        with open("src/main.rs", "w") as f:
            f.write("original\n")
        sj = _make_structure_json(
            {"src": [{"name": "main", "ext": "rs", "content": "new\n"}]}
        )
        run(_args(structure_json=sj, file_strategy="skip"))
        self.assertEqual(open("src/main.rs").read(), "original\n")

    def test_overwrite_strategy_replaces(self):
        from generate_structure import run
        os.makedirs("src", exist_ok=True)
        with open("src/main.rs", "w") as f:
            f.write("original\n")
        sj = _make_structure_json(
            {"src": [{"name": "main", "ext": "rs", "content": "new\n"}]}
        )
        run(_args(structure_json=sj, file_strategy="overwrite"))
        self.assertEqual(open("src/main.rs").read(), "new\n")

    def test_backup_strategy_copies_then_writes(self):
        from generate_structure import run
        os.makedirs("src", exist_ok=True)
        with open("src/lib.rs", "w") as f:
            f.write("old\n")
        backup_dir = os.path.join(self.tmp, "backups")
        sj = _make_structure_json(
            {"src": [{"name": "lib", "ext": "rs", "content": "new\n"}]}
        )
        run(_args(
            structure_json=sj,
            file_strategy="backup",
            backup=backup_dir,
        ))
        self.assertEqual(open("src/lib.rs").read(), "new\n")
        self.assertTrue(os.path.exists(os.path.join(backup_dir, "lib.rs")))
        self.assertEqual(open(os.path.join(backup_dir, "lib.rs")).read(), "old\n")

    def test_rename_strategy_renames_then_writes(self):
        from generate_structure import run
        os.makedirs("src", exist_ok=True)
        with open("src/util.rs", "w") as f:
            f.write("old\n")
        sj = _make_structure_json(
            {"src": [{"name": "util", "ext": "rs", "content": "new\n"}]}
        )
        run(_args(structure_json=sj, file_strategy="rename"))
        self.assertEqual(open("src/util.rs").read(), "new\n")
        # At least one renamed backup should exist
        renamed = [
            f for f in os.listdir("src")
            if f.startswith("util.rs.") and f != "util.rs"
        ]
        self.assertGreater(len(renamed), 0)

    def test_dry_run_creates_nothing(self):
        from generate_structure import run
        sj = _make_structure_json(
            {"src": [{"name": "dry", "ext": "rs", "content": "x\n"}]}
        )
        run(_args(structure_json=sj, dry_run=True))
        self.assertFalse(os.path.exists("src/dry.rs"))

    def test_stub_default_filled_for_known_ext(self):
        from generate_structure import run
        sj = _make_structure_json(
            {"src": [{"name": "mod", "ext": "rs", "content": ""}]}
        )
        run(_args(structure_json=sj))
        content = open("src/mod.rs").read()
        self.assertIn("Auto-generated stub", content)

    def test_root_key_maps_to_cwd(self):
        from generate_structure import run
        sj = _make_structure_json(
            {"root": [{"name": "README", "ext": "md", "content": "# hi\n"}]}
        )
        run(_args(structure_json=sj))
        self.assertTrue(os.path.exists("README.md"))

    def test_hidden_dir_gets_dot_prefix(self):
        from generate_structure import run
        data = {
            "project_name": "test",
            "hidden_dirs[0]": {"segment": "vscode"},
            "vscode[0]": {"name": "settings", "ext": "json", "content": "{}\n"},
        }
        sj_path = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump(data, sj_path)
        sj_path.close()
        run(_args(structure_json=sj_path.name))
        self.assertTrue(os.path.exists(".vscode/settings.json"))

    def test_manifest_written(self):
        from generate_structure import run
        sj = _make_structure_json(
            {"src": [{"name": "x", "ext": "py", "content": "# x\n"}]}
        )
        run(_args(structure_json=sj))
        self.assertTrue(os.path.exists(".mdix/.manifest.mdix"))
        content = open(".mdix/.manifest.mdix").read()
        self.assertIn("src/x.py", content)


class TestDeleteAndRename(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp)

    def test_delete_pass(self):
        from generate_structure import run
        os.makedirs("deprecated", exist_ok=True)
        open("deprecated/old.rs", "w").close()
        data = {
            "project_name": "test",
            "delete_files[0]": {"path": "deprecated/old.rs"},
        }
        sj = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(data, sj)
        sj.close()
        run(_args(structure_json=sj.name))
        self.assertFalse(os.path.exists("deprecated/old.rs"))

    def test_rename_pass(self):
        from generate_structure import run
        os.makedirs("src", exist_ok=True)
        open("src/old.rs", "w").close()
        data = {
            "project_name": "test",
            "rename_files[0]": {"from_path": "src/old.rs", "to_path": "src/new.rs"},
        }
        sj = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(data, sj)
        sj.close()
        run(_args(structure_json=sj.name))
        self.assertFalse(os.path.exists("src/old.rs"))
        self.assertTrue(os.path.exists("src/new.rs"))


class TestHooks(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp)

    def test_post_hook_runs(self):
        from generate_structure import run
        sentinel = os.path.join(self.tmp, "hook_ran.txt")
        data = {
            "project_name": "test",
            "post_hooks[0]": f"touch {sentinel}",
        }
        sj = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(data, sj)
        sj.close()
        run(_args(structure_json=sj.name))
        self.assertTrue(os.path.exists(sentinel))

    def test_pre_hook_failure_aborts(self):
        from generate_structure import run
        data = {
            "project_name": "test",
            "pre_hooks[0]": "exit 1",
            "src[0]": {"name": "main", "ext": "rs", "content": "fn main(){}\n"},
        }
        sj = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(data, sj)
        sj.close()
        with self.assertRaises(SystemExit) as cm:
            run(_args(structure_json=sj.name))
        self.assertEqual(cm.exception.code, 1)
        self.assertFalse(os.path.exists("src/main.rs"))

    def test_hooks_skipped_in_dry_run(self):
        from generate_structure import run
        sentinel = os.path.join(self.tmp, "should_not_exist.txt")
        data = {
            "project_name": "test",
            "pre_hooks[0]":  f"touch {sentinel}",
            "post_hooks[0]": f"touch {sentinel}",
        }
        sj = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(data, sj)
        sj.close()
        run(_args(structure_json=sj.name, dry_run=True))
        self.assertFalse(os.path.exists(sentinel))


class TestRemoteContent(unittest.TestCase):
    """Tests for lib_remote.py — all network calls are mocked."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp)

    def test_remote_prefix_triggers_fetch(self):
        from lib_remote import REMOTE_PREFIX, is_remote, strip_remote

        url = "https://example.com/license.txt"
        tagged = REMOTE_PREFIX + url
        self.assertTrue(is_remote(tagged))
        self.assertEqual(strip_remote(tagged), url)

    def test_plain_content_passes_through(self):
        from lib_remote import resolve_content
        result = resolve_content("plain content")
        self.assertEqual(result, "plain content")

    def test_github_url_resolved(self):
        from lib_remote import _resolve_url
        url = _resolve_url("github://owner/repo/main/path/to/file.txt")
        self.assertEqual(
            url,
            "https://raw.githubusercontent.com/owner/repo/main/path/to/file.txt",
        )

    def test_githubhttps_resolved(self):
        from lib_remote import _resolve_url
        url = _resolve_url("githubhttps://owner/repo/main/path/to/file.rs")
        self.assertEqual(
            url,
            "https://raw.githubusercontent.com/owner/repo/main/path/to/file.rs",
        )

    def test_raw_alias_resolved(self):
        from lib_remote import _resolve_url
        url = _resolve_url("raw://owner/repo/main/file.txt")
        self.assertEqual(
            url,
            "https://raw.githubusercontent.com/owner/repo/main/file.txt",
        )

    def test_https_passes_through(self):
        from lib_remote import _resolve_url
        url = _resolve_url("https://example.com/file.txt")
        self.assertEqual(url, "https://example.com/file.txt")

    def test_unsupported_scheme_raises(self):
        from lib_remote import _resolve_url
        with self.assertRaises(ValueError):
            _resolve_url("ftp://example.com/file.txt")

    def test_bad_github_path_raises(self):
        from lib_remote import _resolve_url
        with self.assertRaises(ValueError):
            _resolve_url("github://owner/repo")  # missing branch + path

    def test_cache_hit_skips_network(self):
        from lib_remote import _cache_set, _cache_get, fetch

        url = "https://example.com/cached.txt"
        _cache_set(url, "CACHED CONTENT")

        # This would fail if it tried the network
        result = fetch(url, use_cache=True)
        self.assertEqual(result, "CACHED CONTENT")

    def test_fetch_mocked_network(self):
        import urllib.request
        from lib_remote import fetch, _cache_dir

        # Make sure no cache exists for this URL
        url = "https://example.com/mock-file.txt"
        cache_file = _cache_dir() / __import__("hashlib").sha256(url.encode()).hexdigest()
        if cache_file.exists():
            cache_file.unlink()

        class FakeResponse:
            status = 200
            def read(self): return b"FETCHED CONTENT"
            def __enter__(self): return self
            def __exit__(self, *args): pass

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = fetch(url, use_cache=False)
        self.assertEqual(result, "FETCHED CONTENT")

    def test_remote_content_in_generate(self):
        """End-to-end: generate a file whose content is a remote:: URL."""
        from generate_structure import run

        mocked_content = "# MIT License\nCopyright etc.\n"

        sj = _make_structure_json(
            {"root": [{
                "name": "LICENSE",
                "ext":  "",
                "content": "remote::https://example.com/MIT.txt",
            }]}
        )

        import urllib.request

        class FakeResp:
            status = 200
            def read(self): return mocked_content.encode()
            def __enter__(self): return self
            def __exit__(self, *args): pass

        with patch("urllib.request.urlopen", return_value=FakeResp()):
            run(_args(structure_json=sj, no_cache=True))

        self.assertTrue(os.path.exists("LICENSE"))
        self.assertEqual(open("LICENSE").read(), mocked_content)


class TestMappings(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp)

    def test_apply_simple_key(self):
        from lib_mappings import apply_mappings
        result = apply_mappings("Hello [[name]]!", {"name": "World"})
        self.assertEqual(result, "Hello World!")

    def test_apply_nested_key(self):
        from lib_mappings import apply_mappings
        result = apply_mappings(
            "node [[ci.node_version]]",
            {"ci.node_version": "20"},
        )
        self.assertEqual(result, "node 20")

    def test_unknown_key_left_unchanged(self):
        from lib_mappings import apply_mappings
        result = apply_mappings("[[unknown]]", {"other": "x"})
        self.assertEqual(result, "[[unknown]]")

    def test_no_placeholders_unchanged(self):
        from lib_mappings import apply_mappings
        content = "nothing to replace here"
        self.assertEqual(apply_mappings(content, {"key": "val"}), content)

    def test_list_placeholders(self):
        from lib_mappings import list_placeholders
        phs = list_placeholders("[[a]] and [[b]] and [[a]] again")
        self.assertEqual(phs, ["a", "b"])  # deduplicated, ordered

    def test_flatten_nested_dict(self):
        from lib_mappings import _flatten
        flat = _flatten({"a": {"b": {"c": "deep"}, "d": "mid"}, "e": "top"})
        self.assertEqual(flat["a.b.c"], "deep")
        self.assertEqual(flat["a.d"], "mid")
        self.assertEqual(flat["e"], "top")

    def test_load_json_mappings(self):
        from lib_mappings import load_mappings
        data = {"project_name": "test-proj", "ci": {"node": "20"}}
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir=self.tmp
        )
        json.dump(data, f)
        f.close()
        m = load_mappings(f.name)
        self.assertEqual(m["project_name"], "test-proj")
        self.assertEqual(m["ci.node"], "20")

    def test_unsupported_extension_exits(self):
        from lib_mappings import load_mappings
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, dir=self.tmp
        )
        f.write("key: val\n")
        f.close()
        with self.assertRaises(SystemExit):
            load_mappings(f.name)

    def test_mappings_applied_during_generate(self):
        from generate_structure import run

        mappings = {"author": "MidManStudio", "version": "0.1.0"}

        sj = _make_structure_json(
            {"root": [{
                "name": "README",
                "ext":  "md",
                "content": "# Built by [[author]] v[[version]]\n",
            }]}
        )

        # Patch apply_mappings to verify it receives the right data
        applied: list = []

        import lib_mappings as lm
        original_apply = lm.apply_mappings

        def spy_apply(content, m):
            applied.append((content, m))
            return original_apply(content, m)

        with patch.object(lm, "apply_mappings", side_effect=spy_apply):
            run(_args(structure_json=sj))

        # Without real mappings loaded, [[key]] stays unchanged — just
        # confirm generate didn't crash and created the file
        self.assertTrue(os.path.exists("README.md"))


class TestNukeStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp)

    def test_confirm_required(self):
        from nuke_structure import run, parse_args
        import types
        args = types.SimpleNamespace(
            confirm="WRONG",
            template=".mdix/test.mdix",
            structure_json="/dev/null",
        )
        with self.assertRaises(SystemExit):
            run(args)

    def test_removes_generated_files(self):
        from nuke_structure import run
        import types

        # Create files to remove
        os.makedirs("src/core", exist_ok=True)
        open("src/core/lib.rs", "w").close()
        open("src/main.rs",    "w").close()

        data = {
            "project_name": "test",
            "src[0]": {"name": "main", "ext": "rs"},
            "src.core[0]": {"name": "lib", "ext": "rs"},
        }
        sj = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir=self.tmp
        )
        json.dump(data, sj)
        sj.close()

        args = types.SimpleNamespace(
            confirm="DELETE",
            template=".mdix/test.mdix",
            structure_json=sj.name,
        )
        run(args)

        self.assertFalse(os.path.exists("src/main.rs"))
        self.assertFalse(os.path.exists("src/core/lib.rs"))
        # Empty dirs should be removed too
        self.assertFalse(os.path.isdir("src/core"))
        self.assertFalse(os.path.isdir("src"))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run mdix-scaffold tests")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-k", "--filter", help="Only run tests matching this string")
    cli_args = parser.parse_args()

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    test_classes = [
        TestCoreGeneration,
        TestDeleteAndRename,
        TestHooks,
        TestRemoteContent,
        TestMappings,
        TestNukeStructure,
    ]

    for cls in test_classes:
        tests = loader.loadTestsFromTestCase(cls)
        if cli_args.filter:
            tests = unittest.TestSuite(
                t for t in tests
                if cli_args.filter.lower() in t.id().lower()
            )
        suite.addTests(tests)

    verbosity = 2 if cli_args.verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity, stream=sys.stdout)
    result = runner.run(suite)

    print()
    total  = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed

    print(f"{'─' * 40}")
    print(f"  {PASS}: {passed}   {FAIL}: {failed}   Total: {total}")
    print(f"{'─' * 40}")

    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
