# SKILL: mdix-scaffold

## What This Is

`mdix-scaffold` is a declarative, idempotent project-structure generator that uses DixScript `.mdix` files. It has three operating modes:

- **Option A — Reusable workflow** (no fork): add one `.github/workflows/generate-structure.yml` to any repo calling `Mid-D-Man/mdix-scaffold/.github/workflows/generate-structure.yml@main`
- **Option B — Fork** the repo and edit templates directly
- **Option C — Local CLI**: `node bin/mdix-scaffold.js generate`

---

## File Layout (in the consuming repo)

```
.mdix/
  project_structure/
    project_structure.mdix        ← main template (default)
    templates/
      rust-lib.mdix               ← example named template
  env/
    mappings.mdix                 ← [[key]] substitution values
  .manifest.mdix                  ← auto-generated; tracks created files
.github/
  workflows/
    generate-structure.yml        ← calls the reusable workflow
```

---

## .mdix File Anatomy

Every template has three sections:

```dixscript
@CONFIG(
  version    -> "1.0.0"
  author     -> "YourName"
  features   -> "quickfuncs,data"
  debug_mode -> "off"
)

@QUICKFUNCS(
  // function definitions — copy verbatim from template, don't edit
)

@DATA(
  // this is where you declare EVERYTHING:
  // metadata, hidden dirs, hooks, file operations, directory groups
)
```

---

## @DATA Keys (order matters — operations run in passes)

### Metadata

```dixscript
project_name = "my-project"
description  = "Short description"
author       = "YourName"
```

### Hidden Directories (dot-prefix on disk)

```dixscript
hidden_dirs::
  hidden("vscode")     // → .vscode/
  hidden("github")     // → .github/
```

### Hooks

```dixscript
pre_hooks::            // failure aborts generation
  "echo 'Starting'"
  "cargo fetch"

post_hooks::           // failure is warning only
  "cargo fmt"
```

### Directory Groups (file creation)

```dixscript
// Key maps to disk path:
//   root         → ./
//   src          → src/
//   src.core     → src/core/
//   github.workflows + hidden("github") → .github/workflows/

src::
  f("main", "rs")                              // stub file
  fc("lib", "rs", "pub fn hello() {}\n")       // file with content
  fremote("config", "toml", "https://example.com/base.toml")  // fetched
  gitkeep()                                    // .gitkeep
```

---

## QuickFuncs Reference

| Function | Creates |
|---|---|
| `f(name, ext)` | Stub file — built-in default content for extension |
| `fc(name, ext, content)` | File with explicit content |
| `fremote(name, ext, url)` | File fetched from URL at generation time |
| `gitkeep()` | `.gitkeep` to preserve empty dirs in git |
| `hidden(segment)` | Marks a directory segment as dot-prefixed |
| `delete_file(path)` | Delete path before create pass |
| `rename(src, dst)` | Rename after deletes, before creates |
| `move(src, dst)` | Cross-filesystem move (shutil.move) |
| `update(path, content)` | Always-overwrite after renames |

---

## File Operation Passes (execution order)

1. **delete_files::** — remove stale files/dirs
2. **rename_files::** — rename files/dirs
3. **move_files::** — cross-filesystem moves
4. **scaffold creation** — create new files (directory groups)
5. **update_files::** — always-overwrite specified files
6. **patch_files::** — surgical edits to existing files

---

## Move Files

```dixscript
move_files::
  move("src/utils/helper.rs", "src/core/helper.rs")
  move("lib/shared/", "src/shared/")
```

- Uses `shutil.move` — works across filesystems
- Parent directories created automatically
- Source not found → skipped with a warning

---

## Update Files

```dixscript
update_files::
  update("src/main.rs", "fn main() {\n    println!(\"v2\");\n}\n")
```

- Always overwrites, even if file already exists
- Creates the file if it doesn't exist yet
- Runs after scaffold creation, before patches

---

## Patch Files — All Operations

All patches go in `patch_files::` and run AFTER update_files.

**Anchor matching is whitespace-normalised.** Multiple matches → warn + use first (or specify `match_index` to target Nth, 0-based).

### Insert

```dixscript
// Insert immediately AFTER the line containing anchor:
patch_insert_after("src/lib.rs", "use std::io;", "use std::fs;\n")

// Insert BEFORE the matching line:
patch_insert_before("src/lib.rs", "pub fn process(", "/// Process data.\n")

// Target the Nth occurrence (0-based):
patch_insert_after_n("src/lib.rs", "use crate::", "use crate::new_mod;\n", 2)
patch_insert_before_n("src/lib.rs", "pub fn", "// auto-inserted\n", 1)
```

### Replace Text / Line

```dixscript
// Mode 1 — exact literal substring replace:
patch_replace_text("src/lib.rs", "fn old_name(", "fn new_name(")

// Mode 2 — whole-line replace (when anchor matches the whole normalised line):
patch_replace_text("src/lib.rs", "let version = \"1.0\"", "let version = \"2.0\";\n")

// Target the Nth match:
patch_replace_text_n("src/lib.rs", "let x =", "    let x = new_val;", 1)
```

### Replace Line Range

```dixscript
// 1-indexed inclusive; verify line numbers with --dry-run first:
patch_replace_lines("src/lib.rs", 10, 25, "// replaced block\n")
```

### Replace Character Range

```dixscript
// 0-indexed, exclusive end; most precise — always --dry-run first:
patch_replace_range("src/lib.rs", 500, 750, "// replaced range\n")
```

### Replace Entire Function

```dixscript
// Curly-brace langs: brace-balanced detection
// Python: indentation-based detection
patch_replace_fn("src/lib.rs", "old_function",
  "fn old_function() -> u32 {\n    42\n}\n")
```

### Replace Block Between Anchors

```dixscript
// Both anchor lines REPLACED:
patch_replace_block("src/lib.rs",
  "// BEGIN_GENERATED", "// END_GENERATED",
  "// BEGIN_GENERATED\npub fn generated() {}\n// END_GENERATED\n")

// Both anchor lines KEPT, only content between them replaced:
patch_replace_block_keep("src/lib.rs",
  "// BEGIN_GENERATED", "// END_GENERATED",
  "pub fn generated() {}\n")
```

### Replace with Regex

```dixscript
// First match (default):
patch_replace_regex("src/main.rs", "version = \"[^\"]+\"", "version = \"2.0.0\"")

// With flags (i=IGNORECASE, m=MULTILINE, s=DOTALL, combinable):
patch_replace_regex_f("src/lib.rs", "pub fn \\w+", "pub fn renamed", "i")

// Nth match (0-based):
patch_replace_regex_n("src/lib.rs", "\\btodo!\\(\\)", "unimplemented!()", 2)

// Flags + Nth match:
patch_replace_regex_fn("src/lib.rs", "pub fn \\w+", "pub fn renamed", "im", 1)

// Capture groups in replacement (\1 \2 or \g<1> \g<2>):
patch_replace_regex_f("Cargo.toml",
  "(version\\s*=\\s*\")([^\"]+)(\")", "\\g<1>2.0.0\\3", "m")
```

### Delete

```dixscript
// Delete the first line matching anchor:
patch_delete_text("src/lib.rs", "// TODO: remove this line")

// Delete the Nth matching line (0-based):
patch_delete_text_n("src/lib.rs", "#[allow(dead_code)]", 0)

// Delete a line range (1-indexed inclusive):
patch_delete_lines("src/lib.rs", 10, 15)

// Delete an entire function definition:
patch_delete_fn("src/lib.rs", "legacy_function")
```

---

## Mappings (`[[key]]` Substitution)

Create `.mdix/env/mappings.mdix`:

```dixscript
@DATA(
  project_name = "my-app"
  author       = "YourName"
  ci: node_version = "20", rust_toolchain = "stable"
)
```

Use in any template content string:

```dixscript
fc("README", "md", "# [[project_name]]\nBy [[author]]\n")
fc("ci", "yml", "node-version: [[ci.node_version]]\n")
```

Run with `--mappings .mdix/env/mappings.mdix`.

---

## Remote URL Formats (for `fremote`)

```
https://example.com/file.txt
github://owner/repo/branch/path/to/file.ext
githubhttps://owner/repo/branch/path/to/file.ext
raw://owner/repo/branch/path/to/file.ext
```

Remote content is cached in `~/.mdix-scaffold/cache/`. Clear with `mdix-scaffold clear-cache`.

---

## File Strategies (how existing files are handled)

| Strategy | Behaviour |
|---|---|
| `skip` (default) | Leave existing files untouched |
| `overwrite` | Always overwrite (same as `--override-stubs`) |
| `backup` | Copy existing to `--backup <dir>`, then overwrite |
| `rename` | Rename existing with timestamp suffix, then write |

---

## CLI Quick Reference

```bash
# Requires Node.js >= 18 and Python 3
git clone https://github.com/Mid-D-Man/mdix-scaffold.git
cd mdix-scaffold

# One-time setup (builds mdix CLI from Rust source, ~3 min)
node bin/mdix-scaffold.js setup

# Generate from default template
node bin/mdix-scaffold.js generate

# Dry run — see what would change
node bin/mdix-scaffold.js generate --dry-run

# Dry run with unified diffs
node bin/mdix-scaffold.js generate --dry-run --diff

# Custom template
node bin/mdix-scaffold.js generate \
  --template .mdix/project_structure/templates/rust-lib.mdix

# With mappings
node bin/mdix-scaffold.js generate \
  --mappings .mdix/env/mappings.mdix

# File strategy
node bin/mdix-scaffold.js generate \
  --file-strategy backup --backup /tmp/bak

# Remove everything that was generated
node bin/mdix-scaffold.js nuke --confirm DELETE
```

---

## GitHub Actions Workflow (Option A — no fork)

```yaml
# .github/workflows/generate-structure.yml
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

---

## Stub Defaults (what `f(name, ext)` produces)

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
| `html` | Minimal HTML5 boilerplate |
| `css` | `/* Auto-generated stub */` |

---

## Common Mistakes

- **Forgetting `\n` in patch content** — the patcher does not inject newlines automatically. Every piece of inserted content must end with `\n`.
- **Using move when rename suffices** — `rename` is for same-filesystem moves; `move` handles cross-filesystem. Both work same-FS, but `move` is more robust.
- **Regex on Cargo.toml without `m` flag** — `version = "…"` can appear anywhere; use `m` (MULTILINE) so `^` and `$` behave per-line.
- **Skipping `--dry-run` before `patch_replace_range`** — character offsets shift with every edit; always preview first.
- **Not including anchor lines in `patch_replace_block` content** — if you want them back, include them in the replacement content, or use `patch_replace_block_keep` instead.
- **Stacking patch_files ops on the same file** — they run sequentially on disk; each op re-reads the file. This is fine, but keep op order in mind.
