# mdix-scaffold

Declarative, validated, idempotent project structure generator using [DixScript](https://github.com/Mid-D-Man/DixScript-Rust) `.mdix` files.

## How it works

Define your project structure in `.mdix/project_structure/project_structure.mdix` using DixScript's dotted group-array syntax. Each dotted key is a directory path; each array item is a file created by a QuickFunc call. Run the generate workflow and the structure appears — idempotently. Run it again and only new entries are created; existing files are never touched unless `override_stubs=true`.

```dixscript
@DATA(
  hidden_prefix = "github"   // "github" maps to ".github" on disk

  github.workflows::
    f("ci", "yml")           // → .github/workflows/ci.yml  (stub)

  src.core::
    f("engine",  "rs")       // → src/core/engine.rs  (stub)
    fc("mod", "rs", "pub mod engine;\n")  // → src/core/mod.rs  (with content)
)
```

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `bootstrap.yml` | Manual | Initialises a blank fork of this repo with a starter template |
| `generate-structure.yml` | Manual or push to `.mdix/**` | Creates/updates project structure from template |
| `nuke-structure.yml` | Manual (must type `DELETE`) | Removes everything the generator created |

## Generate workflow inputs

| Input | Default | Description |
|---|---|---|
| `template` | `.mdix/project_structure/project_structure.mdix` | Path to the `.mdix` template file |
| `override_stubs` | `false` | If `true`, overwrites existing stub files with fresh content |
| `dry_run` | `false` | If `true`, prints what would happen without touching the filesystem |

## Template conventions

| Element | Purpose |
|---|---|
| `hidden_prefix = "github"` | Flat property: segments matching this get a leading `.` on disk |
| `f(name, ext)` | QuickFunc: create a stub file (empty or extension-default content) |
| `fc(name, ext, content)` | QuickFunc: create a file with specific starting content |
| `gitkeep()` | QuickFunc: create a `.gitkeep` with no extension |
| `root::` | Reserved key: files here go in the repository root |
| `some.dotted.path::` | Group array: path segments become directory path `some/dotted/path/` |

## Manifest

After each run, `.mdix/.manifest.mdix` is written tracking every created file. On subsequent runs the generator diffs against this manifest — only new template entries are created. The manifest is itself valid DixScript and can be inspected with `mdix inspect .mdix/.manifest.mdix --keys`.

## Extending the template

Add a new directory and its files by adding a new group array entry in `@DATA`:

```dixscript
my.new.module::
  f("core",  "rs")
  f("utils", "rs")
  fc("mod", "rs", "pub mod core;\npub mod utils;\n")
```

Push the change to `.mdix/project_structure/` and the workflow triggers automatically.

## Building the CLI locally

```bash
git clone https://github.com/Mid-D-Man/DixScript-Rust.git
cd DixScript-Rust
cargo build -p mdix-cli --release
./target/release/mdix validate .mdix/project_structure/project_structure.mdix
./target/release/mdix convert .mdix/project_structure/project_structure.mdix --to json
```

## License

MIT
