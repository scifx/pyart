# Pyart — Arturo in Python

A from-scratch Python implementation of the [Arturo](https://arturo-lang.io) programming
language: tokenizer, parser, arity-driven AST builder, tree-walking evaluator, value
system and a large part of the standard library.

The port is developed **against the reference implementation**
([`arturo-lang/arturo`](https://github.com/arturo-lang/arturo), written in Nim,
`0.10.1-dev`) and is validated by running the real Arturo example corpus and comparing
the output byte for byte.

```console
$ python3 -m arturo -e 'print "Hello world!"'
Hello world!
```

| | |
| --- | --- |
| Example benchmark | **338 / 338 (100 %)** of the examples the reference runtime passes (`--jobs 2 --timeout 60`) |
| Language tests | **103 / 103** (`tests/test_language.py`; current additions are covered by local regression checks) |
| Builtin library | **345 implemented** of 551 registered names (206 still stubs, see [`docs/BUILTIN_STATUS.md`](docs/BUILTIN_STATUS.md)) |
| Code size | ~9.3k lines of Python |
| Main remaining blocker | interpreter **speed** (a few compute-heavy examples need 20–50 s) |

---

## Current progress (2026-10-30)

Current work compares every upstream library module at Arturo revision
`4e549e105c54af2e250381d578474b9064d9d4d2`; all modules except `Ui.nim` are in scope.
The audit lists 395 non-UI builtin declarations and 398 source example blocks, with a
module-by-module dependency order in [`docs/ARTURO_PORT_PLAN.md`](docs/ARTURO_PORT_PLAN.md).
Pyart has matching registered implementations for 316/395 declarations by name; this is
not yet semantic or example parity. The local suite is **103/103**, and the latest full
reference-pass benchmark is **338/338** with a 60-second timeout. The broader registry
reports **345 implemented / 206 stubs**; current completed work and explicit acceptance
gaps are tracked in [`docs/PROGRESS.md`](docs/PROGRESS.md).

`info.get` uses a checked-in snapshot from the pinned Arturo source revision. Reflection
and function metadata are partial, not a claim that the whole Reflection module is done.
This update fixes non-consuming `attr?`, implements `benchmark` and a runtime value-stack
view, and begins the host-system batch (`args`, synchronous `execute`, `process`,
`terminate`, `superuser?`). Async process/task behavior and most other source examples
remain to be ported and differentially verified.

---

## Quick start

No packaging step is required — run from the repository root (Python 3.9+).

```console
$ python3 -m arturo path/to/script.art      # run a file
$ python3 -m arturo -e 'print 2 * 3 + 4'    # evaluate a snippet  -> 14
$ python3 -m arturo                         # interactive REPL
```

Embedding it:

```python
from arturo import Interpreter

interp = Interpreter()
interp.exec('x: [1 2 3]')
print(interp.exec('size x').data)    # 3   (exec returns the last value)
print(interp.get('x'))               # <Block [1 2 3]>  (a variable)
interp.exec_file('script.art')
```

`Interpreter(out=..., argv=[...])` lets you capture output and set the program
arguments (`args`, `script`).

---

## Project layout

| Python module | Ported from | Contents |
| --- | --- | --- |
| `arturo/parser.py` | `src/vm/parse.nim` | tokenizer + block parser: symbols, literals, labels, attributes, paths, strings (`"…"`, `«…`, `««…»»`, `{…}`, `{:…:}`, `{/regex/}`, `---…---`, `~"…|code|…"`), numbers, comments |
| `arturo/ast.py` | `src/vm/ast.nim` | arity-driven AST generation: prefix/infix calls, attribute stacking, `->`, `=>`, `::`, `!`, paths, pipes; also the **compiled fast paths** (`Node.fast`) |
| `arturo/evaluator.py` | `src/vm/eval.nim`, `exec.nim` | tree-walking evaluator, scopes/frames, attribute stack, signals (`break`/`continue`/`return`/`ensure`), collectors, error values |
| `arturo/values.py` | `src/vm/values/*` | value hierarchy (integer, floating, rational, complex, logical, quantity, char, string, block, inline, dictionary, object, range, date, binary, function, iterator, …), printing/formatting, comparison |
| `arturo/library.py` | `src/vm/lib.nim` | symbol table shared by parser, AST builder and evaluator |
| `arturo/reflection.py` + `arturo/builtin_docs.json` | `helpers/helper.nim`, `src/library/*.nim` | source-backed `info` metadata, examples, and user-function data comments |
| `arturo/signatures.py` | `src/library/*.nim` | **551** declared arities + accepted attributes (drives parsing of every call) |
| `arturo/builtins/*.py` | `src/library/*.nim` | the standard library: `core`, `collections`, `strings`, `iterators`, `numbers`, `misc`, `dates` |
| `arturo/nimtime.py` | `std/times` | date pattern handling (`yyyy-MM-dd`, `dddd`, …) |
| `arturo/cli.py`, `repl.py` | `src/arturo.nim` | command line entry point and REPL |
| `tools/inventory.py` | — | regenerates the implemented/stub inventory in `docs/` |
| `tools/audit_upstream_library.py` | `src/library/*.nim` | compares source builtin declarations and reports per-module implementation names |
| `tools/build_builtin_metadata.py` | pinned `arturo-lang/arturo` source | builds the checked-in source metadata snapshot |
| `tests/test_language.py` | — | 103 language-level checks |
| `benchmarks/` | — | harness that runs the upstream examples and diffs their output |

### Core language semantics covered by the current regression corpus

* **Right-to-left evaluation, no operator precedence** — `2 * 3 + 4` is `14`,
  `(2 * 3) + 4` is `10`.
* **Arity-driven calls** — a word that names a function consumes exactly as many values
  as the function takes, which is why `print 1 + 2` needs no parentheses.
* **Blocks are lazy**; `@[…]` (`array`) and `do` evaluate them.
* **Attributes** (`.descending`, `.with: ","`) live on a stack that builtins pop;
  `.attr` / `.attr?` / `.attrs` behave differently.
* **Scoping** — blocks have no scope, functions isolate (with `.inline` running in the
  caller's scope), iterators restore the variables they inject.
* **Values are references** — `a: [1 2]; b: a; 'b ++ 3` makes `a` grow too; `new`
  copies. String literals are detached on assignment so the same rules hold for them.
* **In-place updates via literals** — `'xs ++ 4`, `inc 'i`, `sort 'xs`, `d\key: v`.
* **`=>` injects implicit parameters** (`&`, `__`) into a block; `->` wraps the next
  statement as a single-value block.
* `do.times: n [block]` executes a block n times; `do` without `.times` executes once.
* `if`/`if?`/`else`, `when`/`when?`, `switch`/`switch?`, `case`, `unless`/`unless?`,
  `while`, `until`, `try`/`throw`/`panic`/`ensure`, `loop`/`map`/`select`/`filter`/
  `fold`/`collect`/`arrange`, `return`/`break`/`continue`.

---

## Benchmarks

`benchmarks/examples/` contains the upstream Arturo examples (668 `.art` files, 488 of
them with an expected `.res` file). Only the examples that the **reference runtime
itself passes** are scored — 338 files, listed in `benchmarks/reference_pass.json`.

```console
$ python3 benchmarks/run_examples.py --jobs 2 --timeout 60   # full run (~40 min on 2 CPUs)
$ python3 benchmarks/run_examples.py --jobs 8 --timeout 60   # faster on a bigger box
$ python3 benchmarks/one.py "100 doors"                      # debug one example
$ python3 benchmarks/run_examples.py --show-fail 30          # + worst offenders
```

Latest full run after the current implementation (`--jobs 2 --timeout 60`,
2026-10-30):

```
passed 338/338 examples (100%)
plus 42 examples the reference runtime itself cannot run
```

All reference-passing examples completed within the 60-second limit. The slowest were:

| example | time |
| --- | ---: |
| `perfect numbers` | 32.8 s |
| `curzon numbers` | 27.5 s |
| `permutations - derangements` | 20.7 s |
| `changeable words` | 18.4 s |
| `abundant odd numbers` | 11.5 s |
| `truncatable primes` | 10.1 s |
| `circular primes` | 6.8 s |
| `ascending primes` | 6.1 s |

The default harness timeout is 20 seconds, so use `--timeout 60` for the full reference
set on a constrained machine.

---

## Standard library coverage

`arturo/signatures.py` knows every name the reference library declares (551 of them), so
parsing and arity handling are complete even for builtins that are not implemented yet.
An unimplemented builtin raises `Not Implemented`, which makes the gaps obvious instead
of silently producing wrong results.

| module | implemented |
| --- | ---: |
| `core.py` — control flow, logic, conversion, reflection, bitwise | 132 |
| `numbers.py` — arithmetic, primes, clamps, statistics, random | 58 |
| `collections.py` — blocks, dictionaries, sets, sorting, paths | 52 |
| `strings.py` — splitting, padding, formatting, regex, encoding | 32 |
| `misc.py` — files, paths, JSON, IO, crypto digests, system info | 37 |
| `iterators.py` — `loop`/`map`/`select`/`filter`/`fold`/`combine`/… | 23 |
| `dates.py` — `now`, `today`, date arithmetic and predicates | 11 |
| *(registered but currently stubbed)* | 206 |

**Full list**: [`docs/BUILTIN_STATUS.md`](docs/BUILTIN_STATUS.md) (regenerate with
`python3 tools/inventory.py --markdown > docs/BUILTIN_STATUS.md`).

### Remaining library gaps (206 registered stubs)

The broader signature registry includes generated predicates and translated aliases in
addition to the 395 static non-UI source declarations. Use [`docs/BUILTIN_STATUS.md`](docs/BUILTIN_STATUS.md)
for the exact current stub list and [`docs/ARTURO_PORT_PLAN.md`](docs/ARTURO_PORT_PLAN.md)
for upstream module/function coverage. Important unfinished areas include unit-family
predicates and aliases, colors, quantity introspection, filesystem/terminal operations,
configuration and asynchronous process handling, networking, databases, streams, tasks,
events and the remaining type/core helpers. `Ui.nim` is the only module intentionally
excluded from the target scope.

---

## Extending the library (hot-plugging builtins)

Adding a builtin is a 5-line change in **one** file — the registry is global, and arity +
attributes are registered with it, so the parser immediately knows how many values the
new word consumes:

```python
# arturo/builtins/numbers.py
from . import builtin, impl, inplace, attr, attr_true, fail, to_int, to_number
from .. import values as V

@builtin("half", arity=1)                     # a brand new builtin
def _half(ev, args):
    return V.Floating(to_number(args[0]) / 2)
```

```console
$ python3 -m arturo -e 'print half 5'
2.5
```

Real example — `clamp` (already implemented this way):

```python
@impl("clamp")
def _clamp(ev, args):
    value, bounds = args[0], args[1]          # clamp 42 1..10  =>  10
    ...
```

* `@builtin(name, arity, attrs=[...])` declares a new builtin **and** its call arity;
  `@impl(name)` attaches/replaces the Python body of a builtin that `signatures.py`
  already declares.
* Handlers get `(ev, args) -> Value`; `ev` exposes `ev.ctx` (symbol table, attribute
  stack, `ev.ctx.out`), `ev.do_block(block)`, `ev.inplace_target(literal)`.
* Anything declared in `signatures.py` but without an implementation is installed as a
  stub, so the port can be filled in incrementally without touching the parser.
* Runtime-level aliasing is supported too (`alias.infix`, `DYNAMIC_INFIX`), and users can
  define their own functions (`f: function [x][…]`, `$[x][…]`, `.memoize`, `.import`).

---

## Development workflow

```console
$ python3 tests/test_language.py              # 103 language checks (fast)
$ python3 benchmarks/one.py "bead sort"       # run one example + diff with the .res
$ python3 tools/inventory.py                  # builtin coverage report
$ python3 tools/difftest.py --reference /path/to/arturo   # differential smoke test
```

When behaviour is unclear, the reference binary is the source of truth:

```console
$ arturo --no-color probe.art                 # reference implementation
$ python3 -m arturo probe.art                 # the port
```

A good habit while porting: write the snippet to a file (the reference implementation
parses `-e` differently), run both, and diff.

### Performance notes

The interpreter evaluates the AST with compiled closures: `ast._compile_node` attaches a
`Node.fast` callable to constants, variables, simple calls and single-child stores, and
specialises integer arithmetic/comparison (`_INT_SPEC`) so that tight loops such as
`select 1..n 'i -> 0 = n % i` avoid the generic dispatch path. Frozen literals are thawed
on *store* (not on every evaluation). Typical cost is ~1.5–2 µs per interpreted loop
iteration, 20–50× slower than the compiled Nim runtime — which is exactly why the
handful of heavy examples above are borderline.

---

## Known deviations from the reference implementation

Everything below was found with `tools/difftest.py` (157 snippets run through both
`arturo --no-color` and `python3 -m arturo`): **138 agree, 15 are cases where the port
accepts more than the reference, 22 are rejected by both, 3 genuinely differ**:

| area | deviation |
| --- | --- |
| `->` arrow bodies | only the *next statement* is captured — the parser has no newline/indentation information, so a multi-line chain after `->` is grouped differently than in Arturo |
| date arithmetic | `date - date` raises `Type Error: cannot subtract date from date`; the reference returns a `:duration` |
| `truncate` | the reference keeps the string unchanged in a few cutoff/filler edge cases where the port truncates |
| `digest.sha1` | the reference only documents `.sha`; `.sha1`/`.sha256`/`.md5` are honoured by the port (superset) |
| `path "file"` | the reference's `path` takes no arguments; the port additionally returns file info for a path (superset) |
| permissive extras | `slice`/`drop` on ranges, `to :date` from a plain string, variadic `min`/`max`, `distinct`, `none?` — accepted by the port, rejected by the reference |
| tasks / threads | `.async`, `.parallel`, fiber-based helpers are accepted attribute-wise but not executed concurrently |
| `inspect` | returns the formatted string; the reference prints it as a side effect (and prints a slightly different layout for dictionaries) |

---

## Roadmap (highest value first)

1. **Benchmark parity**: run the reference-pass example corpus after semantic changes; fix
   mismatches and keep performance-sensitive examples inside the harness timeout.
2. **Speed**: compile single-statement loop bodies (`select`/`map`/`loop`) into integer
   expressions — target ~0.3 µs/iteration, which puts every example comfortably under
   the 20 s budget.
3. **Cheap builtins**: the 60 quantity predicates and the 42 translated aliases (both
   mechanical), plus the remaining small helpers (`eval`,
   `parse`, `hash`, `in`, `units`, `conforms?`, …).
4. **Semantic polish**: multi-line `->` capture (needs newline-aware parsing),
   `date - date` → `:duration`, `truncate`/`sample.size` edge cases. Also the
   `same?`/`type` corners.
5. **Subsystems**: filesystem mutation (`rename`, `symlink`, `permissions`), process
   execution, sockets/HTTP, sqlite, tasks/fibers, UI.
