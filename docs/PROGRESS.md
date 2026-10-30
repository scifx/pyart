# Pyart implementation progress

_Last updated: 2026-10-30_

## Scope

Port Arturo's `src/library/*.nim` at upstream revision
[`4e549e105c54af2e250381d578474b9064d9d4d2`](https://github.com/arturo-lang/arturo/tree/4e549e105c54af2e250381d578474b9064d9d4d2/src/library).
All library modules are in scope except `Ui.nim`. The dependency map, exact builtin inventory,
source imports and per-module Pyart coverage are in [`ARTURO_PORT_PLAN.md`](ARTURO_PORT_PLAN.md).

The target is semantic parity, not just a registered name: every source builtin must match its
arguments, attributes, return type, side effects, error behavior and examples. Source example
coverage is **not yet complete**.

## Stage 1 — syntax and runtime foundations (partial)

- Implemented Arturo's documented colon-form quantities (`2:s`, `1:ms`) while preserving
  rational notation (`1:2`), and wired `.times` into `do`.
- Implemented `pause` for integer milliseconds and time quantities, including common SI
  prefixes and upstream time-unit aliases.
- Core parser/evaluator behavior already covers arity-driven calls, attributes, `->`/`=>`,
  functions, control flow, paths and quantities well enough for the current reference corpus;
  known semantic edge cases remain and are listed in the audit/benchmarks.

## Stage 2 — reflection and function metadata (partial; do not treat as full-module completion)

- Read Arturo's `Reflection.nim`, `Core.nim`, `Types.nim`, `System.nim`, runtime helpers and
  function documentation at the pinned upstream revision.
- `arturo/builtin_docs.json` now has **396** source-extracted builtin metadata records from
  that exact revision. `tools/build_builtin_metadata.py` regenerates the snapshot offline from
  a source checkout. The local argument arities and accepted attribute names match all 396
  static declarations; generated aliases and non-static declarations still use local signature
  fallback, so metadata coverage is not 100% of the wider 551-name registry.
- `info`/`info.get` supports builtin records and user-function data comments/type annotations;
  method metadata lookup is available for user-defined objects. This does not imply that every
  Reflection builtin or every metadata field matches upstream in every case.
- This phase fixed `attr?` to observe without consuming an attribute, implemented `benchmark`
  (including `.get` returning elapsed milliseconds), and replaced the empty `stack` placeholder
  with a runtime value-stack view. `inspect` supports output, compact and indexed modes, but its
  formatting/color behavior still needs differential testing against Arturo.

## Stage 3 — source audit and module-by-module port (in progress)

- Audited all **28** upstream module files: **395** declarations outside UI and **398** source
  example blocks. Pyart currently has registered implementations for **316/395** upstream
  declarations by name; this is a name-coverage measure, not proof of semantic parity.
- Reflection corrections covered in this update: `arity` includes local user functions;
  `symbols` returns bound values rather than placeholder nulls; `attr?`, `benchmark`, and
  `stack` have regression coverage.
- Started the host-system batch: `args` now follows the upstream key/value and positional
  block shape; synchronous `execute` modes, process information, process termination and
  the superuser predicate are implemented. `execute.async` still requires the not-yet-ported
  task runtime.
- Next implementation order follows dependencies: foundation and syntax/value contracts;
  pure value modules (`Colors`, missing `Crypto`/`Dates`/`Quantities`/`Sets` cases); then host
  integration (`Files`, `Io`, `System`, `Paths`); then databases, networking, streams, tasks
  and events. `Ui.nim` remains deferred by request.
- All **14 Reflection-module source example blocks** execute without errors in Pyart (smoke
  execution, not output differential). The full set of 398 non-UI source examples has **not**
  been executed or output-differential tested; this remains an explicit acceptance item.

## Verification

- `python3 tests/test_language.py` — **103/103 passed**.
- `python3 -m compileall -q arturo tests tools` — passed.
- `python3 tools/inventory.py` — **345 implemented / 206 stubs** out of 551 registered names.
- Full benchmark after this update, `python3 benchmarks/run_examples.py --jobs 2 --timeout 60`
  — **338/338 reference-pass examples passed (100%)**; 42 additional out-of-reference-set
  examples also passed.
- `python3 -m pytest tests -q` is unavailable because pytest is not installed; the repository's
  direct test runner is used.

## Remaining acceptance work

1. Implement all non-UI declarations to source behavior; prioritize undercovered host/system
   functions and remaining Reflection/Types/Quantities/Colors/Crypto functions.
2. Build a controlled source-example runner and execute/diff all 398 non-UI source examples
   against the same Arturo revision. Isolate filesystem/process/network effects; document only
   true platform-dependent skips.
3. Keep the full Rosetta/example benchmark passing after each semantic batch; report exact
   failures instead of equating language tests with benchmark coverage.
