#!/usr/bin/env node
/**
 * mdix-scaffold CLI
 *
 * A thin Node.js wrapper around the Python scripts in scripts/.
 * Requires:
 *   - Python 3 available as `python3` (or `python` on Windows)
 *   - The mdix CLI on PATH (built from DixScript-Rust)
 *
 * Usage:
 *   mdix-scaffold generate [options]
 *   mdix-scaffold nuke     --confirm DELETE [options]
 *   mdix-scaffold snapshot [options]
 *   mdix-scaffold validate [template]
 *   mdix-scaffold convert  [template]
 *
 * Examples:
 *   mdix-scaffold generate
 *   mdix-scaffold generate --dry-run
 *   mdix-scaffold generate --override-stubs --template path/to/template.mdix
 *   mdix-scaffold nuke --confirm DELETE
 *   mdix-scaffold snapshot --output others/ProjectStructure.txt
 *   mdix-scaffold validate
 *   mdix-scaffold convert
 */

"use strict";

const { spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");

// ---------------------------------------------------------------------------
// Resolve paths
// ---------------------------------------------------------------------------

const PKG_ROOT     = path.resolve(__dirname, "..");
const SCRIPTS_DIR  = path.join(PKG_ROOT, "scripts");

const DEFAULT_TEMPLATE =
  ".mdix/project_structure/project_structure.mdix";
const DEFAULT_JSON_OUT = "/tmp/mdix_structure.json";

// ---------------------------------------------------------------------------
// Detect python binary
// ---------------------------------------------------------------------------

function findPython() {
  for (const candidate of ["python3", "python"]) {
    const result = spawnSync(candidate, ["--version"], { encoding: "utf8" });
    if (result.status === 0) return candidate;
  }
  console.error(
    "ERROR: Python 3 is required but was not found on PATH.\n" +
    "Install Python 3 and ensure it is accessible as 'python3' or 'python'."
  );
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Detect mdix CLI
// ---------------------------------------------------------------------------

function findMdix() {
  const result = spawnSync("mdix", ["--version"], { encoding: "utf8" });
  if (result.status === 0) return "mdix";
  // Not on PATH — check if there's a local build
  const localBin = path.join(PKG_ROOT, "bin", "mdix");
  if (fs.existsSync(localBin)) return localBin;
  console.error(
    "ERROR: The 'mdix' CLI was not found on PATH.\n" +
    "Build it from source:\n" +
    "  git clone https://github.com/Mid-D-Man/DixScript-Rust.git\n" +
    "  cd DixScript-Rust && cargo build -p mdix-cli --release\n" +
    "  cp target/release/mdix /usr/local/bin/mdix"
  );
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Run a subprocess, streaming output, exit on failure
// ---------------------------------------------------------------------------

function run(bin, args, opts = {}) {
  const result = spawnSync(bin, args, {
    stdio: "inherit",
    encoding: "utf8",
    cwd: opts.cwd || process.cwd(),
    env: { ...process.env, ...opts.env },
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

function runPy(script, args, opts = {}) {
  const python = findPython();
  const scriptPath = path.join(SCRIPTS_DIR, script);
  if (!fs.existsSync(scriptPath)) {
    console.error(`ERROR: Script not found: ${scriptPath}`);
    process.exit(1);
  }
  run(python, [scriptPath, ...args], opts);
}

// ---------------------------------------------------------------------------
// Parse minimal CLI args (we keep this dependency-free)
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const args = argv.slice(2); // drop node + script name
  const cmd  = args[0];
  const rest = args.slice(1);

  const flags = {};
  const positional = [];

  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    if (a === "--dry-run")         { flags.dryRun = true; }
    else if (a === "--override-stubs") { flags.overrideStubs = true; }
    else if (a === "--template" || a === "-t") {
      flags.template = rest[++i];
    }
    else if (a === "--output" || a === "-o") {
      flags.output = rest[++i];
    }
    else if (a === "--confirm") {
      flags.confirm = rest[++i];
    }
    else if (a === "--json") {
      flags.json = rest[++i];
    }
    else if (a === "--repo")   { flags.repo   = rest[++i]; }
    else if (a === "--branch") { flags.branch = rest[++i]; }
    else if (a === "--commit") { flags.commit = rest[++i]; }
    else if (a === "--help" || a === "-h") { flags.help = true; }
    else if (a === "--version" || a === "-v") { flags.version = true; }
    else if (!a.startsWith("-")) {
      positional.push(a);
    }
  }

  return { cmd, flags, positional };
}

// ---------------------------------------------------------------------------
// Help text
// ---------------------------------------------------------------------------

const HELP = `
mdix-scaffold — declarative project structure generator

USAGE
  mdix-scaffold <command> [options]

COMMANDS
  generate    Create / update files declared in a .mdix template
  nuke        Remove all files previously generated from a template
  snapshot    Write a plain-text directory layout snapshot
  validate    Validate a .mdix template file (requires mdix CLI)
  convert     Convert a .mdix template to JSON  (requires mdix CLI)
  help        Show this message

GENERATE OPTIONS
  --template, -t  <path>   Path to .mdix template
                           (default: ${DEFAULT_TEMPLATE})
  --dry-run                Preview without writing anything
  --override-stubs         Overwrite existing stub files
  --json        <path>     Path for converted structure JSON
                           (default: ${DEFAULT_JSON_OUT})

NUKE OPTIONS
  --confirm DELETE         Required safety flag
  --template, -t  <path>  Same template used to generate

SNAPSHOT OPTIONS
  --output, -o <path>      Output file (default: others/ProjectStructure.txt)
  --repo       <str>       Repository name shown in header
  --branch     <str>       Branch name shown in header
  --commit     <str>       Commit SHA shown in header

VALIDATE / CONVERT
  [template]               Defaults to ${DEFAULT_TEMPLATE}

EXAMPLES
  mdix-scaffold generate
  mdix-scaffold generate --dry-run
  mdix-scaffold generate --override-stubs
  mdix-scaffold nuke --confirm DELETE
  mdix-scaffold snapshot
  mdix-scaffold validate
`;

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

function cmdGenerate(flags, positional) {
  const template = flags.template || positional[0] || DEFAULT_TEMPLATE;
  const jsonPath = flags.json || DEFAULT_JSON_OUT;
  const mdix = findMdix();

  console.log(`\n→ Validating template: ${template}`);
  run(mdix, ["validate", template]);

  console.log(`\n→ Converting template to JSON: ${jsonPath}`);
  run(mdix, ["convert", template, "--to", "json", "-o", jsonPath]);

  // Load manifest if it exists
  const manifestMdix = ".mdix/.manifest.mdix";
  const manifestJson = "/tmp/mdix_manifest.json";
  if (fs.existsSync(manifestMdix)) {
    console.log("\n→ Reading existing manifest...");
    run(mdix, ["convert", manifestMdix, "--to", "json", "-o", manifestJson]);
  }

  console.log("\n→ Generating project structure...");
  const pyArgs = ["--template", template, "--structure-json", jsonPath];
  if (fs.existsSync(manifestJson)) {
    pyArgs.push("--manifest-json", manifestJson);
  }
  if (flags.dryRun)         pyArgs.push("--dry-run");
  if (flags.overrideStubs)  pyArgs.push("--override-stubs");

  runPy("generate_structure.py", pyArgs);
}

function cmdNuke(flags, positional) {
  if (!flags.confirm) {
    console.error('ERROR: --confirm DELETE is required to nuke.');
    process.exit(1);
  }

  const template = flags.template || positional[0] || DEFAULT_TEMPLATE;
  const jsonPath = flags.json || DEFAULT_JSON_OUT;
  const mdix = findMdix();

  console.log(`\n→ Validating template: ${template}`);
  run(mdix, ["validate", template]);

  console.log(`\n→ Converting template to JSON: ${jsonPath}`);
  run(mdix, ["convert", template, "--to", "json", "-o", jsonPath]);

  console.log("\n→ Removing generated files...");
  runPy("nuke_structure.py", [
    "--confirm", flags.confirm,
    "--template", template,
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
  const mdix = findMdix();
  console.log(`\n→ Validating: ${template}`);
  run(mdix, ["validate", template]);
  console.log("Validation passed.");
}

function cmdConvert(flags, positional) {
  const template = flags.template || positional[0] || DEFAULT_TEMPLATE;
  const jsonPath = flags.json || DEFAULT_JSON_OUT;
  const mdix = findMdix();
  console.log(`\n→ Converting ${template} → ${jsonPath}`);
  run(mdix, ["convert", template, "--to", "json", "-o", jsonPath]);
  console.log(`Done: ${jsonPath}`);
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
    case "generate": cmdGenerate(flags, positional); break;
    case "nuke":     cmdNuke(flags, positional);     break;
    case "snapshot": cmdSnapshot(flags);             break;
    case "validate": cmdValidate(flags, positional); break;
    case "convert":  cmdConvert(flags, positional);  break;
    default:
      console.error(`Unknown command: '${cmd}'\nRun 'mdix-scaffold help' for usage.`);
      process.exit(1);
  }
}

main();
