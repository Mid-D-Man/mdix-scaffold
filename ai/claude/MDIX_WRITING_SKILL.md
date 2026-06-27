# SKILL: DixScript (.mdix) Writing

## What DixScript Is

DixScript is a data interchange format stored in `.mdix` files. It combines config (like TOML), compile-time functions (like Jsonnet), optional encryption (AES-256-GCM), compression, enums, and strong typing — all in one file. It compiles to JSON, binary, or encrypted blobs via the `mdix` CLI.

**Primary use cases:** game data configs, multi-environment server configs, encrypted secrets, any schema with repeated structure.

**Philosophy:** readable over clever. Reduce duplication with QuickFuncs instead of copy-pasting structure. Consistent, typed, clean — type annotations exist so the shape of data is obvious at a glance, not to be skipped for brevity.

---

## House Style: Signature Comment

Every `.mdix` file gets exactly one of these as its first line, before `@CONFIG`:

```dixscript
// Brought to u by MidManStudio
```

Plain `//` comment, every file, no exceptions, no variation in wording.

---

## File Structure

All sections are optional. When present, use this order:

```dixscript
// Brought to u by MidManStudio

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

Not relevant to scaffold/patch templates — those describe filesystem operations, not encrypted payloads. Skip `@DLM` entirely unless you're actually building a secrets bundle.

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
  ~functionName<returnType>(_param1, _param2<paramType>, _param3 = "default") {
    // statements
    return expression
  }
)
```

- Prefix: always `~`
- Return type annotation: `<int>`, `<float>`, `<string>`, `<bool>`, `<object>`, `<array>`, `<enum>`
- Parameter type annotations are optional but recommended for clarity
- `return` statement is required

### Parameter naming: prefix with `_`

Name QuickFunc parameters with a leading underscore — `_name`, `_path`, `_count` — not bare `name`/`path`/`count`. The payoff shows up the moment you build a return object: `name = _name` is unambiguous at a glance, while `name = name` makes you stop and check which side is the field key and which is the local variable. DixScript doesn't care either way; this is purely for the next person (or you, in six months) reading the call site.

```dixscript
// Confusing — which "name" is which?
~weapon<object>(name, damage<int>) {
  return { name = name, damage = damage }
}

// Clear — left side is the object field, right side is the param
~weapon<object>(_name, _damage<int>) {
  return { name = _name, damage = _damage }
}
```

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

---

## Nested Function Calls & String Building

A function call is just an `Identifier` followed by a `FunctionCall` postfix, and a call's arguments are full `Expression`s — so QuickFuncs can call other QuickFuncs as arguments, and `+` concatenation works anywhere inside a call's parentheses, including inside another call. This is confirmed working in DixScript-Rust's own test corpus (`mdix_files/ComparisonFiles/MDIX/Unholy.mdix`):

```dixscript
warranty = prodWarranty(warranty(36, "limited", [...], [...]), [extWarranty(24, 199.99, [...], 0)])
```

### Composing objects (build nested structures without duplicating shape)

```dixscript
~coords<object>(_lat<float>, _lon<float>) {
  return { latitude = _lat, longitude = _lon }
}

~address<object>(_street, _city, _coords<object>) {
  return { street = _street, city = _city, coordinates = _coords }
}

@DATA(
  home = address("221B Baker St", "London", coords(51.5237, -0.1585))
)
```

### Building repetitive strings (e.g. paths) without duplicating prefixes

```dixscript
~srcDir<string>(_subpath) {
  return "packages/com.example.lib/Runtime/" + _subpath
}

@DATA(
  result::
    move(srcDir("Old/Thing.cs"), srcDir("New/Thing.cs"))
)
```

This is a nice-to-have, not a must. Reach for it once the same literal prefix shows up three or more times in one template — below that, an inline literal is usually still the more readable choice. `Array.join()` is also available for the same purpose: `["a", "b", "c"].join("/")`.

---

## Comma Rules

The formal grammar (`others/midx.ebnf` in DixScript-Rust, "COMMA USAGE SUMMARY") defines this exactly:

### Optional (between entries/declarations)
- Between flat properties
- Between table property declarations
- Between group array items (when vertical)
- Between property assignments within a table property
- Between array items within a group array
- Between `@CONFIG` entries
- Between `@ENUMS` declarations
- Between `@IMPORTS` declarations
- Between `@DLM` modules
- Between `@SECURITY` entries

### Required (inside collection literals)
- Function call arguments: `func(a, b, c)`
- Array literals: `[1, 2, 3]`
- Object literal properties: `{ x = 1, y = 2 }`
- Tuple elements: `t:(1, 2, 3)`
- `@SECURITY` field lists: `{ field1 = val, field2 = val }`

No trailing comma after the last element in any of the above — same as most mainstream languages.

### Practical exception: QuickFunc return objects

The formal grammar requires commas between object properties everywhere, including QuickFunc return objects. In practice the compiler is lenient with vertical (newline-separated) object literals, and this repo's own reference templates rely on that leniency constantly:

```dixscript
~example<object>(_a, _b) {
  return {
    a = _a
    b = _b
  }
}
```

This works, but it's implementation leniency, not a grammar guarantee. A horizontal object literal (`{ a = _a, b = _b }`) still needs the comma regardless of context. When in doubt, or anywhere outside a vertically-laid-out QuickFunc return block, use the comma — it's never wrong and matches the spec exactly.

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

## Built-in Instance & Static Methods

Useful for transforming strings, arrays, and numbers inside QuickFunc bodies without hand-rolling logic.

**String instance:** `.charAt()` `.contains()` `.endsWith()` `.indexOf()` `.isBlank()` `.isEmpty()` `.lastIndexOf()` `.length()` `.padLeft()` `.padRight()` `.replace()` `.split()` `.startsWith()` `.substring()` `.toLower()` `.toUpper()` `.trim()`

**Array instance:** `.average()` `.concat()` `.contains()` `.count()` `.distinct()` `.filter()` `.first()` `.flatten()` `.get()` `.indexOf()` `.isEmpty()` `.join()` `.last()` `.lastIndexOf()` `.length()` `.max()` `.min()` `.pop()` `.push()` `.reverse()` `.set()` `.shift()` `.slice()` `.sort()` `.sum()` `.unshift()`

**Number instance:** `.abs()` `.ceil()` `.floor()` `.isEven()` `.isFinite()` `.isInfinity()` `.isNaN()` `.isNegative()` `.isOdd()` `.isPositive()` `.round()` `.sign()` `.toDouble()` `.toFloat()` `.toInt()` `.toString()`

**Object instance:** `.add()` `.containsValue()` `.count()` `.entries()` `.get()` `.has()` `.keys()` `.length()` `.merge()` `.remove()` `.set()` `.toArray()` `.values()`

**Math static:** `Math.abs()` `Math.ceil()` `Math.clamp()` `Math.cos()` `Math.degrees()` `Math.e()` `Math.exp()` `Math.floor()` `Math.log()` `Math.max()` `Math.min()` `Math.pi()` `Math.pow()` `Math.radians()` `Math.remainder()` `Math.round()` `Math.sign()` `Math.sin()` `Math.sqrt()` `Math.tan()` `Math.truncate()`

Example chaining: `first.trim().toUpper() + " " + last.trim().toUpper()`

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
  ~weapon<object>(_id, _class<enum>, _damage<int>, _rarity<enum>) {
    return {
      WeaponId    = _id
      WeaponClass = _class
      BaseDamage  = _damage
      Rarity      = _rarity
      SellPrice   = _damage * 10
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
  ~dbConfig<object>(_host, _port<int>, _name) {
    return { host = _host, port = _port, name = _name }
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

Don't paste this whole block into every template — see the scaffold skill's "only define what you call" rule. This is the full reference; pull individual functions from it as needed.

```dixscript
@QUICKFUNCS(

  ~f<object>(_name, _ext) {
    return { name = _name, ext = _ext, content = "" }
  }

  ~fc<object>(_name, _ext, _content) {
    return { name = _name, ext = _ext, content = _content }
  }

  ~fremote<object>(_name, _ext, _url) {
    return { name = _name, ext = _ext, content = "remote::" + _url }
  }

  ~gitkeep<object>() {
    return { name = ".gitkeep", ext = "", content = "" }
  }

  ~hidden<object>(_segment) {
    return { segment = _segment }
  }

  ~delete_file<object>(_path) {
    return { path = _path }
  }

  ~rename<object>(_src, _dst) {
    return { from_path = _src, to_path = _dst }
  }

  ~move<object>(_src, _dst) {
    return { from_path = _src, to_path = _dst }
  }

  ~update<object>(_path, _content) {
    return { path = _path, content = _content }
  }

)
```

---

## Common Mistakes

- **Commas inside horizontal object/array literals are required.** `{ x = 1 y = 2 }` on one line is a parse error. Use `{ x = 1, y = 2 }`. Vertical layout is the one place this loosens — see Comma Rules.
- **Commas in function calls are required.** `func(a b)` is a parse error. Use `func(a, b)`.
- **Kebab identifiers in `@QUICKFUNCS` are parsed as subtraction.** Use snake_case inside `@QUICKFUNCS`.
- **`->` is for `@CONFIG` and `@SECURITY` only.** Use `=` for `@DATA` flat properties and inside objects.
- **`::` is group array (multiple items), `:` is table property (single-line assignments).** They are not interchangeable.
- **Flat properties must come before grouped entries in `@DATA`.** You can't interleave them.
- **`return` is required in QuickFuncs.** There is no implicit last-expression return.
- **`if:` not `if`.** Control-flow keywords take a trailing colon: `if:`, `elif:`, `chk:`, `log:`.
- **`param = param` instead of `param = _param`.** Prefix QuickFunc parameters with `_` so return-object construction reads unambiguously.
- **Missing the signature comment.** Every `.mdix` file starts with `// Brought to u by MidManStudio`.
