# mdix-scaffold

A generic, declarative project structure generator powered by [DixScript](https://github.com/Mid-D-Man/DixScript-Rust).

Define your project layout once in a `.mdix` file. Run the workflow. Done. Run it again and only new entries are added — existing files are never touched unless you explicitly ask.

---

## How it works
.mdix/project_structure/project_structure.mdix
│
▼
mdix validate
mdix convert --to json
│
▼
python3 generator
- reads dotted keys as directory paths
- calls f() / fc() / gitkeep() results as file entries
- diffs against .mdix/.manifest.mdix
- creates only what is new
│
▼
git commit [skip ci]

---

## Template syntax

Everything is in `@DATA`. Flat properties are metadata. Dotted group arrays are directories and their files.

```dixscript
@CONFIG(
  version  -> "1.0.0"
  features -> "quickfuncs,data"
)

@QUICKFUNCS(
  ~f<object>(name, ext)          { return { name = name, ext = ext, content = "" } }
  ~fc<object>(name, ext, content){ return { name = name, ext = ext, content = content } }
  ~gitkeep<object>()             { return { name = ".gitkeep", ext = "", content = "" } }
)

@DATA(
  project_name  = "my-app"
  hidden_prefix = "github"      // "github" → ".github" on disk

  github.workflows::
    f("ci",      "yml")         // → .github/workflows/ci.yml
    f("release", "yml")         // → .github/workflows/release.yml

  src.core::
    f("lib",  "rs")             // → src/core/lib.rs   (stub)
    f("util", "rs")             // → src/core/util.rs  (stub)

  src::
    fc("main", "rs", "fn main() {}\n")  // → src/main.rs  (with content)

  assets::
    gitkeep()                   // → assets/.gitkeep

  root::
    fc("README", "md", "# my-app\n")   // → README.md
    fc(".gitignore", "", "target/\n")   // → .gitignore
)
```

### Key rules

| Element | Meaning |
|---|---|
| `hidden_prefix = "github"` | Any top-level key matching this gets a leading `.` on disk |
| `f(name, ext)` | Stub file — content comes from a sensible per-extension default |
| `fc(name, ext, content)` | File with specific starting content |
| `gitkeep()` | Creates a `.gitkeep` with no extension |
| `root::` | Reserved — files land in the repository root |
| `a.b.c::` | Everything after `::` goes inside `a/b/c/` |

### Stub defaults

When `f()` is used the generator fills in a minimal stub based on extension:

| Extension | Default stub content |
|---|---|
| `rs` | `// stub` |
| `cs` | `// stub` |
| `py` | `# stub` |
| `ts` | `// stub` |
| `js` | `// stub` |
| `yml` / `yaml` | `# stub` |
| `md` | `# filename` |
| `json` | `{}` |
| `toml` | `# stub` |
| `sh` | `#!/usr/bin/env bash` |
| anything else | empty file |

---

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `bootstrap.yml` | Manual | One-time: creates `.mdix/` folder and starter template in a blank fork |
| `generate-structure.yml` | Manual or push to `.mdix/**` | Generates or updates structure from template |
| `nuke-structure.yml` | Manual — must type `DELETE` | Removes all files the generator created |

### Generate inputs

| Input | Default | Description |
|---|---|---|
| `template` | `.mdix/project_structure/project_structure.mdix` | Which template to use |
| `override_stubs` | `false` | Overwrite existing stub files |
| `dry_run` | `false` | Preview without writing anything |

---

## How the CLI is sourced

The generator needs `mdix` (the DixScript CLI) to validate and convert the template. Because this is a separate repo with no local machine required, the workflow:

1. Checks the weekly binary cache
2. On a cache miss: clones [DixScript-Rust](https://github.com/Mid-D-Man/DixScript-Rust), builds `mdix-cli --release`, saves to cache
3. On a cache hit: skips the build entirely (~seconds)
4. Copies the binary to `/usr/local/bin/mdix`

No secrets, no tokens, no local setup. Everything runs inside the GitHub Actions VM.

---

## Manifest

After each run `.mdix/.manifest.mdix` tracks every file that was created. It is itself valid DixScript — you can inspect it:

```bash
mdix inspect .mdix/.manifest.mdix --keys
```

On re-runs the generator diffs new template entries against the manifest and only creates what is missing. Files in the manifest that no longer appear in the template are left alone (use the nuke workflow to clean up intentionally).

---

## Making it your own

1. Fork this repo
2. Run **Bootstrap scaffold repo** from the Actions tab (creates the `.mdix/` folder if missing)
3. Edit `.mdix/project_structure/project_structure.mdix` to match your project shape
4. Run **Generate project structure** — or push the template change and it runs automatically
5. Delete this README and write your own

---

## License

MIT
