#!/usr/bin/env node
/**
 * mdix-scaffold CLI — local wrapper around scripts/ Python modules.
 *
 * Requirements:
 *   - Python 3  (python3 or python)
 *   - mdix CLI on PATH (built from DixScript-Rust)
 *   - Node.js >= 18
 *
 * Usage:
 *   mdix-scaffold generate [options]
 *   mdix-scaffold nuke     --confirm DELETE [options]
 *   mdix-scaffold snapshot [options]
 *   mdix-scaffold validate [template]
 *   mdix-scaffold convert  [template]
 *   mdix-scaffold templates
 *   mdix-scaffold clear-cache
 */

"use strict";

const { spawnSync } = require("child_process");
const path = require("path");
const fs   = require("fs");

const PKG_ROOT    = path.resolve(__dirname, "..");
const SCRIPTS_DIR = path.join(PKG_ROOT, "scripts");

const DEFAULT_TEMPLATE  = ".mdix/project_structure/project_structure.mdix";
const DEFAULT_JSON_OUT  = "/tmp/mdix_structure.json";
const DEFAULT_MANIFEST  = "/tmp/mdix_manifest.json";

// ---------------------------------------------------------------------------
// Detect Python
// ---------------------------------------------------------------------------

function findPython() {
  for (const c of ["python3", "python"]) {
    if (spawnSync(c, ["--version"], { encoding: "utf8" }).status === 0) return c;
  }
  console.error(
    "ERROR: Python 3 not found.\n" +
    "Install Python 3 and ensure it is on PATH as 'python3' or 'python'."
  );
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Detect mdix CLI
// ---------------------------------------------------------------------------

function findMdix() {
  if (spawnSync("mdix", ["--version"], { encoding: "utf8" }).status === 0) return "mdix";
  const local = path.join(PKG_ROOT, "bin", "mdix");
  if (fs.existsSync(local)) return local;
  console.error(
    "ERROR: 'mdix' CLI not found on PATH.\n" +
    "Build it:\n" +
    "  git clone https://github.com/Mid-D-Man/DixScript-Rust.git\n" +
    "  cd DixScript-Rust && cargo build -p mdix-cli --release\n" +
    "  cp target/release/mdix /usr/local/bin/mdix"
  );
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Run helpers
// ---------------------------------------------------------------------------

function run(bin, args, opts = {}) {
  const r = spawnSync(bin, args, {
    stdio: "inherit",
    encoding: "utf8",
    cwd: opts.cwd || process.cwd(),
    env: { ...process.env, ...(opts.env || {}) },
  });
  if (r.status !== 0) process.exit(r.status ?? 1);
}

function runPy(script, args, opts = {}) {
  const python = findPython();
  const p = path.join(SCRIPTS_DIR, script);
  if (!fs.existsSync(p)) {
    console.error(`ERROR: Script not found: ${p}`);
    process.exit(1);
  }
  run(python, [p, ...args], opts);
}

// ---------------------------------------------------------------------------
// Arg parser
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const args = argv.slice(2);
  const cmd  = args[0];
  const rest = args.slice(1);

  const flags      = {};
  const positional = [];

  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    switch (a) {
      case "--dry-run":            flags.dryRun        = true;  break;
      case "--diff":               flags.diff          = true;  break;
      case "--override-stubs":     flags.overrideStubs = true;  break;
      case "--verbose":            flags.verbose       = true;  break;
      case "--no-cache":           flags.noCache       = true;  break;
      case "--help": case "-h":    flags.help          = true;  break;
      case "--version": case "-v": flags.version       = true;  break;
      case "--template":  case "-t": flags.template      = rest[++i]; break;
      case "--output":    case "-o": flags.output        = rest[++i]; break;
      case "--mappings":  case "-m": flags.mappings      = rest[++i]; break;
      case "--confirm":              flags.confirm       = rest[++i]; break;
      case "--json":                 flags.json          = rest[++i]; break;
      case "--file-strategy":        flags.fileStrategy  = rest[++i]; break;
      case "--backup":               flags.backup        = rest[++i]; break;
      case "--repo":                 flags.repo          = rest[++i]; break;
      case "--branch":               flags.branch        = rest[++i]; break;
      case "--commit":               flags.commit        = rest[++i]; break;
      default:
        if (!a.startsWith("-")) positional.push(a);
    }
  }

  return { cmd, flags, positional };
}

// ---------------------------------------------------------------------------
// Help
// ---------------------------------------------------------------------------

const HELP = `
mdix-scaffold — declarative project structure generator

USAGE
  mdix-scaffold <command> [options]

COMMANDS
  generate     Create / update files from a .mdix template
  nuke         Remove all generated files
  snapshot     Write a plain-text directory layout snapshot
  validate     Validate a .mdix template  (requires mdix CLI)
  convert      Convert a .mdix template to JSON (requires mdix CLI)
  templates    List available project templates
  clear-cache  Clear the remote-content cache (~/.mdix-scaffold/cache/)
  help         Show this message

GENERATE OPTIONS
  --template, -t  <path>     Path to .mdix template
                             (default: ${DEFAULT_TEMPLATE})
  --mappings, -m  <file>     YAML/JSON file for [[key]] substitution in content
  --dry-run                  Preview without writing anything
  --diff                     Show unified diffs alongside --dry-run
  --override-stubs           Alias for --file-strategy overwrite
  --file-strategy <s>        skip | overwrite | backup | rename  (default: skip)
  --backup        <dir>      Backup directory when --file-strategy=backup
  --no-cache                 Skip remote-content cache
  --verbose                  Print remote fetches and mapping substitutions
  --json          <path>     Path for converted structure JSON

NUKE OPTIONS
  --confirm DELETE           Required safety flag
  --template, -t  <path>    Same template used to generate

SNAPSHOT OPTIONS
  --output, -o <path>        Output file (default: others/ProjectStructure.txt)

EXAMPLES
  # Generate with default template
  mdix-scaffold generate

  # Generate a Rust library from a project template
  mdix-scaffold generate --template .mdix/project_structure/templates/rust-lib.mdix

  # Generate with mappings file (substitutes [[key]] placeholders)
  mdix-scaffold generate --mappings .mdix/env/mappings.yaml

  # Dry run + show diffs
  mdix-scaffold generate --dry-run --diff

  # Backup existing files then overwrite
  mdix-scaffold generate --file-strategy backup --backup /tmp/bak

  # Remove everything
  mdix-scaffold nuke --confirm DELETE

  # See available templates
  mdix-scaffold templates

  # Clear cached remote files
  mdix-scaffold clear-cache
`;

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

function cmdGenerate(flags, positional) {
  const template = flags.template || positional[0] || DEFAULT_TEMPLATE;
  const jsonPath = flags.json     || DEFAULT_JSON_OUT;
  const mdix     = findMdix();

  console.log(`\n→ Validating: ${template}`);
  run(mdix, ["validate", template]);

  console.log(`\n→ Converting to JSON: ${jsonPath}`);
  run(mdix, ["convert", template, "--to", "json", "-o", jsonPath]);

  if (fs.existsSync(".mdix/.manifest.mdix")) {
    console.log("\n→ Reading manifest...");
    run(mdix, ["convert", ".mdix/.manifest.mdix", "--to", "json", "-o", DEFAULT_MANIFEST]);
  }

  console.log("\n→ Generating project structure...");

  const pyArgs = ["--template", template, "--structure-json", jsonPath];

  if (fs.existsSync(DEFAULT_MANIFEST)) {
    pyArgs.push("--manifest-json", DEFAULT_MANIFEST);
  }
  if (flags.dryRun)        pyArgs.push("--dry-run");
  if (flags.diff)          pyArgs.push("--diff");
  if (flags.overrideStubs) pyArgs.push("--override-stubs");
  if (flags.fileStrategy)  pyArgs.push("--file-strategy", flags.fileStrategy);
  if (flags.backup)        pyArgs.push("--backup",        flags.backup);
  if (flags.mappings)      pyArgs.push("--mappings",      flags.mappings);
  if (flags.verbose)       pyArgs.push("--verbose");
  if (flags.noCache)       pyArgs.push("--no-cache");

  runPy("generate_structure.py", pyArgs);
}

function cmdNuke(flags, positional) {
  if (!flags.confirm) {
    console.error("ERROR: --confirm DELETE is required.");
    process.exit(1);
  }
  const template = flags.template || positional[0] || DEFAULT_TEMPLATE;
  const jsonPath = flags.json     || DEFAULT_JSON_OUT;
  const mdix     = findMdix();

  console.log(`\n→ Validating: ${template}`);
  run(mdix, ["validate", template]);

  console.log(`\n→ Converting to JSON: ${jsonPath}`);
  run(mdix, ["convert", template, "--to", "json", "-o", jsonPath]);

  console.log("\n→ Removing generated files...");
  runPy("nuke_structure.py", [
    "--confirm",        flags.confirm,
    "--template",       template,
    "--structure-json", jsonPath,
  ]);
}

function cmdSnapshot(flags) {
  const pyArgs = [];
  if (flags.output) pyArgs.push("--output", flags.output);
  if (flags.repo)   pyArgs.push("--repo",   flags.repo);
  if (flags.branch) pyArgs.push("--branch", flags.branch);
  if (flags.commit) pyArgs.push("--commit", flags.commit);
  runPy("update_structure.py", pyArgs);
}

function cmdValidate(flags, positional) {
  const template = flags.template || positional[0] || DEFAULT_TEMPLATE;
  console.log(`\n→ Validating: ${template}`);
  run(findMdix(), ["validate", template]);
  console.log("Validation passed.");
}

function cmdConvert(flags, positional) {
  const template = flags.template || positional[0] || DEFAULT_TEMPLATE;
  const jsonPath = flags.json     || DEFAULT_JSON_OUT;
  console.log(`\n→ Converting ${template} → ${jsonPath}`);
  run(findMdix(), ["convert", template, "--to", "json", "-o", jsonPath]);
  console.log(`Done: ${jsonPath}`);
}

function cmdTemplates() {
  const dirs = [
    path.join(PKG_ROOT, ".mdix", "project_structure", "templates"),
  ];

  let found = [];
  for (const dir of dirs) {
    if (!fs.existsSync(dir)) continue;
    const files = fs.readdirSync(dir).filter(f => f.endsWith(".mdix") && !f.startsWith("."));
    for (const f of files) {
      const name = f.replace(/\.mdix$/, "");
      found.push({ name, path: path.relative(process.cwd(), path.join(dir, f)) });
    }
  }

  if (found.length === 0) {
    console.log("No templates found in .mdix/project_structure/templates/");
    return;
  }

  console.log("\nAvailable project templates:\n");
  const maxLen = Math.max(...found.map(t => t.name.length));
  for (const t of found) {
    console.log(`  ${t.name.padEnd(maxLen + 2)} ${t.path}`);
  }
  console.log(
    "\nUsage:\n" +
    "  mdix-scaffold generate --template <path>\n\n" +
    "With mappings (replaces [[key]] placeholders):\n" +
    "  mdix-scaffold generate --template <path> --mappings .mdix/env/mappings.yaml"
  );
}

function cmdClearCache() {
  runPy("generate_structure.py", ["--clear-cache"]);
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

function main() {
  const { cmd, flags, positional } = parseArgs(process.argv);

  if (flags.version) {
    const pkg = require(path.join(PKG_ROOT, "package.json"));
    console.log(pkg.version);
    process.exit(0);
  }

  if (!cmd || cmd === "help" || flags.help) {
    console.log(HELP);
    process.exit(0);
  }

  switch (cmd) {
    case "generate":    cmdGenerate(flags, positional);  break;
    case "nuke":        cmdNuke(flags, positional);      break;
    case "snapshot":    cmdSnapshot(flags);              break;
    case "validate":    cmdValidate(flags, positional);  break;
    case "convert":     cmdConvert(flags, positional);   break;
    case "templates":   cmdTemplates();                  break;
    case "clear-cache": cmdClearCache();                 break;
      case "setup":       cmdSetup(flags);             break;
    default:
      console.error(`Unknown command: '${cmd}'\nRun 'mdix-scaffold help' for usage.`);
      process.exit(1);
  }
}

main();
