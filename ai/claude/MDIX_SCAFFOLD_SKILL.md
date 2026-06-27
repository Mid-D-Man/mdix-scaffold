# SKILL: mdix-scaffold

## What This Is

`mdix-scaffold` is a declarative, idempotent project-structure generator that uses DixScript `.mdix` files. It has three operating modes:

- **Option A — Reusable workflow** (no fork): add a small caller workflow to any repo calling `Mid-D-Man/mdix-scaffold/.github/workflows/generate-structure.yml@main`
- **Option B — Fork** the repo and edit templates directly
- **Option C — Local CLI**: `node bin/mdix-scaffold.js generate`

---

## Two Template Kinds — Fixed Names, Fixed Paths

There are exactly two kinds of `.mdix` template, and the name/path for each is not negotiable — tooling, manifest tracking, and this skill all assume them:

| Kind | Path | Purpose |
|---|---|---|
| Structure generation | `.mdix/project_structure/project_structure.mdix` | Scaffold a project from scratch / keep its shape in sync |
| Patch | `.mdix/patches/patch.mdix` | One-off surgical fix to an existing repo (moves, renames, content edits) |

Never invent a different filename or folder for either kind. If a repo needs more than one patch over time, that's still one `patch.mdix` — overwrite its contents for the next surgical pass, it isn't meant to accumulate as a history.

---

## File Layout (in the consuming repo).mdix/
project_structure/
project_structure.mdix ← structure template
templates/
rust-lib.mdix ← example named template
patches/
patch.mdix ← one-off surgical fixes
env/
mappings.mdix ← [[key]] substitution values
.manifest.mdix ← auto-generated; tracks created files (shared, template-scoped — see Manifests below)
.github/
workflows/
run-structure.yml ← calls the reusable workflow for project_structure.mdix
run-patch.yml ← calls the reusable workflow for patch.mdix**Rule: never hand off a `.mdix` template without its workflow.** If the consuming repo doesn't already have the matching `.github/workflows/*.yml`, write it in the same response as the template. A template nobody can run isn't a finished deliverable.

---

## .mdix File Anatomy

```dixscript
// Brought to u by MidManStudio

@CONFIG(
  version    -> "1.0.0"
  author     -> "YourName"
  features   -> "quickfuncs,data"
  debug_mode -> "off"
)

@QUICKFUNCS(
  // ONLY the functions this template's @DATA actually calls — see below
)

@DATA(
  // this is where you declare EVERYTHING:
  // metadata, hidden dirs, hooks, file operations, directory groups
)
```

### Only define what you call

Before writing `@QUICKFUNCS`, scan the `@DATA` section you're about to write and list every scaffold function it calls — `move`, `update`, `patch_replace_text`, `fc`, whatever it is. Paste in definitions for exactly those, nothing more. Don't carry the entire reference block from the writing skill into every template "just in case" — an unused `patch_delete_fn` definition sitting in a file that never calls it is noise, and it makes the file lie about what it actually touches.

This also means: if your template needs repeated path prefixes, write small helper QuickFuncs for them (see the writing skill's "Nested Function Calls & String Building") and use `_param`-prefixed parameter names throughout, same as everywhere else in DixScript.

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

Dotted keys only map to literal path segments containing no dots of their own. A package folder literally named `com.example.lib` can't be reached via a dotted key — use `update()`/`move()` with a full literal (or helper-built) path instead; they take any string, not a dotted key.

---

## QuickFuncs Reference

Pull individual entries from this table into a template's `@QUICKFUNCS` — never paste the whole table (see "Only define what you call" above).

| Function | Creates |
|---|---|
| `f(_name, _ext)` | Stub file — built-in default content for extension |
| `fc(_name, _ext, _content)` | File with explicit content |
| `fremote(_name, _ext, _url)` | File fetched from URL at generation time |
| `gitkeep()` | `.gitkeep` to preserve empty dirs in git |
| `hidden(_segment)` | Marks a directory segment as dot-prefixed |
| `delete_file(_path)` | Delete path before create pass |
| `rename(_src, _dst)` | Rename after deletes, before creates |
| `move(_src, _dst)` | Cross-filesystem move (shutil.move) |
| `update(_path, _content)` | Always-overwrite after renames |

---

## File Operation Passes (execution order)

1. **PASS 1 — Prune stale manifest-tracked files.** Gated behind `--prune` / `PRUNE_STALE=true`. **OFF by default.** See "Stale-File Pruning" below — this is its own section because getting the default wrong here means silent, unattended file deletion.
2. **delete_files::** — remove explicitly-listed stale files/dirs
3. **rename_files::** — rename files/dirs
4. **move_files::** — cross-filesystem moves
5. **scaffold creation** — create new files (directory groups)
6. **update_files::** — always-overwrite specified files
7. **patch_files::** — surgical edits to existing files

---

## Stale-File Pruning (`--prune` / `PRUNE_STALE`)

PASS 1 compares the manifest's `previously_created` file list against everything the *current* template still declares across every pass (directory groups, `update_files`, `move_files`/`rename_files` destinations, `patch_files` targets) and can delete whatever's left over — i.e. files a past run created that this run's template no longer mentions.

**This is opt-in, off by default, full stop.** Straight from the script's own comment:

> OFF by default. The scaffold is a generator, not a sync tool. Stale-file deletion must be explicitly opted into; it must never happen as a side-effect of simplifying or patching a template.

**Rule: never set `--prune` / `PRUNE_STALE` to default `true` anywhere** — not in a workflow's `workflow_dispatch` default, not in an env var fallback, not in a CLI wrapper script. If you ever expose it as a workflow input, the dropdown default is `'false'`, same as `override_stubs`. The person opts in by hand, every time, on purpose.

When stale files exist and `--prune` is off, the run just prints a note (`--verbose` lists them) and does nothing destructive. Nothing gets deleted by accident just because a template got smaller.

---

## Manifests Are Template-Scoped

`.mdix/.manifest.mdix` is one shared file on disk, written after every non-dry-run generation, and it records which template produced it. When a run starts, it checks that stored `template` field against the template you're currently running — on a mismatch it treats the run as a first run and does **not** inherit the other template's file list.

Practically: `project_structure.mdix` and `patches/patch.mdix` can coexist and share that one manifest file safely. Running `patch.mdix` will never see `project_structure.mdix`'s tracked files as "stale" (and vice versa), even with PASS 1 pruning enabled. You don't need to do anything to get this — it's automatic — but it's worth knowing why two templates in one repo don't fight over the same manifest.

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

## Remote URL Formats (for `fremote`)https://example.com/file.txt
github://owner/repo/branch/path/to/file.ext
githubhttps://owner/repo/branch/path/to/file.ext
raw://owner/repo/branch/path/to/file.extRemote content is cached in `~/.mdix-scaffold/cache/`. Clear with `mdix-scaffold clear-cache`.

---

## File Strategies (how existing files are handled)

| Strategy | Behaviour |
|---|---|
| `skip` (default) | Leave existing files untouched |
| `overwrite` | Always overwrite (same as `--override-stubs`) |
| `backup` | Copy existing to `--backup <dir>`, then overwrite |
| `rename` | Rename existing with timestamp suffix, then write |

Same principle as `--prune`: `skip` is the only acceptable default anywhere a workflow exposes this choice. `overwrite` is something the person picks, never something they inherit.

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

# Run the patch template explicitly
node bin/mdix-scaffold.js generate \
  --template .mdix/patches/patch.mdix --dry-run --diff

# With mappings
node bin/mdix-scaffold.js generate \
  --mappings .mdix/env/mappings.mdix

# File strategy
node bin/mdix-scaffold.js generate \
  --file-strategy backup --backup /tmp/bak

# Prune stale files — OFF unless you type this yourself; never script a
# default of true anywhere
node bin/mdix-scaffold.js generate --prune
# or: PRUNE_STALE=true node bin/mdix-scaffold.js generate

# Remove everything that was generated (separate, confirm-gated tool)
node bin/mdix-scaffold.js nuke --confirm DELETE
```

---

## GitHub Actions Workflow (Option A — no fork)

Two non-negotiable rules for any workflow YAML wrapping this:

1. **`type: choice` dropdowns for true/false and enum-like inputs** — never plain free-text `string` for `dry_run`, `override_stubs`, `file_strategy`, `prune`, etc. A typo in a free-text "true"/"false" field is a real failure mode; a dropdown can't be typo'd. (Free-text `string` is still correct for arbitrary values like `template` path — there's no finite option list to put in a dropdown.)
2. **Automatic (`push`) runs are always non-committal.** `dry_run` must be forced to `'true'` whenever the trigger isn't a manual `workflow_dispatch`, regardless of any input default. Only a person manually dispatching the workflow — and explicitly flipping the dropdown to `'false'` — can make it actually write and commit.

Note: `type: choice` is only valid on `workflow_dispatch.inputs`. The reusable `generate-structure.yml` workflow's own `workflow_call.inputs` can only be `boolean`/`number`/`string` per GitHub's schema — the dropdown lives entirely in the *caller* workflow shown below; it still passes a plain string through `with:` underneath.

### Structure template

```yaml
# .github/workflows/run-structure.yml
name: Generate project structure

on:
  workflow_dispatch:
    inputs:
      template:
        description: 'Path to .mdix structure template'
        required: false
        default: '.mdix/project_structure/project_structure.mdix'
      dry_run:
        description: 'true = preview only. false = actually write + commit.'
        required: false
        type: choice
        default: 'true'
        options:
          - 'true'
          - 'false'
      override_stubs:
        description: 'Overwrite existing stub files'
        required: false
        type: choice
        default: 'false'
        options:
          - 'false'
          - 'true'
      file_strategy:
        description: 'How to handle existing files'
        required: false
        type: choice
        default: 'skip'
        options:
          - 'skip'
          - 'overwrite'
          - 'backup'
          - 'rename'
  push:
    paths:
      - '.mdix/project_structure/**'

jobs:
  generate:
    uses: Mid-D-Man/mdix-scaffold/.github/workflows/generate-structure.yml@main
    permissions:
      contents: write
    with:
      template:       ${{ inputs.template || '.mdix/project_structure/project_structure.mdix' }}
      # Forced 'true' on every push; only a manual dispatch can flip this.
      dry_run:        ${{ github.event_name == 'workflow_dispatch' && inputs.dry_run || 'true' }}
      override_stubs: ${{ inputs.override_stubs || 'false' }}
      file_strategy:  ${{ inputs.file_strategy  || 'skip' }}
```

### Patch template

Same pattern, different default template path and a narrower push trigger:

```yaml
# .github/workflows/run-patch.yml
name: Run mdix patch

on:
  workflow_dispatch:
    inputs:
      template:
        description: 'Path to .mdix patch file'
        required: false
        default: '.mdix/patches/patch.mdix'
      dry_run:
        description: 'true = preview only. false = actually write + commit.'
        required: false
        type: choice
        default: 'true'
        options:
          - 'true'
          - 'false'
      override_stubs:
        description: 'Overwrite existing stub files'
        required: false
        type: choice
        default: 'false'
        options:
          - 'false'
          - 'true'
      file_strategy:
        description: 'How to handle existing files'
        required: false
        type: choice
        default: 'skip'
        options:
          - 'skip'
          - 'overwrite'
          - 'backup'
          - 'rename'
  push:
    paths:
      - '.mdix/patches/**'

jobs:
  run-patch:
    uses: Mid-D-Man/mdix-scaffold/.github/workflows/generate-structure.yml@main
    permissions:
      contents: write
    with:
      template:       ${{ inputs.template || '.mdix/patches/patch.mdix' }}
      dry_run:        ${{ github.event_name == 'workflow_dispatch' && inputs.dry_run || 'true' }}
      override_stubs: ${{ inputs.override_stubs || 'false' }}
      file_strategy:  ${{ inputs.file_strategy  || 'skip' }}
```

If `--prune` is ever exposed as a workflow input, it follows the exact same pattern: `type: choice`, options `['false', 'true']`, default `'false'`.

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
| `svelte` | `<!-- Auto-generated stub -->` |

---

## Common Mistakes

- **Forgetting `\n` in patch content** — the patcher does not inject newlines automatically. Every piece of inserted content must end with `\n`.
- **Using move when rename suffices** — `rename` is for same-filesystem moves; `move` handles cross-filesystem. Both work same-FS, but `move` is more robust.
- **Regex on Cargo.toml without `m` flag** — `version = "…"` can appear anywhere; use `m` (MULTILINE) so `^` and `$` behave per-line.
- **Skipping `--dry-run` before `patch_replace_range`** — character offsets shift with every edit; always preview first.
- **Not including anchor lines in `patch_replace_block` content** — if you want them back, include them in the replacement content, or use `patch_replace_block_keep` instead.
- **Stacking patch_files ops on the same file** — they run sequentially on disk; each op re-reads the file. This is fine, but keep op order in mind.
- **Defaulting any destructive/overwrite-capable flag to `true`** — `--prune`/`PRUNE_STALE`, `override_stubs`, `file_strategy=overwrite`. All of these default to their safest, least-destructive setting everywhere; the person opts in by hand every time, never by inheriting a default.
- **Free-text string inputs instead of `type: choice`** for true/false or enum-like workflow_dispatch inputs.
- **Letting an automatic `push` trigger write or commit anything.** Gate `dry_run` on `github.event_name == 'workflow_dispatch'`; force `'true'` for every other trigger.
- **Pasting the full QuickFuncs reference into every template.** Define only what that template's `@DATA` actually calls.
- **Wrong template name or path.** Patches are always `.mdix/patches/patch.mdix`; structure generation is always `.mdix/project_structure/project_structure.mdix`. Don't invent alternatives.
- **Shipping a `.mdix` template without its companion workflow `.yml`.** If one doesn't already exist in the repo, write it in the same response.
