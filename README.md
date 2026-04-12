# mdix-scaffold

Declarative, idempotent project structure generator using
[DixScript](https://github.com/Mid-D-Man/DixScript-Rust) `.mdix` files.

Define your layout once in a `.mdix` file. Run a workflow. Done.
Run it again — only new entries are added, existing files are never touched.

---

## Quickstart (two options)

### Option A — Use as a reusable workflow (recommended)

You only need **one file** in your repo. The scaffold repo does everything else.

Create `.github/workflows/generate-structure.yml` in your repo:

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
      template:        '.mdix/project_structure/project_structure.mdix'
      override_stubs:  ${{ inputs.override_stubs || 'false' }}
      dry_run:         ${{ inputs.dry_run || 'false' }}
```

Then add your `.mdix/project_structure/project_structure.mdix` file and push.
The workflow triggers automatically. That is all.

### Option B — Fork this repo

Fork mdix-scaffold, edit the template, run the workflows directly from the
Actions tab of your fork.

---

## How the CLI is sourced

No local tooling required. The generate workflow runs inside a GitHub Actions VM:

1. Checks a **weekly binary cache** for the `mdix` CLI binary
2. **Cache miss** — clones [DixScript-Rust](https://github.com/Mid-D-Man/DixScript-Rust),
   runs `cargo build -p mdix-cli --release`, saves binary to cache (~3 min, once per week)
3. **Cache hit** — skips the build entirely (seconds)
4. Copies binary to `/usr/local/bin/mdix` and proceeds

No secrets, no tokens, no local machine required.

---

## Template syntax

Everything lives in `.mdix/project_structure/project_structure.mdix`.

### The four QuickFuncs

```dixscript
~f<object>(name, ext)                 // stub file — content from extension default
~fc<object>(name, ext, content)       // file with specific starting content
~gitkeep<object>()                    // .gitkeep (no extension)
~hidden<object>(segment)              // mark segment as dot-prefixed on disk
```

### Full template structure

```dixscript
@CONFIG(
  version    -> "1.0.0"
  author     -> "YourName"
  features   -> "quickfuncs,data"
  debug_mode -> "off"
)

@QUICKFUNCS(
  ~f<object>(name, ext) {
    return { name = name, ext = ext, content = "" }
  }
  ~fc<object>(name, ext, content) {
    return { name = name, ext = ext, content = content }
  }
  ~gitkeep<object>() {
    return { name = ".gitkeep", ext = "", content = "" }
  }
  ~hidden<object>(segment) {
    return { segment = segment }
  }
)

@DATA(
  project_name = "my-project"
  description  = "What this project does"

  // Segments listed here get a leading dot on disk
  hidden_dirs::
    hidden("github")          // github.* keys → .github/*
    hidden("vscode")          // vscode key    → .vscode/

  github.workflows::
    f("ci",      "yml")       // → .github/workflows/ci.yml
    f("release", "yml")       // → .github/workflows/release.yml

  vscode::
    fc("extensions", "json", "{\n  \"recommendations\": []\n}\n")

  src.core::
    f("lib",  "rs")           // → src/core/lib.rs
    f("util", "rs")           // → src/core/util.rs
    fc("mod", "rs", "pub mod lib;\npub mod util;\n")

  assets::
    gitkeep()                 // → assets/.gitkeep

  root::
    fc("README",    "md",  "# my-project\n")
    fc(".gitignore", "",   "target/\n.env\n.DS_Store\n")
    fc("Cargo",     "toml","[package]\nname = \"my-project\"\nversion = \"0.1.0\"\nedition = \"2021\"\n")
)
```

### How dotted keys become paths

| Template key | Disk path | Why |
|---|---|---|
| `root` | `./` | Reserved keyword |
| `src` | `src/` | Plain segment |
| `src.core` | `src/core/` | Dots become slashes |
| `github.workflows` | `.github/workflows/` | `github` in `hidden_dirs` |
| `vscode` | `.vscode/` | `vscode` in `hidden_dirs` |

### Stub defaults

When `f(name, ext)` is used the generator fills a minimal default by extension:

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

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `bootstrap.yml` | Manual | Creates `.mdix/` folder and starter template in a blank fork |
| `generate-structure.yml` | Manual or push to `.mdix/**` | Generates/updates structure. Also callable as a reusable workflow |
| `nuke-structure.yml` | Manual — must type `DELETE` | Removes everything the generator created |

### Generate inputs

| Input | Default | Description |
|---|---|---|
| `template` | `.mdix/project_structure/project_structure.mdix` | Path to the template |
| `override_stubs` | `false` | Overwrite existing stub files |
| `dry_run` | `false` | Preview without writing anything |

---

## Manifest

After each run, `.mdix/.manifest.mdix` is written tracking every created file.
It is itself valid DixScript and can be inspected:

```
mdix inspect .mdix/.manifest.mdix --keys
mdix convert .mdix/.manifest.mdix --to json
```

On re-runs the generator diffs new template entries against the manifest.
Already-created files are skipped. Files removed from the template are left
alone — use the nuke workflow to clean up intentionally.

---

## Testing with only the GitHub website

No laptop, no VS Code, no github.dev needed. Everything below uses only
the github.com web interface.

### Step 1 — Create a new repo

github.com → click **+** (top right) → **New repository** → give it a name →
tick **Add a README file** → **Create repository**.

### Step 2 — Create files using the web editor

For each file you need to create:

1. In the repo, click **Add file → Create new file**
2. In the name box at the top, type the full path including folders.
   GitHub creates folders automatically when you type a `/`.
   For example, type `.github/workflows/generate-structure.yml` —
   as you type each `/` the box splits into a new folder segment.
3. Paste the file content into the editor below
4. Scroll down → click **Commit new file**
5. Repeat for the next file

Files to create in this order:

```
.github/workflows/bootstrap.yml
.github/workflows/generate-structure.yml
.github/workflows/nuke-structure.yml
.mdix/project_structure/project_structure.mdix
```

The README is already there from Step 1 — you can edit it by clicking the
pencil icon on the file view.

### Step 3 — Enable Actions

Click the **Actions** tab. If GitHub shows a warning banner, click
**"I understand my workflows, go ahead and enable them"**.

### Step 4 — Dry run

**Actions → Generate project structure → Run workflow**

Set `dry_run = true`. Click **Run workflow**.

Open the running job and expand the **Generate project structure** step.
You should see every `DIR` and `NEW` line that would be created, with no
files actually written.

### Step 5 — Real run

Run again with `dry_run = false`. When the job finishes, go to the
**Code** tab — the generated files are there in a new commit from
`github-actions[bot]`.

### Step 6 — Test idempotency

Run again without changing anything. Every file should show
`--- (exists, kept)` and the commit step should print
`Nothing new to commit`.

### Step 7 — Test a change

Go to `.mdix/project_structure/project_structure.mdix` → click the pencil
icon → add a new file entry to any group array → click **Commit changes**.

Committing to `.mdix/project_structure/` triggers the generate workflow
automatically. Only the new entry appears as `NEW`.

### Step 8 — Test nuke

**Actions → Nuke project structure → Run workflow** → type `DELETE` → **Run workflow**.
All generated files are removed in a commit.

---

## Making it your own

If using the reusable workflow (Option A above):

1. Create the tiny caller workflow shown in the Quickstart section
2. Create your `.mdix/project_structure/project_structure.mdix`
3. Push — the workflow runs automatically

If forking (Option B):

1. Fork this repo on github.com
2. Edit `.mdix/project_structure/project_structure.mdix` via the web editor
3. Run **Generate project structure** from the Actions tab

The template is the only file you need to understand and edit.

---

## License

MIT
