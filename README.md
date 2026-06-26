# mdix-scaffold

[**Read the Docs**](https://dixscript-docs.pages.dev) | [**DixScript Core**](https://github.com/Mid-D-Man/DixScript-Rust)

Declarative, idempotent project structure generator using
[DixScript](https://github.com/Mid-D-Man/DixScript-Rust) `.mdix` files.

Define your layout once. Run a workflow or a local CLI command.
Only new entries are added — existing files are never touched by default.

---

## Quickstart

### Option A — Use as a reusable workflow (no fork required)

Create one file in your repo:

**`.github/workflows/generate-structure.yml`**
```yaml
name: Generate project structure

on:
  workflow_dispatch:
    inputs:
      override_stubs:
        description: 'Overwrite existing stubs (true/false)'
        required: false
        default: 'false'
      dry_run:
        description: 'Preview without writing (true/false)'
        required: false
        default: 'false'
  push:
    paths:
      - '.mdix/**'

jobs:
  generate:
    uses: Mid-D-Man/mdix-scaffold/.github/workflows/generate-structure.yml@main
    permissions:
      contents: write
    with:
      template:       '.mdix/project_structure/project_structure.mdix'
      override_stubs: ${{ inputs.override_stubs || 'false' }}
      dry_run:        ${{ inputs.dry_run || 'false' }}
```

Then add your `.mdix/project_structure/project_structure.mdix` and push.
The workflow triggers automatically on every push to that path.

### Option B — Fork this repo

Fork mdix-scaffold, edit the template, run workflows from the Actions tab.

### Option C — Local CLI

```bash
# Requires Node.js >= 18 and Python 3
git clone https://github.com/Mid-D-Man/mdix-scaffold.git
cd mdix-scaffold

# Install mdix CLI from source (one-time, ~3 min)
node bin/mdix-scaffold.js setup

# Generate from the default template
node bin/mdix-scaffold.js generate

# Dry run — see what would change
node bin/mdix-scaffold.js generate --dry-run

# Dry run with unified diffs
node bin/mdix-scaffold.js generate --dry-run --diff

# Use a project template
node bin/mdix-scaffold.js generate \
  --template .mdix/project_structure/templates/rust-lib.mdix

# Apply mappings ([[key]] substitution)
node bin/mdix-scaffold.js generate \
  --mappings .mdix/env/mappings.mdix

# Remove everything that was generated
node bin/mdix-scaffold.js nuke --confirm DELETE
```

---

## How the mdix CLI is sourced

**GitHub Actions (no local setup needed):**

1. Checks a weekly binary cache for the `mdix` CLI
2. Cache miss — clones [DixScript-Rust](https://github.com/Mid-D-Man/DixScript-Rust),
   runs `cargo build -p mdix-cli --release`, saves to cache (~3 min, once per week)
3. Cache hit — skips the build entirely (seconds)

**Local CLI:**

```bash
node bin/mdix-scaffold.js setup          # builds from source once
node bin/mdix-scaffold.js setup --force  # rebuild
```

The binary is stored in `bin/mdix` and used automatically.

---

## Template syntax

All templates live in `.mdix/project_structure/`.

### QuickFuncs

| Function | What it creates |
|---|---|
| `f(name, ext)` | Stub file — content from built-in extension default |
| `fc(name, ext, content)` | File with explicit starting content |
| `fremote(name, ext, url)` | File fetched from a URL at generation time (cached) |
| `gitkeep()` | `.gitkeep` to keep empty directories in git |
| `hidden(segment)` | Marks a key segment as dot-prefixed on disk |
| `delete_file(path)` | Delete before create pass |
| `rename(src, dst)` | Rename after deletes, before creates |
| `move(src, dst)` | Cross-filesystem move (after renames, before creates) |
| `update(path, content)` | Always-overwrite after renames/moves |

### Remote URL formats (for `fremote`)

```
https://example.com/file.txt
github://owner/repo/branch/path/to/file.ext
githubhttps://owner/repo/branch/path/to/file.ext
raw://owner/repo/branch/path/to/file.ext
```

Remote content is cached in `~/.mdix-scaffold/cache/`.
Clear it with `mdix-scaffold clear-cache`.

### Mappings (`[[key]]` substitution)

Create a mappings file at `.mdix/env/mappings.mdix`:

```dixscript
@DATA(
  project_name = "my-app"
  author       = "YourName"
  ci: node_version = "20", rust_toolchain = "stable"
)
```

Then in any template content string, use `[[key]]` or `[[section.key]]`:

```dixscript
fc("README", "md", "# [[project_name]]\nBuilt by [[author]]\n")
fc("ci", "yml", "node-version: [[ci.node_version]]")
```

Run with:

```bash
mdix-scaffold generate --mappings .mdix/env/mappings.mdix
```

### Hooks

Add pre/post shell commands to your template's `@DATA` section:

```dixscript
pre_hooks::
  "echo 'Starting...'"
  "cargo fetch"

post_hooks::
  "cargo fmt"
  "echo 'Done'"
```

Pre-hook failure aborts generation. Post-hook failure prints a warning.

### Directory group syntax

| Key | Disk path |
|---|---|
| `root` | `./` (repository root) |
| `src` | `src/` |
| `src.core` | `src/core/` |
| `vscode` + hidden | `.vscode/` |
| `github.workflows` + hidden | `.github/workflows/` |

### Stub defaults

| Extension(s) | Default content |
|---|---|
| `rs` `cs` `ts` `js` `go` `java` `cpp` `c` `h` `hpp` `kt` `swift` | `// Auto-generated stub` |
| `py` | `# Auto-generated stub` |
| `lua` | `-- Auto-generated stub` |
| `sh` `bash` | `#!/usr/bin/env bash` + `set -euo pipefail` |
| `yml` `yaml` | `# Auto-generated stub` |
| `md` | `# filename` |
| `json` | `{}` |
| `toml` | `# Auto-generated config` |
| `html` | Minimal HTML5 |
| `css` | `/* Auto-generated stub */` |

---

## File strategies

Control how existing files are handled with `--file-strategy`:

| Strategy | Behaviour |
|---|---|
| `skip` (default) | Leave existing files untouched |
| `overwrite` | Always overwrite (same as `--override-stubs`) |
| `backup` | Copy existing to `--backup <dir>`, then overwrite |
| `rename` | Rename existing with a timestamp suffix, then write |

---

## Operation passes (execution order)

All operations in your `@DATA` block run in a fixed order regardless of where you declare them:

1. **`delete_files::`** — remove stale files or directories
2. **`rename_files::`** — rename files or directories (same filesystem)
3. **`move_files::`** — cross-filesystem move (shutil.move)
4. **Scaffold creation** — create new files from directory groups
5. **`update_files::`** — always-overwrite specified files
6. **`patch_files::`** — surgical edits to existing files

---

## Move files

`move_files::` uses Python's `shutil.move`, which handles cross-filesystem moves and directory trees safely. Use this when moving between devices or volumes, or when moving whole subdirectories.

```dixscript
move_files::
  move("src/utils/helper.rs", "src/core/helper.rs")
  move("lib/shared/", "src/shared/")
```

- Parent directories are created automatically
- Source not found → skipped with a warning, not an error

Use `rename_files::` for simple within-filesystem renames (it uses `os.rename`, which is atomic). Use `move_files::` for everything else.

---

## Surgical patch operations

`patch_files::` runs last — after all files exist — and edits them in-place. Each operation re-reads the file from disk, so a sequence of patches on the same file compound correctly.

**Anchor matching is whitespace-normalised**: leading/trailing whitespace and internal runs of whitespace are collapsed before comparison, so indentation differences don't cause misses.

**Multiple anchor matches**: if an anchor matches more than one line, mdix warns and uses the first match. Add `match_index` (0-based) to target a specific occurrence.

Always preview patch operations with `--dry-run --diff` before applying.

---

### Insert

```dixscript
patch_files::

  // Insert a line immediately AFTER the anchor line:
  patch_insert_after("src/lib.rs", "use std::io;", "use std::fs;\n")

  // Insert immediately BEFORE the anchor line:
  patch_insert_before("src/lib.rs", "pub fn process(", "/// Process data.\n")

  // Target the Nth occurrence (0-based) of a repeated anchor:
  patch_insert_after_n("src/lib.rs", "use crate::", "use crate::new_mod;\n", 2)
  patch_insert_before_n("src/lib.rs", "pub fn", "// injected\n", 1)
```

> **Note:** Always include `\n` at the end of inserted content. The patcher does not inject newlines automatically.

---

### Replace

#### Replace text or line

```dixscript
patch_files::

  // Mode 1 — exact literal substring replace (replaces only the matching chars):
  patch_replace_text("src/lib.rs", "fn old_name(", "fn new_name(")

  // Mode 2 — whole-line replace (when anchor matches the full normalised line):
  patch_replace_text("src/lib.rs", "let version = \"1.0\"", "    let version = \"2.0\";\n")

  // Target the Nth matching line (0-based):
  patch_replace_text_n("src/lib.rs", "let x =", "    let x = new_val;", 1)
```

#### Replace a line range

```dixscript
patch_files::

  // 1-indexed, inclusive. Verify line numbers with --dry-run first:
  patch_replace_lines("src/lib.rs", 10, 25, "// replaced block\n")
```

#### Replace a character range

```dixscript
patch_files::

  // 0-indexed, exclusive end. Most precise option.
  // Always run --dry-run before applying — offsets shift with every edit:
  patch_replace_range("src/lib.rs", 500, 750, "// replaced range\n")
```

#### Replace an entire function definition

```dixscript
patch_files::

  // Curly-brace languages use brace-balanced detection.
  // Python uses indentation-based detection.
  patch_replace_fn("src/lib.rs", "old_function",
    "fn old_function() -> u32 {\n    42\n}\n")
```

#### Replace a block between two anchors

```dixscript
patch_files::

  // Both anchor lines are INCLUDED in the replacement:
  patch_replace_block("src/lib.rs",
    "// BEGIN_GENERATED", "// END_GENERATED",
    "// BEGIN_GENERATED\npub fn generated() {}\n// END_GENERATED\n")

  // Both anchor lines are KEPT; only the content between them is replaced:
  patch_replace_block_keep("src/lib.rs",
    "// BEGIN_GENERATED", "// END_GENERATED",
    "pub fn generated() {}\n")
```

`patch_replace_block_keep` is the safer default when your anchors are permanent markers — it's impossible to accidentally lose them.

#### Replace with regex

```dixscript
patch_files::

  // First match (default):
  patch_replace_regex("src/main.rs", "version = \"[^\"]+\"", "version = \"2.0.0\"")

  // With flags  (i = IGNORECASE,  m = MULTILINE,  s = DOTALL,  combinable):
  patch_replace_regex_f("src/lib.rs", "pub fn \\w+", "pub fn renamed", "i")

  // Nth match (0-based):
  patch_replace_regex_n("src/lib.rs", "\\btodo!\\(\\)", "unimplemented!()", 2)

  // Flags + Nth match:
  patch_replace_regex_fn("src/lib.rs", "pub fn \\w+", "pub fn renamed", "im", 1)

  // Capture groups in replacement content (\1 \2 or \g<1> \g<2>):
  patch_replace_regex_f("Cargo.toml",
    "(version\\s*=\\s*\")([^\"]+)(\")", "\\g<1>2.0.0\\3", "m")
```

---

### Delete

```dixscript
patch_files::

  // Delete the first line matching the anchor:
  patch_delete_text("src/lib.rs", "// TODO: remove this line")

  // Delete the Nth matching line (0-based):
  patch_delete_text_n("src/lib.rs", "#[allow(dead_code)]", 0)

  // Delete a range of lines (1-indexed inclusive):
  patch_delete_lines("src/lib.rs", 10, 15)

  // Delete an entire function definition:
  patch_delete_fn("src/lib.rs", "legacy_function")
```

---

## Patch safety contract

| Condition | Behaviour |
|---|---|
| Zero anchor matches | Error printed, op skipped |
| Multiple anchor matches | Warning with line numbers printed, first (or `match_index`-th) used |
| `match_index` out of range | Error printed, op skipped |
| Bad regex pattern | Error printed, op skipped |
| Unbalanced braces (replace_fn) | Error printed, op skipped |
| Source file missing | Error printed, op skipped |

No patch operation will crash the whole run — errors are reported and that op is skipped, but subsequent patches continue.

---

## Full example template

```dixscript
@CONFIG(
  version    -> "1.0.0"
  author     -> "YourName"
  features   -> "quickfuncs,data"
  debug_mode -> "off"
)

@QUICKFUNCS(
  ~f<object>(name, ext)                  { return { name = name, ext = ext, content = "" } }
  ~fc<object>(name, ext, content)        { return { name = name, ext = ext, content = content } }
  ~gitkeep<object>()                     { return { name = ".gitkeep", ext = "", content = "" } }
  ~hidden<object>(segment)               { return { segment = segment } }
  ~delete_file<object>(path)             { return { path = path } }
  ~rename<object>(src, dst)              { return { from_path = src, to_path = dst } }
  ~move<object>(src, dst)                { return { from_path = src, to_path = dst } }
  ~update<object>(path, content)         { return { path = path, content = content } }
  ~patch_insert_after<object>(path, anchor, content) {
    return { path = path, op = "insert_after", anchor = anchor, content = content }
  }
  ~patch_replace_text<object>(path, anchor, content) {
    return { path = path, op = "replace_text", anchor = anchor, content = content }
  }
  ~patch_replace_block_keep<object>(path, start_anchor, end_anchor, content) {
    return {
      path         = path
      op           = "replace_block"
      start_anchor = start_anchor
      end_anchor   = end_anchor
      content      = content
      keep_anchors = "true"
    }
  }
  ~patch_delete_fn<object>(path, fn_name) {
    return { path = path, op = "delete_function", fn_name = fn_name }
  }
)

@DATA(
  project_name = "my-project"
  author       = "YourName"

  hidden_dirs::
    hidden("vscode")
    hidden("github")

  pre_hooks::
    "echo 'Starting scaffold'"

  post_hooks::
    "cargo fmt"

  delete_files::
    delete_file("deprecated/old_module.rs")

  move_files::
    move("src/utils/helper.rs", "src/core/helper.rs")

  update_files::
    update("src/version.rs", "pub const VERSION: &str = \"2.0.0\";\n")

  patch_files::
    patch_insert_after("src/lib.rs", "use std::io;", "use std::fs;\n")
    patch_replace_text("Cargo.toml", "version = \"1.0.0\"", "version = \"2.0.0\"")
    patch_replace_block_keep("src/lib.rs",
      "// BEGIN_ROUTES", "// END_ROUTES",
      "pub fn routes() -> Vec<Route> { vec![] }\n")
    patch_delete_fn("src/lib.rs", "legacy_init")

  vscode::
    fc("settings", "json", "{\n}\n")

  github.workflows::
    fc("ci", "yml", "name: CI\non:\n  push:\n    branches: [main]\n")

  src::
    fc("main", "rs", "fn main() {\n    println!(\"Hello, [[project_name]]!\");\n}\n")

  src.core::
    f("mod",  "rs")
    f("lib",  "rs")

  root::
    fc("README",     "md",  "# [[project_name]]\n\nBy [[author]]\n")
    fc(".gitignore", "",    "target/\n.env\n.DS_Store\n")
    fc("Cargo",      "toml","[package]\nname = \"[[project_name]]\"\nversion = \"0.1.0\"\nedition = \"2021\"\n\n[dependencies]\n")
)
```

---

## CLI reference

```bash
node bin/mdix-scaffold.js setup                              # build mdix from source
node bin/mdix-scaffold.js setup --force                     # force rebuild
node bin/mdix-scaffold.js generate                          # run default template
node bin/mdix-scaffold.js generate --dry-run                # preview only
node bin/mdix-scaffold.js generate --dry-run --diff         # preview + unified diffs
node bin/mdix-scaffold.js generate --template <path>        # custom template
node bin/mdix-scaffold.js generate --mappings <path>        # [[key]] substitution
node bin/mdix-scaffold.js generate --file-strategy overwrite
node bin/mdix-scaffold.js generate --file-strategy backup --backup /tmp/bak
node bin/mdix-scaffold.js generate --file-strategy rename
node bin/mdix-scaffold.js generate --clear-cache            # clear remote fetch cache
node bin/mdix-scaffold.js nuke --confirm DELETE             # remove all generated files
```

---

## GitHub Actions workflow inputs

| Input | Default | Description |
|---|---|---|
| `template` | `.mdix/project_structure/project_structure.mdix` | Path to `.mdix` template |
| `override_stubs` | `false` | Overwrite existing stub files |
| `dry_run` | `false` | Preview without writing |
| `file_strategy` | `skip` | `skip` / `overwrite` / `backup` / `rename` |
| `mappings_file` | _(blank)_ | Path to mappings file for `[[key]]` substitution |
