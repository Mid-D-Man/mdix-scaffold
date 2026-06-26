# SKILL: DixScript (.mdix) Writing

## What DixScript Is

DixScript is a data interchange format stored in `.mdix` files. It combines config (like TOML), compile-time functions (like Jsonnet), optional encryption (AES-256-GCM), compression, enums, and strong typing — all in one file. It compiles to JSON, binary, or encrypted blobs via the `mdix` CLI.

**Primary use cases:** game data configs, multi-environment server configs, encrypted secrets, any schema with repeated structure.

---

## File Structure

All sections are optional. When present, use this order:

```dixscript
@CONFIG(...)      // compiler settings, metadata
@IMPORTS(...)     // import from other .mdix files
@DLM(...)         // compression + encryption pipeline
@ENUMS(...)       // named constants
@QUICKFUNCS(...)  // compile-time functions
@DATA(...)        // your actual data
@SECURITY(...)    // security configuration
```

---

## @CONFIG

Compiler settings and metadata. All entries use `->` arrow syntax.

```dixscript
@CONFIG(
  version    -> "1.0.0"
  author     -> "YourName"
  features   -> "quickfuncs,data"      // enable sections: quickfuncs, enums, dlm, data
  debug_mode -> "off"                  // off | regular | verbose
)
```

`features` controls which sections the compiler activates. For scaffold templates, always use `"quickfuncs,data"`.

---

## @IMPORTS

```dixscript
@IMPORTS(
  Utils from "common/utils.mdix"
  Config from_cloud "https://example.com/base.mdix" verify "sha256hash"
)
```

Call imported functions as `Utils.myFunc(...)` and access imported enums as `Utils.EnumName.Value`.

---

## @DLM (Data Lifecycle Modules)

```dixscript
@DLM(
  DCompressor.gzip        // gzip | bzip2 | lzma
  DEncryptor.aes256       // xor | aes128 | aes256 | chacha20
)
```

Runs at compile time — output is compressed then encrypted. Pair with `@SECURITY` for key config.

---

## @ENUMS

```dixscript
@ENUMS(
  LogLevel    { DEBUG = 0, INFO = 1, WARN = 2, ERROR = 3 }
  Environment { DEV, STAGING, PROD }          // auto-increments from 0
  CamoRarity  { Basic, Rare, Epic, Legendary }
)
```

Access in `@DATA` and `@QUICKFUNCS` as `LogLevel.INFO`, `Environment.PROD`, etc.

---

## @QUICKFUNCS

Compile-time functions. They execute at compile time — zero runtime overhead.

### Syntax

```dixscript
@QUICKFUNCS(
  ~functionName<returnType>(param1, param2<paramType>, param3 = "default") {
    // statements
    return expression
  }
)
```

- Prefix: always `~`
- Return type annotation: `<int>`, `<float>`, `<string>`, `<bool>`, `<object>`, `<array>`, `<enum>`
- Parameter type annotations are optional but recommended for clarity
- `return` statement is required

### Control flow inside QuickFuncs

```dixscript
// if / elif / else  (note the colon)
if: x > 10 {
  return "big"
} elif: x > 5 {
  return "medium"
} else {
  return "small"
}

// switch  (chk: expression, -> case, -> miss for default)
chk: rarity {
  -> CamoRarity.Rare      { return 100 }
  -> CamoRarity.Epic      { return 250 }
  -> CamoRarity.Legendary { return 500 }
  -> miss                 { return 10  }
}

// ternary
multiplier = difficulty == Difficulty.HARD ? 2.0 : 1.0
```

### Variable declarations

```dixscript
let   name = "Alice"          // mutable
const MAX  = 100              // immutable
let mut count<int> = 0        // explicit type + mutable
```

Semicolons are optional everywhere.

### Arithmetic assignment operators

```dixscript
count += 1
total -= fee
score *= 2
ratio /= 100
rem   %= 7
```

### String interpolation

```dixscript
$"{sprite}(Clone)"            // embed expressions with {}
$"Hello, {name}! Score: {score * 2}"
```

### Logging (debug only)

```dixscript
log: "Processing item: " + name
```

### Operators

| Category | Operators |
|---|---|
| Arithmetic | `+` `-` `*` `/` `%` `^` (power) |
| Comparison | `==` `!=` `>` `<` `>=` `<=` |
| Logical | `&&` / `and`   `\|\|` / `or`   `!` / `not` |
| Ternary | `condition ? then : else` |
| String concat | `+` |

### Object return (most common in scaffold templates)

```dixscript
~myFunc<object>(name, value<int>) {
  return {
    name  = name
    value = value
    extra = value * 2
  }
}
```

### Full example

```dixscript
@QUICKFUNCS(
  ~camo<object>(id, index<int>, rarity<enum>, sprite) {
    return {
      CamoId              = id
      CamoIndex           = index
      CamoRarity          = rarity
      CamoAtlasSpriteName = $"{sprite}(Clone)"
      CamoType            = "Sprite"
    }
  }

  ~calculateDamage<int>(base<int>, hard<bool>) {
    multiplier = hard ? 2.0 : 1.0
    return Math.round(base * multiplier)
  }
)
```

---

## @DATA

The main data section. Uses a **two-tier ordering system**.

### Flat properties (single `=`)

Simple key-value pairs. Must come before any grouped entries.

```dixscript
@DATA(
  app_name    = "MyApp"
  version     = "1.0.0"
  port        = 8080
  debug       = false
  tax_rate    = 0.15f
)
```

### Table properties (single `:`)

Inline object — multiple assignments on one declaration. Commas required between assignments.

```dixscript
@DATA(
  server: host = "localhost", port = 8080, ssl = true
  ci: node_version = "20", rust_toolchain = "stable"
)
```

Access nested values with dot notation: `[[ci.node_version]]`.

### Group arrays (double `::`)

An array of items — one per line (or comma-separated). Can hold primitives, objects, or QuickFunc calls.

```dixscript
@DATA(
  admins::
    "alice"
    "bob"
    "charlie"

  enemies::
    createEnemy("Goblin", 50, 10)
    createEnemy("Orc",   100, 20)
    createEnemy("Troll", 200, 40)
)
```

### Objects and arrays as values

```dixscript
@DATA(
  config = { host = "localhost", port = 8080 }
  tags   = ["rust", "config", "open-source"]
)
```

Objects use commas between properties. Arrays use commas between elements.

---

## Comma Rules

### Optional (between entries/declarations)
- Between flat properties
- Between table property declarations
- Between group array items (when vertical)
- Between `@CONFIG` entries
- Between `@ENUMS` declarations
- Between `@IMPORTS` declarations
- Between `@DLM` modules

### Required (inside collection literals)
- Function call arguments: `func(a, b, c)`
- Array literals: `[1, 2, 3]`
- Object literal properties: `{ x = 1, y = 2 }`
- Tuple elements: `t:(1, 2, 3)`

**Rule of thumb:** commas for horizontal (same line), omit for vertical (different lines).

---

## Type System

### Explicit type annotations

```dixscript
count<int>      = 42
max<long>       = 9_000_000_000L
rate<float>     = 3.14f
pi<double>      = 3.14159265358979
flag<bool>      = true
name<string>    = "Alice"
level<enum>     = LogLevel.INFO
color<hex>      = #FF5733
avatar<blob>    = b:("base64encodeddata")
pattern<regex>  = r:("^[a-z@.]+$")
date            = 2025-12-31
timestamp       = 2025-12-31T23:59:59Z
```

### Numeric literals

```dixscript
42              // Integer (i32)
9_000_000_000L  // Long (i64) — L suffix
3_000_000_000   // Long (auto-promoted, overflows i32)
3.14f           // Float (f32) — f suffix
3.14            // Double (f64)
0xFF            // Hex integer
0xFF_FFDEAD L   // Hex long — L suffix
0b1010_1100     // Binary integer
0b1111L         // Binary long
1_000_000       // Underscores as visual separators (any numeric)
#FF5733         // HexColor (3–8 hex digits)
```

---

## Identifier Rules

**Snake-case** works everywhere:
```dixscript
my_variable
project_name
MAX_RETRIES
```

**Kebab-case** works in all sections **except `@QUICKFUNCS`** (where `-` is arithmetic minus):
```dixscript
// In @DATA, @CONFIG, @ENUMS — valid:
getting-started::
  fc("getting-started", "md", "# Getting Started\n")

// In @QUICKFUNCS — INVALID (hyphen = subtraction):
~my-func<object>()  // ← DON'T do this
~my_func<object>()  // ← correct
```

---

## @SECURITY

```dixscript
@SECURITY(
  encryption -> { mode = "password" }         // prompt for password at compile
  encryption -> { mode = "keyfile", path = "keys/secret.key" }
  validation -> { strict = true }
)
```

---

## String Escapes

```dixscript
"\n"   // newline
"\t"   // tab
"\r"   // carriage return
"\\"   // backslash
"\""   // double quote
"\'"   // single quote
"\{"   // literal { (in interpolated strings)
"\}"   // literal }
"\0"   // null byte
```

---

## CLI Reference

```bash
mdix validate config.mdix          # check syntax
mdix compile config.mdix           # compile to binary
mdix compile secrets.mdix --password   # compile + encrypt
mdix convert config.json --to mdix     # convert from JSON
mdix convert config.mdix --to json -o out.json  # export to JSON
mdix inspect config.mdix --keys    # list all resolved keys
mdix --version
```

---

## Patterns

### Game data config

```dixscript
@ENUMS(
  WeaponClass { SMG, AR, SHOTGUN }
  Rarity      { Basic, Rare, Epic, Legendary }
)

@QUICKFUNCS(
  ~weapon<object>(id, class<enum>, damage<int>, rarity<enum>) {
    return {
      WeaponId    = id
      WeaponClass = class
      BaseDamage  = damage
      Rarity      = rarity
      SellPrice   = damage * 10
    }
  }
)

@DATA(
  weapons::
    weapon("SMG_001", WeaponClass.SMG,      45, Rarity.Basic)
    weapon("SMG_002", WeaponClass.SMG,      80, Rarity.Rare)
    weapon("AR_001",  WeaponClass.AR,       60, Rarity.Basic)
    weapon("AR_LEG",  WeaponClass.AR,      150, Rarity.Legendary)
)
```

### Multi-environment config

```dixscript
@ENUMS(
  Environment { DEV, STAGING, PROD }
)

@QUICKFUNCS(
  ~dbConfig<object>(host, port<int>, name) {
    return { host = host, port = port, name = name }
  }
)

@DATA(
  current_env<enum> = Environment.PROD

  database::
    dbConfig("localhost",    5432, "myapp_dev")
    dbConfig("staging-db",  5432, "myapp_staging")
    dbConfig("prod-db",     5432, "myapp_prod")

  server: host = "0.0.0.0", port = 8080, workers = 4
)
```

### Scaffold template QuickFuncs block (copy-paste starter)

```dixscript
@QUICKFUNCS(

  ~f<object>(name, ext) {
    return { name = name, ext = ext, content = "" }
  }

  ~fc<object>(name, ext, content) {
    return { name = name, ext = ext, content = content }
  }

  ~fremote<object>(name, ext, url) {
    return { name = name, ext = ext, content = "remote::" + url }
  }

  ~gitkeep<object>() {
    return { name = ".gitkeep", ext = "", content = "" }
  }

  ~hidden<object>(segment) {
    return { segment = segment }
  }

  ~delete_file<object>(path) {
    return { path = path }
  }

  ~rename<object>(src, dst) {
    return { from_path = src, to_path = dst }
  }

  ~move<object>(src, dst) {
    return { from_path = src, to_path = dst }
  }

  ~update<object>(path, content) {
    return { path = path, content = content }
  }

)
```

---

## Common Mistakes

- **Commas inside object/array literals are required.** `{ x = 1 y = 2 }` is a parse error. Use `{ x = 1, y = 2 }`.
- **Commas in function calls are required.** `func(a b)` is a parse error. Use `func(a, b)`.
- **Kebab identifiers in `@QUICKFUNCS` are parsed as subtraction.** Use snake_case inside `@QUICKFUNCS`.
- **`->` is for `@CONFIG` and `@SECURITY` only.** Use `=` for `@DATA` flat properties and inside objects.
- **`::` is group array (multiple items), `:` is table property (single-line assignments).** They are not interchangeable.
- **Flat properties must come before grouped entries in `@DATA`.** You can't interleave them.
- **`return` is required in QuickFuncs.** There is no implicit last-expression return.
- **`if:` not `if`.** Control-flow keywords take a trailing colon: `if:`, `elif:`, `chk:`, `log:`.
