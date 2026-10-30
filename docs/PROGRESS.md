# Pyart implementation progress

_Last updated: 2026-10-30_

## Stage 1 — `do.times` and quantity syntax (complete)

- `do` consumes `.times`, validates integer counts, and executes a block or source string
  the requested number of times. Missing counts retain one execution; zero and negative
  counts execute zero iterations.
- Added Arturo's documented colon quantity notation (`2:s`, `1:ms`) while preserving
  rational notation (`1:2`). The backtick quantity form remains supported.
- `pause` now handles integer milliseconds and time quantities, including common SI
  prefixes and the upstream time-unit aliases.
- Coverage includes repeated and zero-pass blocks, parameter-driven nesting, parsing
  rationals and quantities, and `pause 0:s`.

## Stage 2 — source-backed reflection and typed function declarations (complete for the supported model)

- Inspected `helpers/helper.nim`, `vm/lib.nim`, the Core/Reflection/Types/System
  declarations and the user-facing `function` documentation at Arturo-Future revision
  `933420d` (the revision pinned by `arturo-language-skill`).
- Added `arturo/builtin_docs.json` with source-derived descriptions, parameter names and
  types, attributes and attribute descriptions, return types, examples, source lines and
  upstream source URLs for 408 statically declared builtins. The importer is
  `tools/build_builtin_metadata.py`; the runtime does not need network access.
- `info.get` now matches Arturo's documented record structure: `name`, runtime `address`,
  `type`, optional `description`/`module`, typed `args`, typed/documented `attrs`,
  `returns`, example blocks, source line/source URL, and symbol `alias`/`infix?` data.
  Metadata for generated aliases/predicates not statically declared in upstream source
  falls back to the local signature registry.
- `info` prints the upstream-style 80-column help sections, including usage, option
  types/descriptions, return types and aliases. `info.get 'word | get 'example` works.
- The parser now preserves `;;` data comments on function-body blocks. Function creation
  extracts `description`, `options`, `returns`, and `example`; parameter type annotations
  such as `[x :integer :floating]` are retained and enforced at call time. `info.get`
  reports this user-function metadata.
- Implemented `methods` for user-defined types and objects, `arg`/`args`, `sys`, and
  `set?`; version ordering is numeric, including prerelease identifiers.

## Verification for this stage

- `python3 tests/test_language.py` — **101/101 passed**.
- `python3 -m compileall -q arturo tests tools` — passed.
- `python3 tools/inventory.py` — **340 implemented / 211 stubs** out of 551 names.
- The source-derived importer reads the pinned upstream library files; generated metadata
  is checked in so normal runs work offline.
- Full reference-pass benchmark, `python3 benchmarks/run_examples.py --jobs 2 --timeout 60`
  — **338/338 passed (100%)**; 44 additional examples are outside the reference runtime's
  passing set. The slowest scored case was `perfect numbers` at 32.7 s.
- `python3 -m pytest tests -q` is unavailable because pytest is not installed. The
  repository's direct test runner is used instead.

## Remaining work

1. Preserve benchmark parity: rerun the reference-pass corpus after future semantic
   changes, triage any mismatches/timeouts, and keep the documented full-run result current.
2. Generated/upstream aliases and quantities not represented as individual `builtin`
   declarations still have fallback metadata; enrich these contracts and test aliases.
3. Continue the remaining 211 implementations listed in [`BUILTIN_STATUS.md`](BUILTIN_STATUS.md),
   starting with cheap reflection/system helpers (`eval`, `parse`, `hash`, `in`, `units`, etc.), then quantity predicates/translated aliases and larger OS,
   networking, database, task and UI modules.
4. Improve the remaining known semantic deviations (multi-line `->`, date durations,
   edge cases) as benchmark failures or differential tests prioritize them.
