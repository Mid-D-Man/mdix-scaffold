# mdix-scaffold

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
git clone [https://github.com/Mid-D-Man/mdix-scaffold.git](https://github.com/Mid-D-Man/mdix-scaffold.git)
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
| `update(path, content)` | Always-overwrite after renames |

### Remote URL formats (for `fremote`)

https://example.com/file.txt
github://owner/repo/branch/path/to/file.ext
githubhttps://owner/repo/branch/path/to/file.ext
raw://owner/repo/branch/path/to/file.ext

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
| anything else | Empty file |

---

## Project templates

Ready-made templates for common project types:

| Template | Description |
|---|---|
| `templates/rust-lib.mdix` | Rust library crate with CI, benches, examples |
| `templates/python-package.mdix` | Python package with pyproject.toml, pytest, ruff |
| `templates/node-api.mdix` | Node.js REST API with Express + TypeScript |

Use any template with:
```bash
mdix-scaffold generate --template .mdix/project_structure/templates/rust-lib.mdix
mdix-scaffold templates   # list all available templates
```

Combine with mappings to fill in project name, author, etc.:
```bash
mdix-scaffold generate \
  --template  .mdix/project_structure/templates/rust-lib.mdix \
  --mappings  .mdix/env/mappings.mdix
```

---

## File strategies

Control what happens when a file already exists:

| Strategy | Behaviour |
|---|---|
| `skip` | Leave existing files untouched (default — keeps scaffold idempotent) |
| `overwrite` | Replace with template content |
| `backup` | Copy to `--backup <dir>` then overwrite |
| `rename` | Rename existing file with `.timestamp` suffix then write |

```bash
mdix-scaffold generate --file-strategy overwrite
mdix-scaffold generate --file-strategy backup --backup /tmp/bak
mdix-scaffold generate --file-strategy rename
```

---

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `bootstrap.yml` | Manual | Creates `.mdix/` folder and starter files in a blank fork |
| `generate-structure.yml` | Manual or push to `.mdix/**` | Generates/updates structure. Reusable |
| `nuke-structure.yml` | Manual — must type `DELETE` | Removes everything the generator created |
| `update-project-structure.yml` | `[snapshot]` in commit message or manual | Writes `others/ProjectStructure.mdix` |
| `publish-npm.yml` | Push a `v*` tag | Publishes to npm |

### Generate inputs

| Input | Default | Description |
|---|---|---|
| `template` | `.mdix/project_structure/project_structure.mdix` | Template path |
| `override_stubs` | `false` | Overwrite existing files |
| `dry_run` | `false` | Preview without writing |
| `file_strategy` | `skip` | `skip` \| `overwrite` \| `backup` \| `rename` |
| `mappings_file` | _(empty)_ | Path to `.mdix` mappings file |

### Structure snapshot

The snapshot workflow only runs when you include `[snapshot]` in your commit message:

```bash
git commit -m "add new module structure [snapshot]"
git push
```

Or trigger manually from the Actions tab.
Output goes to `others/ProjectStructure.mdix` — a valid DixScript `@DATA` file.

---

## Manifest

After each run, `.mdix/.manifest.mdix` tracks every created file.
Inspect it with:

```bash
mdix inspect .mdix/.manifest.mdix --keys
mdix convert .mdix/.manifest.mdix --to json
```

On re-runs, the generator skips already-tracked files (with `file_strategy=skip`).
Files removed from the template are left alone — use `nuke` to clean up.

---

## Testing

Run the full test suite locally:

```bash
python3 scripts/test_scaffold.py          # all tests
python3 scripts/test_scaffold.py -v       # verbose
python3 scripts/test_scaffold.py -k hooks # filter by keyword
```

Covers: core generation, all file strategies, hooks, remote content (mocked),
mappings substitution, dry-run mode, manifest creation, and nuke.

---

## Local CLI reference

```
mdix-scaffold <command> [options]

COMMANDS
generate     Create / update files from a .mdix template
nuke         Remove all generated files (--confirm DELETE required)
snapshot     Write others/ProjectStructure.mdix
validate     Validate a .mdix template
convert      Convert a .mdix template to JSON
templates    List available project templates
setup        Install the mdix CLI binary from source
clear-cache  Clear remote-content cache (~/.mdix-scaffold/cache/)
help         Show full usage

GENERATE OPTIONS 
--template, -t <path>    Template to use 
--mappings, -m <file>    .mdix mappings file for [[key]] substitution 
--dry-run                Preview without writing 
--diff                   Show unified diffs with --dry-run 
--file-strategy <s>      skip | overwrite | backup | rename 
--backup <dir>           Backup dir for --file-strategy=backup 
--override-stubs         Alias for --file-strategy overwrite 
--no-cache               Skip remote-content cache 
--verbose                Show remote fetches and mapping detail
```

---

## Publishing to npm

1. Update `package.json` `"version"` field
2. Tag the release:
```bash
   git tag v1.0.1
   git push --tags
```
3. The `publish-npm.yml` workflow verifies the tag matches `package.json`
   and publishes automatically

Requires one repository secret: **`NPM_TOKEN`**
(npmjs.com → Account → Access Tokens → Automation token)

---

## Testing with only the GitHub website

1. Fork this repo on github.com
2. **Actions → Bootstrap scaffold repo → Run workflow**
   This creates `.mdix/`, `scripts/`, `bin/`, `package.json`, and `README.md`
3. Edit `.mdix/project_structure/project_structure.mdix` via the web editor
4. **Actions → Generate project structure → Run workflow** with `dry_run = true`
5. Run again with `dry_run = false`
6. Test idempotency: run again — all files show `(skipped)`
7. Add `[snapshot]` to a commit message to update `others/ProjectStructure.mdix`
8. **Actions → Nuke project structure → Run workflow** → type `DELETE`

---

## License

MIT
